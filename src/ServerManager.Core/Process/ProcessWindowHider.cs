using System.Runtime.InteropServices;
using System.Text;

namespace ServerManager.Core.Process;

/// <summary>
/// Hides console windows belonging to game server processes (Palworld, 7DTD, srcds, etc.)
/// so HostUI can own the console UX without flooding the desktop with CMD panels.
/// </summary>
public static class ProcessWindowHider
{
    private const int SwHide = 0;
    private const int SwShow = 5;

    /// <summary>Hide console windows for a PID and its descendants.</summary>
    public static int HideForProcessTree(int rootPid, ProcessIdentityService? identity = null)
    {
        if (!OperatingSystem.IsWindows() || rootPid <= 4) return 0;
        var hidden = 0;
        var pids = new HashSet<int> { rootPid };
        if (identity is not null)
        {
            try
            {
                foreach (var child in identity.EnumerateDescendantPids(rootPid))
                    pids.Add(child);
            }
            catch { /* best effort */ }
        }

        foreach (var pid in pids)
            hidden += HideForPid(pid);
        return hidden;
    }

    public static int HideForPid(int pid)
    {
        if (!OperatingSystem.IsWindows() || pid <= 4) return 0;
        var hidden = 0;
        hidden += HideViaAttachConsole(pid) ? 1 : 0;
        hidden += EnumAndHideConsoleWindows(pid);
        try
        {
            var p = System.Diagnostics.Process.GetProcessById(pid);
            if (p.MainWindowHandle != IntPtr.Zero && IsWindowVisible(p.MainWindowHandle))
            {
                // Dedicated-server "main" window is almost always the console host.
                if (IsConsoleWindow(p.MainWindowHandle) || LooksLikeConsoleTitle(p.MainWindowHandle))
                {
                    ShowWindow(p.MainWindowHandle, SwHide);
                    hidden++;
                }
            }
        }
        catch { /* access / exited */ }
        return hidden;
    }

    private static bool HideViaAttachConsole(int pid)
    {
        try
        {
            FreeConsole();
            if (!AttachConsole((uint)pid))
                return false;
            try
            {
                var hwnd = GetConsoleWindow();
                if (hwnd == IntPtr.Zero || !IsWindowVisible(hwnd))
                    return false;
                ShowWindow(hwnd, SwHide);
                return true;
            }
            finally
            {
                FreeConsole();
            }
        }
        catch
        {
            try { FreeConsole(); } catch { /* ignore */ }
            return false;
        }
    }

    private static int EnumAndHideConsoleWindows(int pid)
    {
        var hidden = 0;
        EnumWindows((hWnd, _) =>
        {
            GetWindowThreadProcessId(hWnd, out var windowPid);
            if (windowPid != (uint)pid) return true;
            if (!IsWindowVisible(hWnd)) return true;
            if (!IsConsoleWindow(hWnd) && !LooksLikeConsoleTitle(hWnd)) return true;
            ShowWindow(hWnd, SwHide);
            hidden++;
            return true;
        }, IntPtr.Zero);
        return hidden;
    }

    private static bool IsConsoleWindow(IntPtr hWnd)
    {
        var sb = new StringBuilder(256);
        if (GetClassName(hWnd, sb, sb.Capacity) <= 0) return false;
        return sb.ToString().Equals("ConsoleWindowClass", StringComparison.OrdinalIgnoreCase);
    }

    private static bool LooksLikeConsoleTitle(IntPtr hWnd)
    {
        var sb = new StringBuilder(512);
        if (GetWindowText(hWnd, sb, sb.Capacity) <= 0) return false;
        var title = sb.ToString();
        // Common dedicated-server console titles
        return title.Contains("cmd.exe", StringComparison.OrdinalIgnoreCase)
               || title.Contains("Command Prompt", StringComparison.OrdinalIgnoreCase)
               || title.Contains("PalServer", StringComparison.OrdinalIgnoreCase)
               || title.Contains("7DaysToDie", StringComparison.OrdinalIgnoreCase)
               || title.Contains("Dedicated Server", StringComparison.OrdinalIgnoreCase)
               || title.Contains("Project Zomboid", StringComparison.OrdinalIgnoreCase)
               || title.Contains("zomboid", StringComparison.OrdinalIgnoreCase)
               || title.Contains("java", StringComparison.OrdinalIgnoreCase)
               || title.Contains("srcds", StringComparison.OrdinalIgnoreCase);
    }

    private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    [DllImport("user32.dll")]
    private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AttachConsole(uint dwProcessId);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool FreeConsole();

    [DllImport("kernel32.dll")]
    private static extern IntPtr GetConsoleWindow();
}
