using System.Diagnostics;
using System.Runtime.InteropServices;

namespace ServerManager.HostUI;

internal static class Program
{
    private const string MutexName = "Global\\ServerManager.HostUI.SingleInstance";
    public const int WmShowMe = 0x8001;

    [STAThread]
    private static void Main(string[] args)
    {
        // PerMonitorV2 avoids bitmap-scaled blurry text on high-DPI / multi-monitor setups.
        Application.SetHighDpiMode(HighDpiMode.PerMonitorV2);
        Application.SetCompatibleTextRenderingDefault(false);
        PortConfig.Load();
        ApplicationConfiguration.Initialize();
        ThemeApplier.Apply(ThemeCatalog.SystemId);

        using var mutex = new Mutex(true, MutexName, out var created);
        if (!created)
        {
            NativeMethods.PostShowMe();
            return;
        }

        var mode = args.FirstOrDefault(a => a.StartsWith("--mode=", StringComparison.OrdinalIgnoreCase))
            ?.Split('=', 2)[1]?.ToLowerInvariant() ?? "dashboard";

        using var api = new ApiClient();
        using var login = new LoginForm(api);
        ApplyAppIcon(login);
        if (login.ShowDialog() != DialogResult.OK)
            return;

        // Service cannot show NotifyIcon — ensure tray in this user session (Settings can disable).
        TrayLauncher.EnsureRunning();

        Form main = mode switch
        {
            "admin" => new AdminForm(api),
            "automation" => new AutomationForm(api),
            _ => new MainForm(api)
        };
        ApplyAppIcon(main);
        Application.Run(main);
    }

    private static void ApplyAppIcon(Form form)
    {
        foreach (var candidate in new[]
                 {
                     Path.Combine(AppContext.BaseDirectory, "icons", "servermanager.ico"),
                     Path.Combine(AppContext.BaseDirectory, "servermanager.ico")
                 })
        {
            try
            {
                if (!File.Exists(candidate)) continue;
                form.Icon = new Icon(candidate);
                return;
            }
            catch { /* ignore */ }
        }
        try { form.Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { /* ignore */ }
    }
}

internal static class NativeMethods
{
    public const int HWND_BROADCAST = 0xffff;

    [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern IntPtr FindWindow(string? lpClassName, string lpWindowName);

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    private static extern bool PostMessage(IntPtr hWnd, int msg, IntPtr wParam, IntPtr lParam);

    public static void PostShowMe()
    {
        foreach (var title in new[]
                 {
                     "Server Manager Dashboard",
                     "Admin Dashboard - User Management",
                     "Automation Settings",
                     "Server Manager - Authentication Required"
                 })
        {
            var hwnd = FindWindow(null, title);
            if (hwnd != IntPtr.Zero)
            {
                ShowWindow(hwnd, 9); // SW_RESTORE
                SetForegroundWindow(hwnd);
                PostMessage(hwnd, Program.WmShowMe, IntPtr.Zero, IntPtr.Zero);
                return;
            }
        }
    }

    public static void LaunchHostUi(string? mode = null)
    {
        var exe = Path.Combine(AppContext.BaseDirectory, "ServerManager.HostUI.exe");
        if (!File.Exists(exe))
            exe = Path.Combine(AppContext.BaseDirectory, "ServerManager.HostUI.dll");
        var args = string.IsNullOrWhiteSpace(mode) ? "" : $"--mode={mode}";
        if (exe.EndsWith(".dll", StringComparison.OrdinalIgnoreCase))
            Process.Start(new ProcessStartInfo { FileName = "dotnet", Arguments = $"\"{exe}\" {args}", UseShellExecute = false });
        else
            Process.Start(new ProcessStartInfo { FileName = exe, Arguments = args, UseShellExecute = true });
    }
}
