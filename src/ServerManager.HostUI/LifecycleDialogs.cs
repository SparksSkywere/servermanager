using System.IO.Compression;
using System.Text.Json;

namespace ServerManager.HostUI;

internal sealed class AddServerWizardForm : HostUiForm
{
    private readonly ApiClient _api;
    private readonly ComboBox _type = new() { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Top };
    private readonly ThemedSectionPanel _steamBox = new() { Title = "Steam login (optional)", Dock = DockStyle.Top, Height = 140, Visible = false };
    private readonly TextBox _steamUser = new() { Dock = DockStyle.Fill };
    private readonly TextBox _steamPass = new() { Dock = DockStyle.Fill, UseSystemPasswordChar = true };
    private readonly TextBox _steam2Fa = new() { Dock = DockStyle.Fill };

    public string? SelectedType { get; private set; }

    public AddServerWizardForm(ApiClient api)
    {
        _api = api;
        Text = "Add Server — Choose Type";
        Width = 420;
        Height = 320;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        StartPosition = FormStartPosition.CenterParent;
        MaximizeBox = false;
        MinimizeBox = false;

        _type.Items.AddRange(new object[]
        {
            new TypeItem("Steam", "steam"),
            new TypeItem("Minecraft", "minecraft"),
            new TypeItem("Modded", "minecraft_modded"),
            new TypeItem("Other", "custom")
        });
        _type.DisplayMember = "Label";
        _type.ValueMember = "Value";
        _type.SelectedIndex = 0;
        _type.SelectedIndexChanged += (_, _) => UpdateSteamVisibility();

        var steamLayout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, Padding = new Padding(8) };
        steamLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 100));
        steamLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        steamLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 28));
        steamLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 28));
        steamLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 28));
        steamLayout.Controls.Add(new Label { Text = "Username", AutoSize = true }, 0, 0);
        steamLayout.Controls.Add(_steamUser, 1, 0);
        steamLayout.Controls.Add(new Label { Text = "Password", AutoSize = true }, 0, 1);
        steamLayout.Controls.Add(_steamPass, 1, 1);
        steamLayout.Controls.Add(new Label { Text = "2FA / Guard", AutoSize = true }, 0, 2);
        steamLayout.Controls.Add(_steam2Fa, 1, 2);
        _steamBox.Controls.Add(steamLayout);

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Bottom,
            Height = 44,
            FlowDirection = FlowDirection.RightToLeft,
            Padding = new Padding(8)
        };
        var next = new Button { Text = "Next", Width = 90 };
        var cancel = new Button { Text = "Cancel", Width = 90, DialogResult = DialogResult.Cancel };
        next.Click += async (_, _) => await NextAsync();
        buttons.Controls.Add(next);
        buttons.Controls.Add(cancel);

        var body = new Panel { Dock = DockStyle.Fill, Padding = new Padding(12) };
        var typeLabel = new Label { Text = "Server type", AutoSize = true, Dock = DockStyle.Top, Padding = new Padding(0, 0, 0, 4) };
        _type.Dock = DockStyle.Top;
        _type.Height = 28;
        // Dock order: last added is topmost for Top docking
        body.Controls.Add(_steamBox);
        body.Controls.Add(_type);
        body.Controls.Add(typeLabel);

        Controls.Add(body);
        Controls.Add(buttons);
        AcceptButton = next;
        CancelButton = cancel;
        UpdateSteamVisibility();
    }

    private void UpdateSteamVisibility()
    {
        var t = (_type.SelectedItem as TypeItem)?.Value ?? "steam";
        _steamBox.Visible = t == "steam";
    }

    private async Task NextAsync()
    {
        var item = _type.SelectedItem as TypeItem;
        SelectedType = item?.Value ?? "steam";

        if (SelectedType == "steam" &&
            (!string.IsNullOrWhiteSpace(_steamUser.Text) || !string.IsNullOrWhiteSpace(_steamPass.Text) || !string.IsNullOrWhiteSpace(_steam2Fa.Text)))
        {
            try
            {
                var map = new Dictionary<string, string>();
                if (!string.IsNullOrWhiteSpace(_steamUser.Text))
                    map["SteamUsername"] = _steamUser.Text.Trim();
                if (!string.IsNullOrWhiteSpace(_steamPass.Text))
                    map["SteamPassword"] = _steamPass.Text;
                if (!string.IsNullOrWhiteSpace(_steam2Fa.Text))
                    map["SteamGuardSecret"] = _steam2Fa.Text.Trim();
                if (map.Count > 0)
                    await _api.PostWebJsonAsync("/api/system-settings", map);
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, "Could not save Steam login to settings:\n" + ex.Message, Text,
                    MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        }

        using var cfg = new ConfigureServerForm(_api, null, SelectedType);
        if (cfg.ShowDialog(this) == DialogResult.OK)
        {
            DialogResult = DialogResult.OK;
            Close();
        }
    }

    private sealed class TypeItem(string label, string value)
    {
        public string Label { get; } = label;
        public string Value { get; } = value;
        public override string ToString() => Label;
    }
}

internal sealed class ImportChooserForm : HostUiForm
{
    public enum ImportKind { ExportFile, Directory }

    public ImportKind Kind { get; private set; } = ImportKind.ExportFile;

    public ImportChooserForm()
    {
        Text = "Import Server";
        Width = 380;
        Height = 180;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        StartPosition = FormStartPosition.CenterParent;
        MaximizeBox = false;
        MinimizeBox = false;

        var lbl = new Label
        {
            Text = "How do you want to import?",
            Dock = DockStyle.Top,
            Height = 36,
            Padding = new Padding(12, 16, 12, 0)
        };

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.TopDown,
            Padding = new Padding(40, 8, 40, 8)
        };
        var fileBtn = new Button { Text = "Import from export file…", Width = 260, Height = 32 };
        var dirBtn = new Button { Text = "Register existing directory…", Width = 260, Height = 32 };
        var cancel = new Button { Text = "Cancel", Width = 260, Height = 28, DialogResult = DialogResult.Cancel };
        fileBtn.Click += (_, _) => { Kind = ImportKind.ExportFile; DialogResult = DialogResult.OK; Close(); };
        dirBtn.Click += (_, _) => { Kind = ImportKind.Directory; DialogResult = DialogResult.OK; Close(); };
        buttons.Controls.Add(fileBtn);
        buttons.Controls.Add(dirBtn);
        buttons.Controls.Add(cancel);

        Controls.Add(buttons);
        Controls.Add(lbl);
        CancelButton = cancel;
    }
}

internal sealed class RegisterDirectoryForm : HostUiForm
{
    private readonly TextBox _name = new() { Dock = DockStyle.Fill };
    private readonly TextBox _dir = new() { Dock = DockStyle.Fill };
    private readonly ComboBox _type = new() { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Fill };

    public string ServerName => _name.Text.Trim();
    public string InstallDir => _dir.Text.Trim();
    public string ServerType => _type.SelectedItem?.ToString() ?? "custom";

    public RegisterDirectoryForm()
    {
        Text = "Register Existing Directory";
        Width = 520;
        Height = 220;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        StartPosition = FormStartPosition.CenterParent;
        MaximizeBox = false;
        MinimizeBox = false;

        _type.Items.AddRange(["steam", "minecraft", "minecraft_modded", "custom"]);
        _type.SelectedIndex = 3;

        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, Padding = new Padding(12) };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 100));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 90));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 32));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 32));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 32));

        layout.Controls.Add(new Label { Text = "Name", AutoSize = true }, 0, 0);
        layout.Controls.Add(_name, 1, 0);
        layout.SetColumnSpan(_name, 2);

        layout.Controls.Add(new Label { Text = "Folder", AutoSize = true }, 0, 1);
        layout.Controls.Add(_dir, 1, 1);
        var browse = new Button { Text = "Browse…", Dock = DockStyle.Fill };
        browse.Click += (_, _) =>
        {
            using var dlg = new FolderBrowserDialog { Description = "Select server install directory" };
            if (dlg.ShowDialog(this) == DialogResult.OK)
                _dir.Text = dlg.SelectedPath;
        };
        layout.Controls.Add(browse, 2, 1);

        layout.Controls.Add(new Label { Text = "Type", AutoSize = true }, 0, 2);
        layout.Controls.Add(_type, 1, 2);
        layout.SetColumnSpan(_type, 2);

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Bottom,
            Height = 44,
            FlowDirection = FlowDirection.RightToLeft,
            Padding = new Padding(8)
        };
        var ok = new Button { Text = "Register", Width = 100 };
        var cancel = new Button { Text = "Cancel", Width = 90, DialogResult = DialogResult.Cancel };
        ok.Click += (_, _) =>
        {
            if (string.IsNullOrWhiteSpace(_name.Text) || string.IsNullOrWhiteSpace(_dir.Text))
            {
                MessageBox.Show(this, "Name and folder are required.", Text);
                return;
            }
            if (!Directory.Exists(_dir.Text.Trim()))
            {
                MessageBox.Show(this, "Folder does not exist.", Text);
                return;
            }
            DialogResult = DialogResult.OK;
            Close();
        };
        buttons.Controls.Add(ok);
        buttons.Controls.Add(cancel);

        Controls.Add(layout);
        Controls.Add(buttons);
        AcceptButton = ok;
        CancelButton = cancel;
    }
}

internal sealed class ExportOptionsForm : HostUiForm
{
    private readonly CheckBox _includeFiles = new() { Text = "Include server files (zip install directory)", AutoSize = true };
    private readonly TextBox _path = new() { Dock = DockStyle.Fill };
    private readonly string _defaultName;

    public bool IncludeFiles => _includeFiles.Checked;
    public string ExportPath => _path.Text.Trim();

    public ExportOptionsForm(string serverName)
    {
        _defaultName = serverName;
        Text = $"Export Server — {serverName}";
        Width = 560;
        Height = 200;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        StartPosition = FormStartPosition.CenterParent;
        MaximizeBox = false;
        MinimizeBox = false;

        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, Padding = new Padding(12) };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 80));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 90));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 32));
        layout.Controls.Add(_includeFiles, 0, 0);
        layout.SetColumnSpan(_includeFiles, 3);
        layout.Controls.Add(new Label { Text = "Save as", AutoSize = true }, 0, 1);
        layout.Controls.Add(_path, 1, 1);
        var browse = new Button { Text = "Browse…", Dock = DockStyle.Fill };
        browse.Click += (_, _) => BrowsePath();
        layout.Controls.Add(browse, 2, 1);

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Bottom,
            Height = 44,
            FlowDirection = FlowDirection.RightToLeft,
            Padding = new Padding(8)
        };
        var ok = new Button { Text = "Export", Width = 100 };
        var cancel = new Button { Text = "Cancel", Width = 90, DialogResult = DialogResult.Cancel };
        ok.Click += (_, _) =>
        {
            if (string.IsNullOrWhiteSpace(_path.Text))
            {
                BrowsePath();
                if (string.IsNullOrWhiteSpace(_path.Text)) return;
            }
            DialogResult = DialogResult.OK;
            Close();
        };
        buttons.Controls.Add(ok);
        buttons.Controls.Add(cancel);

        Controls.Add(layout);
        Controls.Add(buttons);
        AcceptButton = ok;
        CancelButton = cancel;
        _path.Text = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
            $"{serverName}.smserver.json");
    }

    private void BrowsePath()
    {
        if (_includeFiles.Checked)
        {
            using var dlg = new SaveFileDialog
            {
                Title = "Export Server Package",
                Filter = "Zip archive (*.zip)|*.zip",
                FileName = $"{_defaultName}.zip"
            };
            if (dlg.ShowDialog(this) == DialogResult.OK)
                _path.Text = dlg.FileName;
        }
        else
        {
            using var dlg = new SaveFileDialog
            {
                Title = "Export Server",
                Filter = "Server Manager export (*.smserver.json)|*.smserver.json|JSON (*.json)|*.json",
                FileName = $"{_defaultName}.smserver.json"
            };
            if (dlg.ShowDialog(this) == DialogResult.OK)
                _path.Text = dlg.FileName;
        }
    }

    public static async Task RunExportAsync(ApiClient api, IWin32Window owner, string serverName, string? installDir)
    {
        using var opts = new ExportOptionsForm(serverName);
        if (opts.ShowDialog(owner) != DialogResult.OK) return;

        try
        {
            var json = await api.GetWebAsync($"/api/servers/{Uri.EscapeDataString(serverName)}/export");
            var pretty = JsonSerializer.Serialize(JsonDocument.Parse(json).RootElement, new JsonSerializerOptions { WriteIndented = true });

            if (!opts.IncludeFiles)
            {
                await File.WriteAllTextAsync(opts.ExportPath, pretty);
                MessageBox.Show(owner, $"Exported '{serverName}' to:\n{opts.ExportPath}", "Export Server",
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            var dir = installDir;
            if (string.IsNullOrWhiteSpace(dir) || !Directory.Exists(dir))
            {
                MessageBox.Show(owner,
                    "Install directory not found; writing JSON export only beside the chosen path.",
                    "Export Server", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                var jsonBeside = Path.ChangeExtension(opts.ExportPath, ".smserver.json");
                await File.WriteAllTextAsync(jsonBeside, pretty);
                return;
            }

            var smBeside = Path.Combine(dir, "smserver.json");
            await File.WriteAllTextAsync(smBeside, pretty);

            var zipPath = opts.ExportPath;
            if (!zipPath.EndsWith(".zip", StringComparison.OrdinalIgnoreCase))
                zipPath += ".zip";

            if (File.Exists(zipPath)) File.Delete(zipPath);
            try
            {
                ZipFile.CreateFromDirectory(dir, zipPath, CompressionLevel.Optimal, includeBaseDirectory: false);
                MessageBox.Show(owner,
                    $"Exported '{serverName}' with files to:\n{zipPath}\n\n(smserver.json written in install dir)",
                    "Export Server", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
            catch (Exception zipEx)
            {
                MessageBox.Show(owner,
                    $"JSON written to:\n{smBeside}\n\nZip failed (best-effort):\n{zipEx.Message}",
                    "Export Server", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show(owner, ex.Message, "Export Server", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
