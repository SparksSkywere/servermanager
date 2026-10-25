using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using ServerManager.Core.Configuration;
using ServerManager.Core.Process;
using ServerManager.Data;
using ServerManager.Data.Entities;
using ServerManager.Minecraft;
using ServerManager.Steam;

namespace ServerManager.HostRuntime.Services;

public sealed class ManagedServerState
{
    public string Name { get; init; } = string.Empty;
    public System.Diagnostics.Process? Process { get; set; }
    public StreamWriter? Stdin { get; set; }
    public int? Pid { get; set; }
    public DateTime? CreateTime { get; set; }
    public string Status { get; set; } = "stopped";
    public ConcurrentQueue<string> ConsoleBuffer { get; } = new();
    public int ConsoleSeq { get; set; }
    public string? StdoutLog { get; set; }
    public string? StderrLog { get; set; }
    public long StdoutPosition { get; set; }
    /// <summary>True when we adopted a live PID after HostRuntime/dashboard restart (may lack Stdin handle).</summary>
    public bool Reattached { get; set; }
    public string CommandChannel { get; set; } = "none"; // stdin | attachconsole | none
    public TimeSpan? LastCpuTime { get; set; }
    public DateTime? LastCpuSampleUtc { get; set; }
    public double? LastCpuPercent { get; set; }
    public DateTime? LastInstallScanUtc { get; set; }
}

public interface IGameServerHost
{
    Task<IReadOnlyList<object>> ListServersAsync(CancellationToken ct = default);
    Task<object> GetStatusAsync(string name, CancellationToken ct = default);
    Task<object> StartAsync(string name, CancellationToken ct = default);
    Task<object> StopAsync(string name, CancellationToken ct = default);
    Task<object> RestartAsync(string name, CancellationToken ct = default);
    Task<object> KillAsync(string name, CancellationToken ct = default);
    Task<object> ClearAsync(string name, CancellationToken ct = default);
    Task<object> GetProcessDetailsAsync(string name, CancellationToken ct = default);
    Task<object> FindBrokenAsync(CancellationToken ct = default);
    Task<object> VerifyServersAsync(CancellationToken ct = default);
    Task<object> DbMaintenanceAsync(string action, CancellationToken ct = default);
    Task<object> UpdateServerAsync(string name, CancellationToken ct = default);
    Task<object> UpdateAllAsync(CancellationToken ct = default);
    Task<object> GetConsoleAsync(string name, int lines = 100, CancellationToken ct = default);
    Task<object> SendCommandAsync(string name, string command, CancellationToken ct = default);
    Task<object> ReattachAsync(string name, CancellationToken ct = default);
    Task<object> ReattachAllAsync(CancellationToken ct = default);
    object Diagnostics();
}

public sealed class GameServerHost : IGameServerHost, IDisposable
{
    private const int MaxConsoleLines = 500;
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly ProcessIdentityService _identity;
    private readonly WindowsConsoleCommandSender _consoleSender;
    private readonly SteamCmdService _steam;
    private readonly MinecraftInstaller _minecraft;
    private readonly ILogger<GameServerHost> _logger;
    private readonly ConcurrentDictionary<string, ManagedServerState> _states = new(StringComparer.OrdinalIgnoreCase);
    private readonly CancellationTokenSource _tailCts = new();
    private readonly Task _tailTask;
    private readonly Task _persistTask;
    private readonly DateTime _started = DateTime.UtcNow;
    private readonly IConfigStore _cfg;
    private DateTime _hideConsolesCachedUtc = DateTime.MinValue;
    private bool _hideConsolesCached = true;
    private int _hideTick;

    public GameServerHost(
        IServiceScopeFactory scopeFactory,
        ProcessIdentityService identity,
        WindowsConsoleCommandSender consoleSender,
        SteamCmdService steam,
        MinecraftInstaller minecraft,
        IConfigStore cfg,
        ILogger<GameServerHost> logger)
    {
        _scopeFactory = scopeFactory;
        _identity = identity;
        _consoleSender = consoleSender;
        _steam = steam;
        _minecraft = minecraft;
        _cfg = cfg;
        _logger = logger;
        _tailTask = Task.Run(() => TailLoopAsync(_tailCts.Token));
        _persistTask = Task.Run(() => PersistLoopAsync(_tailCts.Token));
    }

    public async Task<object> ReattachAllAsync(CancellationToken ct = default)
    {
        await using var scope = _scopeFactory.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<ServersDbContext>();
        var servers = await db.ServerConfigs.AsNoTracking().Where(s => s.Enabled).ToListAsync(ct);
        var results = new List<object>();
        foreach (var s in servers)
        {
            try
            {
                results.Add(new { name = s.Name, result = await ReattachAsync(s.Name, ct) });
            }
            catch (Exception ex)
            {
                results.Add(new { name = s.Name, error = ex.Message });
            }
        }
        return new { ok = true, servers = results };
    }

    public async Task<object> ReattachAsync(string name, CancellationToken ct = default)
    {
        var cfg = await GetConfigAsync(name, ct) ?? throw new KeyNotFoundException(name);
        var state = _states.GetOrAdd(name, _ => new ManagedServerState { Name = name });

        // Already fully attached with live stdin — dashboard reopen only needs buffer/log continuity.
        if (state.Process is { HasExited: false } && state.Stdin is not null)
        {
            state.Status = "running";
            state.CommandChannel = "stdin";
            await EnsureLogTailTargetAsync(state, cfg.InstallDir, preferGameLog: IsJavaServer(cfg));
            await LoadConsoleFromDbAsync(state, ct);
            AppendConsole(state, $"--- Console session resumed (stdin) at {DateTime.Now:O} ---");
            await PersistConsoleAsync(state, ct);
            return new
            {
                ok = true,
                mode = "live_stdin",
                pid = state.Pid,
                command_channel = state.CommandChannel,
                reattached = false,
                console_seq = state.ConsoleSeq
            };
        }

        int? pid = null;
        DateTime? createTime = null;

        if (state.Pid is int sp && _identity.IsRunning(sp)
            && _identity.BelongsToServer(sp, state.CreateTime ?? cfg.ProcessCreateTime, cfg.InstallDir, cfg.Executable))
        {
            pid = sp;
            createTime = state.CreateTime ?? cfg.ProcessCreateTime;
        }
        else if (cfg.ProcessId is int dbPid && _identity.IsRunning(dbPid)
            && _identity.BelongsToServer(dbPid, cfg.ProcessCreateTime, cfg.InstallDir, cfg.Executable))
        {
            pid = dbPid;
            createTime = cfg.ProcessCreateTime;
            // Prefer the real game/JVM process, not a tiny launcher wrapper
            var promoted = _identity.PromoteToPrimaryProcess(dbPid, cfg.InstallDir, cfg.Executable);
            if (promoted is int better)
            {
                pid = better;
                createTime = _identity.GetCreateTime(better);
            }
        }
        else
        {
            // Scan for live process belonging to install dir
            pid = FindLivePidByInstallDir(cfg);
            if (pid is int found)
                createTime = _identity.GetCreateTime(found);
        }

        if (pid is null || !_identity.IsRunning(pid.Value))
        {
            state.Status = "stopped";
            state.Pid = null;
            state.Reattached = false;
            state.CommandChannel = "none";
            await ClearPidAsync(name, ct);
            return new { ok = true, mode = "stopped", command_channel = "none", reattached = false };
        }

        try
        {
            state.Process = System.Diagnostics.Process.GetProcessById(pid.Value);
        }
        catch
        {
            state.Process = null;
        }

        state.Pid = pid;
        state.CreateTime = createTime;
        state.Status = "running";
        state.Reattached = true;
        state.Stdin = null; // cannot recover redirected stdin after HostRuntime restart
        state.CommandChannel = OperatingSystem.IsWindows() ? "attachconsole" : "none";

        await EnsureLogTailTargetAsync(state, cfg.InstallDir, preferGameLog: IsJavaServer(cfg));
        await LoadConsoleFromDbAsync(state, ct);
        SeedConsoleFromLogTail(state, 80);
        AppendConsole(state, $"--- Reattached to PID {pid} channel={state.CommandChannel} at {DateTime.Now:O} ---");
        await PersistPidAsync(name, pid, createTime, ct);
        await PersistConsoleAsync(state, ct);

        ScheduleHideConsoles(pid.Value);

        _logger.LogInformation("Reattached {Server} to PID {Pid} channel={Channel}", name, pid, state.CommandChannel);
        return new
        {
            ok = true,
            mode = "reattached",
            pid,
            command_channel = state.CommandChannel,
            reattached = true,
            console_seq = state.ConsoleSeq
        };
    }

    public async Task<IReadOnlyList<object>> ListServersAsync(CancellationToken ct = default)
    {
        await using var scope = _scopeFactory.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<ServersDbContext>();
        var servers = await db.ServerConfigs.AsNoTracking().Where(s => s.Enabled).ToListAsync(ct);
        var list = new List<object>();
        foreach (var s in servers)
        {
            var status = await GetStatusInternalAsync(s, ct);
            var state = _states.GetOrAdd(s.Name, _ => new ManagedServerState { Name = s.Name });
            double? cpu = null;
            double? memMb = null;
            string? uptime = null;
            // Only sample process metrics when the server is actually running under a verified PID.
            if (string.Equals(status.status, "running", StringComparison.OrdinalIgnoreCase) && status.pid is int pid)
            {
                // Promote once when the tracked PID looks like a wrapper (helper name or tiny WS)
                var shouldPromote = false;
                try
                {
                    var cur = System.Diagnostics.Process.GetProcessById(pid);
                    shouldPromote = ProcessIdentityService.IsHelperProcess(cur)
                                    || SafeWs(cur) < 48L * 1024 * 1024;
                }
                catch { shouldPromote = true; }

                if (shouldPromote)
                {
                    var primary = _identity.PromoteToPrimaryProcess(pid, s.InstallDir, s.Executable) ?? pid;
                    if (primary != pid)
                    {
                        pid = primary;
                        state.Pid = primary;
                        state.CreateTime = _identity.GetCreateTime(primary);
                        state.Status = "running";
                        state.LastCpuTime = null;
                        state.LastCpuSampleUtc = null;
                        try { state.Process = System.Diagnostics.Process.GetProcessById(primary); } catch { state.Process = null; }
                        await PersistPidAsync(s.Name, primary, state.CreateTime, ct);
                    }
                }
                else if (state.Pid != pid)
                {
                    state.Pid = pid;
                    state.Status = "running";
                }

                try
                {
                    var proc = System.Diagnostics.Process.GetProcessById(pid);
                    proc.Refresh();
                    if (!proc.HasExited)
                    {
                        memMb = proc.WorkingSet64 / (1024.0 * 1024.0);
                        var span = DateTime.Now - proc.StartTime;
                        if (span < TimeSpan.Zero) span = TimeSpan.Zero;
                        uptime = span.TotalDays >= 1
                            ? $"{(int)span.TotalDays}d {span.Hours}h {span.Minutes}m"
                            : $"{(int)span.TotalHours}h {span.Minutes}m";

                        // Interval CPU % (lifetime average looked like 0% on long-lived wrappers)
                        var now = DateTime.UtcNow;
                        var cpuTime = proc.TotalProcessorTime;
                        if (state.LastCpuSampleUtc is DateTime lastSample
                            && state.LastCpuTime is TimeSpan lastCpu
                            && (now - lastSample).TotalSeconds >= 0.5)
                        {
                            var wall = (now - lastSample).TotalSeconds;
                            var delta = (cpuTime - lastCpu).TotalSeconds;
                            if (wall > 0)
                            {
                                cpu = Math.Clamp(delta / wall * 100.0 / Environment.ProcessorCount, 0, 100);
                                state.LastCpuPercent = cpu;
                            }
                        }
                        else
                        {
                            cpu = state.LastCpuPercent;
                        }
                        state.LastCpuTime = cpuTime;
                        state.LastCpuSampleUtc = now;
                    }
                }
                catch { /* process may have exited */ }
            }
            var reportPid = string.Equals(status.status, "running", StringComparison.OrdinalIgnoreCase)
                ? (state.Pid ?? status.pid)
                : null;
            list.Add(new
            {
                name = s.Name,
                type = s.ServerType,
                status = status.status,
                pid = reportPid,
                installDir = s.InstallDir,
                category = s.Category,
                cpu,
                memoryMb = memMb,
                uptime = string.Equals(status.status, "running", StringComparison.OrdinalIgnoreCase) ? uptime : null,
                command_channel = state.CommandChannel ?? "none",
                reattached = state.Reattached
            });
        }
        return list;
    }

    public async Task<object> GetStatusAsync(string name, CancellationToken ct = default)
    {
        var cfg = await GetConfigAsync(name, ct) ?? throw new KeyNotFoundException(name);
        var status = await GetStatusInternalAsync(cfg, ct);
        _states.TryGetValue(name, out var st);
        return new
        {
            status.status,
            status.pid,
            command_channel = st?.CommandChannel ?? "none",
            reattached = st?.Reattached ?? false,
            console_seq = st?.ConsoleSeq ?? 0
        };
    }

    public async Task<object> StartAsync(string name, CancellationToken ct = default)
    {
        var cfg = await GetConfigAsync(name, ct) ?? throw new KeyNotFoundException(name);
        var existing = await GetStatusInternalAsync(cfg, ct);
        if (existing.status == "running")
        {
            // Prefer reattach/resume over "already running" so dashboard reopen recovers channels
            return await ReattachAsync(name, ct);
        }

        var installDir = cfg.InstallDir;
        Directory.CreateDirectory(installDir);
        Directory.CreateDirectory(Path.Combine(installDir, "logs"));

        var (fileName, args, useStdin) = BuildStartCommand(cfg);
        var needsConsole = NeedsDedicatedConsole(cfg);
        var stamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
        var stdoutLog = Path.Combine(installDir, "logs", $"server_stdout_{stamp}.log");
        var stderrLog = Path.Combine(installDir, "logs", $"server_stderr_{stamp}.log");

        System.Diagnostics.Process? proc = null;
        int? launchedPid = null;

        // Service (Session 0) cannot host Project Zomboid's console — launch into the active user session.
        if (needsConsole && InteractiveProcessLauncher.IsRunningInSession0())
        {
            launchedPid = InteractiveProcessLauncher.StartInActiveSession(fileName, args, installDir, _logger);
            if (launchedPid is null)
            {
                return new
                {
                    ok = false,
                    message = "Could not start in the logged-on user session. Sign in locally (or via RDP) and retry; Project Zomboid cannot run in Session 0."
                };
            }
            await Task.Delay(1200, ct);
            if (!_identity.IsRunning(launchedPid.Value))
                return new { ok = false, message = "Process failed to stay running (user-session launch)." };
            try { proc = System.Diagnostics.Process.GetProcessById(launchedPid.Value); }
            catch { /* PID tracked without Process handle */ }
        }
        else
        {
            // Interactive HostRuntime, or non-console servers: normal Process.Start
            var psi = new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = args,
                WorkingDirectory = installDir,
                UseShellExecute = false,
                CreateNoWindow = !needsConsole,
                WindowStyle = needsConsole ? ProcessWindowStyle.Minimized : ProcessWindowStyle.Hidden,
                RedirectStandardOutput = !needsConsole,
                RedirectStandardError = !needsConsole,
                RedirectStandardInput = !needsConsole && useStdin
            };

            for (var attempt = 1; attempt <= 3; attempt++)
            {
                proc = System.Diagnostics.Process.Start(psi);
                if (proc is null) continue;
                await Task.Delay(800, ct);
                if (!proc.HasExited) break;
                _logger.LogWarning("Server {Name} exited immediately (attempt {Attempt})", name, attempt);
                proc.Dispose();
                proc = null;
            }

            if (proc is null || proc.HasExited)
                return new { ok = false, message = "Process failed to stay running" };
            launchedPid = proc.Id;
        }

        var state = _states.GetOrAdd(name, _ => new ManagedServerState { Name = name });
        state.Process = proc;
        state.Pid = launchedPid;
        state.CreateTime = proc?.StartTime.ToUniversalTime() ?? _identity.GetCreateTime(launchedPid!.Value);
        state.Status = "running";
        state.StdoutLog = stdoutLog;
        state.StderrLog = stderrLog;
        state.StdoutPosition = 0;
        state.Reattached = false;
        if (!needsConsole && useStdin && proc is not null)
        {
            state.Stdin = new StreamWriter(
                proc.StandardInput.BaseStream,
                new UTF8Encoding(encoderShouldEmitUTF8Identifier: false),
                bufferSize: 1024,
                leaveOpen: true)
            {
                AutoFlush = true
            };
            state.CommandChannel = "stdin";
        }
        else
        {
            state.Stdin = null;
            state.CommandChannel = OperatingSystem.IsWindows() ? "attachconsole" : "none";
        }

        if (!needsConsole && proc is not null)
        {
            _ = Task.Run(async () =>
            {
                try
                {
                    await using var outFs = new FileStream(stdoutLog, FileMode.Create, FileAccess.Write, FileShare.ReadWrite);
                    await using var errFs = new FileStream(stderrLog, FileMode.Create, FileAccess.Write, FileShare.ReadWrite);
                    await Task.WhenAll(
                        proc.StandardOutput.BaseStream.CopyToAsync(outFs),
                        proc.StandardError.BaseStream.CopyToAsync(errFs));
                }
                catch (Exception ex)
                {
                    _logger.LogDebug(ex, "Log copy ended for {Name}", name);
                }
            }, CancellationToken.None);
        }
        else
        {
            try
            {
                await File.WriteAllTextAsync(stdoutLog,
                    $"--- Launched with dedicated console at {DateTime.Now:O} PID={launchedPid} ---{Environment.NewLine}", ct);
            }
            catch { /* ignore */ }
        }

        // Allow game/JVM a moment to spawn, then track the heavyweight PID (not cmd launcher)
        await Task.Delay(2500, ct);
        if (IsJavaServer(cfg))
        {
            var jvm = _identity.FindJavaChild(proc.Id)
                      ?? _identity.FindJavaForServer(cfg.InstallDir, cfg.Executable)
                      ?? _identity.PromoteToPrimaryProcess(proc.Id, cfg.InstallDir, cfg.Executable);
            if (jvm is int jvmPid)
            {
                state.Pid = jvmPid;
                state.CreateTime = _identity.GetCreateTime(jvmPid);
            }
        }
        else
        {
            var primary = _identity.PromoteToPrimaryProcess(proc.Id, cfg.InstallDir, cfg.Executable);
            if (primary is int betterPid)
            {
                state.Pid = betterPid;
                state.CreateTime = _identity.GetCreateTime(betterPid);
            }
        }

        await PersistPidAsync(cfg.Name, state.Pid, state.CreateTime, ct);
        await EnsureLogTailTargetAsync(state, cfg.InstallDir, preferGameLog: IsJavaServer(cfg));
        AppendConsole(state, $"--- Server started at {DateTime.Now:O} PID={state.Pid} channel={state.CommandChannel} ---");
        await PersistConsoleAsync(state, ct);
        if (state.Pid is int startedPid)
            ScheduleHideConsoles(startedPid);
        return new { ok = true, pid = state.Pid, status = "running", command_channel = state.CommandChannel };
    }

    public async Task<object> StopAsync(string name, CancellationToken ct = default)
    {
        var cfg = await GetConfigAsync(name, ct) ?? throw new KeyNotFoundException(name);
        _states.TryGetValue(name, out var state);
        var pid = state?.Pid ?? cfg.ProcessId;
        if (pid is null || !_identity.IsRunning(pid.Value))
        {
            await ClearPidAsync(name, ct);
            if (state is not null) { state.Status = "stopped"; state.Pid = null; state.CommandChannel = "none"; }
            return new { ok = true, message = "Not running" };
        }

        if (!string.IsNullOrWhiteSpace(cfg.StopCommand))
        {
            await SendCommandAsync(name, cfg.StopCommand, ct);
            for (var i = 0; i < 20; i++)
            {
                await Task.Delay(500, ct);
                if (!_identity.IsRunning(pid.Value)) break;
            }
        }
        else if (OperatingSystem.IsWindows())
        {
            _identity.SendCtrlC(pid.Value);
            await Task.Delay(5000, ct);
        }

        if (_identity.IsRunning(pid.Value))
        {
            try { state?.Process?.Kill(entireProcessTree: true); } catch { /* ignore */ }
            _identity.KillTree(pid.Value);
        }

        try { state?.Stdin?.Dispose(); } catch { /* ignore */ }
        if (state is not null)
        {
            state.Stdin = null;
            state.Process = null;
            state.Pid = null;
            state.Status = "stopped";
            state.Reattached = false;
            state.CommandChannel = "none";
            AppendConsole(state, $"--- Server stopped at {DateTime.Now:O} ---");
            await PersistConsoleAsync(state, ct);
        }
        await ClearPidAsync(name, ct);
        return new { ok = true, status = "stopped" };
    }

    public async Task<object> RestartAsync(string name, CancellationToken ct = default)
    {
        await StopAsync(name, ct);
        await Task.Delay(1000, ct);
        return await StartAsync(name, ct);
    }

    public async Task<object> GetConsoleAsync(string name, int lines = 100, CancellationToken ct = default)
    {
        var state = _states.GetOrAdd(name, _ => new ManagedServerState { Name = name });
        if (state.ConsoleBuffer.IsEmpty)
            await LoadConsoleFromDbAsync(state, ct);

        // Soft reattach when dashboard asks for console of a running server we forgot,
        // or after HostUI was closed/reopened while HostRuntime kept the process.
        if (state.Status != "running" || state.Pid is null || !_identity.IsRunning(state.Pid.Value))
        {
            try { await ReattachAsync(name, ct); } catch { /* config may not exist yet */ }
        }

        var all = state.ConsoleBuffer.ToArray();
        var slice = all.Skip(Math.Max(0, all.Length - lines)).ToArray();
        return new
        {
            server = name,
            lines = slice,
            seq = state.ConsoleSeq,
            command_channel = state.CommandChannel,
            reattached = state.Reattached,
            pid = state.Pid,
            status = state.Status
        };
    }

    public async Task<object> SendCommandAsync(string name, string command, CancellationToken ct = default)
    {
        var state = _states.GetOrAdd(name, _ => new ManagedServerState { Name = name });
        if (state.Pid is null || state.Status != "running")
        {
            try { await ReattachAsync(name, ct); } catch { /* ignore */ }
        }

        // 1) Live redirected stdin (best — owned by HostRuntime, survives dashboard close)
        if (state.Stdin is not null)
        {
            try
            {
                await state.Stdin.WriteLineAsync(command);
                await state.Stdin.FlushAsync();
                AppendConsole(state, $"> {command}");
                await PersistConsoleAsync(state, ct);
                return new { ok = true, channel = "stdin" };
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Stdin write failed for {Server}; falling back", name);
                try { state.Stdin.Dispose(); } catch { /* ignore */ }
                state.Stdin = null;
            }
        }

        // 2) AttachConsole for reattached Windows processes
        if (state.Pid is int pid && OperatingSystem.IsWindows())
        {
            if (_consoleSender.TrySend(pid, command))
            {
                state.CommandChannel = "attachconsole";
                AppendConsole(state, $"> {command}");
                await PersistConsoleAsync(state, ct);
                return new { ok = true, channel = "attachconsole" };
            }

            // Try launcher PID if we tracked JVM child
            if (state.Process is { HasExited: false } p && p.Id != pid && _consoleSender.TrySend(p.Id, command))
            {
                state.CommandChannel = "attachconsole";
                AppendConsole(state, $"> {command}");
                await PersistConsoleAsync(state, ct);
                return new { ok = true, channel = "attachconsole", pid = p.Id };
            }
        }

        return new
        {
            ok = false,
            message = "No command channel available. Start the server from HostRuntime so stdin is owned here, or ensure the process has an attachable console."
        };
    }

    public object Diagnostics()
    {
        return new
        {
            service = "host_runtime",
            started_at = _started,
            uptime_seconds = (int)(DateTime.UtcNow - _started).TotalSeconds,
            managed = _states.Count,
            note = "Dashboard/web never owns stdin; reopen dashboard and call reattach to resume consoles.",
            servers = _states.Select(kv => new
            {
                name = kv.Key,
                kv.Value.Status,
                kv.Value.Pid,
                kv.Value.CommandChannel,
                kv.Value.Reattached,
                console_seq = kv.Value.ConsoleSeq
            }).ToList()
        };
    }

    public async Task<object> InstallSteamAsync(string name, string appId, string installDir, CancellationToken ct = default)
    {
        var (user, pass) = ResolveSteamLogin();
        var (ok, output) = await _steam.InstallOrUpdateAsync(appId, installDir, user, pass, validate: true, ct: ct);
        if (!ok) return new { ok, output };
        await UpsertServerAsync(new ServerConfig
        {
            Name = name,
            ServerType = "steam",
            AppId = appId,
            InstallDir = installDir,
            StopCommand = null,
            Enabled = true
        }, ct);
        return new { ok = true, output };
    }

    public async Task<object> InstallMinecraftAsync(string name, string version, string installDir, CancellationToken ct = default)
    {
        var java = MinecraftInstaller.DetectJava();
        var (ok, msg) = await _minecraft.InstallVanillaAsync(installDir, version, java, ct);
        if (!ok) return new { ok, message = msg };
        await UpsertServerAsync(new ServerConfig
        {
            Name = name,
            ServerType = "minecraft",
            Version = version,
            InstallDir = installDir,
            Executable = "server.jar",
            JavaPath = java,
            StopCommand = "stop",
            Enabled = true
        }, ct);
        return new { ok = true, message = msg };
    }

    private async Task UpsertServerAsync(ServerConfig cfg, CancellationToken ct)
    {
        await using var scope = _scopeFactory.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<ServersDbContext>();
        var existing = await db.ServerConfigs.FirstOrDefaultAsync(s => s.Name == cfg.Name, ct);
        if (existing is null) db.ServerConfigs.Add(cfg);
        else
        {
            existing.ServerType = cfg.ServerType;
            existing.AppId = cfg.AppId;
            existing.InstallDir = cfg.InstallDir;
            existing.Executable = cfg.Executable;
            existing.Version = cfg.Version;
            existing.JavaPath = cfg.JavaPath;
            existing.StopCommand = cfg.StopCommand;
            existing.UpdatedAt = DateTime.UtcNow;
        }
        await db.SaveChangesAsync(ct);
    }

    private static (string FileName, string Args, bool UseStdin) BuildStartCommand(ServerConfig cfg)
    {
        var isMc = IsJavaServer(cfg);
        var exe = cfg.Executable ?? string.Empty;
        var install = cfg.InstallDir;

        // Project Zomboid: StartServer64.bat ends with PAUSE. Launch bundled JRE directly.
        // CRITICAL: keep an open stdin pipe (UseStdin=true). With CreateNoWindow and no stdin
        // redirect, Java sees EOF on System.in and GameServer's console thread QueuedQuit()s
        // right after SteamUtils init — looks like "stops after a few seconds".
        if (IsProjectZomboid(cfg, install, exe))
        {
            var java = Path.Combine(install, "jre64", "bin", "java.exe");
            if (!File.Exists(java))
                java = Path.Combine(install, "jre", "bin", "java.exe");
            if (File.Exists(java))
            {
                var cp = "java/;java/projectzomboid.jar";
                // Match StartServer64.bat heap; omit obsolete "-statistic 0" (unknown on B42).
                var mem = string.IsNullOrWhiteSpace(cfg.JvmArgs) ? "-Xms4g -Xmx8g" : cfg.JvmArgs.Trim();
                if (cfg.RamMb is int ram and > 0)
                    mem = $"-Xms{Math.Max(1, ram / 2)}M -Xmx{ram}M";
                var args =
                    "-Djava.awt.headless=true -Dzomboid.steam=1 -Dzomboid.znetlog=1 " +
                    "-XX:+UseZGC -XX:-CreateCoredumpOnCrash -XX:-OmitStackTraceInFastThrow " +
                    $"{mem} -Djava.library.path=natives/ -cp {cp} zombie.network.GameServer " +
                    (cfg.LaunchArgs ?? "").Trim();
                return (java, args.Trim(), UseStdin: true);
            }
        }

        if (isMc || exe.EndsWith(".jar", StringComparison.OrdinalIgnoreCase))
        {
            // Modpack launchers (run.bat / startserver.bat): prefer the bat so @user_jvm_args.txt works.
            if (exe.EndsWith(".bat", StringComparison.OrdinalIgnoreCase) || exe.EndsWith(".cmd", StringComparison.OrdinalIgnoreCase))
            {
                var path = Path.IsPathRooted(exe) ? exe : Path.Combine(install, exe);
                return ("cmd.exe", $"/c \"{path}\" {cfg.LaunchArgs}".Trim(), UseStdin: false);
            }

            var java = string.IsNullOrWhiteSpace(cfg.JavaPath) ? "java" : cfg.JavaPath;
            var jar = string.IsNullOrWhiteSpace(exe) ? "server.jar" : exe;
            var jarPath = Path.IsPathRooted(jar) ? jar : Path.Combine(install, jar);
            return (java, $"-Xmx1024M -Xms1024M -jar \"{jarPath}\" nogui", UseStdin: true);
        }

        if (exe.EndsWith(".bat", StringComparison.OrdinalIgnoreCase) || exe.EndsWith(".cmd", StringComparison.OrdinalIgnoreCase))
        {
            var path = Path.IsPathRooted(exe) ? exe : Path.Combine(install, exe);
            // Steam/game .bat launchers often break with redirected stdin (PZ, etc.).
            var useStdin = isMc;
            return ("cmd.exe", $"/c \"{path}\" {cfg.LaunchArgs}".Trim(), UseStdin: useStdin);
        }

        if (exe.EndsWith(".ps1", StringComparison.OrdinalIgnoreCase))
        {
            var path = Path.IsPathRooted(exe) ? exe : Path.Combine(install, exe);
            return ("powershell.exe", $"-NoProfile -ExecutionPolicy Bypass -File \"{path}\" {cfg.LaunchArgs}".Trim(), UseStdin: true);
        }

        if (exe.EndsWith(".sh", StringComparison.OrdinalIgnoreCase))
        {
            var path = Path.IsPathRooted(exe) ? exe : Path.Combine(install, exe);
            return ("/bin/bash", $"\"{path}\" {cfg.LaunchArgs}".Trim(), UseStdin: true);
        }

        var file = string.IsNullOrWhiteSpace(exe)
            ? throw new InvalidOperationException("Executable not set")
            : (Path.IsPathRooted(exe) ? exe : Path.Combine(install, exe));

        var launchArgs = cfg.LaunchArgs ?? string.Empty;
        if (Path.GetFileName(file).StartsWith("srcds", StringComparison.OrdinalIgnoreCase) && !launchArgs.Contains("-console", StringComparison.OrdinalIgnoreCase))
            launchArgs = $"-console -condebug {launchArgs}".Trim();
        if (Path.GetFileName(file).Equals("factorio.exe", StringComparison.OrdinalIgnoreCase) && !launchArgs.Contains("--console-log", StringComparison.OrdinalIgnoreCase))
            launchArgs = $"{launchArgs} --console-log \"{Path.Combine(install, "logs", "factorio-console.log")}\"".Trim();

        return (file, launchArgs, UseStdin: true);
    }

    private static bool IsProjectZomboid(ServerConfig cfg, string install, string exe)
    {
        if (cfg.Name.Contains("Zomboid", StringComparison.OrdinalIgnoreCase)) return true;
        if (install.Contains("Zomboid", StringComparison.OrdinalIgnoreCase)) return true;
        if (exe.Contains("StartServer64", StringComparison.OrdinalIgnoreCase)) return true;
        return string.Equals(cfg.AppId, "380870", StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>
    /// Servers that must own a real console (not redirected pipes). Redirected/CreateNoWindow
    /// launches cause Project Zomboid to QueuedQuit shortly after SteamUtils init.
    /// </summary>
    private static bool NeedsDedicatedConsole(ServerConfig cfg)
        => IsProjectZomboid(cfg, cfg.InstallDir ?? "", cfg.Executable ?? "");

    private static bool IsJavaServer(ServerConfig cfg)
        => cfg.ServerType.Contains("minecraft", StringComparison.OrdinalIgnoreCase)
           || (cfg.Executable?.EndsWith(".jar", StringComparison.OrdinalIgnoreCase) ?? false);

    private static long SafeWs(System.Diagnostics.Process p)
    {
        try { return p.WorkingSet64; } catch { return 0L; }
    }

    private Task<(string status, int? pid)> GetStatusInternalAsync(ServerConfig cfg, CancellationToken ct)
    {
        if (_states.TryGetValue(cfg.Name, out var state) && state.Pid is int live
            && _identity.IsRunning(live))
        {
            // Keep the existing PID unless it is a known helper wrapper
            var promote = false;
            try
            {
                var cur = System.Diagnostics.Process.GetProcessById(live);
                promote = ProcessIdentityService.IsHelperProcess(cur);
            }
            catch { promote = true; }

            var primary = promote
                ? (_identity.PromoteToPrimaryProcess(live, cfg.InstallDir, cfg.Executable) ?? live)
                : live;

            // JVM binaries live outside the install dir — BelongsToServer alone used to reject them as "stopped"
            if (IsJavaServer(cfg))
            {
                try
                {
                    var proc = System.Diagnostics.Process.GetProcessById(primary);
                    if (ProcessIdentityService.IsJavaProcess(proc)
                        || ProcessIdentityService.IsHelperProcess(proc))
                    {
                        var jvm = _identity.FindJavaChild(live)
                                  ?? _identity.FindJavaForServer(cfg.InstallDir, cfg.Executable);
                        if (jvm is int j)
                            primary = j;
                    }
                }
                catch { /* ignore */ }
            }

            // Ignore create-time skew after promotion; path/exe (or same live PID) is enough.
            if (_identity.BelongsToServer(primary, null, cfg.InstallDir, cfg.Executable)
                || _identity.BelongsToServer(live, null, cfg.InstallDir, cfg.Executable)
                || primary == live
                || (IsJavaServer(cfg) && _identity.IsRunning(primary)))
            {
                if (primary != state.Pid)
                {
                    state.Pid = primary;
                    state.CreateTime = _identity.GetCreateTime(primary);
                }
                state.Status = "running";
                return Task.FromResult(("running", (int?)primary));
            }
        }

        if (cfg.ProcessId is int pid && _identity.IsRunning(pid))
        {
            var promote = false;
            try
            {
                var cur = System.Diagnostics.Process.GetProcessById(pid);
                promote = ProcessIdentityService.IsHelperProcess(cur);
            }
            catch { promote = true; }

            var primary = promote
                ? (_identity.PromoteToPrimaryProcess(pid, cfg.InstallDir, cfg.Executable) ?? pid)
                : pid;

            if (IsJavaServer(cfg))
            {
                var jvm = _identity.FindJavaChild(pid)
                          ?? _identity.FindJavaForServer(cfg.InstallDir, cfg.Executable);
                if (jvm is int j)
                    primary = j;
            }

            if (_identity.BelongsToServer(primary, null, cfg.InstallDir, cfg.Executable)
                || _identity.BelongsToServer(pid, null, cfg.InstallDir, cfg.Executable)
                || primary == pid
                || (IsJavaServer(cfg) && _identity.IsRunning(primary)))
            {
                if (_states.TryGetValue(cfg.Name, out var st))
                {
                    st.Pid = primary;
                    st.Status = "running";
                    st.CreateTime = _identity.GetCreateTime(primary);
                }
                return Task.FromResult(("running", (int?)primary));
            }
        }

        // Expensive install-dir scan only when we have no live candidate (reattach / PID churn).
        // Throttle via state so dashboard refresh does not WMI-scan every process every few seconds.
        if (state is null)
            state = _states.GetOrAdd(cfg.Name, _ => new ManagedServerState { Name = cfg.Name });

        var now = DateTime.UtcNow;
        if (state.LastInstallScanUtc is null || (now - state.LastInstallScanUtc.Value) > TimeSpan.FromSeconds(15))
        {
            state.LastInstallScanUtc = now;
            var found = IsJavaServer(cfg)
                ? (_identity.FindJavaForServer(cfg.InstallDir, cfg.Executable)
                   ?? _identity.FindBestMatchingProcess(cfg.InstallDir, cfg.Executable))
                : _identity.FindBestMatchingProcess(cfg.InstallDir, cfg.Executable);
            if (found is int fp)
            {
                state.Pid = fp;
                state.CreateTime = _identity.GetCreateTime(fp);
                state.Status = "running";
                return Task.FromResult(("running", (int?)fp));
            }
        }
        else if (state.Pid is int cached && _identity.IsRunning(cached))
        {
            return Task.FromResult(("running", (int?)cached));
        }

        return Task.FromResult(("stopped", (int?)null));
    }

    public async Task<object> KillAsync(string name, CancellationToken ct = default)
    {
        var cfg = await GetConfigAsync(name, ct) ?? throw new KeyNotFoundException(name);
        _states.TryGetValue(name, out var state);
        var pid = state?.Pid ?? cfg.ProcessId;
        if (pid is int p && _identity.IsRunning(p))
        {
            try { state?.Process?.Kill(entireProcessTree: true); } catch { /* ignore */ }
            _identity.KillTree(p);
        }
        try { state?.Stdin?.Dispose(); } catch { /* ignore */ }
        if (state is not null)
        {
            state.Stdin = null;
            state.Process = null;
            state.Pid = null;
            state.Status = "stopped";
            state.CommandChannel = "none";
        }
        await ClearPidAsync(name, ct);
        return new { ok = true, killed = true };
    }

    public async Task<object> ClearAsync(string name, CancellationToken ct = default)
    {
        _states.TryRemove(name, out var state);
        if (state is not null)
        {
            try { state.Stdin?.Dispose(); } catch { /* ignore */ }
            state.ConsoleBuffer.Clear();
        }
        await ClearPidAsync(name, ct);
        return new { ok = true, cleared = true };
    }

    public async Task<object> GetProcessDetailsAsync(string name, CancellationToken ct = default)
    {
        var cfg = await GetConfigAsync(name, ct) ?? throw new KeyNotFoundException(name);
        var status = await GetStatusInternalAsync(cfg, ct);
        if (status.pid is not int pid)
            return new { name, status = status.status, running = false };
        try
        {
            var p = System.Diagnostics.Process.GetProcessById(pid);
            string? path = null;
            try { path = p.MainModule?.FileName; } catch { /* access */ }
            return new
            {
                name,
                running = true,
                pid,
                processName = p.ProcessName,
                startTime = p.StartTime,
                memoryMb = p.WorkingSet64 / (1024.0 * 1024.0),
                path,
                installDir = cfg.InstallDir,
                executable = cfg.Executable
            };
        }
        catch (Exception ex)
        {
            return new { name, pid, error = ex.Message };
        }
    }

    public async Task<object> FindBrokenAsync(CancellationToken ct = default)
    {
        await using var scope = _scopeFactory.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<ServersDbContext>();
        var servers = await db.ServerConfigs.AsNoTracking().Where(s => s.Enabled).ToListAsync(ct);
        var broken = servers
            .Where(s => string.IsNullOrWhiteSpace(s.InstallDir) || !Directory.Exists(s.InstallDir)
                        || (string.IsNullOrWhiteSpace(s.Executable) && !s.ServerType.Contains("minecraft", StringComparison.OrdinalIgnoreCase)))
            .Select(s => new { s.Name, s.InstallDir, s.Executable, reason = "missing install dir or executable" })
            .ToList();
        return new { count = broken.Count, servers = broken };
    }

    public async Task<object> VerifyServersAsync(CancellationToken ct = default)
    {
        await using var scope = _scopeFactory.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<ServersDbContext>();
        var servers = await db.ServerConfigs.AsNoTracking().ToListAsync(ct);
        var rows = new List<object>();
        foreach (var s in servers)
        {
            var status = await GetStatusInternalAsync(s, ct);
            rows.Add(new
            {
                s.Name,
                s.Enabled,
                installExists = !string.IsNullOrWhiteSpace(s.InstallDir) && Directory.Exists(s.InstallDir),
                status = status.status,
                pid = status.pid
            });
        }
        return new { count = rows.Count, servers = rows };
    }

    public async Task<object> DbMaintenanceAsync(string action, CancellationToken ct = default)
    {
        await using var scope = _scopeFactory.CreateAsyncScope();
        var servers = scope.ServiceProvider.GetRequiredService<ServersDbContext>();
        var users = scope.ServiceProvider.GetRequiredService<UsersDbContext>();
        var cluster = scope.ServiceProvider.GetRequiredService<ClusterDbContext>();
        await servers.Database.ExecuteSqlRawAsync("PRAGMA wal_checkpoint(TRUNCATE);", ct);
        await users.Database.ExecuteSqlRawAsync("PRAGMA wal_checkpoint(TRUNCATE);", ct);
        await cluster.Database.ExecuteSqlRawAsync("PRAGMA wal_checkpoint(TRUNCATE);", ct);
        var serverCount = await servers.ServerConfigs.CountAsync(ct);
        var userCount = await users.Users.CountAsync(ct);
        var message = action.Equals("verify", StringComparison.OrdinalIgnoreCase)
            ? "Databases reachable (checkpoint verified)."
            : "Database checkpoint complete (WAL truncated). This is not a game/catalog update.";
        return new { ok = true, action = action.Equals("verify", StringComparison.OrdinalIgnoreCase) ? "verify" : "checkpoint", serverCount, userCount, message };
    }

    public async Task<object> UpdateServerAsync(string name, CancellationToken ct = default)
    {
        var cfg = await GetConfigAsync(name, ct) ?? throw new KeyNotFoundException(name);
        if (string.Equals(cfg.ServerType, "steam", StringComparison.OrdinalIgnoreCase))
        {
            if (string.IsNullOrWhiteSpace(cfg.AppId) || string.IsNullOrWhiteSpace(cfg.InstallDir))
                return new { ok = false, name, message = "Steam server missing AppId or InstallDir." };
            var (user, pass) = ResolveSteamLogin();
            var (ok, output) = await _steam.InstallOrUpdateAsync(cfg.AppId!, cfg.InstallDir, user, pass, validate: false, ct: ct);
            var hint = "";
            if (!ok && (output.Contains("No subscription", StringComparison.OrdinalIgnoreCase)
                        || output.Contains("Invalid Password", StringComparison.OrdinalIgnoreCase)
                        || output.Contains("Login Failure", StringComparison.OrdinalIgnoreCase)))
            {
                hint = user is null
                    ? " SteamCMD used anonymous login — set Steam username/password under Settings → Steam (SteamAnon=false)."
                    : " Check Steam credentials under Settings → Steam.";
            }
            return new { ok, name, message = (ok ? "Steam update finished." : "Steam update failed.") + hint, output };
        }
        if (string.Equals(cfg.ServerType, "minecraft", StringComparison.OrdinalIgnoreCase)
            || string.Equals(cfg.ServerType, "minecraft_modded", StringComparison.OrdinalIgnoreCase))
        {
            return new { ok = false, name, message = "Minecraft auto-update is not wired yet; reinstall via Create/Install." };
        }
        return new { ok = false, name, message = $"No update handler for type '{cfg.ServerType}'." };
    }

    /// <summary>Resolve SteamCMD login from Settings (SteamAnon / SteamUsername / SteamPassword).</summary>
    private (string? Username, string? PasswordOrProtected) ResolveSteamLogin()
    {
        var anon = string.Equals(_cfg.Get("SteamAnon") ?? _cfg.Get("SteamAnonymous"), "true", StringComparison.OrdinalIgnoreCase);
        if (anon) return (null, null);
        var user = (_cfg.Get("SteamUsername") ?? "").Trim();
        if (string.IsNullOrWhiteSpace(user))
        {
            _logger.LogWarning(
                "SteamAnon is false but SteamUsername is empty — falling back to anonymous (many app_updates will fail with No subscription)");
            return (null, null);
        }
        var pass = _cfg.Get("SteamPassword");
        return (user, string.IsNullOrWhiteSpace(pass) ? null : pass);
    }

    public async Task<object> UpdateAllAsync(CancellationToken ct = default)
    {
        await using var scope = _scopeFactory.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<ServersDbContext>();
        var servers = await db.ServerConfigs.AsNoTracking().Where(s => s.Enabled).ToListAsync(ct);
        var results = new List<object>();
        var updated = 0;
        var failed = 0;
        foreach (var s in servers)
        {
            try
            {
                var r = await UpdateServerAsync(s.Name, ct);
                results.Add(r);
                var okProp = r.GetType().GetProperty("ok")?.GetValue(r);
                if (okProp is true) updated++; else failed++;
            }
            catch (Exception ex)
            {
                failed++;
                results.Add(new { ok = false, name = s.Name, message = ex.Message });
            }
        }
        return new
        {
            ok = failed == 0,
            updated,
            failed,
            count = servers.Count,
            message = $"Update All finished: {updated} ok, {failed} failed of {servers.Count}.",
            results
        };
    }

    private async Task<ServerConfig?> GetConfigAsync(string name, CancellationToken ct)
    {
        await using var scope = _scopeFactory.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<ServersDbContext>();
        return await db.ServerConfigs.FirstOrDefaultAsync(s => s.Name == name, ct);
    }

    private async Task PersistPidAsync(string name, int? pid, DateTime? createTime, CancellationToken ct)
    {
        await using var scope = _scopeFactory.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<ServersDbContext>();
        var cfg = await db.ServerConfigs.FirstOrDefaultAsync(s => s.Name == name, ct);
        if (cfg is null) return;
        cfg.ProcessId = pid;
        cfg.ProcessCreateTime = createTime;
        cfg.UpdatedAt = DateTime.UtcNow;
        await db.SaveChangesAsync(ct);
    }

    private async Task ClearPidAsync(string name, CancellationToken ct) => await PersistPidAsync(name, null, null, ct);

    private void AppendConsole(ManagedServerState state, string line)
    {
        state.ConsoleBuffer.Enqueue(line);
        state.ConsoleSeq++;
        while (state.ConsoleBuffer.Count > MaxConsoleLines)
            state.ConsoleBuffer.TryDequeue(out _);
    }

    private async Task LoadConsoleFromDbAsync(ManagedServerState state, CancellationToken ct)
    {
        try
        {
            await using var scope = _scopeFactory.CreateAsyncScope();
            var db = scope.ServiceProvider.GetRequiredService<ConsoleDbContext>();
            var row = await db.ConsoleStates.AsNoTracking().FirstOrDefaultAsync(c => c.ServerName == state.Name, ct);
            if (row is null || string.IsNullOrWhiteSpace(row.BufferJson)) return;
            var lines = ParseConsoleBufferJson(row.BufferJson);
            if (state.ConsoleBuffer.IsEmpty)
            {
                foreach (var line in lines.TakeLast(MaxConsoleLines))
                    state.ConsoleBuffer.Enqueue(line);
                state.ConsoleSeq = Math.Max(state.ConsoleSeq, state.ConsoleBuffer.Count);
            }
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Load console DB failed for {Server}", state.Name);
        }
    }

    /// <summary>Accepts C# string[] or legacy Python objects with a "text" field.</summary>
    private static List<string> ParseConsoleBufferJson(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            if (doc.RootElement.ValueKind != JsonValueKind.Array)
                return new List<string>();
            var lines = new List<string>();
            foreach (var el in doc.RootElement.EnumerateArray())
            {
                if (el.ValueKind == JsonValueKind.String)
                {
                    var s = el.GetString();
                    if (!string.IsNullOrEmpty(s)) lines.Add(s);
                }
                else if (el.ValueKind == JsonValueKind.Object &&
                         el.TryGetProperty("text", out var text) &&
                         text.ValueKind == JsonValueKind.String)
                {
                    var s = text.GetString();
                    if (!string.IsNullOrEmpty(s)) lines.Add(s);
                }
            }
            return lines;
        }
        catch
        {
            return new List<string>();
        }
    }

    private async Task PersistConsoleAsync(ManagedServerState state, CancellationToken ct)
    {
        try
        {
            await using var scope = _scopeFactory.CreateAsyncScope();
            var db = scope.ServiceProvider.GetRequiredService<ConsoleDbContext>();
            var json = JsonSerializer.Serialize(state.ConsoleBuffer.ToArray().TakeLast(MaxConsoleLines).ToArray());
            var row = await db.ConsoleStates.FirstOrDefaultAsync(c => c.ServerName == state.Name, ct);
            if (row is null)
            {
                db.ConsoleStates.Add(new ConsoleStateEntry
                {
                    ServerName = state.Name,
                    BufferJson = json,
                    UpdatedAt = DateTime.UtcNow
                });
            }
            else
            {
                row.BufferJson = json;
                row.UpdatedAt = DateTime.UtcNow;
            }
            await db.SaveChangesAsync(ct);
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Persist console failed for {Server}", state.Name);
        }
    }

    private static Task EnsureLogTailTargetAsync(ManagedServerState state, string installDir, bool preferGameLog = false)
    {
        // Project Zomboid writes the live console under the user profile, not install\logs.
        var zomboidConsole = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            "Zomboid", "server-console.txt");
        if (File.Exists(zomboidConsole)
            && (state.Name.Contains("Zomboid", StringComparison.OrdinalIgnoreCase)
                || installDir.Contains("Zomboid", StringComparison.OrdinalIgnoreCase)))
        {
            if (!string.Equals(state.StdoutLog, zomboidConsole, StringComparison.OrdinalIgnoreCase))
            {
                state.StdoutLog = zomboidConsole;
                var len = new FileInfo(zomboidConsole).Length;
                state.StdoutPosition = Math.Max(0, len - 64 * 1024);
            }
            return Task.CompletedTask;
        }

        var logs = Path.Combine(installDir, "logs");

        // Minecraft writes logs/latest.log — prefer it so console keeps updating after launcher handoff
        if (preferGameLog && Directory.Exists(logs))
        {
            var latestLog = Path.Combine(logs, "latest.log");
            if (File.Exists(latestLog))
            {
                if (!string.Equals(state.StdoutLog, latestLog, StringComparison.OrdinalIgnoreCase))
                {
                    state.StdoutLog = latestLog;
                    var len = new FileInfo(latestLog).Length;
                    state.StdoutPosition = Math.Max(0, len - 32 * 1024);
                }
                return Task.CompletedTask;
            }
        }

        if (state.StdoutLog is not null && File.Exists(state.StdoutLog))
        {
            // If redirected stdout stalled, fall through to newest game log
            try
            {
                var age = DateTime.UtcNow - File.GetLastWriteTimeUtc(state.StdoutLog);
                if (age < TimeSpan.FromSeconds(45) || !Directory.Exists(logs))
                    return Task.CompletedTask;
            }
            catch { return Task.CompletedTask; }
        }

        if (!Directory.Exists(logs)) return Task.CompletedTask;

        var latest = Directory.GetFiles(logs, "server_stdout_*.log")
            .OrderByDescending(File.GetLastWriteTimeUtc)
            .FirstOrDefault();
        if (latest is null)
        {
            latest = Directory.GetFiles(logs, "latest.log")
                .Concat(Directory.GetFiles(logs, "*.log"))
                .OrderByDescending(File.GetLastWriteTimeUtc)
                .FirstOrDefault();
        }

        if (latest is not null)
        {
            state.StdoutLog = latest;
            var len = new FileInfo(latest).Length;
            state.StdoutPosition = Math.Max(0, len - 32 * 1024);
        }
        return Task.CompletedTask;
    }

    private void SeedConsoleFromLogTail(ManagedServerState state, int maxLines)
    {
        if (state.StdoutLog is null || !File.Exists(state.StdoutLog)) return;
        try
        {
            var lines = File.ReadLines(state.StdoutLog).Where(l => !IsNoise(l)).TakeLast(maxLines).ToList();
            if (!state.ConsoleBuffer.IsEmpty) return;
            foreach (var line in lines)
                AppendConsole(state, line);
            state.StdoutPosition = new FileInfo(state.StdoutLog).Length;
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Seed console from log failed for {Server}", state.Name);
        }
    }

    private int? FindLivePidByInstallDir(ServerConfig cfg)
        => _identity.FindBestMatchingProcess(cfg.InstallDir, cfg.Executable);

    private async Task TailLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                foreach (var kv in _states)
                {
                    var state = kv.Value;
                    // Refresh log target periodically (MC latest.log, stalled stdout pipes)
                    if (_hideTick % 10 == 0)
                    {
                        try
                        {
                            await using var scope = _scopeFactory.CreateAsyncScope();
                            var db = scope.ServiceProvider.GetRequiredService<ServersDbContext>();
                            var cfg = await db.ServerConfigs.AsNoTracking()
                                .FirstOrDefaultAsync(s => s.Name == state.Name, ct);
                            if (cfg is not null)
                                await EnsureLogTailTargetAsync(state, cfg.InstallDir, preferGameLog: IsJavaServer(cfg));
                        }
                        catch { /* ignore */ }
                    }

                    if (state.StdoutLog is null || !File.Exists(state.StdoutLog)) continue;
                    await using var fs = new FileStream(state.StdoutLog, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
                    if (fs.Length < state.StdoutPosition) state.StdoutPosition = 0;
                    fs.Seek(state.StdoutPosition, SeekOrigin.Begin);
                    using var reader = new StreamReader(fs, Encoding.UTF8);
                    while (await reader.ReadLineAsync(ct) is { } line)
                    {
                        if (IsNoise(line)) continue;
                        AppendConsole(state, line);
                    }
                    state.StdoutPosition = fs.Position;
                    // Persistence is handled by PersistLoopAsync (every 10s) to avoid DB thrash
                }
            }
            catch (Exception ex)
            {
                _logger.LogDebug(ex, "Console tailer tick failed");
            }

            // Keep game consoles hidden (Palworld/7DTD/etc. often AllocConsole after start)
            if (++_hideTick % 4 == 0 && ShouldHideConsoles())
            {
                foreach (var kv in _states)
                {
                    if (kv.Value.Pid is int pid && string.Equals(kv.Value.Status, "running", StringComparison.OrdinalIgnoreCase))
                    {
                        try { ProcessWindowHider.HideForProcessTree(pid, _identity); }
                        catch { /* ignore */ }
                    }
                }
            }

            await Task.Delay(500, ct);
        }
    }

    private bool ShouldHideConsoles()
    {
        var now = DateTime.UtcNow;
        if ((now - _hideConsolesCachedUtc).TotalSeconds < 20)
            return _hideConsolesCached;
        _hideConsolesCachedUtc = now;
        try
        {
            var v = _cfg.Get("HideConsoles");
            _hideConsolesCached = string.IsNullOrWhiteSpace(v)
                                  || v.Equals("true", StringComparison.OrdinalIgnoreCase)
                                  || v == "1";
        }
        catch
        {
            _hideConsolesCached = true;
        }
        return _hideConsolesCached;
    }

    private void ScheduleHideConsoles(int rootPid)
    {
        if (!ShouldHideConsoles()) return;
        _ = Task.Run(async () =>
        {
            try
            {
                // Games often create their console a few seconds after launch
                for (var i = 0; i < 20; i++)
                {
                    ProcessWindowHider.HideForProcessTree(rootPid, _identity);
                    await Task.Delay(750);
                }
            }
            catch (Exception ex)
            {
                _logger.LogDebug(ex, "ScheduleHideConsoles failed for PID {Pid}", rootPid);
            }
        });
    }

    private async Task PersistLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                foreach (var kv in _states)
                {
                    if (!kv.Value.ConsoleBuffer.IsEmpty)
                        await PersistConsoleAsync(kv.Value, ct);
                }
            }
            catch (Exception ex)
            {
                _logger.LogDebug(ex, "Console persist loop failed");
            }
            await Task.Delay(TimeSpan.FromSeconds(10), ct);
        }
    }

    private static bool IsNoise(string line)
        => line.Contains("Setting breakpad minidump", StringComparison.OrdinalIgnoreCase)
           || line.Contains("SteamInternal_SetMinidumpSteamID", StringComparison.OrdinalIgnoreCase);

    public void Dispose()
    {
        _tailCts.Cancel();
        try { Task.WaitAll(new[] { _tailTask, _persistTask }, 2000); } catch { /* ignore */ }
        _tailCts.Dispose();
    }
}

/// <summary>On HostRuntime boot, reattach to any still-running game servers so consoles survive runtime restarts.
/// Runs in the background so Kestrel can bind /health immediately (HostUI login must not wait on reattach).</summary>
public sealed class ServerReattachHostedService : BackgroundService
{
    private readonly IGameServerHost _host;
    private readonly ILogger<ServerReattachHostedService> _logger;

    public ServerReattachHostedService(IGameServerHost host, ILogger<ServerReattachHostedService> logger)
    {
        _host = host;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        // Let Kestrel start listening before heavy reattach work.
        try { await Task.Delay(1500, stoppingToken); }
        catch (OperationCanceledException) { return; }

        try
        {
            var result = await _host.ReattachAllAsync(stoppingToken);
            _logger.LogInformation("Startup reattach completed: {Result}", result);
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { /* shutting down */ }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Startup reattach failed");
        }
    }
}
