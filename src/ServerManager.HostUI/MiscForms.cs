using System.Diagnostics;
using System.Reflection;
using System.Text;
using System.Text.Json;

namespace ServerManager.HostUI;

internal sealed class ProcessDetailsForm : HostUiForm
{
    private readonly ApiClient _api;
    private readonly ServerRow _row;
    private readonly TextBox _basic = MakeBox();
    private readonly TextBox _resources = MakeBox();
    private readonly TextBox _children = MakeBox();
    private readonly TextBox _network = MakeBox();
    private readonly TextBox _logs = MakeBox();

    public ProcessDetailsForm(ApiClient api, ServerRow row)
    {
        _api = api;
        _row = row;
        Text = $"Process Details — {row.Name}";
        Width = 720;
        Height = 520;
        StartPosition = FormStartPosition.CenterParent;

        var tabs = new ThemedTabControl { Dock = DockStyle.Fill };
        tabs.TabPages.Add(MakeTab("Basic", _basic));
        tabs.TabPages.Add(MakeTab("Resources", _resources));
        tabs.TabPages.Add(MakeTab("Children", _children));
        tabs.TabPages.Add(MakeTab("Network", _network));
        tabs.TabPages.Add(MakeTab("Logs", _logs));

        var bar = new ToolStrip();
        bar.Items.Add("Monitor", null, async (_, _) => await RefreshAsync());
        Controls.Add(tabs);
        Controls.Add(bar);
        Shown += async (_, _) => await RefreshAsync();
    }

    private async Task RefreshAsync()
    {
        try
        {
            var json = await _api.GetRuntimeAsync($"/api/runtime/servers/{Uri.EscapeDataString(_row.Name)}/process");
            ParseIntoTabs(json);
        }
        catch
        {
            _basic.Text = LocalFallback(_row);
            _resources.Text = "(unavailable)";
            _children.Text = "(unavailable)";
            _network.Text = "(unavailable)";
            _logs.Text = "(unavailable)";
        }
    }

    private void ParseIntoTabs(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            _basic.Text = Extract(root, "basic", "info", "process") ?? PickProps(root,
                "name", "pid", "status", "executable", "commandLine", "startTime", "workingDirectory", "user");
            _resources.Text = Extract(root, "resources", "resource", "metrics") ?? PickProps(root,
                "cpu", "cpuPercent", "memory", "memoryMb", "workingSet", "threads", "handles");
            _children.Text = Extract(root, "children", "childProcesses", "processes") ?? "(none)";
            _network.Text = Extract(root, "network", "connections", "ports") ?? PickProps(root, "ports", "listeners", "connections");
            _logs.Text = Extract(root, "logs", "log", "console") ?? Pretty(json);
        }
        catch
        {
            _basic.Text = Pretty(json);
            _resources.Text = "";
            _children.Text = "";
            _network.Text = "";
            _logs.Text = json;
        }
    }

    private static string? Extract(JsonElement root, params string[] keys)
    {
        foreach (var key in keys)
        {
            if (!root.TryGetProperty(key, out var p)) continue;
            if (p.ValueKind is JsonValueKind.Object or JsonValueKind.Array)
                return JsonSerializer.Serialize(p, new JsonSerializerOptions { WriteIndented = true });
            if (p.ValueKind == JsonValueKind.String) return p.GetString();
            return p.ToString();
        }
        return null;
    }

    private static string PickProps(JsonElement root, params string[] names)
    {
        var sb = new StringBuilder();
        foreach (var n in names)
        {
            if (!root.TryGetProperty(n, out var p) || p.ValueKind == JsonValueKind.Null) continue;
            sb.Append(n).Append(": ").AppendLine(p.ToString());
        }
        return sb.Length == 0 ? Pretty(root.GetRawText()) : sb.ToString();
    }

    private static TabPage MakeTab(string title, TextBox box)
    {
        var page = new TabPage(title)
        {
            BackColor = UiTheme.FormBack,
            ForeColor = UiTheme.FormFore,
            UseVisualStyleBackColor = false
        };
        page.Controls.Add(box);
        return page;
    }

    private static TextBox MakeBox() => new()
    {
        Multiline = true,
        ReadOnly = true,
        Dock = DockStyle.Fill,
        Font = new Font("Consolas", 9f),
        ScrollBars = ScrollBars.Both
    };

    private static string Pretty(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            return JsonSerializer.Serialize(doc.RootElement, new JsonSerializerOptions { WriteIndented = true });
        }
        catch { return json; }
    }

    private static string LocalFallback(ServerRow row)
    {
        if (row.Pid is not int pid) return "No PID / process not running.";
        try
        {
            var p = Process.GetProcessById(pid);
            return $"Name: {p.ProcessName}\nPID: {p.Id}\nStart: {p.StartTime}\nWS: {p.WorkingSet64 / 1024 / 1024} MB\nPath: {SafePath(p)}";
        }
        catch (Exception ex) { return ex.Message; }
    }

    private static string SafePath(Process p)
    {
        try { return p.MainModule?.FileName ?? ""; }
        catch { return ""; }
    }
}

internal sealed class AboutForm : HostUiForm
{
    public AboutForm()
    {
        Text = "About";
        Width = 460;
        Height = 260;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterParent;

        var ver = Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "1.0.0";
        var info = Assembly.GetExecutingAssembly()
            .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion;
        if (!string.IsNullOrWhiteSpace(info)) ver = info;

        Controls.Add(new Label
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(16),
            Text = $"Server Manager Host Dashboard\n\n" +
                   $"Version: {ver}\n" +
                   $"Native WinForms operator UI.\n" +
                   $"Talks to HostRuntime / Web APIs.\n\n" +
                   $"Skywere Industries"
        });
    }
}

internal sealed class HelpForm : HostUiForm
{
    public HelpForm()
    {
        Text = "Help";
        Width = 720;
        Height = 520;
        StartPosition = FormStartPosition.CenterParent;

        var tabs = new ThemedTabControl { Dock = DockStyle.Fill };
        tabs.TabPages.Add(HelpTab("Overview", """
Overview
- This Host Dashboard manages game servers via HostRuntime (not the browser).
- Tray Open Server Dashboard launches this window.
- Server configs live in SQLite (runtime\db\servermanager_servers.db).
- Login uses the same users database as the web UI (default admin/admin).
"""));
        tabs.TabPages.Add(HelpTab("Controls", """
Controls
- Toolbar: Add / Start / Stop / Import / Update All / Schedules / Consoles / Cluster / Automation / Expand All / Collapse All
- Categories use [+] / [−] rows (click to expand/collapse), like the Python Host tree
- Click a column header to sort A–Z (click again to reverse)
- File → Settings for Dashboard/Updates/Steam/System/Hardware/Cluster/Minecraft tabs
- File → Hardware for local/BMC probes; File → Admin for users (admins)
- Tools → Modded Minecraft Pack Browser for Modrinth/CurseForge search
"""));
        tabs.TabPages.Add(HelpTab("Server Management", """
Server Management
- Right-click a server for Kill, Configure, Console, Export Server, Open Folder, Remove, Process Details
- Double-click a server to configure it
- Export Server writes a .smserver.json transfer file (no live PID)
- Import Server upserts that file into SQLite (overwrite / rename / skip)
- Schedules: edit auto-start, scheduled restart, MOTD interval, warning intervals
- Automation: MOTD/start/stop/save/warning commands and templates
- Cluster: enable in Settings → Cluster; approve pending joins on the host
"""));
        tabs.TabPages.Add(HelpTab("Troubleshooting", """
Troubleshooting
- If Host Runtime shows Disconnected, start ServerManager.exe (AppHost) or the Windows service
- Checkpoint Databases only WAL-checkpoints SQLite — it does not refresh Steam/MC catalogs
- Use Tools → Update Databases / catalog scanners to refresh AppID and Minecraft catalogs
- Admin → Email/SMTP: Test SMTP before enabling Notify on crash/update
- 2FA: Admin → Reset 2FA then Setup 2FA for a selected user
- Theme changes apply immediately via ThemeApplier when saved from Settings
"""));

        var bar = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 44, Padding = new Padding(8) };
        var docs = new Button { Text = "Open Docs", Width = 110 };
        docs.Click += (_, _) =>
        {
            try
            {
                Process.Start(new ProcessStartInfo
                {
                    FileName = "https://github.com/",
                    UseShellExecute = true
                });
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, ex.Message, Text);
            }
        };
        bar.Controls.Add(docs);

        Controls.Add(tabs);
        Controls.Add(bar);
    }

    private static TabPage HelpTab(string title, string text)
    {
        var page = new TabPage(title)
        {
            BackColor = UiTheme.FormBack,
            ForeColor = UiTheme.FormFore,
            UseVisualStyleBackColor = false
        };
        page.Controls.Add(new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            ReadOnly = true,
            ScrollBars = ScrollBars.Vertical,
            Text = text.Trim(),
            BackColor = UiTheme.ControlBack,
            ForeColor = UiTheme.ControlFore,
            BorderStyle = BorderStyle.None
        });
        return page;
    }
}

internal sealed class DebugCentreForm : HostUiForm
{
    private readonly ApiClient _api;
    private readonly TextBox _out = new() { Dock = DockStyle.Fill, Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Both, Font = new Font("Consolas", 9f) };

    public DebugCentreForm(ApiClient api)
    {
        _api = api;
        Text = "Debug Centre";
        Width = 800;
        Height = 560;
        StartPosition = FormStartPosition.CenterParent;
        var bar = new ToolStrip();
        bar.Items.Add("System Information", null, (_, _) => _out.Text = LocalMetrics.Snapshot() + "\n" + Environment.OSVersion + "\n" + Environment.MachineName);
        bar.Items.Add("HostRuntime Diagnostics", null, async (_, _) => await LoadAsync("/api/runtime/diagnostics", runtime: true));
        bar.Items.Add("Temperatures", null, async (_, _) => await LoadAsync("/api/analytics/temperatures", runtime: false));
        bar.Items.Add("SNMP shim", null, async (_, _) => await LoadAsync("/api/analytics/snmp", runtime: false));
        bar.Items.Add("Full Diagnostics", null, async (_, _) => await FullAsync());
        Controls.Add(_out);
        Controls.Add(bar);
    }

    private async Task LoadAsync(string path, bool runtime)
    {
        try
        {
            var json = runtime ? await _api.GetRuntimeAsync(path) : await _api.GetWebAsync(path);
            _out.Text = Pretty(json);
        }
        catch (Exception ex) { _out.Text = ex.Message; }
    }

    private async Task FullAsync()
    {
        try
        {
            var rt = await _api.HealthRuntimeAsync();
            var web = await _api.HealthWebAsync();
            var diag = "";
            try { diag = await _api.GetRuntimeAsync("/api/runtime/diagnostics"); } catch (Exception ex) { diag = ex.Message; }
            _out.Text = $"Runtime healthy: {rt}\nWeb reachable: {web}\n\n{LocalMetrics.Snapshot()}\n\n{Pretty(diag)}";
        }
        catch (Exception ex) { _out.Text = ex.Message; }
    }

    private static string Pretty(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            return JsonSerializer.Serialize(doc.RootElement, new JsonSerializerOptions { WriteIndented = true });
        }
        catch { return json; }
    }
}
