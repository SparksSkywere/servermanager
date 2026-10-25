namespace ServerManager.HostUI;

internal sealed class LoginForm : HostUiForm
{
    private readonly TextBox _user = new();
    private readonly TextBox _pass = new() { UseSystemPasswordChar = true };
    private readonly TextBox _totp = new();
    private readonly Label _status = new()
    {
        AutoSize = true,
        ForeColor = Color.Firebrick,
        MaximumSize = new Size(400, 0),
        Margin = new Padding(0, 8, 0, 4)
    };
    private readonly ApiClient _api;
    private bool _backendReady;

    public LoginForm(ApiClient api)
    {
        _api = api;
        Text = "Server Manager - Authentication Required";
        DialogLayout.ApplyFormDefaults(this, 420, 320, allowResize: false);
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        Width = 480;
        Height = 380;
        AcceptButton = null;

        // Single table — heading inside the grid avoids Dock.Top overlapping the Username row.
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            Padding = new Padding(20, 16, 20, 12),
            RowCount = 7
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 110));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));      // heading
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));  // user
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));  // pass
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));  // totp
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));      // status
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 44));  // buttons
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));  // spacer

        var heading = new Label
        {
            Text = "Administrator Access Required",
            Font = new Font(Font.FontFamily, 11, FontStyle.Bold),
            AutoSize = true,
            Margin = new Padding(0, 4, 0, 12)
        };
        layout.Controls.Add(heading, 0, 0);
        layout.SetColumnSpan(heading, 2);

        void Field(string label, Control c, int r)
        {
            c.Dock = DockStyle.Fill;
            c.Margin = new Padding(0, 4, 0, 4);
            layout.Controls.Add(new Label
            {
                Text = label,
                AutoSize = true,
                Anchor = AnchorStyles.Left,
                Margin = new Padding(0, 10, 8, 0)
            }, 0, r);
            layout.Controls.Add(c, 1, r);
        }

        Field("Username", _user, 1);
        Field("Password", _pass, 2);
        Field("2FA code", _totp, 3);

        layout.Controls.Add(_status, 0, 4);
        layout.SetColumnSpan(_status, 2);

        var buttons = new FlowLayoutPanel
        {
            FlowDirection = FlowDirection.RightToLeft,
            Dock = DockStyle.Fill,
            WrapContents = false,
            Margin = new Padding(0, 8, 0, 0)
        };
        var ok = new Button { Text = "Login", Width = 90, DialogResult = DialogResult.None };
        var cancel = new Button { Text = "Cancel", Width = 90, DialogResult = DialogResult.Cancel };
        ok.Click += async (_, _) => await DoLoginAsync();
        buttons.Controls.Add(ok);
        buttons.Controls.Add(cancel);
        layout.Controls.Add(buttons, 0, 5);
        layout.SetColumnSpan(buttons, 2);

        _user.Text = "admin";
        Controls.Add(layout);
        AcceptButton = ok;
        CancelButton = cancel;

        Shown += async (_, _) => await EnsureBackendAsync();
    }

    private async Task EnsureBackendAsync()
    {
        _status.ForeColor = Color.DimGray;
        _status.Text = "Checking Server Manager services…";
        try
        {
            var (ok, message) = await BackendBootstrap.EnsureRunningAsync(_api, s =>
            {
                if (IsDisposed) return;
                BeginInvoke(() =>
                {
                    _status.ForeColor = Color.DimGray;
                    _status.Text = s;
                });
            });
            _backendReady = ok;
            _status.ForeColor = ok ? Color.ForestGreen : Color.Firebrick;
            _status.Text = ok ? "Services ready — sign in." : message;
        }
        catch (Exception ex)
        {
            _backendReady = false;
            _status.ForeColor = Color.Firebrick;
            _status.Text = ex.Message;
        }
    }

    private async Task DoLoginAsync()
    {
        _status.ForeColor = Color.DimGray;
        _status.Text = "Checking services…";
        try
        {
            var (ready, message) = await BackendBootstrap.EnsureRunningAsync(_api, s =>
            {
                if (IsDisposed) return;
                BeginInvoke(() =>
                {
                    _status.ForeColor = Color.DimGray;
                    _status.Text = s;
                });
            });
            _backendReady = ready;
            if (!ready)
            {
                _status.ForeColor = Color.Firebrick;
                _status.Text = message;
                return;
            }
        }
        catch (Exception ex)
        {
            _backendReady = false;
            _status.ForeColor = Color.Firebrick;
            _status.Text = ex.Message;
            return;
        }

        _status.ForeColor = Color.DimGray;
        _status.Text = "Signing in…";
        try
        {
            var (ok, error, needs2fa) = await _api.LoginAsync(_user.Text.Trim(), _pass.Text, string.IsNullOrWhiteSpace(_totp.Text) ? null : _totp.Text.Trim());
            if (needs2fa)
            {
                _status.ForeColor = Color.DarkOrange;
                _status.Text = "Enter your 2FA code.";
                _totp.Focus();
                return;
            }
            if (!ok)
            {
                _status.ForeColor = Color.Firebrick;
                _status.Text = error ?? "Login failed";
                return;
            }
            DialogResult = DialogResult.OK;
            Close();
        }
        catch (HttpRequestException ex)
        {
            _backendReady = false;
            _status.ForeColor = Color.Firebrick;
            _status.Text = "Cannot reach Web API:\n" + ex.Message;
        }
        catch (Exception ex)
        {
            _status.ForeColor = Color.Firebrick;
            _status.Text = ex.Message;
        }
    }
}
