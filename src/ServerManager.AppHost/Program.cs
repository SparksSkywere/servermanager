using System.Diagnostics;
using Microsoft.Extensions.Options;
using ServerManager.Automation;
using ServerManager.Core;
using ServerManager.Core.Configuration;
using ServerManager.Core.Paths;
using ServerManager.Core.Process;
using ServerManager.Data;
using Serilog;

namespace ServerManager.AppHost;

public class Program
{
    public static async Task Main(string[] args)
    {
        var builder = Host.CreateApplicationBuilder(args);

        var root = RuntimeRootResolver.Resolve(builder.Configuration);
        builder.Configuration.AddJsonFile(Path.Combine(root, "config", "appsettings.json"), optional: true, reloadOnChange: true);
        // Re-resolve after optional runtime config (may set RootPath explicitly)
        root = RuntimeRootResolver.Resolve(builder.Configuration);

        builder.Services.Configure<ServerManagerOptions>(builder.Configuration.GetSection(ServerManagerOptions.SectionName));
        builder.Services.PostConfigure<ServerManagerOptions>(o =>
        {
            if (string.IsNullOrWhiteSpace(o.RootPath)) o.RootPath = root;
        });

        builder.Services.AddServerManagerCore();
        builder.Services.AddServerManagerData();
        builder.Services.AddServerManagerAutomation();
        builder.Services.AddSingleton<ChildProcessSupervisor>();
        builder.Services.AddHostedService<AppHostWorker>();

        if (OperatingSystem.IsWindows())
            builder.Services.AddWindowsService(o => o.ServiceName = "ServerManagerService");

        var early = new AppPaths(Options.Create(new ServerManagerOptions { RootPath = root }));
        early.EnsureDirectories();
        ServiceCollectionExtensions.ConfigureServerManagerLogging("AppHost", early);
        builder.Services.AddLogging(b => b.AddServerManagerSerilog());

        var host = builder.Build();

        using (var scope = host.Services.CreateScope())
        {
            var paths = scope.ServiceProvider.GetRequiredService<IAppPaths>();
            paths.EnsureDirectories();
            var pids = scope.ServiceProvider.GetRequiredService<PidFileManager>();
            pids.CleanupStale();
            if (pids.AnyCoreComponentRunning("apphost") && !args.Contains("--force"))
            {
                Log.Warning("Another Server Manager core component is running. Use --force to override.");
                // Still continue when running as a Windows Service — otherwise the service stays dead.
                if (!WindowsServiceHelpers.IsWindowsService())
                    return;
            }
            pids.Write("apphost", Environment.ProcessId);
            await scope.ServiceProvider.GetRequiredService<DatabaseInitializer>().InitializeAsync();
        }

        await host.RunAsync();
    }

    /// <summary>Legacy helper kept for tests; prefers installed {base}\runtime.</summary>
    internal static string ResolveRuntimeRoot() => RuntimeRootResolver.Resolve();
}

internal static class WindowsServiceHelpers
{
    public static bool IsWindowsService()
    {
        if (!OperatingSystem.IsWindows()) return false;
        try
        {
            if (!Environment.UserInteractive) return true;
        }
        catch { /* ignore */ }
        return false;
    }
}

public sealed class ChildProcessSupervisor
{
    private readonly IAppPaths _paths;
    private readonly IOptions<ServerManagerOptions> _options;
    private readonly ILogger<ChildProcessSupervisor> _logger;
    private readonly Dictionary<string, ProcessSlot> _slots = new(StringComparer.OrdinalIgnoreCase);

    private sealed class ProcessSlot
    {
        public Process? Process { get; set; }
        public int Restarts { get; set; }
        public string Exe { get; set; } = "";
        public string Args { get; set; } = "";
    }

    public ChildProcessSupervisor(IAppPaths paths, IOptions<ServerManagerOptions> options, ILogger<ChildProcessSupervisor> logger)
    {
        _paths = paths;
        _options = options;
        _logger = logger;
    }

    public void StartDefaults()
    {
        var publishDir = AppContext.BaseDirectory;
        var hostRuntimeExe = Path.Combine(publishDir, "ServerManager.HostRuntime.exe");
        var webExe = Path.Combine(publishDir, "ServerManager.Web.exe");
        var trayExe = Path.Combine(publishDir, "ServerManager.Tray.exe");

        if (File.Exists(hostRuntimeExe) && File.Exists(webExe))
        {
            _logger.LogInformation("Starting children from published exes in {Dir}", publishDir);
            StartOrTrack("hostruntime", hostRuntimeExe, "", maxRestarts: 3);
            StartOrTrack("web", webExe, "", maxRestarts: 3);
            if (OperatingSystem.IsWindows() && Environment.UserInteractive && File.Exists(trayExe))
                StartOrTrack("tray", trayExe, "", maxRestarts: 1);
            return;
        }

        // Dev fallback: dotnet run against source projects
        var repoRoot = Path.GetFullPath(Path.Combine(_paths.Root, ".."));
        var src = Path.Combine(repoRoot, "src");
        var hostRuntime = Path.Combine(src, "ServerManager.HostRuntime");
        var web = Path.Combine(src, "ServerManager.Web");
        var tray = Path.Combine(src, "ServerManager.Tray");

        _logger.LogWarning("Published exes not found beside AppHost; falling back to dotnet run");
        StartOrTrack("hostruntime", "dotnet", $"run --project \"{hostRuntime}\" --no-build", maxRestarts: 3);
        StartOrTrack("web", "dotnet", $"run --project \"{web}\" --no-build", maxRestarts: 3);
        if (OperatingSystem.IsWindows() && Environment.UserInteractive)
            StartOrTrack("tray", "dotnet", $"run --project \"{tray}\" --no-build", maxRestarts: 1);
    }

    public void StartOrTrack(string name, string fileName, string args, int maxRestarts)
    {
        _slots[name] = new ProcessSlot { Exe = fileName, Args = args, Restarts = 0 };
        Launch(name, maxRestarts);
    }

    private void Launch(string name, int maxRestarts)
    {
        if (!_slots.TryGetValue(name, out var slot)) return;
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = slot.Exe,
                Arguments = slot.Args,
                WorkingDirectory = AppContext.BaseDirectory,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            psi.Environment["ServerManager__RootPath"] = _paths.Root;
            psi.Environment["ServerManager__WebPort"] = _options.Value.WebPort.ToString();
            psi.Environment["ServerManager__HostRuntimePort"] = _options.Value.HostRuntimePort.ToString();
            psi.Environment["ServerManager__ClusterPort"] = _options.Value.ClusterPort.ToString();

            slot.Process = Process.Start(psi);
            _logger.LogInformation("Started {Name} PID={Pid}", name, slot.Process?.Id);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to start {Name}", name);
        }
    }

    public void Supervise(int maxRestarts = 3)
    {
        foreach (var kv in _slots.ToList())
        {
            var slot = kv.Value;
            if (slot.Process is null || slot.Process.HasExited)
            {
                if (slot.Restarts >= maxRestarts)
                {
                    _logger.LogError("{Name} exceeded restart limit", kv.Key);
                    continue;
                }
                slot.Restarts++;
                _logger.LogWarning("Restarting {Name} (attempt {N})", kv.Key, slot.Restarts);
                Launch(kv.Key, maxRestarts);
            }
        }
    }

    public async Task StopAllAsync()
    {
        foreach (var kv in _slots)
        {
            try
            {
                if (kv.Key.Equals("hostruntime", StringComparison.OrdinalIgnoreCase) && kv.Value.Process is { HasExited: false })
                {
                    try
                    {
                        using var http = new HttpClient { BaseAddress = new Uri(RuntimeUrls.HostRuntimeBase(_options.Value)), Timeout = TimeSpan.FromSeconds(5) };
                        await http.PostAsync("/api/runtime/shutdown", null);
                        await Task.Delay(1500);
                    }
                    catch { /* fall through */ }
                }

                if (kv.Value.Process is { HasExited: false } p)
                {
                    p.Kill(entireProcessTree: true);
                    await p.WaitForExitAsync();
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Error stopping {Name}", kv.Key);
            }
        }
    }
}

public sealed class AppHostWorker : BackgroundService
{
    private readonly ChildProcessSupervisor _supervisor;
    private readonly PidFileManager _pids;
    private readonly ILogger<AppHostWorker> _logger;

    public AppHostWorker(ChildProcessSupervisor supervisor, PidFileManager pids, ILogger<AppHostWorker> logger)
    {
        _supervisor = supervisor;
        _pids = pids;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var hostRuntimeExe = Path.Combine(AppContext.BaseDirectory, "ServerManager.HostRuntime.exe");
        if (!File.Exists(hostRuntimeExe))
        {
            // Dev only: ensure projects are built for `dotnet run --no-build`
            try
            {
                var repoRoot = Path.GetFullPath(Path.Combine(_pathsRootGuess(), "ServerManager.sln"));
                if (File.Exists(repoRoot))
                {
                    var build = Process.Start(new ProcessStartInfo
                    {
                        FileName = "dotnet",
                        Arguments = $"build \"{repoRoot}\" -c Debug --verbosity minimal",
                        UseShellExecute = false,
                        CreateNoWindow = true
                    });
                    build?.WaitForExit(180000);
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Initial solution build failed; children may use `dotnet run` with build");
            }
        }

        _supervisor.StartDefaults();
        while (!stoppingToken.IsCancellationRequested)
        {
            _supervisor.Supervise();
            await Task.Delay(TimeSpan.FromSeconds(5), stoppingToken);
        }
    }

    private static string _pathsRootGuess()
    {
        var fromDist = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", ".."));
        if (File.Exists(Path.Combine(fromDist, "ServerManager.sln"))) return fromDist;
        return Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", ".."));
    }

    public override async Task StopAsync(CancellationToken cancellationToken)
    {
        _logger.LogInformation("AppHost stopping children");
        await _supervisor.StopAllAsync();
        _pids.Remove("apphost");
        await base.StopAsync(cancellationToken);
    }
}
