using System.Text.Json;

namespace ServerManager.HostUI;

internal sealed class AutomationForm : HostUiForm
{
    private readonly ApiClient _api;
    private readonly ComboBox _servers = new() { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Top };
    private readonly TextBox _motdMessage = new() { Dock = DockStyle.Fill };
    private readonly TextBox _motdCommand = new() { Dock = DockStyle.Fill };
    private readonly NumericUpDown _motdInterval = new() { Minimum = 0, Maximum = 10080, Dock = DockStyle.Left, Width = 100 };
    private readonly TextBox _stopCommand = new() { Dock = DockStyle.Fill };
    private readonly TextBox _saveCommand = new() { Dock = DockStyle.Fill };
    private readonly TextBox _startCommand = new() { Dock = DockStyle.Fill };
    private readonly TextBox _warningCommand = new() { Dock = DockStyle.Fill };
    private readonly TextBox _warningIntervals = new() { Dock = DockStyle.Fill, Text = "30,15,10,5,1" };
    private readonly TextBox _warningMessageTemplate = new() { Dock = DockStyle.Fill };
    private readonly CheckBox _scheduledRestart = new() { Text = "Scheduled restart enabled", AutoSize = true };

    public AutomationForm(ApiClient api)
    {
        _api = api;
        Text = "Automation Settings";
        Width = 580;
        Height = 560;
        StartPosition = FormStartPosition.CenterParent;

        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, Padding = new Padding(12) };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 160));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        void Row(string label, Control c)
        {
            var r = layout.RowCount++;
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 32));
            layout.Controls.Add(new Label { Text = label, AutoSize = true }, 0, r);
            layout.Controls.Add(c, 1, r);
        }
        Row("Server", _servers);
        Row("MOTD message", _motdMessage);
        Row("MOTD command", _motdCommand);
        Row("MOTD interval (min)", _motdInterval);
        Row("Start command", _startCommand);
        Row("Stop command", _stopCommand);
        Row("Save command", _saveCommand);
        Row("Warning command", _warningCommand);
        Row("Warning intervals", _warningIntervals);
        Row("Warning message", _warningMessageTemplate);
        layout.Controls.Add(_scheduledRestart, 1, layout.RowCount++);

        var save = new Button { Text = "Save", Width = 100, Dock = DockStyle.Bottom };
        save.Click += async (_, _) => await SaveAsync();
        _servers.SelectedIndexChanged += async (_, _) => await LoadSelectedAsync();

        Controls.Add(layout);
        Controls.Add(save);
        Shown += async (_, _) => await LoadServersAsync();
    }

    private async Task LoadServersAsync()
    {
        try
        {
            var list = await _api.ListServersAsync();
            _servers.Items.Clear();
            foreach (var s in list) _servers.Items.Add(s.Name);
            if (_servers.Items.Count > 0) _servers.SelectedIndex = 0;
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private async Task LoadSelectedAsync()
    {
        if (_servers.SelectedItem is not string name) return;
        try
        {
            var json = await _api.GetWebAsync($"/api/servers/{Uri.EscapeDataString(name)}");
            using var doc = JsonDocument.Parse(json);
            var e = doc.RootElement;
            _motdMessage.Text = Prop(e, "motdMessage", "motd_message");
            _motdCommand.Text = Prop(e, "motdCommand", "motd_command");
            if (e.TryGetProperty("motdInterval", out var mi) && mi.TryGetInt32(out var v)) _motdInterval.Value = v;
            else if (e.TryGetProperty("motd_interval", out var mi2) && mi2.TryGetInt32(out var v2)) _motdInterval.Value = v2;
            _stopCommand.Text = Prop(e, "stopCommand", "stop_command");
            _saveCommand.Text = Prop(e, "saveCommand", "save_command");
            _startCommand.Text = Prop(e, "startCommand", "start_command");
            _warningCommand.Text = Prop(e, "warningCommand", "warning_command");
            _warningIntervals.Text = Prop(e, "warningIntervals", "warning_intervals");
            if (string.IsNullOrWhiteSpace(_warningIntervals.Text)) _warningIntervals.Text = "30,15,10,5,1";
            _warningMessageTemplate.Text = Prop(e, "warningMessageTemplate", "warning_message_template");
            _scheduledRestart.Checked = (e.TryGetProperty("scheduledRestartEnabled", out var sr) && sr.GetBoolean())
                || (e.TryGetProperty("scheduled_restart_enabled", out var sr2) && sr2.GetBoolean());
        }
        catch { /* ignore */ }
    }

    private async Task SaveAsync()
    {
        if (_servers.SelectedItem is not string name) return;
        try
        {
            await _api.PutWebJsonAsync($"/api/servers/{Uri.EscapeDataString(name)}", new
            {
                motdMessage = _motdMessage.Text,
                motdCommand = _motdCommand.Text,
                motdInterval = (int)_motdInterval.Value,
                stopCommand = _stopCommand.Text,
                saveCommand = _saveCommand.Text,
                startCommand = _startCommand.Text,
                warningCommand = _warningCommand.Text,
                warningIntervals = _warningIntervals.Text,
                warningMessageTemplate = _warningMessageTemplate.Text,
                scheduledRestartEnabled = _scheduledRestart.Checked
            });
            MessageBox.Show(this, "Automation settings saved.", Text);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private static string Prop(JsonElement e, string a, string b)
    {
        if (e.TryGetProperty(a, out var p) && p.ValueKind != JsonValueKind.Null) return p.GetString() ?? "";
        if (e.TryGetProperty(b, out var p2) && p2.ValueKind != JsonValueKind.Null) return p2.GetString() ?? "";
        return "";
    }
}
