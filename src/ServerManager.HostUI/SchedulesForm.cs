using System.Text.Json;

namespace ServerManager.HostUI;

internal sealed class SchedulesForm : HostUiForm
{
    private readonly ApiClient _api;
    private readonly ListView _list = new() { Dock = DockStyle.Fill, View = View.Details, FullRowSelect = true, GridLines = true };

    public SchedulesForm(ApiClient api)
    {
        _api = api;
        Text = "Schedule Manager";
        Width = 760;
        Height = 500;
        StartPosition = FormStartPosition.CenterParent;
        _list.Columns.Add("Server", 180);
        _list.Columns.Add("Auto-start", 90);
        _list.Columns.Add("Scheduled restart", 120);
        _list.Columns.Add("MOTD interval", 100);
        _list.Columns.Add("Warnings", 120);
        _list.Columns.Add("Status", 90);

        var bar = new ToolStrip();
        bar.Items.Add("Refresh", null, async (_, _) => await LoadAsync());
        bar.Items.Add("Edit", null, async (_, _) => await EditAsync());
        bar.Items.Add("Open Automation", null, (_, _) =>
        {
            new AutomationForm(_api).ShowDialog(this);
            _ = LoadAsync();
        });
        _list.DoubleClick += async (_, _) => await EditAsync();
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
                string auto = "", restart = "", motd = "", warnings = "";
                try
                {
                    var json = await _api.GetWebAsync($"/api/servers/{Uri.EscapeDataString(s.Name)}");
                    using var doc = JsonDocument.Parse(json);
                    var e = doc.RootElement;
                    auto = (e.TryGetProperty("autoStart", out var a) && a.GetBoolean()
                            || e.TryGetProperty("auto_start", out var a2) && a2.GetBoolean()).ToString();
                    restart = (e.TryGetProperty("scheduledRestartEnabled", out var r) && r.GetBoolean()
                               || e.TryGetProperty("scheduled_restart_enabled", out var r2) && r2.GetBoolean()).ToString();
                    motd = e.TryGetProperty("motdInterval", out var m) ? m.ToString()
                        : e.TryGetProperty("motd_interval", out var m2) ? m2.ToString() : "";
                    warnings = e.TryGetProperty("warningIntervals", out var w) ? w.GetString() ?? w.ToString()
                        : e.TryGetProperty("warning_intervals", out var w2) ? w2.GetString() ?? w2.ToString() : "";
                }
                catch { /* ignore */ }
                _list.Items.Add(new ListViewItem(new[] { s.Name, auto, restart, motd, warnings, s.Status }));
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private async Task EditAsync()
    {
        if (_list.SelectedItems.Count == 0)
        {
            MessageBox.Show(this, "Select a server row first.", Text);
            return;
        }
        var name = _list.SelectedItems[0].Text;
        try
        {
            var json = await _api.GetWebAsync($"/api/servers/{Uri.EscapeDataString(name)}");
            using var doc = JsonDocument.Parse(json);
            var e = doc.RootElement;

            using var f = new HostUiForm
            {
                Text = $"Edit Schedule — {name}",
                Width = 420,
                Height = 260,
                FormBorderStyle = FormBorderStyle.FixedDialog,
                StartPosition = FormStartPosition.CenterParent,
                MaximizeBox = false
            };
            var autoStart = new CheckBox
            {
                Text = "Auto-start",
                AutoSize = true,
                Checked = (e.TryGetProperty("autoStart", out var a) && a.GetBoolean())
                          || (e.TryGetProperty("auto_start", out var a2) && a2.GetBoolean())
            };
            var scheduled = new CheckBox
            {
                Text = "Scheduled restart enabled",
                AutoSize = true,
                Checked = (e.TryGetProperty("scheduledRestartEnabled", out var r) && r.GetBoolean())
                          || (e.TryGetProperty("scheduled_restart_enabled", out var r2) && r2.GetBoolean())
            };
            var motd = new NumericUpDown { Minimum = 0, Maximum = 10080, Dock = DockStyle.Fill };
            if (e.TryGetProperty("motdInterval", out var mi) && mi.TryGetInt32(out var mv)) motd.Value = mv;
            else if (e.TryGetProperty("motd_interval", out var mi2) && mi2.TryGetInt32(out var mv2)) motd.Value = mv2;
            var warnings = new TextBox
            {
                Dock = DockStyle.Fill,
                Text = e.TryGetProperty("warningIntervals", out var wi) ? wi.GetString() ?? ""
                    : e.TryGetProperty("warning_intervals", out var wi2) ? wi2.GetString() ?? "" : "30,15,10,5,1"
            };

            var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, Padding = new Padding(12) };
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 150));
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            layout.Controls.Add(autoStart, 1, 0);
            layout.Controls.Add(scheduled, 1, 1);
            layout.Controls.Add(new Label { Text = "MOTD interval (min)", AutoSize = true }, 0, 2);
            layout.Controls.Add(motd, 1, 2);
            layout.Controls.Add(new Label { Text = "Warning intervals", AutoSize = true }, 0, 3);
            layout.Controls.Add(warnings, 1, 3);
            var ok = new Button { Text = "Save", DialogResult = DialogResult.OK, Dock = DockStyle.Bottom };
            f.Controls.Add(layout);
            f.Controls.Add(ok);
            f.AcceptButton = ok;
            if (f.ShowDialog(this) != DialogResult.OK) return;

            await _api.PutWebJsonAsync($"/api/servers/{Uri.EscapeDataString(name)}", new
            {
                autoStart = autoStart.Checked,
                scheduledRestartEnabled = scheduled.Checked,
                motdInterval = (int)motd.Value,
                warningIntervals = warnings.Text.Trim()
            });
            await LoadAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }
}
