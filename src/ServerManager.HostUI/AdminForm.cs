using System.Text.Json;

namespace ServerManager.HostUI;

internal sealed class AdminForm : HostUiForm
{
    private readonly ApiClient _api;
    private readonly ListView _users = new() { Dock = DockStyle.Fill, View = View.Details, FullRowSelect = true, GridLines = true };
    private readonly TextBox _smtpHost = new();
    private readonly NumericUpDown _smtpPort = new() { Minimum = 1, Maximum = 65535, Value = 587 };
    private readonly TextBox _smtpUser = new();
    private readonly TextBox _smtpPass = new() { UseSystemPasswordChar = true };
    private readonly TextBox _smtpFrom = new();
    private readonly CheckBox _smtpTls = new() { Text = "Use TLS", Checked = true, AutoSize = true };
    private readonly CheckBox _notifyCrash = new() { Text = "Notify on crash", AutoSize = true };
    private readonly CheckBox _notifyUpdate = new() { Text = "Notify on update", AutoSize = true };
    private readonly ComboBox _theme = new() { DropDownStyle = ComboBoxStyle.DropDownList };

    public AdminForm(ApiClient api)
    {
        _api = api;
        Text = "Admin Dashboard - User Management";
        Width = 980;
        Height = 640;
        StartPosition = FormStartPosition.CenterScreen;
        foreach (var opt in ThemeCatalog.PickerOptions)
            _theme.Items.Add(opt);
        _theme.SelectedItem = ThemeCatalog.FindPickerOption(ThemeCatalog.SystemId);
        _theme.Width = 220;

        _users.Columns.Add("Username", 130);
        _users.Columns.Add("Display", 140);
        _users.Columns.Add("Email", 180);
        _users.Columns.Add("Admin", 60);
        _users.Columns.Add("Active", 60);
        _users.Columns.Add("2FA", 60);

        var tabs = new ThemedTabControl { Dock = DockStyle.Fill };
        var usersPage = new TabPage("Users")
        {
            BackColor = UiTheme.FormBack,
            ForeColor = UiTheme.FormFore,
            UseVisualStyleBackColor = false
        };
        var bar = new ToolStrip();
        bar.Items.Add("Refresh", null, async (_, _) => await LoadUsersAsync());
        bar.Items.Add("Add", null, async (_, _) => await AddUserAsync());
        bar.Items.Add("Edit", null, async (_, _) => await EditUserAsync());
        bar.Items.Add("Delete", null, async (_, _) => await DeleteUserAsync());
        bar.Items.Add("Reset Password", null, async (_, _) => await ResetPasswordAsync());
        bar.Items.Add("Reset 2FA", null, async (_, _) => await Reset2FaAsync());
        bar.Items.Add("Setup 2FA", null, async (_, _) => await Setup2FaAsync());
        bar.Items.Add("Permissions", null, async (_, _) => await OpenPermissionsAsync());
        usersPage.Controls.Add(_users);
        usersPage.Controls.Add(bar);
        tabs.TabPages.Add(usersPage);

        var smtpPage = new TabPage("Email / SMTP")
        {
            BackColor = UiTheme.FormBack,
            ForeColor = UiTheme.FormFore,
            UseVisualStyleBackColor = false
        };
        var smtpPanel = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            Padding = new Padding(12),
            AutoScroll = true,
            BackColor = UiTheme.FormBack
        };
        smtpPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 140));
        smtpPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        void SRow(string label, Control c)
        {
            var r = smtpPanel.RowCount++;
            smtpPanel.RowStyles.Add(new RowStyle(SizeType.Absolute, 32));
            smtpPanel.Controls.Add(new Label { Text = label, AutoSize = true }, 0, r);
            c.Dock = DockStyle.Fill;
            smtpPanel.Controls.Add(c, 1, r);
        }
        SRow("Host", _smtpHost);
        SRow("Port", _smtpPort);
        SRow("Username", _smtpUser);
        SRow("Password", _smtpPass);
        SRow("From", _smtpFrom);
        smtpPanel.Controls.Add(_smtpTls, 1, smtpPanel.RowCount++);
        smtpPanel.Controls.Add(_notifyCrash, 1, smtpPanel.RowCount++);
        smtpPanel.Controls.Add(_notifyUpdate, 1, smtpPanel.RowCount++);

        var smtpButtons = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true };
        var testSmtp = new Button { Text = "Test SMTP", Width = 110 };
        var saveSmtp = new Button { Text = "Save", Width = 100 };
        var bulk = new Button { Text = "Send Bulk Email", Width = 130 };
        testSmtp.Click += async (_, _) => await TestSmtpAsync();
        saveSmtp.Click += async (_, _) => await SaveSmtpAsync();
        bulk.Click += async (_, _) => await BulkEmailAsync();
        smtpButtons.Controls.Add(testSmtp);
        smtpButtons.Controls.Add(saveSmtp);
        smtpButtons.Controls.Add(bulk);
        smtpPanel.Controls.Add(smtpButtons, 1, smtpPanel.RowCount++);
        smtpPage.Controls.Add(smtpPanel);
        tabs.TabPages.Add(smtpPage);

        var extras = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 40, Padding = new Padding(8) };
        extras.Controls.Add(new Label { Text = "Theme", AutoSize = true, Padding = new Padding(0, 6, 0, 0) });
        extras.Controls.Add(_theme);
        var applyTheme = new Button { Text = "Apply Theme", Width = 100 };
        applyTheme.Click += async (_, _) => await ApplyThemeAsync();
        var about = new Button { Text = "About", Width = 80 };
        about.Click += (_, _) => new AboutForm().ShowDialog(this);
        var logout = new Button { Text = "Logout", Width = 80 };
        logout.Click += (_, _) =>
        {
            if (MessageBox.Show(this, "Close admin dashboard?", Text, MessageBoxButtons.YesNo) == DialogResult.Yes)
                Close();
        };
        extras.Controls.Add(applyTheme);
        extras.Controls.Add(about);
        extras.Controls.Add(logout);

        Controls.Add(tabs);
        Controls.Add(extras);
        Shown += async (_, _) => { await LoadUsersAsync(); await LoadSmtpAsync(); await LoadThemeAsync(); };
    }

    private string? SelectedUsername()
        => _users.SelectedItems.Count > 0 ? _users.SelectedItems[0].Text : null;

    private async Task LoadUsersAsync()
    {
        try
        {
            var json = await _api.GetWebAsync("/api/users");
            using var doc = JsonDocument.Parse(json);
            _users.Items.Clear();
            foreach (var u in doc.RootElement.EnumerateArray())
            {
                var tfa = BoolProp(u, "twoFactorEnabled", "TwoFactorEnabled", "two_factor_enabled");
                _users.Items.Add(new ListViewItem(new[]
                {
                    Str(u, "username", "Username") ?? "",
                    Str(u, "displayName", "DisplayName", "display_name") ?? "",
                    Str(u, "email", "Email") ?? "",
                    BoolProp(u, "isAdmin", "IsAdmin", "is_admin").ToString(),
                    (u.TryGetProperty("isActive", out var act) ? Truthy(act)
                        : u.TryGetProperty("IsActive", out var act2) ? Truthy(act2)
                        : u.TryGetProperty("is_active", out var act3) ? Truthy(act3)
                        : true).ToString(),
                    tfa.ToString()
                }));
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private async Task AddUserAsync()
    {
        var user = Prompt("Username");
        if (user is null) return;
        var pass = Prompt("Password", password: true);
        if (pass is null) return;
        try
        {
            await _api.PostWebJsonAsync("/api/users", new { username = user, password = pass, isAdmin = false, isActive = true });
            await LoadUsersAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private async Task EditUserAsync()
    {
        var username = SelectedUsername();
        if (username is null)
        {
            MessageBox.Show(this, "Select a user first.", Text);
            return;
        }
        var item = _users.SelectedItems[0];
        using var f = new HostUiForm
        {
            Text = $"Edit User — {username}",
            Width = 400,
            Height = 240,
            FormBorderStyle = FormBorderStyle.FixedDialog,
            StartPosition = FormStartPosition.CenterParent,
            MaximizeBox = false
        };
        var display = new TextBox { Text = item.SubItems[1].Text, Dock = DockStyle.Fill };
        var email = new TextBox { Text = item.SubItems[2].Text, Dock = DockStyle.Fill };
        var isAdmin = new CheckBox { Text = "Administrator", AutoSize = true, Checked = item.SubItems[3].Text == bool.TrueString };
        var isActive = new CheckBox { Text = "Active", AutoSize = true, Checked = item.SubItems[4].Text == bool.TrueString };
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, Padding = new Padding(12) };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 110));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        void Row(string label, Control c)
        {
            var r = layout.RowCount++;
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 32));
            layout.Controls.Add(new Label { Text = label, AutoSize = true }, 0, r);
            layout.Controls.Add(c, 1, r);
        }
        Row("Display name", display);
        Row("Email", email);
        layout.Controls.Add(isAdmin, 1, layout.RowCount++);
        layout.Controls.Add(isActive, 1, layout.RowCount++);
        var ok = new Button { Text = "Save", DialogResult = DialogResult.OK, Dock = DockStyle.Bottom };
        f.Controls.Add(layout);
        f.Controls.Add(ok);
        f.AcceptButton = ok;
        if (f.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            await _api.PutWebJsonAsync($"/api/users/{Uri.EscapeDataString(username)}", new
            {
                displayName = display.Text.Trim(),
                email = email.Text.Trim(),
                isAdmin = isAdmin.Checked,
                isActive = isActive.Checked
            });
            await LoadUsersAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private async Task DeleteUserAsync()
    {
        var username = SelectedUsername();
        if (username is null)
        {
            MessageBox.Show(this, "Select a user first.", Text);
            return;
        }
        if (MessageBox.Show(this, $"Delete user '{username}'?", Text, MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes)
            return;
        try
        {
            await _api.DeleteWebAsync($"/api/users/{Uri.EscapeDataString(username)}");
            await LoadUsersAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private async Task ResetPasswordAsync()
    {
        var username = SelectedUsername();
        if (username is null)
        {
            MessageBox.Show(this, "Select a user first.", Text);
            return;
        }
        var pass = Prompt("New password", password: true);
        if (pass is null) return;
        try
        {
            var json = await _api.PostWebJsonAsync($"/api/users/{Uri.EscapeDataString(username)}/reset-password", new { password = pass });
            UiMessages.ShowApiResult(this, "Reset Password", json);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private async Task Reset2FaAsync()
    {
        var username = SelectedUsername();
        if (username is null)
        {
            MessageBox.Show(this, "Select a user first.", Text);
            return;
        }
        if (MessageBox.Show(this, $"Reset 2FA for '{username}'?", Text, MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes)
            return;
        try
        {
            var json = await _api.PostWebJsonAsync($"/api/users/{Uri.EscapeDataString(username)}/reset-2fa", new { });
            UiMessages.ShowApiResult(this, "Reset 2FA", json);
            await LoadUsersAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private async Task Setup2FaAsync()
    {
        var username = SelectedUsername();
        // Prefer selected user for admin setup; fall back to current login.
        var target = username ?? _api.Username;
        using var f = new TwoFactorSetupForm(_api, target);
        f.ShowDialog(this);
        await LoadUsersAsync();
    }

    private async Task OpenPermissionsAsync()
    {
        try
        {
            var servers = await _api.ListServersAsync();
            if (servers.Count == 0)
            {
                MessageBox.Show(this, "No servers found.", Text);
                return;
            }
            using var f = new HostUiForm
            {
                Text = "Select Server",
                Width = 360,
                Height = 140,
                FormBorderStyle = FormBorderStyle.FixedDialog,
                StartPosition = FormStartPosition.CenterParent,
                MaximizeBox = false
            };
            var combo = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Top };
            foreach (var s in servers) combo.Items.Add(s.Name);
            combo.SelectedIndex = 0;
            var ok = new Button { Text = "OK", DialogResult = DialogResult.OK, Dock = DockStyle.Bottom };
            f.Controls.Add(combo);
            f.Controls.Add(ok);
            f.AcceptButton = ok;
            if (f.ShowDialog(this) != DialogResult.OK || combo.SelectedItem is not string name) return;
            using var editor = new PermissionsEditorForm(_api, name);
            editor.ShowDialog(this);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private async Task LoadSmtpAsync()
    {
        try
        {
            var json = await _api.GetWebAsync("/api/system-settings");
            using var doc = JsonDocument.Parse(json);
            foreach (var p in doc.RootElement.EnumerateObject())
            {
                switch (p.Name)
                {
                    case "SmtpHost": _smtpHost.Text = p.Value.GetString() ?? ""; break;
                    case "SmtpPort": if (int.TryParse(p.Value.GetString(), out var port)) _smtpPort.Value = port; break;
                    case "SmtpUser": _smtpUser.Text = p.Value.GetString() ?? ""; break;
                    case "SmtpFrom": _smtpFrom.Text = p.Value.GetString() ?? ""; break;
                    case "SmtpTls": _smtpTls.Checked = p.Value.GetString() != "false"; break;
                    case "NotifyOnCrash": _notifyCrash.Checked = p.Value.GetString() == "true"; break;
                    case "NotifyOnUpdate": _notifyUpdate.Checked = p.Value.GetString() == "true"; break;
                }
            }
        }
        catch { /* optional */ }
    }

    private async Task SaveSmtpAsync()
    {
        try
        {
            await _api.PostWebJsonAsync("/api/system-settings", new Dictionary<string, string>
            {
                ["SmtpHost"] = _smtpHost.Text.Trim(),
                ["SmtpPort"] = ((int)_smtpPort.Value).ToString(),
                ["SmtpUser"] = _smtpUser.Text.Trim(),
                ["SmtpPassword"] = _smtpPass.Text,
                ["SmtpFrom"] = _smtpFrom.Text.Trim(),
                ["SmtpTls"] = _smtpTls.Checked ? "true" : "false",
                ["NotifyOnCrash"] = _notifyCrash.Checked ? "true" : "false",
                ["NotifyOnUpdate"] = _notifyUpdate.Checked ? "true" : "false"
            });
            MessageBox.Show(this, "SMTP settings saved.", Text);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private async Task TestSmtpAsync()
    {
        try
        {
            await SaveSmtpAsync();
            var json = await _api.PostWebJsonAsync("/api/analytics/smtp/test", new { });
            UiMessages.ShowApiResult(this, "Test SMTP", json);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private async Task BulkEmailAsync()
    {
        var subject = Prompt("Email subject");
        if (subject is null) return;
        var body = PromptMultiline("Email body");
        if (body is null) return;
        try
        {
            var json = await _api.PostWebJsonAsync("/api/users/bulk-email", new { subject, body });
            UiMessages.ShowApiResult(this, "Bulk Email", json);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text);
        }
    }

    private async Task LoadThemeAsync()
    {
        try
        {
            var profile = await _api.GetWebAsync("/api/profile");
            using var doc = JsonDocument.Parse(profile);
            var theme = doc.RootElement.TryGetProperty("theme", out var th) ? th.GetString() ?? "system" : "system";
            var opt = ThemeCatalog.FindPickerOption(theme);
            foreach (ThemePickerOption item in _theme.Items)
            {
                if (item.Id.Equals(opt.Id, StringComparison.OrdinalIgnoreCase))
                {
                    _theme.SelectedItem = item;
                    return;
                }
            }
            _theme.SelectedItem = opt;
        }
        catch { /* optional */ }
    }

    private async Task ApplyThemeAsync()
    {
        var theme = (_theme.SelectedItem as ThemePickerOption)?.Id
                    ?? ThemeCatalog.NormalizeId(_theme.SelectedItem?.ToString());
        try
        {
            await _api.PutWebJsonAsync("/api/profile", new { theme });
        }
        catch { /* optional */ }
        ThemeApplier.Apply(theme);
    }

    private string? Prompt(string title, bool password = false)
    {
        using var f = new HostUiForm
        {
            Text = title,
            Width = 360,
            Height = 140,
            FormBorderStyle = FormBorderStyle.FixedDialog,
            StartPosition = FormStartPosition.CenterParent,
            MaximizeBox = false
        };
        var box = new TextBox { Dock = DockStyle.Top, Margin = new Padding(12) };
        if (password) box.UseSystemPasswordChar = true;
        var ok = new Button { Text = "OK", DialogResult = DialogResult.OK, Dock = DockStyle.Bottom };
        f.Controls.Add(box);
        f.Controls.Add(ok);
        f.AcceptButton = ok;
        return f.ShowDialog(this) == DialogResult.OK ? box.Text.Trim() : null;
    }

    private string? PromptMultiline(string title)
    {
        using var f = new HostUiForm
        {
            Text = title,
            Width = 480,
            Height = 320,
            FormBorderStyle = FormBorderStyle.Sizable,
            StartPosition = FormStartPosition.CenterParent
        };
        var box = new TextBox { Dock = DockStyle.Fill, Multiline = true, ScrollBars = ScrollBars.Vertical };
        var ok = new Button { Text = "OK", DialogResult = DialogResult.OK, Dock = DockStyle.Bottom };
        f.Controls.Add(box);
        f.Controls.Add(ok);
        f.AcceptButton = ok;
        return f.ShowDialog(this) == DialogResult.OK ? box.Text : null;
    }

    private static string? Str(JsonElement e, params string[] names)
    {
        foreach (var n in names)
            if (e.TryGetProperty(n, out var p) && p.ValueKind == JsonValueKind.String)
                return p.GetString();
        return null;
    }

    private static bool BoolProp(JsonElement e, params string[] names)
    {
        foreach (var n in names)
            if (e.TryGetProperty(n, out var p))
                return Truthy(p);
        return false;
    }

    private static bool Truthy(JsonElement p) =>
        p.ValueKind == JsonValueKind.True
        || (p.ValueKind == JsonValueKind.String && string.Equals(p.GetString(), "true", StringComparison.OrdinalIgnoreCase));
}
