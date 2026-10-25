using System.Text.Json;

namespace ServerManager.HostUI;

internal sealed class TwoFactorSetupForm : HostUiForm
{
    private readonly ApiClient _api;
    private readonly string? _targetUsername;
    private readonly TextBox _secret = new() { ReadOnly = true, Dock = DockStyle.Fill };
    private readonly TextBox _uri = new() { ReadOnly = true, Multiline = true, Height = 60, Dock = DockStyle.Fill, ScrollBars = ScrollBars.Vertical };
    private readonly TextBox _code = new() { Dock = DockStyle.Fill };
    private readonly Label _status = new() { AutoSize = true, Dock = DockStyle.Fill };

    public TwoFactorSetupForm(ApiClient api, string? targetUsername = null)
    {
        _api = api;
        _targetUsername = string.IsNullOrWhiteSpace(targetUsername) ? null : targetUsername.Trim();
        Text = _targetUsername is null
            ? "Setup Two-Factor Authentication"
            : $"Setup 2FA — {_targetUsername}";
        Width = 520;
        Height = 360;
        StartPosition = FormStartPosition.CenterParent;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;

        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, Padding = new Padding(12) };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 100));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        void Row(string label, Control c, int h = 28)
        {
            var r = layout.RowCount++;
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, h));
            layout.Controls.Add(new Label { Text = label, AutoSize = true }, 0, r);
            layout.Controls.Add(c, 1, r);
        }
        Row("Secret", _secret);
        Row("otpauth URI", _uri, 72);
        Row("Verify code", _code);
        Row("", _status, 40);

        var bar = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 44, FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(8) };
        var verify = new Button { Text = "Verify", Width = 100 };
        var close = new Button { Text = "Close", Width = 90, DialogResult = DialogResult.Cancel };
        verify.Click += async (_, _) => await VerifyAsync();
        bar.Controls.Add(verify);
        bar.Controls.Add(close);

        Controls.Add(layout);
        Controls.Add(bar);
        Shown += async (_, _) => await SetupAsync();
    }

    private async Task SetupAsync()
    {
        try
        {
            object body = _targetUsername is null
                ? new { }
                : new { username = _targetUsername };
            var path = _targetUsername is null
                ? "/api/auth/2fa/setup"
                : $"/api/auth/2fa/setup?username={Uri.EscapeDataString(_targetUsername)}";
            var json = await _api.PostWebJsonAsync(path, body);
            using var doc = JsonDocument.Parse(json);
            var e = doc.RootElement;
            _secret.Text = Str(e, "secret", "Secret", "totpSecret") ?? "";
            _uri.Text = Str(e, "otpauthUri", "otpauth_uri", "uri", "otpauth") ?? "";
            if (string.IsNullOrWhiteSpace(_secret.Text) && string.IsNullOrWhiteSpace(_uri.Text))
            {
                _status.Text = e.TryGetProperty("error", out var err) ? err.GetString() ?? json : json;
                _status.ForeColor = Color.Firebrick;
            }
            else
            {
                _status.Text = "Scan the otpauth URI / secret in your authenticator, then enter a code.";
                _status.ForeColor = SystemColors.ControlText;
            }
        }
        catch (Exception ex)
        {
            _status.Text = ex.Message;
            _status.ForeColor = Color.Firebrick;
        }
    }

    private async Task VerifyAsync()
    {
        var code = _code.Text.Trim();
        if (string.IsNullOrWhiteSpace(code))
        {
            MessageBox.Show(this, "Enter the 6-digit code from your authenticator.", Text);
            return;
        }
        try
        {
            object body = _targetUsername is null
                ? new { code }
                : new { code, username = _targetUsername };
            var json = await _api.PostWebJsonAsync("/api/auth/2fa/verify", body);
            using var doc = JsonDocument.Parse(json);
            var e = doc.RootElement;
            var ok = (e.TryGetProperty("success", out var s) && s.ValueKind == JsonValueKind.True)
                     || (e.TryGetProperty("ok", out var o) && o.ValueKind == JsonValueKind.True);
            if (ok || (!e.TryGetProperty("error", out _) && !e.TryGetProperty("message", out var m)))
            {
                MessageBox.Show(this, "Two-factor authentication enabled.", Text);
                DialogResult = DialogResult.OK;
                Close();
                return;
            }
            var msg = e.TryGetProperty("error", out var err) ? err.GetString()
                : e.TryGetProperty("message", out var msgEl) ? msgEl.GetString()
                : json;
            MessageBox.Show(this, msg ?? "Verification failed.", Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private static string? Str(JsonElement e, params string[] names)
    {
        foreach (var n in names)
            if (e.TryGetProperty(n, out var p) && p.ValueKind == JsonValueKind.String)
                return p.GetString();
        return null;
    }
}
