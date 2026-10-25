using System.Text.Json;

namespace ServerManager.HostUI;

internal sealed class AppIdBrowserForm : HostUiForm
{
    private readonly ApiClient _api;
    private readonly TextBox _query = new() { Width = 260 };
    private readonly CheckBox _dedicatedOnly = new() { Text = "Dedicated servers only", AutoSize = true, Checked = true, Padding = new Padding(8, 6, 0, 0) };
    private readonly ListView _list = new() { Dock = DockStyle.Fill, View = View.Details, FullRowSelect = true, GridLines = true };
    private readonly Label _status = new() { Dock = DockStyle.Bottom, Height = 22, Padding = new Padding(8, 2, 8, 2) };

    public string? SelectedAppId { get; private set; }
    public string? SelectedName { get; private set; }

    public AppIdBrowserForm(ApiClient api)
    {
        _api = api;
        Text = "Steam App ID Browser";
        Width = 720;
        Height = 520;
        StartPosition = FormStartPosition.CenterParent;
        _list.Columns.Add("AppId", 100);
        _list.Columns.Add("Name", 520);

        var top = new FlowLayoutPanel { Dock = DockStyle.Top, Height = 40, Padding = new Padding(8) };
        top.Controls.Add(new Label { Text = "Search", AutoSize = true, Padding = new Padding(0, 6, 0, 0) });
        top.Controls.Add(_query);
        var search = new Button { Text = "Search", Width = 90 };
        search.Click += async (_, _) => await SearchAsync();
        top.Controls.Add(search);
        top.Controls.Add(_dedicatedOnly);
        _query.KeyDown += async (_, e) =>
        {
            if (e.KeyCode == Keys.Enter) { e.SuppressKeyPress = true; await SearchAsync(); }
        };

        var bottom = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 44, FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(8) };
        var ok = new Button { Text = "OK", Width = 90 };
        var cancel = new Button { Text = "Cancel", Width = 90, DialogResult = DialogResult.Cancel };
        ok.Click += (_, _) => AcceptSelection();
        bottom.Controls.Add(ok);
        bottom.Controls.Add(cancel);

        _list.DoubleClick += (_, _) => AcceptSelection();
        AcceptButton = ok;
        CancelButton = cancel;

        Controls.Add(_list);
        Controls.Add(_status);
        Controls.Add(top);
        Controls.Add(bottom);

        Shown += async (_, _) =>
        {
            await RefreshStatusAsync();
            await SearchAsync();
        };
    }

    private async Task RefreshStatusAsync()
    {
        try
        {
            var json = await _api.GetWebAsync("/api/catalog/status");
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            var steam = root.TryGetProperty("steam", out var s) ? s : default;
            var count = steam.ValueKind == JsonValueKind.Object && steam.TryGetProperty("count", out var c) ? c.GetInt32() : 0;
            var path = steam.ValueKind == JsonValueKind.Object && steam.TryGetProperty("path", out var p) ? p.GetString() : null;
            _status.Text = count > 0
                ? $"Steam catalog: {count:N0} apps — {path}"
                : $"Steam catalog empty or missing. Run Tools → Update Databases (steam). Path: {path}";
        }
        catch (Exception ex)
        {
            _status.Text = "Could not read catalog status: " + ex.Message;
        }
    }

    private async Task SearchAsync()
    {
        try
        {
            UseWaitCursor = true;
            var q = Uri.EscapeDataString(_query.Text.Trim());
            var dedicated = _dedicatedOnly.Checked ? "true" : "false";
            var json = await _api.GetWebAsync($"/api/catalog/steam?q={q}&dedicatedOnly={dedicated}");
            using var doc = JsonDocument.Parse(json);
            _list.Items.Clear();
            if (doc.RootElement.ValueKind == JsonValueKind.Object &&
                doc.RootElement.TryGetProperty("error", out var err))
            {
                MessageBox.Show(this, err.GetString() ?? "Catalog error", Text);
                return;
            }
            var arr = AsArray(doc.RootElement);
            if (arr.ValueKind != JsonValueKind.Array || arr.GetArrayLength() == 0)
            {
                _status.Text = "No matching Steam apps. Try another search, or run Tools → Update Databases.";
                return;
            }
            foreach (var item in arr.EnumerateArray())
            {
                var appId = Prop(item, "appId", "app_id", "AppId", "id") ?? "";
                var name = Prop(item, "name", "Name", "title") ?? "";
                _list.Items.Add(new ListViewItem(new[] { appId, name }));
            }
            _status.Text = $"Showing {_list.Items.Count} result(s). Double-click or OK to select.";
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
        finally
        {
            UseWaitCursor = false;
        }
    }

    private void AcceptSelection()
    {
        if (_list.SelectedItems.Count == 0)
        {
            MessageBox.Show(this, "Select an app first.", Text);
            return;
        }
        SelectedAppId = _list.SelectedItems[0].SubItems[0].Text;
        SelectedName = _list.SelectedItems[0].SubItems[1].Text;
        DialogResult = DialogResult.OK;
        Close();
    }

    private static JsonElement AsArray(JsonElement root)
    {
        if (root.ValueKind == JsonValueKind.Array) return root;
        foreach (var key in new[] { "items", "results", "data", "apps" })
            if (root.TryGetProperty(key, out var a) && a.ValueKind == JsonValueKind.Array)
                return a;
        return default;
    }

    private static string? Prop(JsonElement e, params string[] names)
    {
        foreach (var n in names)
        {
            if (!e.TryGetProperty(n, out var p) || p.ValueKind == JsonValueKind.Null) continue;
            return p.ValueKind switch
            {
                JsonValueKind.String => p.GetString(),
                JsonValueKind.Number => p.ToString(),
                JsonValueKind.True => "true",
                JsonValueKind.False => "false",
                _ => p.ToString()
            };
        }
        return null;
    }
}

internal sealed class McVersionBrowserForm : HostUiForm
{
    private readonly ApiClient _api;
    private readonly TextBox _query = new() { Width = 260 };
    private readonly ListView _list = new() { Dock = DockStyle.Fill, View = View.Details, FullRowSelect = true, GridLines = true };
    private readonly Label _status = new() { Dock = DockStyle.Bottom, Height = 22, Padding = new Padding(8, 2, 8, 2) };

    public string? SelectedVersion { get; private set; }

    public McVersionBrowserForm(ApiClient api)
    {
        _api = api;
        Text = "Minecraft Version Browser";
        Width = 720;
        Height = 520;
        StartPosition = FormStartPosition.CenterParent;
        _list.Columns.Add("Version", 160);
        _list.Columns.Add("Type", 120);
        _list.Columns.Add("ModLoader", 160);

        var top = new FlowLayoutPanel { Dock = DockStyle.Top, Height = 40, Padding = new Padding(8) };
        top.Controls.Add(new Label { Text = "Search", AutoSize = true, Padding = new Padding(0, 6, 0, 0) });
        top.Controls.Add(_query);
        var search = new Button { Text = "Search", Width = 90 };
        search.Click += async (_, _) => await SearchAsync();
        top.Controls.Add(search);
        _query.KeyDown += async (_, e) =>
        {
            if (e.KeyCode == Keys.Enter) { e.SuppressKeyPress = true; await SearchAsync(); }
        };

        var bottom = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 44, FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(8) };
        var ok = new Button { Text = "OK", Width = 90 };
        var cancel = new Button { Text = "Cancel", Width = 90, DialogResult = DialogResult.Cancel };
        ok.Click += (_, _) => AcceptSelection();
        bottom.Controls.Add(ok);
        bottom.Controls.Add(cancel);

        _list.DoubleClick += (_, _) => AcceptSelection();
        AcceptButton = ok;
        CancelButton = cancel;

        Controls.Add(_list);
        Controls.Add(_status);
        Controls.Add(top);
        Controls.Add(bottom);

        Shown += async (_, _) =>
        {
            await RefreshStatusAsync();
            await SearchAsync();
        };
    }

    private async Task RefreshStatusAsync()
    {
        try
        {
            var json = await _api.GetWebAsync("/api/catalog/status");
            using var doc = JsonDocument.Parse(json);
            var mc = doc.RootElement.TryGetProperty("minecraft", out var m) ? m : default;
            var count = mc.ValueKind == JsonValueKind.Object && mc.TryGetProperty("count", out var c) ? c.GetInt32() : 0;
            var path = mc.ValueKind == JsonValueKind.Object && mc.TryGetProperty("path", out var p) ? p.GetString() : null;
            _status.Text = count > 0
                ? $"Minecraft catalog: {count:N0} versions — {path}"
                : $"Minecraft catalog empty. Run Tools → Update Databases (minecraft). Path: {path}";
        }
        catch (Exception ex)
        {
            _status.Text = "Could not read catalog status: " + ex.Message;
        }
    }

    private async Task SearchAsync()
    {
        try
        {
            UseWaitCursor = true;
            var q = Uri.EscapeDataString(_query.Text.Trim());
            var json = await _api.GetWebAsync($"/api/catalog/minecraft?q={q}");
            using var doc = JsonDocument.Parse(json);
            _list.Items.Clear();
            var arr = AsArray(doc.RootElement);
            if (arr.ValueKind != JsonValueKind.Array || arr.GetArrayLength() == 0)
            {
                _status.Text = "No matching Minecraft versions. Try another search, or run Tools → Update Databases.";
                return;
            }
            foreach (var item in arr.EnumerateArray())
            {
                var version = Prop(item, "version", "Version", "id", "name") ?? "";
                var type = Prop(item, "type", "Type", "releaseType", "versionType", "VersionType") ?? "";
                var loader = Prop(item, "modLoader", "mod_loader", "ModLoader", "loader") ?? "";
                _list.Items.Add(new ListViewItem(new[] { version, type, loader }));
            }
            _status.Text = $"Showing {_list.Items.Count} result(s). Double-click or OK to select.";
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
        finally
        {
            UseWaitCursor = false;
        }
    }

    private void AcceptSelection()
    {
        if (_list.SelectedItems.Count == 0)
        {
            MessageBox.Show(this, "Select a version first.", Text);
            return;
        }
        SelectedVersion = _list.SelectedItems[0].SubItems[0].Text;
        DialogResult = DialogResult.OK;
        Close();
    }

    private static JsonElement AsArray(JsonElement root)
    {
        if (root.ValueKind == JsonValueKind.Array) return root;
        foreach (var key in new[] { "items", "results", "data", "versions" })
            if (root.TryGetProperty(key, out var a) && a.ValueKind == JsonValueKind.Array)
                return a;
        return default;
    }

    private static string? Prop(JsonElement e, params string[] names)
    {
        foreach (var n in names)
        {
            if (!e.TryGetProperty(n, out var p) || p.ValueKind == JsonValueKind.Null) continue;
            return p.ValueKind == JsonValueKind.String ? p.GetString() : p.ToString();
        }
        return null;
    }
}
