using System.Text.Json;

namespace ServerManager.HostUI;

internal static class CategoryDialogs
{
    public static void Create(ApiClient api, IWin32Window owner, Func<Task> refresh)
    {
        var name = Prompt(owner, "Create Category", "Category name:");
        if (string.IsNullOrWhiteSpace(name)) return;
        _ = PersistCategoryAsync(api, owner, name!.Trim(), null, refresh);
    }

    public static void Rename(ApiClient api, IWin32Window owner, string? current, Func<Task> refresh)
    {
        if (string.IsNullOrWhiteSpace(current) || current == "Uncategorized")
        {
            MessageBox.Show(owner, "Select a server in a category (not Uncategorized) to rename.", "Rename Category");
            return;
        }
        var name = Prompt(owner, "Rename Category", "New name:", current);
        if (string.IsNullOrWhiteSpace(name) || name == current) return;
        _ = PersistCategoryAsync(api, owner, name!.Trim(), current, refresh);
    }

    public static void Delete(ApiClient api, IWin32Window owner, string? current, Func<Task> refresh)
    {
        if (string.IsNullOrWhiteSpace(current) || current == "Uncategorized")
        {
            MessageBox.Show(owner, "Cannot delete Uncategorized / empty selection.", "Delete Category");
            return;
        }
        if (MessageBox.Show(owner, $"Move all servers in '{current}' to Uncategorized and remove the category label?", "Delete Category",
                MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
        _ = PersistCategoryAsync(api, owner, "Uncategorized", current, refresh);
    }

    private static async Task PersistCategoryAsync(ApiClient api, IWin32Window owner, string newName, string? oldName, Func<Task> refresh)
    {
        try
        {
            var list = await api.ListServersAsync();
            foreach (var s in list)
            {
                var cat = string.IsNullOrWhiteSpace(s.Category) ? "Uncategorized" : s.Category!;
                if (oldName is null)
                {
                    // create: store empty category list in settings
                    continue;
                }
                if (!string.Equals(cat, oldName, StringComparison.OrdinalIgnoreCase)) continue;
                await api.PutWebJsonAsync($"/api/servers/{Uri.EscapeDataString(s.Name)}", new { category = newName });
            }
            var cats = await api.GetWebAsync("/api/system-settings");
            // also persist category list key
            await api.PostWebJsonAsync("/api/system-settings", new Dictionary<string, string>
            {
                ["Categories"] = MergeCategories(cats, newName, oldName)
            });
            await refresh();
        }
        catch (Exception ex)
        {
            MessageBox.Show(owner, ex.Message, "Category");
        }
    }

    private static string MergeCategories(string settingsJson, string newName, string? oldName)
    {
        var set = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "Uncategorized" };
        try
        {
            using var doc = JsonDocument.Parse(settingsJson);
            if (doc.RootElement.TryGetProperty("Categories", out var c))
            {
                foreach (var part in (c.GetString() ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
                    set.Add(part);
            }
        }
        catch { /* ignore */ }
        if (oldName is not null) set.Remove(oldName);
        set.Add(newName);
        return string.Join(",", set.OrderBy(x => x, StringComparer.OrdinalIgnoreCase));
    }

    private static string? Prompt(IWin32Window owner, string title, string label, string? initial = null)
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
        var tb = new TextBox { Left = 12, Top = 36, Width = 320, Text = initial ?? "" };
        f.Controls.Add(new Label { Left = 12, Top = 12, AutoSize = true, Text = label });
        f.Controls.Add(tb);
        var ok = new Button { Text = "OK", DialogResult = DialogResult.OK, Left = 170, Top = 70, Width = 75 };
        var cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, Left = 255, Top = 70, Width = 75 };
        f.Controls.Add(ok);
        f.Controls.Add(cancel);
        f.AcceptButton = ok;
        f.CancelButton = cancel;
        return f.ShowDialog(owner) == DialogResult.OK ? tb.Text : null;
    }
}

internal sealed class DelayedActionForm : HostUiForm
{
    private readonly NumericUpDown _mins = new() { Minimum = 0, Maximum = 120, Value = 0, Width = 80 };
    public int DelayMinutes => (int)_mins.Value;

    public DelayedActionForm(string action)
    {
        Text = char.ToUpper(action[0]) + action[1..] + " Server";
        Width = 360;
        Height = 160;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        StartPosition = FormStartPosition.CenterParent;
        MaximizeBox = false;
        MinimizeBox = false;
        Controls.Add(new Label
        {
            Left = 12,
            Top = 16,
            Width = 320,
            Height = 40,
            Text = "Immediate (0) or delay in minutes before the action runs:"
        });
        Controls.Add(new Label { Left = 12, Top = 60, AutoSize = true, Text = "Minutes:" });
        _mins.Left = 80;
        _mins.Top = 58;
        Controls.Add(_mins);
        var ok = new Button { Text = "OK", DialogResult = DialogResult.OK, Left = 170, Top = 95, Width = 75 };
        var cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, Left = 255, Top = 95, Width = 75 };
        Controls.Add(ok);
        Controls.Add(cancel);
        AcceptButton = ok;
        CancelButton = cancel;
    }
}

internal sealed class ProgressConsoleForm : HostUiForm
{
    private readonly TextBox _out = new()
    {
        Multiline = true,
        ReadOnly = true,
        Dock = DockStyle.Fill,
        Font = new Font("Consolas", 9f),
        ScrollBars = ScrollBars.Both
    };

    public ProgressConsoleForm(string title)
    {
        Text = title;
        Width = 640;
        Height = 360;
        StartPosition = FormStartPosition.CenterParent;
        Controls.Add(_out);
        var bar = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 40, FlowDirection = FlowDirection.RightToLeft };
        var close = new Button { Text = "Close", Width = 90, Enabled = false };
        close.Click += (_, _) => Close();
        bar.Controls.Add(close);
        Controls.Add(bar);
        Tag = close;
    }

    public void Append(string text)
    {
        if (InvokeRequired) { BeginInvoke(() => Append(text)); return; }
        _out.AppendText(text + Environment.NewLine);
        _out.SelectionStart = _out.TextLength;
        _out.ScrollToCaret();
    }

    public void Done()
    {
        if (InvokeRequired) { BeginInvoke(Done); return; }
        if (Tag is Button b) b.Enabled = true;
    }
}

internal sealed class ConsoleManagerForm : HostUiForm
{
    private readonly ApiClient _api;
    private readonly ListView _list = new() { Dock = DockStyle.Fill, View = View.Details, FullRowSelect = true, GridLines = true };

    public ConsoleManagerForm(ApiClient api)
    {
        _api = api;
        Text = "Console Manager";
        Width = 720;
        Height = 420;
        StartPosition = FormStartPosition.CenterParent;
        _list.Columns.Add("Server", 200);
        _list.Columns.Add("Status", 100);
        _list.Columns.Add("PID", 80);
        _list.Columns.Add("Type", 100);
        var bar = new ToolStrip();
        bar.Items.Add("Refresh", null, async (_, _) => await LoadAsync());
        bar.Items.Add("Show Console", null, (_, _) => OpenSelected());
        bar.Items.Add("Kill Process", null, async (_, _) => await KillSelectedAsync());
        Controls.Add(_list);
        Controls.Add(bar);
        Shown += async (_, _) => await LoadAsync();
    }

    private async Task LoadAsync()
    {
        try
        {
            var servers = await _api.ListServersAsync();
            _list.Items.Clear();
            foreach (var s in servers)
            {
                _list.Items.Add(new ListViewItem(new[]
                {
                    s.Name, s.Status, s.Pid?.ToString() ?? "", s.Type
                }) { Tag = s.Name });
            }
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, Text); }
    }

    private void OpenSelected()
    {
        if (_list.SelectedItems.Count == 0) return;
        var name = _list.SelectedItems[0].Tag as string;
        if (name is null) return;
        new ConsoleForm(_api, name).Show(Owner);
    }

    private async Task KillSelectedAsync()
    {
        if (_list.SelectedItems.Count == 0) return;
        var name = _list.SelectedItems[0].Tag as string;
        if (name is null) return;
        await _api.PostRuntimeAsync($"/api/runtime/servers/{Uri.EscapeDataString(name)}/kill");
        await LoadAsync();
    }
}

internal sealed class UpdateDatabasesForm : HostUiForm
{
    private readonly ApiClient _api;
    private readonly CheckedListBox _scanners = new() { Dock = DockStyle.Top, Height = 140, CheckOnClick = true };
    private readonly TextBox _log = new() { Dock = DockStyle.Fill, Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, Font = new Font("Consolas", 9f) };
    private readonly Label _status = new() { Dock = DockStyle.Top, Height = 48, Padding = new Padding(8) };

    public UpdateDatabasesForm(ApiClient api)
    {
        _api = api;
        Text = "Update Databases";
        Width = 720;
        Height = 520;
        StartPosition = FormStartPosition.CenterParent;
        foreach (var s in new[] { "steam", "minecraft", "modded:modrinth", "modded:curseforge", "modded:technic", "modded:ftb", "modded:atlauncher" })
            _scanners.Items.Add(s, s is "steam" or "minecraft");
        var bar = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 44, FlowDirection = FlowDirection.RightToLeft };
        var run = new Button { Text = "Update", Width = 100 };
        var refresh = new Button { Text = "Refresh status", Width = 120 };
        var close = new Button { Text = "Close", Width = 90, DialogResult = DialogResult.Cancel };
        run.Click += async (_, _) => await RunAsync();
        refresh.Click += async (_, _) => await LoadStatusAsync();
        bar.Controls.Add(run);
        bar.Controls.Add(refresh);
        bar.Controls.Add(close);
        Controls.Add(_log);
        Controls.Add(_scanners);
        Controls.Add(_status);
        Controls.Add(bar);
        Shown += async (_, _) => await LoadStatusAsync();
    }

    private async Task LoadStatusAsync()
    {
        try
        {
            var json = await _api.GetWebAsync("/api/catalog/status");
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            var dbRoot = root.TryGetProperty("dbRoot", out var dr) ? dr.GetString() : "";
            string Line(string key)
            {
                if (!root.TryGetProperty(key, out var el)) return $"{key}: ?";
                var count = el.TryGetProperty("count", out var c) ? c.GetInt32() : 0;
                var ok = el.TryGetProperty("ok", out var o) && o.GetBoolean();
                var path = el.TryGetProperty("path", out var p) ? p.GetString() : "";
                return $"{key}: {(ok ? "OK" : "EMPTY")} ({count:N0}) — {path}";
            }
            _status.Text = $"DB root: {dbRoot}\r\n{Line("steam")}  |  {Line("minecraft")}  |  {Line("modded")}";
            _log.AppendText($"Status @ {DateTime.Now:HH:mm:ss}\r\n{_status.Text}\r\n\r\n");
        }
        catch (Exception ex)
        {
            _status.Text = "Status failed: " + ex.Message;
        }
    }

    private async Task RunAsync()
    {
        _log.Clear();
        await LoadStatusAsync();
        foreach (var item in _scanners.CheckedItems)
        {
            var name = item!.ToString()!;
            _log.AppendText($"Running {name}…\r\n");
            try
            {
                var json = await _api.PostWebJsonAsync("/api/catalog/scan", new { scanner = name });
                _log.AppendText(json + "\r\n");
            }
            catch (Exception ex)
            {
                _log.AppendText("Error: " + ex.Message + "\r\n");
            }
        }
        await LoadStatusAsync();
        _log.AppendText("Done.\r\n");
    }
}
