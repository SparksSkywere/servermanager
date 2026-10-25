using System.Text.Json;

namespace ServerManager.HostUI;

internal sealed class SettingsForm : HostUiForm
{
    private readonly ApiClient _api;

    // Dashboard
    private readonly CheckBox _debugMode = new() { Text = "Debug mode", AutoSize = true };
    private readonly CheckBox _hideConsoles = new() { Text = "Hide consoles", AutoSize = true, Checked = true };
    private readonly NumericUpDown _refreshInterval = new() { Minimum = 1, Maximum = 3600, Value = 5 };
    private readonly NumericUpDown _windowWidth = new() { Minimum = 640, Maximum = 10000, Value = 1280 };
    private readonly NumericUpDown _windowHeight = new() { Minimum = 480, Maximum = 10000, Value = 800 };

    // Updates
    private readonly ComboBox _updateChannel = new() { DropDownStyle = ComboBoxStyle.DropDownList };
    private readonly TextBox _updateBranch = new();

    // Steam
    private readonly CheckBox _steamAnon = new() { Text = "Anonymous login", AutoSize = true };
    private readonly TextBox _steamUser = new();
    private readonly TextBox _steamPass = new() { UseSystemPasswordChar = true };
    private readonly CheckBox _showSteamPass = new() { Text = "Show", AutoSize = true };
    private readonly TextBox _steamGuard = new() { UseSystemPasswordChar = true };
    private readonly TextBox _steamCmd = new();
    private readonly TextBox _steamWebApiKey = new() { UseSystemPasswordChar = true };
    private readonly CheckBox _showSteamWebApiKey = new() { Text = "Show", AutoSize = true };

    // System
    private readonly ComboBox _theme = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 280 };
    private readonly NumericUpDown _web = new() { Minimum = 1, Maximum = 65535 };
    private readonly NumericUpDown _runtime = new() { Minimum = 1, Maximum = 65535 };
    private readonly CheckBox _autoUpdates = new() { Text = "Auto updates", AutoSize = true };
    private readonly CheckBox _trayIcon = new() { Text = "Tray icon", AutoSize = true, Checked = true };
    private readonly ComboBox _logLevel = new() { DropDownStyle = ComboBoxStyle.DropDownList };
    private readonly NumericUpDown _logMaxMb = new() { Minimum = 1, Maximum = 10240, Value = 50 };

    // Hardware
    private readonly ComboBox _tempMode = new() { DropDownStyle = ComboBoxStyle.DropDownList };
    private readonly NumericUpDown _pollInterval = new() { Minimum = 5, Maximum = 3600, Value = 30 };
    private readonly TextBox _iloHost = new();
    private readonly TextBox _iloUser = new();
    private readonly TextBox _iloPass = new() { UseSystemPasswordChar = true };
    private readonly TextBox _idracHost = new();
    private readonly TextBox _idracUser = new();
    private readonly TextBox _idracPass = new() { UseSystemPasswordChar = true };
    private readonly CheckBox _bmcTlsVerify = new() { Text = "BMC TLS verify", AutoSize = true, Checked = true };

    // Cluster
    private readonly ComboBox _hostType = new() { DropDownStyle = ComboBoxStyle.DropDownList };
    private readonly CheckBox _clusterEnabled = new() { Text = "Enable cluster", AutoSize = true };
    private readonly TextBox _hostAddress = new();
    private readonly TextBox _clusterToken = new();
    private readonly NumericUpDown _cluster = new() { Minimum = 1, Maximum = 65535 };

    // Minecraft
    private readonly TextBox _curseForge = new() { UseSystemPasswordChar = true };
    private readonly CheckBox _showCurse = new() { Text = "Show", AutoSize = true };

    public SettingsForm(ApiClient api)
    {
        _api = api;
        Text = "Settings";
        Width = 720;
        Height = 680;
        DialogLayout.ApplyFormDefaults(this, 560, 480, allowResize: true);
        StartPosition = FormStartPosition.CenterParent;
        _hostType.Items.AddRange(["standalone", "host", "subhost"]);
        foreach (var opt in ThemeCatalog.PickerOptions)
            _theme.Items.Add(opt);
        _theme.SelectedItem = ThemeCatalog.FindPickerOption(ThemeCatalog.SystemId);
        _updateChannel.Items.AddRange(["stable", "beta", "dev"]);
        _updateChannel.SelectedItem = "stable";
        _logLevel.Items.AddRange(["Verbose", "Debug", "Information", "Warning", "Error", "Fatal"]);
        _logLevel.SelectedItem = "Information";
        _tempMode.Items.AddRange(["auto", "local", "ilo", "idrac"]);
        _tempMode.SelectedItem = "auto";
        _showSteamPass.CheckedChanged += (_, _) => _steamPass.UseSystemPasswordChar = !_showSteamPass.Checked;
        _showSteamWebApiKey.CheckedChanged += (_, _) => _steamWebApiKey.UseSystemPasswordChar = !_showSteamWebApiKey.Checked;
        _showCurse.CheckedChanged += (_, _) => _curseForge.UseSystemPasswordChar = !_showCurse.Checked;

        var tabs = new ThemedTabControl { Dock = DockStyle.Fill };

        tabs.TabPages.Add(Page("Dashboard",
            DialogLayout.CheckRow(_debugMode),
            DialogLayout.CheckRow(_hideConsoles),
            DialogLayout.LabeledRow("Refresh interval (sec)", _refreshInterval),
            DialogLayout.LabeledRow("Window width", _windowWidth),
            DialogLayout.LabeledRow("Window height", _windowHeight),
            DialogLayout.LabeledRow("Theme", _theme)));

        var checkUpdates = new Button { Text = "Check Updates" };
        checkUpdates.Click += (_, _) => MessageBox.Show(this, "Update check is not available yet.", Text);
        var runUpdater = new Button { Text = "Run Updater" };
        runUpdater.Click += (_, _) => MessageBox.Show(this, "Updater stub — not available yet.", Text);
        tabs.TabPages.Add(Page("Updates",
            DialogLayout.LabeledRow("Update channel", _updateChannel),
            DialogLayout.LabeledRow("Update branch", _updateBranch),
            DialogLayout.ButtonRow(160, checkUpdates, runUpdater)));

        var testSteam = new Button { Text = "Test Code" };
        testSteam.Click += async (_, _) => await TestSteamGuardAsync();
        var saveSteam = new Button { Text = "Save Steam" };
        saveSteam.Click += async (_, _) => await SaveSteamAsync();
        var clearSteam = new Button { Text = "Clear Steam" };
        clearSteam.Click += async (_, _) => await ClearSteamAsync();
        tabs.TabPages.Add(Page("Steam",
            DialogLayout.CheckRow(_steamAnon),
            DialogLayout.LabeledRow("Username", _steamUser),
            DialogLayout.LabeledRow("Password", WrapWithShow(_steamPass, _showSteamPass)),
            DialogLayout.LabeledRow("Steam Guard secret", _steamGuard),
            DialogLayout.LabeledRow("SteamCMD path", _steamCmd),
            DialogLayout.LabeledRow("Web API key (catalog scan)", WrapWithShow(_steamWebApiKey, _showSteamWebApiKey)),
            DialogLayout.ButtonRow(160, testSteam, saveSteam, clearSteam)));

        tabs.TabPages.Add(Page("System",
            DialogLayout.LabeledRow("Web port", _web),
            DialogLayout.LabeledRow("HostRuntime port", _runtime),
            DialogLayout.CheckRow(_autoUpdates),
            DialogLayout.CheckRow(_trayIcon),
            DialogLayout.LabeledRow("Log level", _logLevel),
            DialogLayout.LabeledRow("Log max MB", _logMaxMb)));

        var testIlo = new Button { Text = "Test iLO" };
        testIlo.Click += async (_, _) => await TestHardwareAsync("ilo");
        var testIdrac = new Button { Text = "Test iDRAC" };
        testIdrac.Click += async (_, _) => await TestHardwareAsync("idrac");
        tabs.TabPages.Add(Page("Hardware",
            DialogLayout.LabeledRow("Temp mode", _tempMode),
            DialogLayout.LabeledRow("Poll interval (sec)", _pollInterval),
            DialogLayout.LabeledRow("iLO host", _iloHost),
            DialogLayout.LabeledRow("iLO user", _iloUser),
            DialogLayout.LabeledRow("iLO password", _iloPass),
            DialogLayout.LabeledRow("iDRAC host", _idracHost),
            DialogLayout.LabeledRow("iDRAC user", _idracUser),
            DialogLayout.LabeledRow("iDRAC password", _idracPass),
            DialogLayout.CheckRow(_bmcTlsVerify),
            DialogLayout.ButtonRow(160, testIlo, testIdrac)));

        tabs.TabPages.Add(Page("Cluster",
            DialogLayout.LabeledRow("Host type", _hostType),
            DialogLayout.CheckRow(_clusterEnabled),
            DialogLayout.LabeledRow("Host address", _hostAddress),
            DialogLayout.LabeledRow("Cluster token", _clusterToken),
            DialogLayout.LabeledRow("Cluster peer port", _cluster)));

        var saveCf = new Button { Text = "Save Key" };
        saveCf.Click += async (_, _) => await SaveCurseAsync();
        var clearCf = new Button { Text = "Clear Key" };
        clearCf.Click += async (_, _) => await ClearCurseAsync();
        tabs.TabPages.Add(Page("Minecraft",
            DialogLayout.LabeledRow("CurseForge API key", WrapWithShow(_curseForge, _showCurse)),
            DialogLayout.ButtonRow(160, saveCf, clearCf)));

        var save = new Button { Text = "Save" };
        var cancel = new Button { Text = "Close", DialogResult = DialogResult.Cancel };
        save.Click += async (_, _) => await SaveAsync();
        DialogLayout.Host(this, tabs, DialogLayout.ButtonBar(save, cancel));
        Shown += async (_, _) => await LoadAsync();
    }

    private async Task LoadAsync()
    {
        try
        {
            var json = await _api.GetWebAsync("/api/settings");
            using var doc = JsonDocument.Parse(json);
            var e = doc.RootElement;
            if (e.TryGetProperty("web_port", out var wp)) _web.Value = wp.GetInt32();
            if (e.TryGetProperty("host_runtime_port", out var rp)) _runtime.Value = rp.GetInt32();
            if (e.TryGetProperty("cluster_port", out var cp)) _cluster.Value = cp.GetInt32();
            _steamCmd.Text = e.TryGetProperty("steam_cmd_path", out var sc) ? sc.GetString() ?? "" : "";
            var ht = e.TryGetProperty("host_type", out var h) ? h.GetString() ?? "standalone" : "standalone";
            _hostType.SelectedItem = _hostType.Items.Contains(ht) ? ht : "standalone";
            _clusterEnabled.Checked = e.TryGetProperty("cluster_enabled", out var ce) && ce.ValueKind == JsonValueKind.True;
            _hostAddress.Text = e.TryGetProperty("host_address", out var ha) ? ha.GetString() ?? "" : "";

            if (_api.IsAdmin)
            {
                var all = await _api.GetWebAsync("/api/system-settings");
                using var doc2 = JsonDocument.Parse(all);
                foreach (var p in doc2.RootElement.EnumerateObject())
                {
                    var v = p.Value.GetString() ?? "";
                    switch (p.Name)
                    {
                        case "SteamUsername": _steamUser.Text = v; break;
                        case "SteamAnonymous":
                        case "SteamAnon": _steamAnon.Checked = v == "true"; break;
                        case "SteamGuardSecret": _steamGuard.Text = v; break;
                        case "SteamCmdPath": if (!string.IsNullOrWhiteSpace(v)) _steamCmd.Text = v; break;
                        case "SteamWebApiKey": _steamWebApiKey.Text = v; break;
                        case "IloHost": _iloHost.Text = v; break;
                        case "IloUser": _iloUser.Text = v; break;
                        case "IdracHost": _idracHost.Text = v; break;
                        case "IdracUser": _idracUser.Text = v; break;
                        case "BmcTlsVerify": _bmcTlsVerify.Checked = v != "false"; break;
                        case "TempMode":
                            if (_tempMode.Items.Contains(v)) _tempMode.SelectedItem = v;
                            break;
                        case "HardwarePollIntervalSec":
                        case "PollInterval":
                            if (int.TryParse(v, out var pi)) _pollInterval.Value = Math.Clamp(pi, 5, 3600);
                            break;
                        case "CurseForgeApiKey": _curseForge.Text = v; break;
                        case "ClusterToken": _clusterToken.Text = v; break;
                        case "HostAddress":
                            if (string.IsNullOrWhiteSpace(_hostAddress.Text)) _hostAddress.Text = v;
                            break;
                        case "ClusterEnabled": _clusterEnabled.Checked = v == "true"; break;
                        case "DebugMode": _debugMode.Checked = v == "true"; break;
                        case "HideConsoles": _hideConsoles.Checked = v == "true"; break;
                        case "RefreshIntervalSec":
                            if (int.TryParse(v, out var ri)) _refreshInterval.Value = Math.Clamp(ri, 1, 3600);
                            break;
                        case "WindowWidth":
                            if (int.TryParse(v, out var ww)) _windowWidth.Value = Math.Clamp(ww, 640, 10000);
                            break;
                        case "WindowHeight":
                            if (int.TryParse(v, out var wh)) _windowHeight.Value = Math.Clamp(wh, 480, 10000);
                            break;
                        case "UpdateChannel":
                            if (_updateChannel.Items.Contains(v)) _updateChannel.SelectedItem = v;
                            break;
                        case "UpdateBranch": _updateBranch.Text = v; break;
                        case "AutoUpdates": _autoUpdates.Checked = v == "true"; break;
                        case "TrayIcon": _trayIcon.Checked = v != "false"; break;
                        case "LogLevel":
                            if (_logLevel.Items.Contains(v)) _logLevel.SelectedItem = v;
                            break;
                        case "LogMaxMb":
                            if (int.TryParse(v, out var lm)) _logMaxMb.Value = Math.Clamp(lm, 1, 10240);
                            break;
                        case "Theme":
                            SelectTheme(v);
                            break;
                    }
                }
            }

            try
            {
                var profile = await _api.GetWebAsync("/api/profile");
                using var pdoc = JsonDocument.Parse(profile);
                var theme = pdoc.RootElement.TryGetProperty("theme", out var th) ? th.GetString() ?? "system" : "system";
                if (_theme.SelectedItem is null || SelectedThemeId() == ThemeCatalog.SystemId)
                    SelectTheme(theme);
            }
            catch { if (_theme.SelectedItem is null) SelectTheme(ThemeCatalog.SystemId); }
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private async Task SaveAsync()
    {
        try
        {
            var map = BuildCommonMap();
            if (!string.IsNullOrWhiteSpace(_steamPass.Text))
                map["SteamPassword"] = _steamPass.Text;
            if (!string.IsNullOrWhiteSpace(_iloPass.Text))
                map["IloPassword"] = _iloPass.Text;
            if (!string.IsNullOrWhiteSpace(_idracPass.Text))
                map["IdracPassword"] = _idracPass.Text;
            if (!string.IsNullOrWhiteSpace(_clusterToken.Text))
                map["ClusterToken"] = _clusterToken.Text.Trim();
            if (!string.IsNullOrWhiteSpace(_steamGuard.Text))
                map["SteamGuardSecret"] = _steamGuard.Text.Trim();
            if (!string.IsNullOrWhiteSpace(_curseForge.Text))
                map["CurseForgeApiKey"] = _curseForge.Text.Trim();
            if (!string.IsNullOrWhiteSpace(_steamWebApiKey.Text))
                map["SteamWebApiKey"] = _steamWebApiKey.Text.Trim();

            await _api.PostWebJsonAsync("/api/system-settings", map);
            TrayLauncher.ApplyPreference(_trayIcon.Checked);
            var theme = SelectedThemeId();
            try
            {
                await _api.PutWebJsonAsync("/api/profile", new { theme });
            }
            catch { /* optional */ }
            try { ThemeApplier.Apply(theme); } catch { /* optional */ }
            MessageBox.Show(this, "Settings saved. Restart services if ports or cluster role changed.", Text);
            DialogResult = DialogResult.OK;
            Close();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private Dictionary<string, string> BuildCommonMap() => new()
    {
        ["WebPort"] = ((int)_web.Value).ToString(),
        ["HostRuntimePort"] = ((int)_runtime.Value).ToString(),
        ["ClusterPort"] = ((int)_cluster.Value).ToString(),
        ["HostType"] = _hostType.SelectedItem?.ToString() ?? "standalone",
        ["ClusterEnabled"] = _clusterEnabled.Checked ? "true" : "false",
        ["HostAddress"] = _hostAddress.Text.Trim(),
        ["SteamCmdPath"] = _steamCmd.Text.Trim(),
        ["SteamUsername"] = _steamUser.Text.Trim(),
        ["SteamAnon"] = _steamAnon.Checked ? "true" : "false",
        ["SteamCmdPath"] = _steamCmd.Text.Trim(),
        ["SteamWebApiKey"] = _steamWebApiKey.Text.Trim(),
        ["IloHost"] = _iloHost.Text.Trim(),
        ["IloUser"] = _iloUser.Text.Trim(),
        ["IdracHost"] = _idracHost.Text.Trim(),
        ["IdracUser"] = _idracUser.Text.Trim(),
        ["BmcTlsVerify"] = _bmcTlsVerify.Checked ? "true" : "false",
        ["TempMode"] = _tempMode.SelectedItem?.ToString() ?? "auto",
        ["HardwarePollIntervalSec"] = ((int)_pollInterval.Value).ToString(),
        ["DebugMode"] = _debugMode.Checked ? "true" : "false",
        ["HideConsoles"] = _hideConsoles.Checked ? "true" : "false",
        ["RefreshIntervalSec"] = ((int)_refreshInterval.Value).ToString(),
        ["WindowWidth"] = ((int)_windowWidth.Value).ToString(),
        ["WindowHeight"] = ((int)_windowHeight.Value).ToString(),
        ["UpdateChannel"] = _updateChannel.SelectedItem?.ToString() ?? "stable",
        ["UpdateBranch"] = _updateBranch.Text.Trim(),
        ["AutoUpdates"] = _autoUpdates.Checked ? "true" : "false",
        ["TrayIcon"] = _trayIcon.Checked ? "true" : "false",
        ["LogLevel"] = _logLevel.SelectedItem?.ToString() ?? "Information",
        ["LogMaxMb"] = ((int)_logMaxMb.Value).ToString(),
        ["Theme"] = SelectedThemeId()
    };

    private string SelectedThemeId()
        => (_theme.SelectedItem as ThemePickerOption)?.Id
           ?? ThemeCatalog.NormalizeId(_theme.SelectedItem?.ToString());

    private void SelectTheme(string? preference)
    {
        var opt = ThemeCatalog.FindPickerOption(preference);
        foreach (ThemePickerOption item in _theme.Items)
        {
            if (item.Id.Equals(opt.Id, StringComparison.OrdinalIgnoreCase))
            {
                _theme.SelectedItem = item;
                return;
            }
        }
        _theme.SelectedItem = opt;
    }

    private async Task SaveSteamAsync()
    {
        try
        {
            var map = new Dictionary<string, string>
            {
                ["SteamUsername"] = _steamUser.Text.Trim(),
                ["SteamAnon"] = _steamAnon.Checked ? "true" : "false",
                ["SteamCmdPath"] = _steamCmd.Text.Trim(),
                ["SteamGuardSecret"] = _steamGuard.Text.Trim(),
                ["SteamWebApiKey"] = _steamWebApiKey.Text.Trim()
            };
            if (!string.IsNullOrWhiteSpace(_steamPass.Text))
                map["SteamPassword"] = _steamPass.Text;
            await _api.PostWebJsonAsync("/api/system-settings", map);
            MessageBox.Show(this, "Steam settings saved.", Text);
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, Text); }
    }

    private async Task ClearSteamAsync()
    {
        try
        {
            await _api.PostWebJsonAsync("/api/system-settings", new Dictionary<string, string>
            {
                ["SteamUsername"] = "",
                ["SteamPassword"] = "",
                ["SteamGuardSecret"] = "",
                ["SteamAnon"] = "true"
            });
            _steamUser.Clear();
            _steamPass.Clear();
            _steamGuard.Clear();
            _steamAnon.Checked = true;
            MessageBox.Show(this, "Steam credentials cleared.", Text);
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, Text); }
    }

    private async Task TestSteamGuardAsync()
    {
        try
        {
            var json = await _api.PostWebJsonAsync("/api/steam/guard/test", new { secret = _steamGuard.Text.Trim() });
            UiMessages.ShowApiResult(this, "Steam Guard Test", json);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this,
                "Steam Guard test API unavailable.\n" +
                "Ensure SteamGuardSecret is set and use your authenticator app for codes.\n\n" +
                ex.Message, Text);
        }
    }

    private async Task TestHardwareAsync(string kind)
    {
        try
        {
            var map = new Dictionary<string, string>
            {
                ["TempMode"] = kind,
                ["IloHost"] = _iloHost.Text.Trim(),
                ["IloUser"] = _iloUser.Text.Trim(),
                ["IdracHost"] = _idracHost.Text.Trim(),
                ["IdracUser"] = _idracUser.Text.Trim(),
                ["BmcTlsVerify"] = _bmcTlsVerify.Checked ? "true" : "false"
            };
            if (!string.IsNullOrWhiteSpace(_iloPass.Text)) map["IloPassword"] = _iloPass.Text;
            if (!string.IsNullOrWhiteSpace(_idracPass.Text)) map["IdracPassword"] = _idracPass.Text;
            await _api.PostWebJsonAsync("/api/system-settings", map);
            var json = await _api.GetWebAsync("/api/analytics/temperatures");
            UiMessages.ShowApiResult(this, $"Test {kind.ToUpperInvariant()}", json);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private async Task SaveCurseAsync()
    {
        try
        {
            await _api.PostWebJsonAsync("/api/system-settings", new Dictionary<string, string>
            {
                ["CurseForgeApiKey"] = _curseForge.Text.Trim()
            });
            MessageBox.Show(this, "CurseForge API key saved.", Text);
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, Text); }
    }

    private async Task ClearCurseAsync()
    {
        try
        {
            await _api.PostWebJsonAsync("/api/system-settings", new Dictionary<string, string>
            {
                ["CurseForgeApiKey"] = ""
            });
            _curseForge.Clear();
            MessageBox.Show(this, "CurseForge API key cleared.", Text);
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, Text); }
    }

    private static TabPage Page(string title, params Control[] rows)
    {
        var page = new TabPage(title)
        {
            BackColor = UiTheme.FormBack,
            ForeColor = UiTheme.FormFore,
            UseVisualStyleBackColor = false,
            Padding = new Padding(4)
        };
        page.Controls.Add(DialogLayout.ScrollableStack(rows));
        return page;
    }

    private static Control WrapWithShow(TextBox box, CheckBox show)
    {
        var wrap = new TableLayoutPanel { ColumnCount = 2, Dock = DockStyle.Fill, Height = 28 };
        wrap.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        wrap.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 70));
        box.Dock = DockStyle.Fill;
        show.AutoSize = true;
        show.Dock = DockStyle.Fill;
        wrap.Controls.Add(box, 0, 0);
        wrap.Controls.Add(show, 1, 0);
        return wrap;
    }
}
