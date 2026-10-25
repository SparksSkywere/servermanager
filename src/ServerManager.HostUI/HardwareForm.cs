using System.Text.Json;

namespace ServerManager.HostUI;

internal sealed class HardwareForm : HostUiForm
{
    private readonly ApiClient _api;
    private readonly TextBox _out = new()
    {
        Dock = DockStyle.Fill,
        Multiline = true,
        ReadOnly = true,
        ScrollBars = ScrollBars.Both,
        Font = new Font("Consolas", 9f)
    };
    private readonly Label _summary = new()
    {
        Dock = DockStyle.Top,
        Height = 56,
        Padding = new Padding(8),
        AutoSize = false
    };

    public HardwareForm(ApiClient api)
    {
        _api = api;
        Text = "Hardware Panel";
        Width = 720;
        Height = 520;
        StartPosition = FormStartPosition.CenterParent;

        var bar = new ToolStrip();
        bar.Items.Add("Refresh Local + BMC", null, async (_, _) => await LoadAsync());
        bar.Items.Add("Temperatures only", null, async (_, _) => await LoadTempsAsync());
        Controls.Add(_out);
        Controls.Add(_summary);
        Controls.Add(bar);
        Shown += async (_, _) => await LoadAsync();
    }

    private async Task LoadAsync()
    {
        try
        {
            var temps = await _api.GetWebAsync("/api/analytics/temperatures");
            var host = "";
            try { host = await _api.GetRuntimeAsync("/api/runtime/metrics/host"); } catch { /* optional */ }
            _summary.Text = "Local OS sensors plus optional iLO/iDRAC (configure hosts in Settings → Hardware).";
            _out.Text = "=== Host metrics ===\n" + Pretty(host) + "\n\n=== Temperatures / BMC ===\n" + Pretty(temps);
        }
        catch (Exception ex)
        {
            _out.Text = ex.Message;
        }
    }

    private async Task LoadTempsAsync()
    {
        try
        {
            var temps = await _api.GetWebAsync("/api/analytics/temperatures");
            _summary.Text = "Temperature probe result.";
            _out.Text = Pretty(temps);
        }
        catch (Exception ex) { _out.Text = ex.Message; }
    }

    private static string Pretty(string json)
    {
        if (string.IsNullOrWhiteSpace(json)) return "(empty)";
        try
        {
            using var doc = JsonDocument.Parse(json);
            return JsonSerializer.Serialize(doc.RootElement, new JsonSerializerOptions { WriteIndented = true });
        }
        catch { return json; }
    }
}
