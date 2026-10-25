using System.Diagnostics;
using System.Text.Json;

namespace ServerManager.HostUI;

internal sealed class MainForm : HostUiForm
{
    private readonly ApiClient _api;
    private readonly ServerCategoryListView _servers = new() { Dock = DockStyle.Fill };
    private readonly ListView _remoteServers = new()
    {
        Dock = DockStyle.Fill,
        View = View.Details,
        FullRowSelect = true,
        GridLines = true,
        Visible = false
    };
    private readonly Label _remoteNote = new()
    {
        Dock = DockStyle.Top,
        Height = 48,
        Padding = new Padding(8),
        Text = "Remote server list is not available for this node. Use Start/Stop with a server name, or open Cluster for node management."
    };
    private readonly Panel _remotePane = new() { Dock = DockStyle.Fill, Visible = false };
    private readonly ThemedTabControl _hostTabs = new() { Dock = DockStyle.Top, Height = 30 };
    private readonly SystemInformationPanel _sysInfo = new() { Dock = DockStyle.Fill };
    private readonly Panel _sysPane = new() { Dock = DockStyle.Right, Width = 320, MinimumSize = new Size(280, 0) };
    private readonly Button _collapseBtn = new() { Text = "◀", Width = 22, Dock = DockStyle.Fill, FlatStyle = FlatStyle.Flat };
    private readonly Panel _collapseStrip = new() { Dock = DockStyle.Right, Width = 24 };
    private bool _sysVisible = true;
    private readonly ThemedSectionPanel _serversBox = new() { Title = "Host Servers — Local Host", Dock = DockStyle.Fill };
    private readonly StatusStrip _status = new();
    private readonly ToolStripStatusLabel _statusText = new() { Text = "Ready" };
    private readonly System.Windows.Forms.Timer _timer = new() { Interval = 3000 };
    private Panel? _loadingOverlay;
    private string? _activeSubhostId;
    private readonly Dictionary<string, string> _tabNodeIds = new(StringComparer.OrdinalIgnoreCase);

    public MainForm(ApiClient api)
    {
        _api = api;
        Text = $"Server Manager Dashboard (Logged in as: {_api.Username})";
        Width = 1280;
        Height = 800;
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(960, 600);

        _remoteServers.BorderStyle = BorderStyle.None;
        _remoteServers.BackColor = UiTheme.ControlBack;
        _remoteNote.BackColor = UiTheme.FormBack;
        _remoteNote.ForeColor = UiTheme.FormFore;
        _remotePane.BackColor = UiTheme.FormBack;
        _sysPane.BackColor = UiTheme.FormBack;
        _collapseStrip.BackColor = UiTheme.FormBack;
        _remoteServers.Columns.Add("Name", 180);
        _remoteServers.Columns.Add("Status", 100);
        _remoteServers.Columns.Add("Type", 120);
        _remoteServers.Columns.Add("Notes", 280);

        BuildMenu();
        BuildToolbar();
        BuildLayout();
        BuildContextMenu();
        ShowLoadingOverlay();

        _status.Items.Add(_statusText);
        Controls.Add(_status);

        _timer.Tick += async (_, _) => await RefreshAllAsync();
        Shown += async (_, _) =>
        {
            await ApplyProfileThemeAsync();
            await ApplyTrayPreferenceAsync();
            await RefreshAllAsync();
            HideLoadingOverlay();
            _timer.Start();
        };
        FormClosed += (_, _) => _timer.Stop();
    }

    private async Task ApplyTrayPreferenceAsync()
    {
        var enabled = true;
        try
        {
            var json = await _api.GetWebAsync("/api/system-settings");
            using var doc = JsonDocument.Parse(json);
            if (doc.RootElement.TryGetProperty("TrayIcon", out var t) ||
                doc.RootElement.TryGetProperty("trayIcon", out t))
            {
                var v = t.ValueKind == JsonValueKind.String ? t.GetString() : t.ToString();
                enabled = !string.Equals(v, "false", StringComparison.OrdinalIgnoreCase);
            }
        }
        catch { /* default on */ }
        TrayLauncher.ApplyPreference(enabled);
    }

    protected override void WndProc(ref Message m)
    {
        if (m.Msg == Program.WmShowMe)
        {
            if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
            Activate();
            return;
        }
        base.WndProc(ref m);
    }

    private void BuildMenu()
    {
        var menu = new MenuStrip();
        var file = new ToolStripMenuItem("File");
        file.DropDownItems.Add("Settings", null, (_, _) => new SettingsForm(_api).ShowDialog(this));
        if (_api.IsAdmin)
            file.DropDownItems.Add("Admin…", null, (_, _) => new AdminForm(_api).ShowDialog(this));
        file.DropDownItems.Add("Hardware…", null, (_, _) => new HardwareForm(_api).ShowDialog(this));
        file.DropDownItems.Add(new ToolStripSeparator());
        file.DropDownItems.Add("Exit", null, (_, _) => Close());

        var tools = new ToolStripMenuItem("Tools");
        tools.DropDownItems.Add("Find Broken Servers", null, async (_, _) => await FindBrokenAsync());
        tools.DropDownItems.Add("Verify Server Information", null, async (_, _) => await VerifyServersAsync());
        tools.DropDownItems.Add(new ToolStripSeparator());
        tools.DropDownItems.Add("Browse Steam AppIDs…", null, (_, _) =>
        {
            using var dlg = new AppIdBrowserForm(_api);
            dlg.ShowDialog(this);
        });
        tools.DropDownItems.Add("Browse Minecraft Versions…", null, (_, _) =>
        {
            using var dlg = new McVersionBrowserForm(_api);
            dlg.ShowDialog(this);
        });
        tools.DropDownItems.Add(new ToolStripSeparator());
        tools.DropDownItems.Add("Update Databases", null, (_, _) => new UpdateDatabasesForm(_api).ShowDialog(this));
        tools.DropDownItems.Add("Checkpoint Databases", null, async (_, _) => await DbToolAsync("checkpoint"));
        tools.DropDownItems.Add("Verify Databases", null, async (_, _) => await DbToolAsync("verify"));
        tools.DropDownItems.Add(new ToolStripSeparator());
        tools.DropDownItems.Add("Reattach All Consoles", null, async (_, _) => await ReattachAllAsync());
        tools.DropDownItems.Add("Modded Minecraft Packs…", null, (_, _) => new ModpackBrowserForm(_api).ShowDialog(this));
        tools.DropDownItems.Add("Debug Centre", null, (_, _) => new DebugCentreForm(_api).ShowDialog(this));

        var help = new ToolStripMenuItem("Help");
        help.DropDownItems.Add("Help", null, (_, _) => new HelpForm().ShowDialog(this));
        help.DropDownItems.Add("About", null, (_, _) => new AboutForm().ShowDialog(this));

        menu.Items.Add(file);
        menu.Items.Add(tools);
        menu.Items.Add(help);
        MainMenuStrip = menu;
        Controls.Add(menu);
    }

    private void BuildToolbar()
    {
        var bar = new ToolStrip { GripStyle = ToolStripGripStyle.Hidden };
        bar.Items.Add(Btn("Add Server", (_, _) => ShowAddServer()));
        bar.Items.Add(Btn("Start Server", async (_, _) => await ActSelectedAsync("start")));
        bar.Items.Add(Btn("Stop Server", async (_, _) => await ActSelectedAsync("stop")));
        bar.Items.Add(Btn("Import Server", async (_, _) => await ImportServerAsync()));
        bar.Items.Add(Btn("Update All", async (_, _) => await UpdateAllAsync()));
        bar.Items.Add(new ToolStripSeparator());
        bar.Items.Add(Btn("Schedules", (_, _) => new SchedulesForm(_api).ShowDialog(this)));
        bar.Items.Add(Btn("Consoles", (_, _) => OpenConsoleManager()));
        bar.Items.Add(Btn("Cluster", (_, _) => OpenCluster()));
        bar.Items.Add(Btn("Automation", (_, _) => new AutomationForm(_api).ShowDialog(this)));
        bar.Items.Add(new ToolStripSeparator());
        bar.Items.Add(Btn("Refresh", async (_, _) => await RefreshAllAsync()));
        Controls.Add(bar);
    }

    private static ToolStripButton Btn(string text, EventHandler onClick)
    {
        var b = new ToolStripButton(text) { DisplayStyle = ToolStripItemDisplayStyle.Text };
        b.Click += onClick;
        return b;
    }

    private void BuildLayout()
    {
        var localPage = new TabPage("Local") { Tag = null };
        _hostTabs.TabPages.Add(localPage);
        _hostTabs.SelectedIndexChanged += async (_, _) => await OnHostTabChangedAsync();

        var serverHeader = new ToolStrip { GripStyle = ToolStripGripStyle.Hidden, Dock = DockStyle.Top };
        serverHeader.Items.Add(Btn("Expand All", (_, _) => _servers.ExpandAll()));
        serverHeader.Items.Add(Btn("Collapse All", (_, _) => _servers.CollapseAll()));

        var remoteBar = new ToolStrip { GripStyle = ToolStripGripStyle.Hidden, Dock = DockStyle.Top };
        remoteBar.Items.Add(Btn("Start…", async (_, _) => await RemoteActAsync("start")));
        remoteBar.Items.Add(Btn("Stop…", async (_, _) => await RemoteActAsync("stop")));
        remoteBar.Items.Add(Btn("Refresh", async (_, _) => await LoadRemoteTabAsync(_activeSubhostId)));

        _remotePane.Controls.Add(_remoteServers);
        _remotePane.Controls.Add(_remoteNote);
        _remotePane.Controls.Add(remoteBar);

        var listHost = new Panel { Dock = DockStyle.Fill, BackColor = UiTheme.FormBack, Padding = new Padding(1) };
        listHost.Paint += (_, e) =>
        {
            e.Graphics.Clear(UiTheme.FormBack);
            using var pen = new Pen(UiTheme.Border);
            e.Graphics.DrawRectangle(pen, 0, 0, listHost.Width - 1, listHost.Height - 1);
        };
        listHost.Controls.Add(_servers);
        listHost.Controls.Add(_remotePane);

        _serversBox.Controls.Add(listHost);
        _serversBox.Controls.Add(serverHeader);
        _serversBox.Controls.Add(_hostTabs);

        _collapseBtn.FlatAppearance.BorderSize = 0;
        _collapseBtn.Click += (_, _) => ToggleSystemPane();
        _collapseStrip.Controls.Add(_collapseBtn);

        var sysBox = new ThemedSectionPanel { Title = "System Information", Dock = DockStyle.Fill };
        sysBox.Controls.Add(_sysInfo);
        _sysPane.Controls.Add(sysBox);

        var body = new Panel { Dock = DockStyle.Fill, Padding = new Padding(8, 56, 8, 28), BackColor = UiTheme.FormBack };
        body.Controls.Add(_serversBox);
        body.Controls.Add(_collapseStrip);
        body.Controls.Add(_sysPane);
        Controls.Add(body);
        body.SendToBack();
    }

    private void ToggleSystemPane()
    {
        _sysVisible = !_sysVisible;
        _sysPane.Visible = _sysVisible;
        _collapseBtn.Text = _sysVisible ? "◀" : "▶";
    }

    private void ShowLoadingOverlay()
    {
        _loadingOverlay = new Panel { Dock = DockStyle.Fill, BackColor = UiTheme.FormBack };
        var lbl = new Label
        {
            Text = "Loading Dashboard…",
            Font = new Font(SystemFonts.MessageBoxFont.FontFamily, 14f, FontStyle.Bold),
            AutoSize = true,
            ForeColor = UiTheme.FormFore,
            BackColor = Color.Transparent
        };
        _loadingOverlay.Controls.Add(lbl);
        _loadingOverlay.Resize += (_, _) =>
        {
            lbl.Left = (_loadingOverlay.Width - lbl.Width) / 2;
            lbl.Top = (_loadingOverlay.Height - lbl.Height) / 2;
        };
        Controls.Add(_loadingOverlay);
        _loadingOverlay.BringToFront();
    }

    private void HideLoadingOverlay()
    {
        if (_loadingOverlay is null) return;
        Controls.Remove(_loadingOverlay);
        _loadingOverlay.Dispose();
        _loadingOverlay = null;
    }

    private void BuildContextMenu()
    {
        var cm = new ContextMenuStrip();
        cm.Items.Add("Add Server", null, (_, _) => ShowAddServer());
        cm.Items.Add("Refresh", null, async (_, _) => await RefreshAllAsync());
        cm.Items.Add(new ToolStripSeparator());
        cm.Items.Add("Create Category", null, (_, _) => CategoryDialogs.Create(_api, this, RefreshAllAsync));
        cm.Items.Add("Rename Category", null, (_, _) => CategoryDialogs.Rename(_api, this, _servers.SelectedServerRow?.Category, RefreshAllAsync));
        cm.Items.Add("Delete Category", null, (_, _) => CategoryDialogs.Delete(_api, this, _servers.SelectedServerRow?.Category, RefreshAllAsync));
        cm.Items.Add(new ToolStripSeparator());
        cm.Items.Add("Start Server", null, async (_, _) => await ActSelectedAsync("start"));
        cm.Items.Add("Stop Server", null, async (_, _) => await StopOrRestartAsync("stop"));
        cm.Items.Add("Kill Process", null, async (_, _) => await ActSelectedAsync("kill"));
        cm.Items.Add("Clear Server", null, async (_, _) => await ActSelectedAsync("clear"));
        cm.Items.Add("Restart Server", null, async (_, _) => await StopOrRestartAsync("restart"));
        cm.Items.Add("View Process Details", null, (_, _) => ShowProcessDetails());
        cm.Items.Add("Show Console", null, (_, _) => OpenSelectedConsole());
        cm.Items.Add("Configure Server", null, (_, _) => ConfigureSelected());
        if (_api.IsAdmin)
        {
            cm.Items.Add("Permissions…", null, (_, _) => OpenPermissions());
        }
        cm.Items.Add(new ToolStripSeparator());
        cm.Items.Add("Check for Updates", null, async (_, _) => await UpdateSelectedAsync(checkOnly: true));
        cm.Items.Add("Update Server", null, async (_, _) => await UpdateSelectedAsync(checkOnly: false));
        cm.Items.Add("Schedule", null, (_, _) => new SchedulesForm(_api).ShowDialog(this));
        cm.Items.Add("Console Manager", null, (_, _) => new ConsoleManagerForm(_api).ShowDialog(this));
        cm.Items.Add(new ToolStripSeparator());
        cm.Items.Add("Export Server", null, async (_, _) => await ExportServerAsync());
        cm.Items.Add("Open Folder Directory", null, (_, _) => OpenFolder());
        cm.Items.Add("Remove Server", null, async (_, _) => await RemoveSelectedAsync());
        _servers.ContextMenuStrip = cm;
        _servers.ServerActivated += (_, _) => ConfigureSelected();
    }

    private void OpenPermissions()
    {
        var name = SelectedName();
        if (name is null) { MessageBox.Show(this, "Select a server first.", Text); return; }
        using var editor = new PermissionsEditorForm(_api, name);
        editor.ShowDialog(this);
    }

    private void OpenCluster()
    {
        new ClusterForm(_api).ShowDialog(this);
    }

    private string? SelectedName() => _servers.SelectedServer;

    private ServerRow? SelectedRow() => _servers.SelectedServerRow;

    private async Task ApplyProfileThemeAsync()
    {
        try
        {
            var profile = await _api.GetWebAsync("/api/profile");
            using var doc = JsonDocument.Parse(profile);
            var theme = doc.RootElement.TryGetProperty("theme", out var th) ? th.GetString() ?? "system" : "system";
            ThemeApplier.Apply(theme);
        }
        catch { /* theme optional */ }
    }

    private async Task RefreshAllAsync()
    {
        try
        {
            var webOk = await _api.HealthWebAsync();
            var rtOk = await _api.HealthRuntimeAsync();
            _sysInfo.SetConnectionStatus(webOk, rtOk, PortConfig.WebPort, PortConfig.HostRuntimePort);

            if (rtOk) await RefreshMetricsAsync();

            if (_api.IsAuthenticated && !_api.AuthExpired)
                await RefreshHostTabsAsync();
            else if (_api.AuthExpired)
            {
                _statusText.Text = "Session expired — sign in again (Web API calls paused to avoid log spam)";
                TrimRemoteTabs();
            }

            if (_activeSubhostId is not null)
            {
                await LoadRemoteTabAsync(_activeSubhostId);
                return;
            }

            if (!rtOk)
            {
                _statusText.Text = "Host Runtime offline";
                return;
            }

            var list = await _api.ListServersAsync();
            var selected = SelectedName();
            _servers.Bind(list, selected);
            if (!_api.AuthExpired)
                _statusText.Text = $"{list.Count} servers — {list.Count(s => s.Status == "running")} running — user {_api.Username}";
            else
                _statusText.Text = $"{list.Count} servers — session expired (sign in again)";
        }
        catch (Exception ex)
        {
            _statusText.Text = ex.Message;
        }
    }

    private async Task RefreshHostTabsAsync()
    {
        try
        {
            var statusJson = await _api.GetWebAsync("/api/cluster/status");
            using var statusDoc = JsonDocument.Parse(statusJson);
            var enabled = statusDoc.RootElement.TryGetProperty("enabled", out var en) && en.ValueKind == JsonValueKind.True;
            if (!enabled)
            {
                TrimRemoteTabs();
                return;
            }

            var nodesJson = await _api.GetWebAsync("/api/cluster/nodes");
            using var doc = JsonDocument.Parse(nodesJson);
            if (doc.RootElement.ValueKind != JsonValueKind.Array) return;

            var wanted = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var n in doc.RootElement.EnumerateArray())
            {
                var nodeType = Prop(n, "nodeType", "NodeType");
                // Local host is the Local tab; only show peer/subhost nodes as remote tabs.
                if (string.Equals(nodeType, "host", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(nodeType, "standalone", StringComparison.OrdinalIgnoreCase))
                    continue;

                var id = Prop(n, "nodeId", "NodeId");
                if (string.IsNullOrWhiteSpace(id)) continue;
                wanted.Add(id);
                var label = Prop(n, "displayName", "DisplayName");
                if (string.IsNullOrWhiteSpace(label)) label = Prop(n, "machineName", "MachineName");
                if (string.IsNullOrWhiteSpace(label)) label = id;
                var status = Prop(n, "status", "Status");
                var title = string.IsNullOrWhiteSpace(status) ? label : $"{label} ({status})";

                if (_tabNodeIds.ContainsKey(id))
                {
                    foreach (TabPage page in _hostTabs.TabPages)
                    {
                        if (page.Tag as string == id)
                        {
                            page.Text = title;
                            break;
                        }
                    }
                    continue;
                }

                var tab = new TabPage(title) { Tag = id };
                _hostTabs.TabPages.Add(tab);
                _tabNodeIds[id] = title;
            }

            // remove stale remote tabs
            for (var i = _hostTabs.TabPages.Count - 1; i >= 1; i--)
            {
                var page = _hostTabs.TabPages[i];
                var id = page.Tag as string;
                if (id is null || !wanted.Contains(id))
                {
                    if (id is not null) _tabNodeIds.Remove(id);
                    _hostTabs.TabPages.RemoveAt(i);
                }
            }
        }
        catch
        {
            // cluster optional
        }
    }

    private void TrimRemoteTabs()
    {
        for (var i = _hostTabs.TabPages.Count - 1; i >= 1; i--)
            _hostTabs.TabPages.RemoveAt(i);
        _tabNodeIds.Clear();
        if (_hostTabs.SelectedIndex != 0)
            _hostTabs.SelectedIndex = 0;
        ShowLocalView();
    }

    private async Task OnHostTabChangedAsync()
    {
        var tag = _hostTabs.SelectedTab?.Tag as string;
        _activeSubhostId = tag;
        if (tag is null)
        {
            ShowLocalView();
            await RefreshAllAsync();
            return;
        }

        _serversBox.Title = $"Host Servers — {_hostTabs.SelectedTab?.Text ?? tag}";
        await LoadRemoteTabAsync(tag);
    }

    private void ShowLocalView()
    {
        _activeSubhostId = null;
        _serversBox.Title = "Host Servers — Local Host";
        _servers.Visible = true;
        _remotePane.Visible = false;
    }

    private async Task LoadRemoteTabAsync(string? nodeId)
    {
        if (string.IsNullOrWhiteSpace(nodeId)) return;
        _servers.Visible = false;
        _remotePane.Visible = true;
        _remoteServers.Items.Clear();
        _remoteNote.Visible = true;

        try
        {
            var json = await _api.GetWebAsync($"/api/cluster/subhost/{Uri.EscapeDataString(nodeId)}/servers");
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            string? arrayJson = null;
            if (root.ValueKind == JsonValueKind.Array)
                arrayJson = root.GetRawText();
            else if (root.TryGetProperty("servers", out var s) && s.ValueKind == JsonValueKind.Array)
                arrayJson = s.GetRawText();
            else if (root.TryGetProperty("body", out var bodyEl))
            {
                var bodyText = bodyEl.ValueKind == JsonValueKind.String ? bodyEl.GetString() : bodyEl.GetRawText();
                if (!string.IsNullOrWhiteSpace(bodyText))
                {
                    using var inner = JsonDocument.Parse(bodyText!);
                    if (inner.RootElement.ValueKind == JsonValueKind.Array)
                        arrayJson = inner.RootElement.GetRawText();
                }
            }

            if (arrayJson is not null)
            {
                using var arrDoc = JsonDocument.Parse(arrayJson);
                _remoteNote.Visible = false;
                foreach (var item in arrDoc.RootElement.EnumerateArray())
                {
                    _remoteServers.Items.Add(new ListViewItem(new[]
                    {
                        Prop(item, "name", "Name", "id"),
                        Prop(item, "status", "Status"),
                        Prop(item, "type", "serverType", "ServerType"),
                        Prop(item, "notes", "Notes", "install_dir", "installDir")
                    }));
                }
                _statusText.Text = $"Remote node {nodeId}: {_remoteServers.Items.Count} servers";
                return;
            }
        }
        catch
        {
            // fall through to placeholder
        }

        _remoteNote.Text =
            $"No server list endpoint for subhost '{nodeId}'.\n" +
            "Use Start… / Stop… and enter a server name (POST /api/cluster/subhost/{id}/servers/{server}/start|stop).";
        _remoteServers.Items.Add(new ListViewItem(new[] { "(none listed)", "—", "—", "Prompted actions available via toolbar" }));
        _statusText.Text = $"Remote node {nodeId} (placeholder)";
        await Task.CompletedTask;
    }

    private async Task RemoteActAsync(string action)
    {
        if (string.IsNullOrWhiteSpace(_activeSubhostId))
        {
            MessageBox.Show(this, "Select a remote subhost tab first.", Text);
            return;
        }

        var name = _remoteServers.SelectedItems.Count > 0
            ? _remoteServers.SelectedItems[0].Text
            : null;
        if (string.IsNullOrWhiteSpace(name) || name.StartsWith('('))
        {
            name = PromptText("Remote server name", "Server name:");
            if (string.IsNullOrWhiteSpace(name)) return;
        }

        try
        {
            var json = await _api.PostWebJsonAsync(
                $"/api/cluster/subhost/{Uri.EscapeDataString(_activeSubhostId)}/servers/{Uri.EscapeDataString(name)}/{action}",
                new { });
            UiMessages.ShowApiResult(this, $"Remote {action}", json);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private static string? PromptText(string title, string label)
    {
        using var f = new HostUiForm
        {
            Text = title,
            Width = 360,
            Height = 140,
            FormBorderStyle = FormBorderStyle.FixedDialog,
            StartPosition = FormStartPosition.CenterParent,
            MaximizeBox = false,
            MinimizeBox = false
        };
        var tb = new TextBox { Left = 12, Top = 36, Width = 320 };
        f.Controls.Add(new Label { Left = 12, Top = 12, AutoSize = true, Text = label });
        f.Controls.Add(tb);
        var ok = new Button { Text = "OK", Left = 176, Top = 70, Width = 70, DialogResult = DialogResult.OK };
        var cancel = new Button { Text = "Cancel", Left = 256, Top = 70, Width = 70, DialogResult = DialogResult.Cancel };
        f.Controls.Add(ok);
        f.Controls.Add(cancel);
        f.AcceptButton = ok;
        f.CancelButton = cancel;
        return f.ShowDialog() == DialogResult.OK ? tb.Text.Trim() : null;
    }

    private static string Prop(JsonElement e, params string[] names)
    {
        foreach (var n in names)
            if (e.TryGetProperty(n, out var p) && p.ValueKind != JsonValueKind.Null)
                return p.ValueKind == JsonValueKind.String ? p.GetString() ?? "" : p.ToString();
        return "";
    }

    private static string FormatTemperatures(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            var lines = new List<string>();

            if (root.TryGetProperty("local", out var local) && local.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in local.EnumerateArray())
                {
                    var source = item.TryGetProperty("source", out var s) ? s.GetString() ?? "local" : "local";
                    if (item.TryGetProperty("celsius", out var c) && c.TryGetDouble(out var deg))
                        lines.Add($"Local ({source}): {deg:0.0} °C");
                    else if (item.TryGetProperty("message", out var m))
                        lines.Add(m.GetString() ?? "Local sensors unavailable");
                    else if (item.TryGetProperty("note", out var n) && n.GetString() == "unavailable")
                        lines.Add("Local sensors unavailable on this host");
                    else if (item.TryGetProperty("error", out var err))
                        lines.Add($"Local ({source}): unavailable");
                }
            }

            if (root.TryGetProperty("redfish", out var redfish) && redfish.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in redfish.EnumerateArray())
                {
                    var source = item.TryGetProperty("source", out var s) ? s.GetString() ?? "BMC" : "BMC";
                    var host = item.TryGetProperty("host", out var h) ? h.GetString() : null;
                    if (item.TryGetProperty("ok", out var ok) && ok.ValueKind == JsonValueKind.True)
                        lines.Add($"{source} ({host}): reachable");
                    else if (item.TryGetProperty("error", out var err))
                        lines.Add($"{source} ({host}): {err.GetString()}");
                    else if (item.TryGetProperty("note", out var note))
                        lines.Add($"{source} ({host}): {note.GetString()}");
                }
            }

            if (lines.Count == 0)
                return "No temperature data. Local ACPI often unavailable; set iLO/iDRAC in Settings → Hardware.";
            return string.Join(Environment.NewLine, lines);
        }
        catch
        {
            return "Temperature sensors not available";
        }
    }

    private async Task RefreshMetricsAsync()
    {
        try
        {
            var json = await _api.GetRuntimeAsync("/api/runtime/metrics/host");
            using var doc = JsonDocument.Parse(json);
            _sysInfo.ApplyMetrics(doc.RootElement);
            if (_api.IsAuthenticated && !_api.AuthExpired)
            {
                try
                {
                    var temps = await _api.GetWebAsync("/api/analytics/temperatures");
                    _sysInfo.SetTemperature(FormatTemperatures(temps));
                }
                catch
                {
                    if (_api.AuthExpired)
                        _sysInfo.SetTemperature("Session expired — sign in again for live temperatures.");
                    else
                        _sysInfo.SetTemperature("Local sensors unavailable. Configure iLO/iDRAC in Settings → Hardware if needed.");
                }
            }
        }
        catch { /* metrics optional */ }
    }

    private async Task StopOrRestartAsync(string action)
    {
        var name = SelectedName();
        if (name is null) { MessageBox.Show(this, "Select a server first.", Text); return; }
        using var dlg = new DelayedActionForm(action);
        if (dlg.ShowDialog(this) != DialogResult.OK) return;
        if (dlg.DelayMinutes > 0)
        {
            _statusText.Text = $"{action} {name} in {dlg.DelayMinutes} min…";
            await Task.Delay(TimeSpan.FromMinutes(dlg.DelayMinutes));
        }
        await ActSelectedAsync(action);
    }

    private async Task UpdateSelectedAsync(bool checkOnly)
    {
        var name = SelectedName();
        if (name is null) { MessageBox.Show(this, "Select a server first.", Text); return; }
        try
        {
            using var progress = new ProgressConsoleForm(checkOnly ? $"Check updates — {name}" : $"Update — {name}");
            progress.Show(this);
            progress.Append(checkOnly ? "Checking for updates…" : "Updating server…");
            var json = await _api.PostRuntimeAsync($"/api/runtime/servers/{Uri.EscapeDataString(name)}/update");
            progress.Append(json);
            progress.Done();
            if (!checkOnly) await RefreshAllAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private async Task ActSelectedAsync(string action)
    {
        if (_activeSubhostId is not null)
        {
            await RemoteActAsync(action is "start" or "stop" ? action : "start");
            return;
        }

        var name = SelectedName();
        if (name is null) { MessageBox.Show(this, "Select a server first.", Text); return; }
        try
        {
            _statusText.Text = $"{action} {name}…";
            var path = action switch
            {
                "kill" => $"/api/runtime/servers/{Uri.EscapeDataString(name)}/kill",
                "clear" => $"/api/runtime/servers/{Uri.EscapeDataString(name)}/clear",
                _ => $"/api/runtime/servers/{Uri.EscapeDataString(name)}/{action}"
            };
            await _api.PostRuntimeAsync(path);
            await RefreshAllAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private async Task ExportServerAsync()
    {
        var name = SelectedName();
        if (name is null) { MessageBox.Show(this, "Select a server first.", Text); return; }
        await ExportOptionsForm.RunExportAsync(_api, this, name, SelectedRow()?.InstallDir);
    }

    private async Task ImportServerAsync()
    {
        using var chooser = new ImportChooserForm();
        if (chooser.ShowDialog(this) != DialogResult.OK) return;

        if (chooser.Kind == ImportChooserForm.ImportKind.Directory)
        {
            using var reg = new RegisterDirectoryForm();
            if (reg.ShowDialog(this) != DialogResult.OK) return;
            try
            {
                await _api.PostWebJsonAsync("/api/servers", new
                {
                    name = reg.ServerName,
                    serverType = reg.ServerType,
                    installDir = reg.InstallDir
                });
                MessageBox.Show(this, $"Registered '{reg.ServerName}'.", Text, MessageBoxButtons.OK, MessageBoxIcon.Information);
                await RefreshAllAsync();
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, ex.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            return;
        }

        using var dlg = new OpenFileDialog
        {
            Title = "Import Server",
            Filter = "Server Manager export (*.smserver.json;*.json)|*.smserver.json;*.json|All files (*.*)|*.*"
        };
        if (dlg.ShowDialog(this) != DialogResult.OK) return;

        var mode = "overwrite";
        var choice = MessageBox.Show(this,
            "If a server with the same name exists:\n\nYes = Overwrite\nNo = Rename imported copy\nCancel = Skip if exists",
            "Import conflict mode", MessageBoxButtons.YesNoCancel, MessageBoxIcon.Question);
        if (choice == DialogResult.Cancel) mode = "skip";
        else if (choice == DialogResult.No) mode = "rename";

        try
        {
            var body = await File.ReadAllTextAsync(dlg.FileName);
            var json = await _api.PostWebRawAsync($"/api/servers/import?mode={mode}", body);
            UiMessages.ShowApiResult(this, "Import Server", json);
            await RefreshAllAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private void OpenSelectedConsole()
    {
        var name = SelectedName();
        if (name is null) return;
        new ConsoleForm(_api, name).Show(this);
    }

    private void OpenConsoleManager()
    {
        new ConsoleManagerForm(_api).ShowDialog(this);
    }

    private void ConfigureSelected()
    {
        var name = SelectedName();
        if (name is null) return;
        if (new ConfigureServerForm(_api, name).ShowDialog(this) == DialogResult.OK)
            _ = RefreshAllAsync();
    }

    private void ShowProcessDetails()
    {
        var row = SelectedRow();
        if (row is null) return;
        new ProcessDetailsForm(_api, row).ShowDialog(this);
    }

    private void OpenFolder()
    {
        var row = SelectedRow();
        if (row?.InstallDir is null || !Directory.Exists(row.InstallDir))
        {
            MessageBox.Show(this, "Install directory not found.", Text);
            return;
        }
        Process.Start(new ProcessStartInfo { FileName = row.InstallDir, UseShellExecute = true });
    }

    private async Task RemoveSelectedAsync()
    {
        var name = SelectedName();
        if (name is null) return;
        if (MessageBox.Show(this, $"Remove server '{name}' from the database?", Text, MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes)
            return;
        try
        {
            await _api.DeleteWebAsync($"/api/servers/{Uri.EscapeDataString(name)}");
            await RefreshAllAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private void ShowAddServer()
    {
        using var wizard = new AddServerWizardForm(_api);
        if (wizard.ShowDialog(this) == DialogResult.OK)
            _ = RefreshAllAsync();
    }

    private async Task UpdateAllAsync()
    {
        try
        {
            _statusText.Text = "Updating all servers…";
            var json = await _api.PostRuntimeAsync("/api/runtime/servers/update-all");
            UiMessages.ShowApiResult(this, "Update All", json);
            await RefreshAllAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private async Task ReattachAllAsync()
    {
        try
        {
            var json = await _api.PostRuntimeAsync("/api/runtime/reattach-all");
            UiMessages.ShowApiResult(this, "Reattach All Consoles", json);
            await RefreshAllAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private async Task FindBrokenAsync()
    {
        try
        {
            var json = await _api.GetRuntimeAsync("/api/runtime/servers/broken");
            UiMessages.ShowApiResult(this, "Find Broken Servers", json);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private async Task VerifyServersAsync()
    {
        try
        {
            var json = await _api.GetRuntimeAsync("/api/runtime/servers/verify");
            UiMessages.ShowApiResult(this, "Verify Servers", json);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private async Task DbToolAsync(string action)
    {
        try
        {
            var apiAction = action.Equals("checkpoint", StringComparison.OrdinalIgnoreCase) ? "update" : action;
            var json = await _api.PostRuntimeAsync($"/api/runtime/db/{apiAction}");
            UiMessages.ShowApiResult(this, action.Equals("checkpoint", StringComparison.OrdinalIgnoreCase) ? "Checkpoint Databases" : "Verify Databases", json);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
