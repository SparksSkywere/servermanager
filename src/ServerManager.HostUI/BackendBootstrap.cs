using System.Diagnostics;
using System.ServiceProcess;
using Microsoft.Win32;

namespace ServerManager.HostUI;

/// <summary>
/// Ensures AppHost (and therefore Web + HostRuntime) is up before the UI talks to APIs.
/// Login only needs Web; HostRuntime is preferred but not required to pass the gate.
/// </summary>
internal static class BackendBootstrap
{
    private const string ServiceName = "ServerManagerService";

    public static async Task<(bool Ok, string Message)> EnsureRunningAsync(ApiClient api, Action<string>? status = null, CancellationToken ct = default)
    {
        var (web, rt) = await ProbeAsync(api, ct);
        if (web)
            return (true, rt
                ? "Backend already running."
                : "Web API ready (Host Runtime still starting — dashboard metrics may be delayed).");

        status?.Invoke("Backend not running — starting Server Manager…");

        if (!TryStartService(out var serviceMsg))
        {
            if (!TryStartAppHost(out var appMsg))
                return (false, $"Could not start backend.\n{serviceMsg}\n{appMsg}");
        }

        var deadline = DateTime.UtcNow.AddSeconds(30);
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            (web, rt) = await ProbeAsync(api, ct);
            if (web)
                return (true, rt ? "Backend started." : "Web API ready — you can sign in.");
            status?.Invoke($"Waiting for Web API… ({PortConfig.WebBase})  Runtime={(rt ? "ok" : "…")}");
            await Task.Delay(750, ct);
        }

        // Last chance: if the Windows service is running, allow login attempt anyway.
        if (IsServiceRunning())
            return (true, $"Service is running but health checks timed out.\nWeb: {PortConfig.WebBase}\nRuntime: {PortConfig.HostRuntimeBase}\nYou can still try signing in.");

        return (false,
            $"Server Manager did not become ready in time.\n" +
            $"Web ({PortConfig.WebBase}): {(web ? "ok" : "not responding")}\n" +
            $"Runtime ({PortConfig.HostRuntimeBase}): {(rt ? "ok" : "not responding")}\n" +
            "Check that ServerManagerService / ServerManager.exe is running.");
    }

    private static async Task<(bool Web, bool Runtime)> ProbeAsync(ApiClient api, CancellationToken ct)
    {
        var webTask = api.HealthWebAsync(ct);
        var rtTask = api.HealthRuntimeAsync(ct);
        await Task.WhenAll(webTask, rtTask).ConfigureAwait(false);
        return (await webTask.ConfigureAwait(false), await rtTask.ConfigureAwait(false));
    }

    private static bool IsServiceRunning()
    {
        if (!OperatingSystem.IsWindows()) return false;
        try
        {
#pragma warning disable CA1416
            using var sc = new ServiceController(ServiceName);
            return sc.Status is ServiceControllerStatus.Running or ServiceControllerStatus.StartPending;
#pragma warning restore CA1416
        }
        catch { return false; }
    }

    private static bool TryStartService(out string message)
    {
        message = "";
        if (!OperatingSystem.IsWindows()) { message = "Not Windows."; return false; }
        try
        {
#pragma warning disable CA1416
            using var sc = new ServiceController(ServiceName);
            if (sc.Status is ServiceControllerStatus.Running or ServiceControllerStatus.StartPending)
            {
                message = "Service already running/starting.";
                return true;
            }
            sc.Start();
            sc.WaitForStatus(ServiceControllerStatus.Running, TimeSpan.FromSeconds(30));
            message = "Service started.";
            return true;
#pragma warning restore CA1416
        }
        catch (InvalidOperationException ex)
        {
            message = "Service not installed: " + ex.Message;
            return false;
        }
        catch (Exception ex)
        {
            message = "Service start failed: " + ex.Message;
            return false;
        }
    }

    private static bool TryStartAppHost(out string message)
    {
        message = "";
        try
        {
            foreach (var p in Process.GetProcessesByName("ServerManager"))
            {
                var path = SafePath(p);
                if (path is not null && path.EndsWith("ServerManager.exe", StringComparison.OrdinalIgnoreCase)
                    && !path.Contains("system32", StringComparison.OrdinalIgnoreCase))
                {
                    message = "AppHost process already present.";
                    return true;
                }
            }

            var exe = ResolveAppHostExe();
            if (exe is null || !File.Exists(exe))
            {
                message = "ServerManager.exe not found beside HostUI or in InstallPath.";
                return false;
            }

            var installDir = Path.GetDirectoryName(exe)!;
            var runtime = Path.Combine(installDir, "runtime");
            var psi = new ProcessStartInfo
            {
                FileName = exe,
                WorkingDirectory = installDir,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            psi.Environment["ServerManager__RootPath"] = runtime;
            Process.Start(psi);
            message = "Started " + exe;
            return true;
        }
        catch (Exception ex)
        {
            message = "AppHost start failed: " + ex.Message;
            return false;
        }
    }

    private static string? ResolveAppHostExe()
    {
        var beside = Path.Combine(AppContext.BaseDirectory, "ServerManager.exe");
        if (File.Exists(beside)) return beside;

        try
        {
            using var key = Registry.LocalMachine.OpenSubKey(@"Software\SkywereIndustries\Servermanager");
            var install = key?.GetValue("InstallPath") as string;
            if (!string.IsNullOrWhiteSpace(install))
            {
                var candidate = Path.Combine(install, "ServerManager.exe");
                if (File.Exists(candidate)) return candidate;
            }
        }
        catch { /* optional */ }

        return null;
    }

    private static string? SafePath(Process p)
    {
        try { return p.MainModule?.FileName; }
        catch { return null; }
    }
}
