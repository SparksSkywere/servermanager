using System.Diagnostics;
using System.Drawing;
using System.Net.Http;
using System.ServiceProcess;
using System.Text.Json;
using System.Windows.Forms;
using Microsoft.Win32;

namespace ServerManager.Tray;

internal static class Program
{
    private const string MutexName = "Local\\ServerManagerTraySingleton";

    [STAThread]
    private static void Main()
    {
        using var mutex = new Mutex(true, MutexName, out var created);
        if (!created)
            return;

        ApplicationConfiguration.Initialize();
        Application.Run(new TrayApplicationContext());
    }
}

internal sealed class TrayApplicationContext : ApplicationContext
{
    private const string ServiceName = "ServerManagerService";
    private readonly NotifyIcon _icon;
    private readonly ContextMenuStrip _menu = new();
    private readonly ToolStripMenuItem _runningItem = new("Running servers (…)") { Enabled = false };
    private readonly ToolStripMenuItem _webItem = new("Webserver (…)") { Enabled = false };
    private readonly ToolStripMenuItem _runtimeItem = new("Host Runtime (…)") { Enabled = false };
    private readonly System.Windows.Forms.Timer _timer = new() { Interval = 10000 };
    private readonly int _webPort;
    private readonly int _runtimePort;
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(3) };

    public TrayApplicationContext()
    {
        _webPort = ReadPort("ServerManager__WebPort", "WebPort", 18080);
        _runtimePort = ReadPort("ServerManager__HostRuntimePort", "HostRuntimePort", 18091);

        _menu.Items.Add(_runningItem);
        _menu.Items.Add(_webItem);
        _menu.Items.Add(_runtimeItem);
        _menu.Items.Add(new ToolStripSeparator());
        _menu.Items.Add("Open Admin Dashboard", null, (_, _) => LaunchHostUi("admin"));
        _menu.Items.Add("Open Server Dashboard", null, (_, _) => LaunchHostUi("dashboard"));
        _menu.Items.Add("Open Web Dashboard", null, (_, _) => OpenUrl("/dashboard.html"));
        _menu.Items.Add("Automation Settings", null, (_, _) => LaunchHostUi("automation"));
        _menu.Items.Add(new ToolStripSeparator());
        _menu.Items.Add("Restart Server Manager", null, async (_, _) => await RestartStackAsync());
        _menu.Items.Add("Exit Tray", null, (_, _) => ExitTrayOnly());
        if (!IsServiceRunning())
            _menu.Items.Add("Exit and Stop Services", null, async (_, _) => await ExitStackAsync());

        _icon = new NotifyIcon
        {
            Icon = LoadIcon(),
            Visible = true,
            Text = "Server Manager",
            ContextMenuStrip = _menu
        };
        _icon.DoubleClick += (_, _) => LaunchHostUi("dashboard");

        _timer.Tick += async (_, _) => await RefreshStatusAsync();
        _timer.Start();
        _ = RefreshStatusAsync();
    }

    private static bool IsServiceRunning()
    {
        try
        {
            using var sc = new ServiceController(ServiceName);
            return sc.Status is ServiceControllerStatus.Running or ServiceControllerStatus.StartPending;
        }
        catch
        {
            return false;
        }
    }

    private static bool ServiceInstalled()
    {
        try
        {
            using var sc = new ServiceController(ServiceName);
            _ = sc.Status;
            return true;
        }
        catch
        {
            return false;
        }
    }

    private static Icon LoadIcon()
    {
        foreach (var candidate in new[]
                 {
                     Path.Combine(AppContext.BaseDirectory, "icons", "servermanager.ico"),
                     Path.Combine(AppContext.BaseDirectory, "servermanager.ico"),
                     Path.Combine(AppContext.BaseDirectory, "..", "icons", "servermanager.ico"),
                     Path.Combine(AppContext.BaseDirectory, "..", "..", "assets", "server-icons-3705.ico")
                 })
        {
            try
            {
                if (File.Exists(candidate)) return new Icon(candidate);
            }
            catch { /* ignore */ }
        }
        return Icon.ExtractAssociatedIcon(Application.ExecutablePath) ?? SystemIcons.Application;
    }

    private static int ReadPort(string envName, string regName, int fallback)
    {
        var env = Environment.GetEnvironmentVariable(envName);
        if (int.TryParse(env, out var ep)) return ep;
        try
        {
            using var key = Registry.LocalMachine.OpenSubKey(@"Software\SkywereIndustries\Servermanager");
            if (int.TryParse(key?.GetValue(regName)?.ToString(), out var rp)) return rp;
        }
        catch { /* ignore */ }
        return fallback;
    }

    private async Task RefreshStatusAsync()
    {
        var running = 0;
        var web = "Disconnected";
        var runtime = "Disconnected";
        try
        {
            var json = await _http.GetStringAsync($"http://127.0.0.1:{_runtimePort}/api/runtime/servers");
            using var doc = JsonDocument.Parse(json);
            foreach (var el in doc.RootElement.EnumerateArray())
            {
                if (el.TryGetProperty("status", out var s) &&
                    string.Equals(s.GetString(), "running", StringComparison.OrdinalIgnoreCase))
                    running++;
            }
            runtime = "Connected";
        }
        catch { runtime = "Disconnected"; }

        try
        {
            using var resp = await _http.GetAsync($"http://127.0.0.1:{_webPort}/");
            web = resp.IsSuccessStatusCode || (int)resp.StatusCode < 500 ? "Connected" : "Error";
        }
        catch { web = "Disconnected"; }

        void Apply()
        {
            _runningItem.Text = $"Running servers ({running})";
            _webItem.Text = $"Webserver ({web})";
            _runtimeItem.Text = $"Host Runtime ({runtime})";
            var mode = IsServiceRunning() ? "service" : "app";
            _icon.Text = $"Server Manager ({mode}) — {running} running";
        }

        if (_menu.InvokeRequired) _menu.BeginInvoke(Apply);
        else Apply();
    }

    private void LaunchHostUi(string mode)
    {
        var exe = Path.Combine(AppContext.BaseDirectory, "ServerManager.HostUI.exe");
        if (!File.Exists(exe))
        {
            MessageBox.Show($"Host UI not found:\n{exe}\nRebuild with build.ps1.", "Server Manager Tray");
            return;
        }
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = exe,
                Arguments = $"--mode={mode}",
                UseShellExecute = true,
                WorkingDirectory = AppContext.BaseDirectory
            });
        }
        catch (Exception ex)
        {
            MessageBox.Show(ex.Message, "Server Manager Tray");
        }
    }

    private void OpenUrl(string path)
    {
        var url = $"http://127.0.0.1:{_webPort}{path}";
        try
        {
            Process.Start(new ProcessStartInfo { FileName = url, UseShellExecute = true });
        }
        catch (Exception ex)
        {
            MessageBox.Show($"Could not open browser:\n{ex.Message}", "Server Manager Tray");
        }
    }

    private async Task RestartStackAsync()
    {
        try
        {
            if (ServiceInstalled())
            {
                using var sc = new ServiceController(ServiceName);
                if (sc.Status is not ServiceControllerStatus.Stopped and not ServiceControllerStatus.StopPending)
                {
                    sc.Stop();
                    sc.WaitForStatus(ServiceControllerStatus.Stopped, TimeSpan.FromSeconds(30));
                }
                sc.Start();
                return;
            }

            try { await _http.PostAsync($"http://127.0.0.1:{_runtimePort}/api/runtime/shutdown", null); } catch { /* ignore */ }
            await Task.Delay(1500);
            var appHost = Path.Combine(AppContext.BaseDirectory, "ServerManager.exe");
            if (File.Exists(appHost))
            {
                Process.Start(new ProcessStartInfo { FileName = appHost, UseShellExecute = true, WorkingDirectory = AppContext.BaseDirectory });
            }
            else
            {
                MessageBox.Show("ServerManager.exe not found beside tray.", "Server Manager Tray");
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show(ex.Message, "Server Manager Tray");
        }
    }

    private void ExitTrayOnly()
    {
        _timer.Stop();
        _icon.Visible = false;
        _icon.Dispose();
        _http.Dispose();
        Application.Exit();
    }

    private async Task ExitStackAsync()
    {
        try
        {
            if (ServiceInstalled())
            {
                try
                {
                    using var sc = new ServiceController(ServiceName);
                    if (sc.Status is not ServiceControllerStatus.Stopped and not ServiceControllerStatus.StopPending)
                    {
                        sc.Stop();
                        sc.WaitForStatus(ServiceControllerStatus.Stopped, TimeSpan.FromSeconds(30));
                    }
                }
                catch { /* fall through to process kill */ }
            }

            try { await _http.PostAsync($"http://127.0.0.1:{_runtimePort}/api/runtime/shutdown", null); } catch { /* ignore */ }
            foreach (var name in new[] { "ServerManager.Web", "ServerManager.HostRuntime", "ServerManager", "ServerManager.HostUI" })
            {
                foreach (var p in Process.GetProcessesByName(name))
                {
                    try { p.Kill(entireProcessTree: true); } catch { /* ignore */ }
                }
            }
        }
        catch { /* ignore */ }
        finally
        {
            ExitTrayOnly();
        }
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _timer.Dispose();
            _icon.Dispose();
            _http.Dispose();
        }
        base.Dispose(disposing);
    }
}
