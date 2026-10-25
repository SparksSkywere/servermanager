using System.Text.Json;

namespace ServerManager.HostUI;

internal sealed class PermissionsEditorForm : HostUiForm
{
    private readonly ApiClient _api;
    private readonly string _serverName;
    private readonly DataGridView _grid = new()
    {
        Dock = DockStyle.Fill,
        AllowUserToAddRows = false,
        AllowUserToDeleteRows = false,
        AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill,
        RowHeadersVisible = false,
        SelectionMode = DataGridViewSelectionMode.FullRowSelect
    };

    public PermissionsEditorForm(ApiClient api, string serverName)
    {
        _api = api;
        _serverName = serverName;
        Text = $"Permissions — {serverName}";
        Width = 780;
        Height = 480;
        StartPosition = FormStartPosition.CenterParent;

        _grid.Columns.Add(new DataGridViewTextBoxColumn { Name = "Username", HeaderText = "Username", ReadOnly = true, FillWeight = 140 });
        _grid.Columns.Add(new DataGridViewCheckBoxColumn { Name = "CanView", HeaderText = "View", FillWeight = 60 });
        _grid.Columns.Add(new DataGridViewCheckBoxColumn { Name = "CanStart", HeaderText = "Start", FillWeight = 60 });
        _grid.Columns.Add(new DataGridViewCheckBoxColumn { Name = "CanStop", HeaderText = "Stop", FillWeight = 60 });
        _grid.Columns.Add(new DataGridViewCheckBoxColumn { Name = "CanRestart", HeaderText = "Restart", FillWeight = 70 });
        _grid.Columns.Add(new DataGridViewCheckBoxColumn { Name = "CanConsole", HeaderText = "Console", FillWeight = 70 });
        _grid.Columns.Add(new DataGridViewCheckBoxColumn { Name = "CanEdit", HeaderText = "Edit", FillWeight = 60 });

        var bar = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 44, FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(8) };
        var save = new Button { Text = "Save", Width = 100 };
        var cancel = new Button { Text = "Close", Width = 90, DialogResult = DialogResult.Cancel };
        var refresh = new Button { Text = "Refresh", Width = 90 };
        save.Click += async (_, _) => await SaveAsync();
        refresh.Click += async (_, _) => await LoadAsync();
        bar.Controls.Add(save);
        bar.Controls.Add(cancel);
        bar.Controls.Add(refresh);

        Controls.Add(_grid);
        Controls.Add(bar);
        Shown += async (_, _) => await LoadAsync();
    }

    private async Task LoadAsync()
    {
        try
        {
            var usersJson = await _api.GetWebAsync("/api/users");
            var permsJson = await _api.GetWebAsync($"/api/servers/{Uri.EscapeDataString(_serverName)}/permissions");

            var permMap = new Dictionary<string, JsonElement>(StringComparer.OrdinalIgnoreCase);
            using (var pdoc = JsonDocument.Parse(permsJson))
            {
                var root = pdoc.RootElement;
                var arr = root.ValueKind == JsonValueKind.Array ? root
                    : root.TryGetProperty("permissions", out var p) ? p
                    : default;
                if (arr.ValueKind == JsonValueKind.Array)
                {
                    foreach (var item in arr.EnumerateArray())
                    {
                        var user = Str(item, "username", "Username");
                        if (!string.IsNullOrWhiteSpace(user))
                            permMap[user!] = item.Clone();
                    }
                }
            }

            _grid.Rows.Clear();
            using var udoc = JsonDocument.Parse(usersJson);
            foreach (var u in udoc.RootElement.EnumerateArray())
            {
                var username = Str(u, "username", "Username") ?? "";
                if (string.IsNullOrWhiteSpace(username)) continue;
                permMap.TryGetValue(username, out var perm);
                _grid.Rows.Add(
                    username,
                    Bool(perm, "canView", "CanView", defaultTrue: true),
                    Bool(perm, "canStart", "CanStart"),
                    Bool(perm, "canStop", "CanStop"),
                    Bool(perm, "canRestart", "CanRestart"),
                    Bool(perm, "canConsole", "CanConsole"),
                    Bool(perm, "canEdit", "CanEdit"));
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private async Task SaveAsync()
    {
        try
        {
            var list = new List<object>();
            foreach (DataGridViewRow row in _grid.Rows)
            {
                if (row.IsNewRow) continue;
                var username = row.Cells["Username"].Value?.ToString() ?? "";
                if (string.IsNullOrWhiteSpace(username)) continue;
                var canView = row.Cells["CanView"].Value is true;
                var canStart = row.Cells["CanStart"].Value is true;
                var canStop = row.Cells["CanStop"].Value is true;
                var canRestart = row.Cells["CanRestart"].Value is true;
                var canConsole = row.Cells["CanConsole"].Value is true;
                var canEdit = row.Cells["CanEdit"].Value is true;
                if (!canView && !canStart && !canStop && !canRestart && !canConsole && !canEdit)
                    continue;
                list.Add(new
                {
                    username,
                    canView,
                    canStart,
                    canStop,
                    canRestart,
                    canConsole,
                    canEdit
                });
            }

            var json = await _api.PutWebJsonAsync(
                $"/api/servers/{Uri.EscapeDataString(_serverName)}/permissions",
                new { permissions = list });
            UiMessages.ShowApiResult(this, "Save Permissions", json);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private static string? Str(JsonElement e, params string[] names)
    {
        if (e.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null) return null;
        foreach (var n in names)
            if (e.TryGetProperty(n, out var p) && p.ValueKind == JsonValueKind.String)
                return p.GetString();
        return null;
    }

    private static bool Bool(JsonElement e, string a, string b, bool defaultTrue = false)
    {
        if (e.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null) return defaultTrue;
        if (e.TryGetProperty(a, out var p)) return Truthy(p);
        if (e.TryGetProperty(b, out var p2)) return Truthy(p2);
        return defaultTrue;
    }

    private static bool Truthy(JsonElement p) =>
        p.ValueKind == JsonValueKind.True
        || (p.ValueKind == JsonValueKind.String && string.Equals(p.GetString(), "true", StringComparison.OrdinalIgnoreCase));
}
