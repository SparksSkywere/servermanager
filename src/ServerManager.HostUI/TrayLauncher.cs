using System.Diagnostics;
using Microsoft.Win32;

namespace ServerManager.HostUI;

/// <summary>
/// Tray must run in the interactive user session. The Windows service cannot show NotifyIcon.
/// </summary>
internal static class TrayLauncher
{
    private const string RunValueName = "ServerManagerTray";

    public static bool IsRunning()
        => Process.GetProcessesByName("ServerManager.Tray").Length > 0;

    public static void EnsureRunning()
    {
        if (IsRunning()) return;
        var exe = ResolveTrayExe();
        if (exe is null) return;
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = exe,
                WorkingDirectory = Path.GetDirectoryName(exe) ?? AppContext.BaseDirectory,
                UseShellExecute = true
            });
            RegisterUserLogon(exe);
        }
        catch
        {
            /* tray optional */
        }
    }

    public static void Stop()
    {
        foreach (var p in Process.GetProcessesByName("ServerManager.Tray"))
        {
            try { p.Kill(entireProcessTree: true); } catch { /* ignore */ }
        }
        UnregisterUserLogon();
    }

    public static void ApplyPreference(bool enabled)
    {
        if (enabled) EnsureRunning();
        else Stop();
    }

    private static string? ResolveTrayExe()
    {
        var exe = Path.Combine(AppContext.BaseDirectory, "ServerManager.Tray.exe");
        return File.Exists(exe) ? exe : null;
    }

    private static void RegisterUserLogon(string trayExe)
    {
        try
        {
            using var key = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run");
            key?.SetValue(RunValueName, $"\"{trayExe}\"");
        }
        catch { /* ignore */ }
    }

    private static void UnregisterUserLogon()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run", writable: true);
            key?.DeleteValue(RunValueName, throwOnMissingValue: false);
        }
        catch { /* ignore */ }
    }
}
