using System.Text.Json;

namespace ServerManager.HostUI;

internal sealed class ModpackBrowserForm : HostUiForm
{
    private readonly ApiClient _api;
    private readonly ComboBox _provider = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 140 };
    private readonly TextBox _query = new() { Width = 220 };
    private readonly ListView _results = new() { Dock = DockStyle.Fill, View = View.Details, FullRowSelect = true, GridLines = true };
    private readonly TextBox _serverName = new() { Width = 180 };
    private readonly TextBox _installDir = new() { Width = 280 };
    private readonly Label _status = new() { Dock = DockStyle.Bottom, Height = 22, Padding = new Padding(8, 2, 8, 2) };

    public ModpackBrowserForm(ApiClient api)
    {
        _api = api;
        Text = "Modded Minecraft Pack Browser";
        Width = 860;
        Height = 560;
        StartPosition = FormStartPosition.CenterParent;

        _provider.Items.AddRange(["modrinth", "curseforge", "technic", "ftb", "atlauncher"]);
        _provider.SelectedIndex = 0;
        _results.Columns.Add("Name", 260);
        _results.Columns.Add("Slug / Id", 160);
        _results.Columns.Add("MC", 90);
        _results.Columns.Add("Loader", 100);
        _results.Columns.Add("Summary", 280);

        var top = new FlowLayoutPanel { Dock = DockStyle.Top, Height = 40, Padding = new Padding(8) };
        top.Controls.Add(new Label { Text = "Provider", AutoSize = true, Padding = new Padding(0, 6, 0, 0) });
        top.Controls.Add(_provider);
        top.Controls.Add(new Label { Text = "Search", AutoSize = true, Padding = new Padding(8, 6, 0, 0) });
        top.Controls.Add(_query);
        var search = new Button { Text = "Search", Width = 90 };
        search.Click += async (_, _) => await SearchAsync();
        top.Controls.Add(search);
        _query.KeyDown += async (_, e) =>
        {
            if (e.KeyCode == Keys.Enter) { e.SuppressKeyPress = true; await SearchAsync(); }
        };

        var bottom = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 48, Padding = new Padding(8) };
        bottom.Controls.Add(new Label { Text = "Server name", AutoSize = true, Padding = new Padding(0, 6, 0, 0) });
        bottom.Controls.Add(_serverName);
        bottom.Controls.Add(new Label { Text = "Install dir", AutoSize = true, Padding = new Padding(8, 6, 0, 0) });
        bottom.Controls.Add(_installDir);
        var browse = new Button { Text = "…", Width = 32 };
        browse.Click += (_, _) =>
        {
            using var dlg = new FolderBrowserDialog();
            if (dlg.ShowDialog(this) == DialogResult.OK) _installDir.Text = dlg.SelectedPath;
        };
        bottom.Controls.Add(browse);
        var install = new Button { Text = "Install selected", Width = 120 };
        install.Click += async (_, _) => await InstallAsync();
        bottom.Controls.Add(install);

        Controls.Add(_results);
        Controls.Add(_status);
        Controls.Add(top);
        Controls.Add(bottom);

        Shown += async (_, _) => await SearchAsync();
    }

    private async Task SearchAsync()
    {
        try
        {
            UseWaitCursor = true;
            var provider = _provider.SelectedItem?.ToString() ?? "modrinth";
            var q = Uri.EscapeDataString(_query.Text.Trim());
            // Prefer local SQLite/catalog DB so offline installs work
            var json = await _api.GetWebAsync($"/api/catalog/modpacks?provider={provider}&q={q}");
            using var doc = JsonDocument.Parse(json);
            _results.Items.Clear();
            var arr = AsArray(doc.RootElement);
            if (arr.ValueKind != JsonValueKind.Array || arr.GetArrayLength() == 0)
            {
                // Live search fallback for modrinth/curseforge
                json = await _api.GetWebAsync($"/api/minecraft/modpacks/search?provider={provider}&q={q}");
                using var live = JsonDocument.Parse(json);
                arr = AsArray(live.RootElement);
                if (arr.ValueKind != JsonValueKind.Array || arr.GetArrayLength() == 0)
                {
                    var msg = live.RootElement.TryGetProperty("message", out var m) ? m.GetString() : null;
                    _status.Text = msg ?? $"No {provider} packs found. Run Tools → Update Databases for modded:{provider}.";
                    return;
                }
            }
            foreach (var item in arr.EnumerateArray())
            {
                var name = Prop(item, "title", "name", "Name") ?? "";
                var slug = Prop(item, "slug", "pack_id", "project_id", "id", "Id") ?? "";
                var mc = Prop(item, "mcVersion", "mc_version", "gameVersions") ?? "";
                var loader = Prop(item, "modLoader", "modloader", "loader") ?? "";
                var summary = Prop(item, "description", "summary", "shortDescription") ?? "";
                if (summary.Length > 80) summary = summary[..80] + "…";
                var row = new ListViewItem(new[] { name, slug, mc, loader, summary }) { Tag = item.GetRawText() };
                _results.Items.Add(row);
            }
            _status.Text = $"Showing {_results.Items.Count} {provider} pack(s).";
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

    private async Task InstallAsync()
    {
        if (_results.SelectedItems.Count == 0)
        {
            MessageBox.Show(this, "Select a pack first.", Text);
            return;
        }
        var name = _serverName.Text.Trim();
        var dir = _installDir.Text.Trim();
        if (string.IsNullOrWhiteSpace(name) || string.IsNullOrWhiteSpace(dir))
        {
            MessageBox.Show(this, "Server name and install directory are required.", Text);
            return;
        }
        try
        {
            var packJson = _results.SelectedItems[0].Tag as string ?? "{}";
            using var packDoc = JsonDocument.Parse(packJson);
            var provider = _provider.SelectedItem?.ToString() ?? "modrinth";
            var json = await _api.PostWebJsonAsync("/api/minecraft/modpacks/install", new
            {
                name,
                installDir = dir,
                provider,
                pack = packDoc.RootElement
            });
            MessageBox.Show(this, json, Text);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private static JsonElement AsArray(JsonElement root)
    {
        if (root.ValueKind == JsonValueKind.Array) return root;
        foreach (var key in new[] { "hits", "data", "packs", "items", "results" })
            if (root.TryGetProperty(key, out var a) && a.ValueKind == JsonValueKind.Array)
                return a;
        return default;
    }

    private static string? Prop(JsonElement e, params string[] names)
    {
        foreach (var n in names)
        {
            if (!e.TryGetProperty(n, out var p) || p.ValueKind == JsonValueKind.Null) continue;
            if (p.ValueKind == JsonValueKind.Array)
                return string.Join(", ", p.EnumerateArray().Select(x => x.ToString()).Take(3));
            return p.ValueKind == JsonValueKind.String ? p.GetString() : p.ToString();
        }
        return null;
    }
}
