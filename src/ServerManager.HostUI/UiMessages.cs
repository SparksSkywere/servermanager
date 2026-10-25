using System.Text;
using System.Text.Json;

namespace ServerManager.HostUI;

internal static class UiMessages
{
    public static void ShowApiResult(IWin32Window owner, string title, string jsonOrText)
    {
        var (summary, details) = Format(jsonOrText);
        using var dlg = new HostUiForm
        {
            Text = title,
            Width = 560,
            Height = 340,
            StartPosition = FormStartPosition.CenterParent,
            MinimizeBox = false,
            MaximizeBox = true
        };
        DialogLayout.ApplyFormDefaults(dlg, 420, 260, allowResize: true);

        var label = new Label
        {
            Text = summary,
            Dock = DockStyle.Top,
            AutoSize = true,
            MaximumSize = new Size(520, 0),
            Padding = new Padding(12, 12, 12, 8),
            Font = new Font(SystemFonts.MessageBoxFont!.FontFamily, 10f)
        };
        var detailsBox = new TextBox
        {
            Multiline = true,
            ReadOnly = true,
            Dock = DockStyle.Fill,
            Font = new Font("Consolas", 9f),
            ScrollBars = ScrollBars.Both,
            Text = details,
            Visible = false
        };
        var ok = new Button { Text = "OK", DialogResult = DialogResult.OK };
        var copy = new Button { Text = "Copy details" };
        var toggle = new Button { Text = "Show details" };
        copy.Click += (_, _) =>
        {
            try { Clipboard.SetText(string.IsNullOrWhiteSpace(details) ? summary : details); }
            catch { /* ignore */ }
        };
        toggle.Click += (_, _) =>
        {
            detailsBox.Visible = !detailsBox.Visible;
            toggle.Text = detailsBox.Visible ? "Hide details" : "Show details";
            dlg.Height = detailsBox.Visible
                ? Math.Max(dlg.MinimumSize.Height + 160, 440)
                : Math.Max(dlg.MinimumSize.Height, 300);
        };
        var bar = DialogLayout.ButtonBar(ok, copy, toggle);
        DialogLayout.Host(dlg, detailsBox, bar, label);
        dlg.AcceptButton = ok;
        dlg.ShowDialog(owner);
    }

    public static (string Summary, string Details) Format(string jsonOrText)
    {
        var raw = jsonOrText?.Trim() ?? "";
        if (string.IsNullOrWhiteSpace(raw)) return ("No response.", "");
        try
        {
            using var doc = JsonDocument.Parse(raw);
            var e = doc.RootElement;
            var sb = new StringBuilder();
            if (e.TryGetProperty("message", out var msg) && msg.ValueKind == JsonValueKind.String)
                sb.AppendLine(msg.GetString());
            else if (e.TryGetProperty("ok", out var ok))
                sb.AppendLine(ok.GetBoolean() ? "Completed successfully." : "Completed with errors.");

            if (e.TryGetProperty("serverCount", out var sc)) sb.AppendLine($"Servers in DB: {sc}");
            if (e.TryGetProperty("userCount", out var uc)) sb.AppendLine($"Users in DB: {uc}");
            if (e.TryGetProperty("count", out var c)) sb.AppendLine($"Count: {c}");
            if (e.TryGetProperty("updated", out var u)) sb.AppendLine($"Updated: {u}");
            if (e.TryGetProperty("failed", out var f)) sb.AppendLine($"Failed: {f}");
            if (e.TryGetProperty("action", out var a) && a.ValueKind == JsonValueKind.String)
                sb.AppendLine($"Action: {a.GetString()}");

            if (e.ValueKind == JsonValueKind.Array)
                sb.AppendLine($"Items returned: {e.GetArrayLength()}");

            var summary = sb.Length == 0 ? "Done." : sb.ToString().Trim();
            var pretty = JsonSerializer.Serialize(e, new JsonSerializerOptions { WriteIndented = true });
            return (summary, pretty);
        }
        catch
        {
            return (raw.Length > 400 ? raw[..400] + "…" : raw, raw);
        }
    }
}
