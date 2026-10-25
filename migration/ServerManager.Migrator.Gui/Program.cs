using System.Diagnostics;

namespace ServerManager.Migrator.Gui;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        Application.Run(new MainForm());
    }
}

internal sealed class MainForm : Form
{
    private readonly TextBox _source = new() { Dock = DockStyle.Fill };
    private readonly TextBox _dest = new() { Dock = DockStyle.Fill };
    private readonly TextBox _remap = new() { Dock = DockStyle.Fill };
    private readonly CheckBox _dryRun = new() { Text = "Dry run (report only)", AutoSize = true, Checked = true };
    private readonly CheckBox _clearDest = new() { Text = "Clear destination DBs first", AutoSize = true };
    private readonly CheckBox _copySsl = new() { Text = "Copy ssl\\ certificates", AutoSize = true, Checked = true };
    private readonly CheckBox _importJson = new()
    {
        Text = "Import leftover servers\\*.json into SQL (recommended)",
        AutoSize = true,
        Checked = true
    };
    private readonly CheckBox _skipUsers = new() { Text = "Skip users", AutoSize = true };
    private readonly CheckBox _skipServers = new() { Text = "Skip servers", AutoSize = true };
    private readonly CheckBox _skipCluster = new() { Text = "Skip cluster / config", AutoSize = true };
    private readonly CheckBox _skipCatalogs = new() { Text = "Skip catalog DBs", AutoSize = true };
    private readonly CheckBox _showAdvanced = new()
    {
        Text = "Show advanced: path remap (install-folder prefixes only)",
        AutoSize = true
    };
    private readonly Panel _advancedPanel = new() { Dock = DockStyle.Top, AutoSize = true, Visible = false };
    private readonly TextBox _log = new()
    {
        Multiline = true,
        ReadOnly = true,
        ScrollBars = ScrollBars.Both,
        Dock = DockStyle.Fill,
        Font = new Font("Consolas", 9f),
        WordWrap = false
    };
    private readonly Button _run = new() { Text = "Run migration", Width = 130, Height = 32 };
    private readonly Button _close = new() { Text = "Close", Width = 90, Height = 32 };
    private CancellationTokenSource? _cts;

    public MainForm()
    {
        Text = "Server Manager — Data Migration";
        Width = 820;
        Height = 660;
        MinimumSize = new Size(700, 520);
        StartPosition = FormStartPosition.CenterScreen;

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
            Padding = new Padding(12)
        };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        var form = new TableLayoutPanel { Dock = DockStyle.Top, ColumnCount = 3, AutoSize = true };
        form.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 150));
        form.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        form.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 90));

        void AddPathRow(TableLayoutPanel target, string label, TextBox box, Action browse)
        {
            var r = target.RowCount++;
            target.RowStyles.Add(new RowStyle(SizeType.Absolute, 32));
            target.Controls.Add(new Label
            {
                Text = label,
                AutoSize = true,
                Anchor = AnchorStyles.Left,
                Margin = new Padding(0, 8, 8, 0)
            }, 0, r);
            target.Controls.Add(box, 1, r);
            var btn = new Button { Text = "Browse…", Dock = DockStyle.Fill };
            btn.Click += (_, _) => browse();
            target.Controls.Add(btn, 2, r);
        }

        AddPathRow(form, "Legacy source", _source, () => BrowseFolder(_source, "Select legacy Server Manager root (contains db\\)"));
        AddPathRow(form, "Destination runtime", _dest, () => BrowseFolder(_dest, "Select destination runtime root (will contain db\\)"));

        var advForm = new TableLayoutPanel { Dock = DockStyle.Top, ColumnCount = 3, AutoSize = true };
        advForm.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 150));
        advForm.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        advForm.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 90));
        AddPathRow(advForm, "Path remap JSON", _remap, BrowseRemapFile);
        _advancedPanel.Controls.Add(new Label
        {
            Text = "Only if game install folders moved drives/paths. Not server config — servers go into SQLite.",
            AutoSize = true,
            ForeColor = Color.DimGray,
            Dock = DockStyle.Top,
            Padding = new Padding(0, 4, 0, 4)
        });
        _advancedPanel.Controls.Add(advForm);

        var checks = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            FlowDirection = FlowDirection.TopDown,
            WrapContents = false,
            Margin = new Padding(0, 8, 0, 0)
        };
        checks.Controls.Add(_dryRun);
        checks.Controls.Add(_clearDest);
        checks.Controls.Add(_copySsl);
        checks.Controls.Add(_importJson);

        var skips = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = true,
            Margin = new Padding(0, 4, 0, 0)
        };
        skips.Controls.Add(_skipServers);
        skips.Controls.Add(_skipUsers);
        skips.Controls.Add(_skipCluster);
        skips.Controls.Add(_skipCatalogs);

        _showAdvanced.CheckedChanged += (_, _) => _advancedPanel.Visible = _showAdvanced.Checked;

        var note = new Label
        {
            Text = "Server configs are stored only in SQLite (db\\servermanager_servers.db). Legacy servers\\*.json are imported into that DB — not kept as JSON files.",
            AutoSize = true,
            ForeColor = Color.DimGray,
            MaximumSize = new Size(760, 0),
            Margin = new Padding(0, 8, 0, 4)
        };

        var header = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            FlowDirection = FlowDirection.TopDown,
            WrapContents = false
        };
        header.Controls.Add(form);
        header.Controls.Add(checks);
        header.Controls.Add(skips);
        header.Controls.Add(_showAdvanced);
        header.Controls.Add(_advancedPanel);
        header.Controls.Add(note);

        root.Controls.Add(header, 0, 0);
        root.Controls.Add(_log, 0, 1);

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.RightToLeft,
            AutoSize = true
        };
        _run.Click += async (_, _) => await RunAsync();
        _close.Click += (_, _) =>
        {
            _cts?.Cancel();
            Close();
        };
        buttons.Controls.Add(_close);
        buttons.Controls.Add(_run);
        root.Controls.Add(buttons, 0, 2);

        Controls.Add(root);
        PrefillFromRegistryAndDefaults();
        Append("Ready. Prefer Dry run first, then uncheck and run again.");
        Append("All server data is written to SQLite — not to JSON config files.");
    }

    private void PrefillFromRegistryAndDefaults()
    {
        try
        {
            using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"Software\SkywereIndustries\Servermanager");
            var install = key?.GetValue("InstallPath") as string;
            var runtime = key?.GetValue("Servermanagerdir") as string;
            if (!string.IsNullOrWhiteSpace(runtime) && Directory.Exists(runtime))
                _dest.Text = runtime;
            else if (!string.IsNullOrWhiteSpace(install))
            {
                var rt = Path.Combine(install, "runtime");
                if (Directory.Exists(rt)) _dest.Text = rt;
                else if (Directory.Exists(install)) _dest.Text = install;
            }
        }
        catch { /* optional */ }

        var migrationDir = FindMigrationRoot();
        if (migrationDir is not null)
        {
            var repoRuntime = Path.GetFullPath(Path.Combine(migrationDir, "..", "runtime"));
            if (string.IsNullOrWhiteSpace(_dest.Text) && Directory.Exists(repoRuntime))
                _dest.Text = repoRuntime;
        }
    }

    private static string? FindMigrationRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        for (var i = 0; i < 8 && dir is not null; i++, dir = dir.Parent)
        {
            if (File.Exists(Path.Combine(dir.FullName, "Migrate-ServerManager.ps1"))
                || Directory.Exists(Path.Combine(dir.FullName, "ServerManager.Migrator")))
                return dir.FullName;
        }
        return null;
    }

    private void BrowseFolder(TextBox target, string description)
    {
        using var dlg = new FolderBrowserDialog
        {
            Description = description,
            UseDescriptionForTitle = true,
            ShowNewFolderButton = true
        };
        if (!string.IsNullOrWhiteSpace(target.Text) && Directory.Exists(target.Text))
            dlg.SelectedPath = target.Text;
        if (dlg.ShowDialog(this) == DialogResult.OK)
            target.Text = dlg.SelectedPath;
    }

    private void BrowseRemapFile()
    {
        using var dlg = new OpenFileDialog
        {
            Title = "Path remap JSON (optional — install folder prefixes only, not server config)",
            Filter = "JSON (*.json)|*.json|All files (*.*)|*.*",
            CheckFileExists = true
        };
        if (!string.IsNullOrWhiteSpace(_remap.Text) && File.Exists(_remap.Text))
            dlg.FileName = _remap.Text;
        if (dlg.ShowDialog(this) == DialogResult.OK)
            _remap.Text = dlg.FileName;
    }

    private async Task RunAsync()
    {
        var source = _source.Text.Trim();
        var dest = _dest.Text.Trim();
        if (string.IsNullOrWhiteSpace(source) || !Directory.Exists(source))
        {
            MessageBox.Show(this, "Select a valid legacy source folder (must exist and contain db\\).", Text,
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        if (!Directory.Exists(Path.Combine(source, "db")))
        {
            MessageBox.Show(this, "Source folder has no db\\ subdirectory.", Text,
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        if (string.IsNullOrWhiteSpace(dest))
        {
            MessageBox.Show(this, "Select a destination runtime folder.", Text,
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        if (!_dryRun.Checked && _clearDest.Checked)
        {
            var confirm = MessageBox.Show(this,
                "Clear destination DBs will delete existing *.db files under dest\\db. Continue?",
                Text, MessageBoxButtons.YesNo, MessageBoxIcon.Warning);
            if (confirm != DialogResult.Yes) return;
        }

        string migrator;
        try
        {
            migrator = ResolveMigratorExe();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        Directory.CreateDirectory(dest);

        var args = new List<string>
        {
            "--source", Quote(source),
            "--dest", Quote(dest)
        };
        if (_dryRun.Checked) args.Add("--dry-run");
        if (_clearDest.Checked) args.Add("--clear-dest-db");
        if (!_copySsl.Checked) args.AddRange(["--copy-ssl", "false"]);
        if (_skipUsers.Checked) args.Add("--skip-users");
        if (_skipServers.Checked) args.Add("--skip-servers");
        if (!_importJson.Checked) args.Add("--skip-json-servers");
        if (_skipCluster.Checked) args.Add("--skip-cluster");
        if (_skipCatalogs.Checked) args.Add("--skip-catalogs");
        if (!string.IsNullOrWhiteSpace(_remap.Text))
        {
            if (!File.Exists(_remap.Text))
            {
                MessageBox.Show(this, "Path remap file not found.", Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            args.Add("--path-remap");
            args.Add(Quote(_remap.Text.Trim()));
        }

        _cts = new CancellationTokenSource();
        SetBusy(true);
        _log.Clear();
        Append($"Migrator: {migrator}");
        Append($"Args: {string.Join(' ', args)}");
        Append("");

        try
        {
            var code = await RunProcessAsync(migrator, string.Join(' ', args), _cts.Token);
            Append("");
            Append(code == 0 ? "Finished successfully." : $"Finished with exit code {code}.");
            if (code == 0 && !_dryRun.Checked)
            {
                MessageBox.Show(this,
                    "Migration complete.\n\nServer configs are in SQLite (runtime\\db\\servermanager_servers.db).\nRe-enter Steam password in settings if SteamCMD login fails.\nStart servers from the new HostRuntime (PIDs were not migrated).",
                    Text, MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
        }
        catch (OperationCanceledException)
        {
            Append("Cancelled.");
        }
        catch (Exception ex)
        {
            Append("ERROR: " + ex.Message);
            MessageBox.Show(this, ex.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally
        {
            SetBusy(false);
            _cts.Dispose();
            _cts = null;
        }
    }

    private void SetBusy(bool busy)
    {
        UseWaitCursor = busy;
        _run.Enabled = !busy;
        _source.Enabled = !busy;
        _dest.Enabled = !busy;
        _remap.Enabled = !busy;
        _importJson.Enabled = !busy;
        _showAdvanced.Enabled = !busy;
    }

    private string ResolveMigratorExe()
    {
        var migrationRoot = FindMigrationRoot() ?? AppContext.BaseDirectory;
        var candidates = new[]
        {
            Path.Combine(migrationRoot, "dist", "ServerManager.Migrator.exe"),
            Path.Combine(AppContext.BaseDirectory, "ServerManager.Migrator.exe"),
            Path.Combine(migrationRoot, "ServerManager.Migrator", "bin", "Release", "net8.0", "ServerManager.Migrator.exe"),
            Path.Combine(migrationRoot, "ServerManager.Migrator", "bin", "Debug", "net8.0", "ServerManager.Migrator.exe"),
        };
        foreach (var c in candidates)
        {
            if (File.Exists(c)) return c;
        }

        var proj = Path.Combine(migrationRoot, "ServerManager.Migrator", "ServerManager.Migrator.csproj");
        if (!File.Exists(proj))
            throw new FileNotFoundException("ServerManager.Migrator.exe not found. Build the migrator first (dotnet publish migration\\ServerManager.Migrator).");

        Append("Building migrator…");
        var dist = Path.Combine(migrationRoot, "dist");
        Directory.CreateDirectory(dist);
        var psi = new ProcessStartInfo
        {
            FileName = "dotnet",
            Arguments = $"publish \"{proj}\" -c Release -o \"{dist}\" --nologo",
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true
        };
        using var p = Process.Start(psi) ?? throw new InvalidOperationException("Failed to start dotnet publish");
        var stdout = p.StandardOutput.ReadToEnd();
        var stderr = p.StandardError.ReadToEnd();
        p.WaitForExit();
        if (!string.IsNullOrWhiteSpace(stdout)) Append(stdout.Trim());
        if (p.ExitCode != 0)
            throw new InvalidOperationException(string.IsNullOrWhiteSpace(stderr) ? $"dotnet publish failed ({p.ExitCode})" : stderr);

        var built = Path.Combine(dist, "ServerManager.Migrator.exe");
        if (!File.Exists(built))
            throw new FileNotFoundException("Publish completed but ServerManager.Migrator.exe is missing.", built);
        return built;
    }

    private async Task<int> RunProcessAsync(string file, string args, CancellationToken ct)
    {
        var psi = new ProcessStartInfo
        {
            FileName = file,
            Arguments = args,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true
        };
        using var p = Process.Start(psi) ?? throw new InvalidOperationException($"Failed to start {file}");
        p.OutputDataReceived += (_, e) => { if (e.Data is not null) BeginInvoke(() => Append(e.Data)); };
        p.ErrorDataReceived += (_, e) => { if (e.Data is not null) BeginInvoke(() => Append(e.Data)); };
        p.BeginOutputReadLine();
        p.BeginErrorReadLine();

        await p.WaitForExitAsync(ct);
        return p.ExitCode;
    }

    private void Append(string line)
    {
        if (InvokeRequired)
        {
            BeginInvoke(() => Append(line));
            return;
        }
        _log.AppendText(line + Environment.NewLine);
    }

    private static string Quote(string path) =>
        path.Contains(' ', StringComparison.Ordinal) ? $"\"{path}\"" : path;
}
