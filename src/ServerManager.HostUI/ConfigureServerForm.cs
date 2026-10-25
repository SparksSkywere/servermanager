using System.Text.Json;

namespace ServerManager.HostUI;

internal sealed class ConfigureServerForm : HostUiForm
{
    private readonly ApiClient _api;
    private readonly string? _existingName;
    private readonly TextBox _name = new();
    private readonly ComboBox _type = new() { DropDownStyle = ComboBoxStyle.DropDownList };
    private readonly TextBox _appId = new();
    private readonly TextBox _installDir = new();
    private readonly TextBox _executable = new();
    private readonly TextBox _launchArgs = new();
    private readonly TextBox _stopCommand = new();
    private readonly TextBox _saveCommand = new();
    private readonly TextBox _startCommand = new();
    private readonly TextBox _javaPath = new();
    private readonly TextBox _version = new();
    private readonly TextBox _motdMessage = new();
    private readonly TextBox _motdCommand = new();
    private readonly NumericUpDown _motdInterval = new() { Minimum = 0, Maximum = 10080, Value = 0 };
    private readonly TextBox _warningCommand = new();
    private readonly TextBox _warningIntervals = new() { Text = "30,15,10,5,1" };
    private readonly TextBox _warningMessageTemplate = new();
    private readonly CheckBox _autoStart = new() { Text = "Auto-start", AutoSize = true };
    private readonly CheckBox _autoUpdate = new() { Text = "Auto-update", AutoSize = true };
    private readonly CheckBox _scheduledRestart = new() { Text = "Scheduled restart", AutoSize = true };
    private readonly TextBox _ramMb = new();
    private readonly TextBox _jvmArgs = new();
    private readonly TextBox _modLoader = new();
    private readonly TextBox _category = new();
    private readonly TextBox _notes = new();

    private Control? _rowAppId;
    private Control? _rowJava;
    private Control? _rowVersion;
    private Control? _rowRam;
    private Control? _rowJvm;
    private Control? _rowModLoader;
    private Control? _rowAutoUpdate;

    public ConfigureServerForm(ApiClient api, string? existingName, string? preferredType = null)
    {
        _api = api;
        _existingName = existingName;
        Text = existingName is null ? "Add Server" : $"Configure Server — {existingName}";
        Width = 720;
        Height = 780;
        DialogLayout.ApplyFormDefaults(this, 600, 520, allowResize: true);
        StartPosition = FormStartPosition.CenterParent;
        MaximizeBox = true;

        _type.Items.AddRange(["steam", "minecraft", "minecraft_modded", "custom"]);
        _type.SelectedIndex = 0;
        if (!string.IsNullOrWhiteSpace(preferredType))
            Set(_type, preferredType!);

        _rowAppId = BrowseRow("App ID", _appId, "Browse…", BrowseAppId);
        _rowJava = Labeled("Java path", _javaPath);
        _rowVersion = BrowseRow("Version", _version, "Browse…", BrowseVersion);
        _rowRam = Labeled("RAM (MB)", _ramMb);
        _rowJvm = Labeled("JVM args", _jvmArgs);
        _rowModLoader = Labeled("Mod loader", _modLoader);
        _rowAutoUpdate = CheckRow(_autoUpdate);

        var tabs = new ThemedTabControl { Dock = DockStyle.Fill };
        tabs.TabPages.Add(MakePage("Identity",
            Labeled("Name", _name),
            Labeled("Type", _type),
            _rowAppId,
            BrowseRow("Install dir", _installDir, "Browse…", BrowseInstallDir),
            BrowseRow("Executable", _executable, "Browse…", BrowseExecutable),
            Labeled("Category", _category),
            Labeled("Notes", _notes)));
        tabs.TabPages.Add(MakePage("Startup",
            Labeled("Launch args", _launchArgs),
            Labeled("Stop command", _stopCommand),
            Labeled("Save command", _saveCommand),
            Labeled("Start command", _startCommand),
            _rowJava,
            _rowVersion,
            _rowRam,
            _rowJvm,
            _rowModLoader,
            CheckRow(_autoStart),
            _rowAutoUpdate,
            CheckRow(_scheduledRestart)));
        tabs.TabPages.Add(MakePage("Scheduled",
            Labeled("MOTD message", _motdMessage),
            Labeled("MOTD command", _motdCommand),
            Labeled("MOTD interval (min)", _motdInterval),
            Labeled("Warning command", _warningCommand),
            Labeled("Warning intervals", _warningIntervals),
            Labeled("Warning message", _warningMessageTemplate)));

        var save = new Button { Text = "Save" };
        var cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel };
        save.Click += async (_, _) => await SaveAsync();
        Button? perms = null;
        if (existingName is not null)
        {
            perms = new Button { Text = "Permissions…" };
            perms.Click += (_, _) =>
            {
                using var editor = new PermissionsEditorForm(_api, existingName);
                editor.ShowDialog(this);
            };
        }

        DialogLayout.Host(this, tabs, perms is null
            ? DialogLayout.ButtonBar(save, cancel)
            : DialogLayout.ButtonBar(save, cancel, perms));
        CancelButton = cancel;

        _type.SelectedIndexChanged += (_, _) => ApplyTypePanels();
        ApplyTypePanels();

        if (existingName is not null)
        {
            _name.Text = existingName;
            _name.ReadOnly = true;
            Shown += async (_, _) => await LoadAsync();
        }
    }

    private void ApplyTypePanels()
    {
        var t = (_type.SelectedItem?.ToString() ?? "steam").ToLowerInvariant();
        var steam = t is "steam";
        var mc = t is "minecraft" or "minecraft_modded";
        var modded = t is "minecraft_modded";

        if (_rowAppId is not null) _rowAppId.Visible = steam || t == "custom";
        if (_rowAutoUpdate is not null) _rowAutoUpdate.Visible = steam;
        if (_rowJava is not null) _rowJava.Visible = mc;
        if (_rowVersion is not null) _rowVersion.Visible = mc;
        if (_rowRam is not null) _rowRam.Visible = mc;
        if (_rowJvm is not null) _rowJvm.Visible = mc;
        if (_rowModLoader is not null) _rowModLoader.Visible = modded;
    }

    private void BrowseAppId()
    {
        using var dlg = new AppIdBrowserForm(_api);
        if (dlg.ShowDialog(this) == DialogResult.OK && !string.IsNullOrWhiteSpace(dlg.SelectedAppId))
            _appId.Text = dlg.SelectedAppId!;
    }

    private void BrowseVersion()
    {
        using var dlg = new McVersionBrowserForm(_api);
        if (dlg.ShowDialog(this) == DialogResult.OK && !string.IsNullOrWhiteSpace(dlg.SelectedVersion))
            _version.Text = dlg.SelectedVersion!;
    }

    private void BrowseInstallDir()
    {
        using var dlg = new FolderBrowserDialog { Description = "Select install directory" };
        if (!string.IsNullOrWhiteSpace(_installDir.Text) && Directory.Exists(_installDir.Text))
            dlg.SelectedPath = _installDir.Text;
        if (dlg.ShowDialog(this) == DialogResult.OK)
            _installDir.Text = dlg.SelectedPath;
    }

    private void BrowseExecutable()
    {
        using var dlg = new OpenFileDialog
        {
            Title = "Select executable",
            Filter = "Executables (*.exe;*.bat;*.cmd;*.sh;*.jar)|*.exe;*.bat;*.cmd;*.sh;*.jar|All files (*.*)|*.*"
        };
        if (!string.IsNullOrWhiteSpace(_installDir.Text) && Directory.Exists(_installDir.Text))
            dlg.InitialDirectory = _installDir.Text;
        if (dlg.ShowDialog(this) == DialogResult.OK)
            _executable.Text = dlg.FileName;
    }

    private async Task LoadAsync()
    {
        try
        {
            var json = await _api.GetWebAsync($"/api/servers/{Uri.EscapeDataString(_existingName!)}");
            using var doc = JsonDocument.Parse(json);
            var e = doc.RootElement;
            Set(_type, Str(e, "type") ?? Str(e, "serverType") ?? "steam");
            _appId.Text = Str(e, "app_id") ?? Str(e, "appId") ?? "";
            _installDir.Text = Str(e, "install_dir") ?? Str(e, "installDir") ?? "";
            _executable.Text = Str(e, "executable") ?? "";
            _launchArgs.Text = Str(e, "launch_args") ?? Str(e, "launchArgs") ?? "";
            _stopCommand.Text = Str(e, "stop_command") ?? Str(e, "stopCommand") ?? "";
            _saveCommand.Text = Str(e, "save_command") ?? Str(e, "saveCommand") ?? "";
            _startCommand.Text = Str(e, "start_command") ?? Str(e, "startCommand") ?? "";
            _javaPath.Text = Str(e, "java_path") ?? Str(e, "javaPath") ?? "";
            _version.Text = Str(e, "version") ?? "";
            _modLoader.Text = Str(e, "mod_loader") ?? Str(e, "modLoader") ?? "";
            _ramMb.Text = Str(e, "ram_mb") ?? Str(e, "ramMb") ?? "";
            if (string.IsNullOrEmpty(_ramMb.Text) && e.TryGetProperty("ram_mb", out var ram) && ram.ValueKind == JsonValueKind.Number)
                _ramMb.Text = ram.GetInt32().ToString();
            else if (string.IsNullOrEmpty(_ramMb.Text) && e.TryGetProperty("ramMb", out var ram2) && ram2.ValueKind == JsonValueKind.Number)
                _ramMb.Text = ram2.GetInt32().ToString();
            _jvmArgs.Text = Str(e, "jvm_args") ?? Str(e, "jvmArgs") ?? "";
            _motdMessage.Text = Str(e, "motd_message") ?? Str(e, "motdMessage") ?? "";
            _motdCommand.Text = Str(e, "motd_command") ?? Str(e, "motdCommand") ?? "";
            if (e.TryGetProperty("motd_interval", out var mi) && mi.TryGetInt32(out var miv)) _motdInterval.Value = miv;
            else if (e.TryGetProperty("motdInterval", out var mi2) && mi2.TryGetInt32(out var miv2)) _motdInterval.Value = miv2;
            _warningCommand.Text = Str(e, "warning_command") ?? Str(e, "warningCommand") ?? "";
            _warningIntervals.Text = Str(e, "warning_intervals") ?? Str(e, "warningIntervals") ?? _warningIntervals.Text;
            _warningMessageTemplate.Text = Str(e, "warning_message_template") ?? Str(e, "warningMessageTemplate") ?? "";
            _autoStart.Checked = Bool(e, "auto_start") || Bool(e, "autoStart");
            _autoUpdate.Checked = Bool(e, "auto_update") || Bool(e, "autoUpdate");
            _scheduledRestart.Checked = Bool(e, "scheduled_restart_enabled") || Bool(e, "scheduledRestartEnabled");
            _category.Text = Str(e, "category") ?? "";
            _notes.Text = Str(e, "notes") ?? "";
            ApplyTypePanels();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, "Could not load server details (using blanks).\n" + ex.Message, Text);
        }
    }

    private async Task SaveAsync()
    {
        if (string.IsNullOrWhiteSpace(_name.Text) || string.IsNullOrWhiteSpace(_installDir.Text))
        {
            MessageBox.Show(this, "Name and install dir are required.", Text);
            return;
        }

        int? ram = null;
        if (int.TryParse(_ramMb.Text.Trim(), out var ramVal)) ram = ramVal;

        var body = new Dictionary<string, object?>
        {
            ["name"] = _name.Text.Trim(),
            ["serverType"] = _type.SelectedItem?.ToString() ?? "steam",
            ["appId"] = NullIfEmpty(_appId.Text),
            ["installDir"] = _installDir.Text.Trim(),
            ["executable"] = NullIfEmpty(_executable.Text),
            ["launchArgs"] = NullIfEmpty(_launchArgs.Text),
            ["stopCommand"] = NullIfEmpty(_stopCommand.Text),
            ["saveCommand"] = NullIfEmpty(_saveCommand.Text),
            ["startCommand"] = NullIfEmpty(_startCommand.Text),
            ["javaPath"] = NullIfEmpty(_javaPath.Text),
            ["version"] = NullIfEmpty(_version.Text),
            ["modLoader"] = NullIfEmpty(_modLoader.Text),
            ["ramMb"] = ram,
            ["jvmArgs"] = NullIfEmpty(_jvmArgs.Text),
            ["motdMessage"] = NullIfEmpty(_motdMessage.Text),
            ["motdCommand"] = NullIfEmpty(_motdCommand.Text),
            ["motdInterval"] = (int)_motdInterval.Value,
            ["warningCommand"] = NullIfEmpty(_warningCommand.Text),
            ["warningIntervals"] = NullIfEmpty(_warningIntervals.Text),
            ["warningMessageTemplate"] = NullIfEmpty(_warningMessageTemplate.Text),
            ["autoStart"] = _autoStart.Checked,
            ["autoUpdate"] = _autoUpdate.Checked,
            ["scheduledRestartEnabled"] = _scheduledRestart.Checked,
            ["category"] = NullIfEmpty(_category.Text),
            ["notes"] = NullIfEmpty(_notes.Text)
        };

        try
        {
            if (_existingName is null)
                await _api.PostWebJsonAsync("/api/servers", body);
            else
                await _api.PutWebJsonAsync($"/api/servers/{Uri.EscapeDataString(_existingName)}", body);
            DialogResult = DialogResult.OK;
            Close();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private static TabPage MakePage(string title, params Control[] rows)
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

    private static Control Labeled(string label, Control c)
        => DialogLayout.LabeledRow(label, c, labelWidth: 140);

    private static Control BrowseRow(string label, Control c, string buttonText, Action onBrowse)
    {
        c.Dock = DockStyle.Fill;
        var wrap = new TableLayoutPanel
        {
            ColumnCount = 3,
            Dock = DockStyle.Top,
            Height = 34,
            Margin = new Padding(0, 4, 0, 4),
            MinimumSize = new Size(0, 34)
        };
        wrap.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 140));
        wrap.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        wrap.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 96));
        wrap.Controls.Add(new Label { Text = label, AutoSize = true, Anchor = AnchorStyles.Left, Margin = new Padding(0, 8, 8, 0) }, 0, 0);
        wrap.Controls.Add(c, 1, 0);
        var btn = new Button { Text = buttonText, Dock = DockStyle.Fill, AutoSize = true };
        btn.Click += (_, _) => onBrowse();
        wrap.Controls.Add(btn, 2, 0);
        return wrap;
    }

    private static Control CheckRow(Control c)
        => c is CheckBox cb ? DialogLayout.CheckRow(cb, indent: 140) : DialogLayout.CheckRow(new CheckBox { Text = c.Text }, 140);

    private static void Set(ComboBox box, string value)
    {
        var idx = box.Items.IndexOf(value);
        box.SelectedIndex = idx >= 0 ? idx : 0;
    }

    private static string? Str(JsonElement e, string name)
        => e.TryGetProperty(name, out var p) && p.ValueKind != JsonValueKind.Null
            ? p.ValueKind == JsonValueKind.String ? p.GetString() : p.ToString()
            : null;

    private static bool Bool(JsonElement e, string name)
        => e.TryGetProperty(name, out var p) && p.ValueKind == JsonValueKind.True;

    private static string? NullIfEmpty(string s) => string.IsNullOrWhiteSpace(s) ? null : s.Trim();
}
