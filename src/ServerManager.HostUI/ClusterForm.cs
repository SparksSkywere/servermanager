using System.Text.Json;

namespace ServerManager.HostUI;

internal sealed class ClusterForm : HostUiForm
{
    private readonly ApiClient _api;
    private readonly Label _banner = new()
    {
        Dock = DockStyle.Fill,
        AutoSize = false,
        Padding = new Padding(8),
        Font = new Font(SystemFonts.MessageBoxFont.FontFamily, 10f)
    };
    private readonly ListView _nodes = new() { Dock = DockStyle.Fill, View = View.Details, FullRowSelect = true, GridLines = true };
    private readonly ListView _pending = new() { Dock = DockStyle.Fill, View = View.Details, FullRowSelect = true, GridLines = true };
    private bool _enabled;
    private string _role = "standalone";

    public ClusterForm(ApiClient api)
    {
        _api = api;
        Text = "Cluster Management";
        Width = 780;
        Height = 560;
        StartPosition = FormStartPosition.CenterParent;

        _nodes.Columns.Add("Node", 160);
        _nodes.Columns.Add("Type", 80);
        _nodes.Columns.Add("Address", 160);
        _nodes.Columns.Add("Status", 90);
        _nodes.Columns.Add("Last seen", 140);
        _pending.Columns.Add("Id", 50);
        _pending.Columns.Add("Subhost", 160);
        _pending.Columns.Add("Machine", 140);
        _pending.Columns.Add("Address", 140);
        _pending.Columns.Add("Status", 80);

        var split = new SplitContainer { Dock = DockStyle.Fill, Orientation = Orientation.Horizontal, SplitterDistance = 240 };
        var top = new GroupBox { Text = "Cluster Nodes", Dock = DockStyle.Fill };
        var nodePanel = new Panel { Dock = DockStyle.Fill };
        var nodeBar = new ToolStrip { Dock = DockStyle.Top };
        nodeBar.Items.Add("View remote servers", null, async (_, _) => await ViewRemoteServersAsync());
        nodeBar.Items.Add("Ping node", null, async (_, _) => await PingNodeAsync());
        nodeBar.Items.Add("Remote start", null, async (_, _) => await RemoteServerActionAsync("start"));
        nodeBar.Items.Add("Remote stop", null, async (_, _) => await RemoteServerActionAsync("stop"));
        nodeBar.Items.Add(new ToolStripSeparator());
        nodeBar.Items.Add("Remove Node", null, async (_, _) => await RemoveNodeAsync());
        nodeBar.Items.Add("Refresh", null, async (_, _) => await LoadAsync());
        nodePanel.Controls.Add(_nodes);
        nodePanel.Controls.Add(nodeBar);
        top.Controls.Add(nodePanel);

        var bottom = new GroupBox { Text = "Pending Join Requests", Dock = DockStyle.Fill };
        var pendingPanel = new Panel { Dock = DockStyle.Fill };
        var bar = new ToolStrip { Dock = DockStyle.Top };
        bar.Items.Add("Approve", null, async (_, _) => await ApproveAsync(true));
        bar.Items.Add("Reject", null, async (_, _) => await ApproveAsync(false));
        bar.Items.Add("Request Join (this machine)", null, async (_, _) => await RequestJoinAsync());
        bar.Items.Add("Refresh", null, async (_, _) => await LoadAsync());
        pendingPanel.Controls.Add(_pending);
        pendingPanel.Controls.Add(bar);
        bottom.Controls.Add(pendingPanel);
        split.Panel1.Controls.Add(top);
        split.Panel2.Controls.Add(bottom);

        var header = new Panel { Dock = DockStyle.Top, Height = 72, Padding = new Padding(4) };
        header.Controls.Add(_banner);
        Controls.Add(split);
        Controls.Add(header);
        Shown += async (_, _) => await LoadAsync();
    }

    private async Task LoadAsync()
    {
        try
        {
            var statusJson = await _api.GetWebAsync("/api/cluster/status");
            using (var doc = JsonDocument.Parse(statusJson))
            {
                var e = doc.RootElement;
                _role = e.TryGetProperty("role", out var r) ? r.GetString() ?? "standalone" : "standalone";
                _enabled = e.TryGetProperty("enabled", out var en) && en.ValueKind == JsonValueKind.True;
                var port = e.TryGetProperty("port", out var p) ? p.ToString() : "?";
                var note = e.TryGetProperty("note", out var n) ? n.GetString() : null;
                _banner.Text = _enabled
                    ? $"Role: {_role.ToUpperInvariant()}  ·  Cluster ON  ·  Peer port {port}\n{(note ?? "Approve pending subhosts, then watch last-seen update from heartbeats.")}"
                    : "Cluster is disabled.\nOpen Settings → enable Cluster, set Host type (host/subhost) and Host address, then save and reopen this window.";
                _banner.ForeColor = _enabled ? Color.DarkGreen : Color.DarkOrange;
            }

            _nodes.Items.Clear();
            _pending.Items.Clear();
            if (!_enabled) return;

            try
            {
                var nodes = await _api.GetWebAsync("/api/cluster/nodes");
                using var doc = JsonDocument.Parse(nodes);
                if (doc.RootElement.ValueKind == JsonValueKind.Array)
                {
                    foreach (var n in doc.RootElement.EnumerateArray())
                    {
                        var item = new ListViewItem(new[]
                        {
                            Prop(n, "nodeId", "NodeId"),
                            Prop(n, "nodeType", "NodeType"),
                            Prop(n, "address", "Address"),
                            Prop(n, "status", "Status"),
                            Prop(n, "lastHeartbeat", "LastHeartbeat")
                        });
                        item.Tag = Prop(n, "nodeId", "NodeId");
                        _nodes.Items.Add(item);
                    }
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, "Could not load nodes: " + ex.Message, Text);
            }

            try
            {
                var pending = await _api.GetWebAsync("/api/cluster/pending");
                using var doc = JsonDocument.Parse(pending);
                if (doc.RootElement.ValueKind == JsonValueKind.Array)
                {
                    foreach (var n in doc.RootElement.EnumerateArray())
                    {
                        var id = n.TryGetProperty("id", out var idEl) ? idEl.GetInt32()
                            : n.TryGetProperty("Id", out var idEl2) ? idEl2.GetInt32() : 0;
                        _pending.Items.Add(new ListViewItem(new[]
                        {
                            id.ToString(),
                            Prop(n, "subhostId", "SubhostId"),
                            Prop(n, "machineName", "MachineName"),
                            Prop(n, "address", "Address"),
                            Prop(n, "status", "Status")
                        })
                        { Tag = id });
                    }
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, "Could not load pending joins: " + ex.Message, Text);
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private async Task ApproveAsync(bool approve)
    {
        if (!_enabled)
        {
            MessageBox.Show(this, "Enable Cluster in Settings first.", Text);
            return;
        }
        if (_pending.SelectedItems.Count == 0) return;
        if (_pending.SelectedItems[0].Tag is not int id || id <= 0)
        {
            MessageBox.Show(this, "Pending request has no numeric id.", Text);
            return;
        }
        try
        {
            var action = approve ? "approve" : "reject";
            var json = await _api.PostWebJsonAsync($"/api/cluster/{action}/{id}", new { });
            if (approve)
            {
                using var doc = JsonDocument.Parse(json);
                var token = doc.RootElement.TryGetProperty("token", out var t) ? t.GetString() : null;
                var nodeId = doc.RootElement.TryGetProperty("node_id", out var n) ? n.GetString() : null;
                MessageBox.Show(this,
                    string.IsNullOrWhiteSpace(token)
                        ? "Approved."
                        : $"Approved subhost '{nodeId}'.\n\nThe subhost will pick up its token automatically via join-status.\nToken (for manual paste if needed):\n{token}",
                    Text, MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
            else
            {
                MessageBox.Show(this, "Join request rejected.", Text, MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
            await LoadAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private string? SelectedNodeId()
    {
        if (_nodes.SelectedItems.Count == 0) return null;
        return _nodes.SelectedItems[0].Tag as string;
    }

    private async Task ViewRemoteServersAsync()
    {
        var nodeId = SelectedNodeId();
        if (string.IsNullOrWhiteSpace(nodeId))
        {
            MessageBox.Show(this, "Select a node first.", Text);
            return;
        }
        try
        {
            var json = await _api.GetWebAsync($"/api/cluster/subhost/{Uri.EscapeDataString(nodeId)}/servers");
            UiMessages.ShowApiResult(this, $"Remote servers — {nodeId}", json);
        }
        catch
        {
            MessageBox.Show(this,
                $"No server list endpoint for '{nodeId}'.\n\nUse Remote start / Remote stop with a server name\n(POST /api/cluster/subhost/{{id}}/servers/{{server}}/start|stop).",
                Text, MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        await Task.CompletedTask;
    }

    private async Task PingNodeAsync()
    {
        var nodeId = SelectedNodeId();
        if (string.IsNullOrWhiteSpace(nodeId))
        {
            MessageBox.Show(this, "Select a node first.", Text);
            return;
        }
        try
        {
            await LoadAsync();
            ListViewItem? row = null;
            foreach (ListViewItem item in _nodes.Items)
            {
                if (string.Equals(item.Tag as string, nodeId, StringComparison.OrdinalIgnoreCase))
                {
                    row = item;
                    break;
                }
            }
            if (row is null)
            {
                MessageBox.Show(this, $"Node '{nodeId}' not found after refresh.", Text);
                return;
            }
            MessageBox.Show(this,
                $"Node: {row.SubItems[0].Text}\nType: {row.SubItems[1].Text}\nAddress: {row.SubItems[2].Text}\nStatus: {row.SubItems[3].Text}\nLast seen: {row.SubItems[4].Text}",
                "Ping node", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private async Task RemoteServerActionAsync(string action)
    {
        var nodeId = SelectedNodeId();
        if (string.IsNullOrWhiteSpace(nodeId))
        {
            MessageBox.Show(this, "Select a node first.", Text);
            return;
        }
        var server = Prompt("Remote server name");
        if (string.IsNullOrWhiteSpace(server)) return;
        try
        {
            var json = await _api.PostWebJsonAsync(
                $"/api/cluster/subhost/{Uri.EscapeDataString(nodeId)}/servers/{Uri.EscapeDataString(server.Trim())}/{action}",
                new { });
            UiMessages.ShowApiResult(this, $"Remote {action}", json);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private static string? Prompt(string title)
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
        f.Controls.Add(new Label { Left = 12, Top = 12, AutoSize = true, Text = "Server name:" });
        f.Controls.Add(tb);
        var ok = new Button { Text = "OK", Left = 176, Top = 70, Width = 70, DialogResult = DialogResult.OK };
        var cancel = new Button { Text = "Cancel", Left = 256, Top = 70, Width = 70, DialogResult = DialogResult.Cancel };
        f.Controls.Add(ok);
        f.Controls.Add(cancel);
        f.AcceptButton = ok;
        f.CancelButton = cancel;
        return f.ShowDialog() == DialogResult.OK ? tb.Text.Trim() : null;
    }

    private async Task RemoveNodeAsync()
    {
        if (_nodes.SelectedItems.Count == 0) return;
        var nodeId = _nodes.SelectedItems[0].Tag as string;
        if (string.IsNullOrWhiteSpace(nodeId)) return;
        if (MessageBox.Show(this, $"Remove node '{nodeId}'?", Text, MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes)
            return;
        try
        {
            await _api.DeleteWebAsync($"/api/cluster/nodes/{Uri.EscapeDataString(nodeId)}");
            await LoadAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private async Task RequestJoinAsync()
    {
        if (!_enabled)
        {
            MessageBox.Show(this, "Enable Cluster in Settings and set Host type to subhost.", Text);
            return;
        }
        try
        {
            var json = await _api.PostWebJsonAsync("/api/cluster/request-join", new
            {
                subhostId = Environment.MachineName + "-" + Guid.NewGuid().ToString("N")[..8],
                machineName = Environment.MachineName,
                address = Environment.MachineName
            });
            UiMessages.ShowApiResult(this, "Request Join", json);
            await LoadAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private static string Prop(JsonElement e, params string[] names)
    {
        foreach (var n in names)
            if (e.TryGetProperty(n, out var p) && p.ValueKind != JsonValueKind.Null)
                return p.ToString();
        return "";
    }
}
