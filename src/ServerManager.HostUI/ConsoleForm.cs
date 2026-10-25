using System.Runtime.InteropServices;
using System.Text.Json;

namespace ServerManager.HostUI;

internal sealed class ConsoleForm : HostUiForm
{
    private readonly ApiClient _api;
    private readonly string _server;
    private readonly TextBox _output = new()
    {
        Multiline = true,
        ReadOnly = true,
        ScrollBars = ScrollBars.Both,
        Dock = DockStyle.Fill,
        Font = new Font("Consolas", 9f),
        BackColor = Color.Black,
        ForeColor = Color.LightGreen,
        WordWrap = false
    };
    private readonly TextBox _command = new() { Dock = DockStyle.Fill };
    private readonly System.Windows.Forms.Timer _timer = new() { Interval = 1000 };
    private bool _pause;
    private int _lastSeq = -1;
    private string? _motdCommand;
    private string? _motdMessage;
    private string? _saveCommand;
    private string? _warningCommand;
    private string? _warningMessageTemplate;

    public ConsoleForm(ApiClient api, string server)
    {
        _api = api;
        _server = server;
        Text = $"Console - {server}";
        Width = 960;
        Height = 600;
        DialogLayout.ApplyFormDefaults(this, 640, 400, allowResize: true);
        StartPosition = FormStartPosition.CenterParent;

        var bottom = new TableLayoutPanel
        {
            Dock = DockStyle.Bottom,
            AutoSize = true,
            ColumnCount = 3,
            Padding = new Padding(8, 6, 8, 8)
        };
        bottom.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        bottom.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        bottom.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        bottom.RowStyles.Add(new RowStyle(SizeType.Absolute, 32));
        var send = new Button { Text = "Send", AutoSize = true, MinimumSize = new Size(80, 28), Dock = DockStyle.Fill };
        var pause = new Button { Text = "Pause Scroll", AutoSize = true, MinimumSize = new Size(110, 28), Dock = DockStyle.Fill };
        send.Click += async (_, _) => await SendAsync();
        pause.Click += (_, _) =>
        {
            _pause = !_pause;
            pause.Text = _pause ? "Resume Scroll" : "Pause Scroll";
            if (!_pause) _lastSeq = -1; // force a refresh after resume
        };
        bottom.Controls.Add(_command, 0, 0);
        bottom.Controls.Add(send, 1, 0);
        bottom.Controls.Add(pause, 2, 0);

        var bar = new ToolStrip();
        bar.Items.Add("Start", null, async (_, _) => await _api.PostRuntimeAsync($"/api/runtime/servers/{Uri.EscapeDataString(_server)}/start"));
        bar.Items.Add("Stop", null, async (_, _) => await _api.PostRuntimeAsync($"/api/runtime/servers/{Uri.EscapeDataString(_server)}/stop"));
        bar.Items.Add("Restart", null, async (_, _) => await _api.PostRuntimeAsync($"/api/runtime/servers/{Uri.EscapeDataString(_server)}/restart"));
        bar.Items.Add("Kill", null, async (_, _) => await _api.PostRuntimeAsync($"/api/runtime/servers/{Uri.EscapeDataString(_server)}/kill"));
        bar.Items.Add("Clear", null, (_, _) => { _output.Clear(); _lastSeq = -1; });
        bar.Items.Add(new ToolStripSeparator());
        bar.Items.Add("Test MOTD", null, async (_, _) => await SendConfigCommandAsync("MOTD", BuildMotdCommand()));
        bar.Items.Add("Save", null, async (_, _) => await SendConfigCommandAsync("Save", _saveCommand));
        bar.Items.Add("Warning", null, async (_, _) => await SendConfigCommandAsync("Warning", BuildWarningCommand()));

        // Top/Bottom first, Fill last — otherwise the command bar gets crushed.
        DialogLayout.Host(this, _output, bar, bottom);

        AcceptButton = send;
        _timer.Tick += async (_, _) => await PollAsync();
        Shown += async (_, _) =>
        {
            await LoadConfigCommandsAsync();
            await PollAsync();
            _timer.Start();
        };
        FormClosed += (_, _) => _timer.Stop();
    }

    private async Task LoadConfigCommandsAsync()
    {
        try
        {
            var json = await _api.GetWebAsync($"/api/servers/{Uri.EscapeDataString(_server)}");
            using var doc = JsonDocument.Parse(json);
            var e = doc.RootElement;
            _motdCommand = Str(e, "motd_command", "motdCommand");
            _motdMessage = Str(e, "motd_message", "motdMessage");
            _saveCommand = Str(e, "save_command", "saveCommand");
            _warningCommand = Str(e, "warning_command", "warningCommand");
            _warningMessageTemplate = Str(e, "warning_message_template", "warningMessageTemplate");
        }
        catch { /* optional */ }
    }

    private string? BuildMotdCommand()
    {
        if (!string.IsNullOrWhiteSpace(_motdCommand) && !string.IsNullOrWhiteSpace(_motdMessage))
        {
            if (_motdCommand!.Contains("{message}", StringComparison.OrdinalIgnoreCase))
                return _motdCommand.Replace("{message}", _motdMessage, StringComparison.OrdinalIgnoreCase);
            return $"{_motdCommand.Trim()} {_motdMessage}";
        }
        if (!string.IsNullOrWhiteSpace(_motdCommand)) return _motdCommand;
        if (!string.IsNullOrWhiteSpace(_motdMessage)) return $"say {_motdMessage}";
        return null;
    }

    private string? BuildWarningCommand()
    {
        var msg = _warningMessageTemplate;
        if (!string.IsNullOrWhiteSpace(_warningCommand) && !string.IsNullOrWhiteSpace(msg))
        {
            if (_warningCommand!.Contains("{message}", StringComparison.OrdinalIgnoreCase))
                return _warningCommand.Replace("{message}", msg, StringComparison.OrdinalIgnoreCase);
            if (_warningCommand.Contains("{minutes}", StringComparison.OrdinalIgnoreCase))
                return _warningCommand.Replace("{minutes}", "1", StringComparison.OrdinalIgnoreCase)
                    .Replace("{message}", msg ?? "", StringComparison.OrdinalIgnoreCase);
            return $"{_warningCommand.Trim()} {msg}";
        }
        if (!string.IsNullOrWhiteSpace(_warningCommand)) return _warningCommand;
        if (!string.IsNullOrWhiteSpace(msg)) return $"say {msg}";
        return null;
    }

    private async Task SendConfigCommandAsync(string label, string? cmd)
    {
        if (string.IsNullOrWhiteSpace(cmd))
        {
            MessageBox.Show(this, $"No {label} command configured for this server.", Text);
            return;
        }
        try
        {
            await _api.PostRuntimeJsonAsync($"/api/runtime/servers/{Uri.EscapeDataString(_server)}/command", new { command = cmd });
            await PollAsync();
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

    private async Task PollAsync()
    {
        try
        {
            // Larger window so the console doesn't look "stuck" on a tiny rolling buffer.
            var json = await _api.GetRuntimeAsync($"/api/runtime/servers/{Uri.EscapeDataString(_server)}/console?lines=400");
            using var doc = JsonDocument.Parse(json);
            var seq = doc.RootElement.TryGetProperty("seq", out var seqEl) && seqEl.TryGetInt32(out var s) ? s : -1;

            // Pause Scroll: skip updates entirely so reading mid-buffer isn't reset by Text replacement.
            if (_pause && seq == _lastSeq)
                return;
            if (_pause && seq != _lastSeq)
            {
                _lastSeq = seq;
                return;
            }

            if (seq >= 0 && seq == _lastSeq)
                return;

            string? text = null;
            if (doc.RootElement.TryGetProperty("lines", out var lines) && lines.ValueKind == JsonValueKind.Array)
                text = string.Join(Environment.NewLine, lines.EnumerateArray().Select(l => l.GetString()));
            else if (doc.RootElement.TryGetProperty("buffer", out var buf))
                text = buf.ToString();

            if (text is null || _output.Text == text)
            {
                _lastSeq = seq;
                return;
            }

            var stickToBottom = IsScrolledNearBottom();
            _output.Text = text;
            _lastSeq = seq;
            if (stickToBottom)
            {
                _output.SelectionStart = _output.TextLength;
                _output.ScrollToCaret();
            }

            if (doc.RootElement.TryGetProperty("status", out var st) && st.ValueKind == JsonValueKind.String)
                Text = $"Console - {_server} ({st.GetString()})";
        }
        catch (Exception ex)
        {
            Text = $"Console - {_server} ({ex.Message})";
        }
    }

    private bool IsScrolledNearBottom()
    {
        try
        {
            // Prefer scrollbar position so mouse-wheel reading mid-buffer doesn't get yanked,
            // and so we keep following when the caret was left at the end.
            if (_output.IsHandleCreated && GetScrollInfo(_output.Handle, SbVert, ref _scrollInfo))
            {
                var max = Math.Max(0, _scrollInfo.nMax - _scrollInfo.nPage);
                return max <= 0 || _scrollInfo.nPos >= max - 3;
            }
            return _output.TextLength == 0
                   || _output.SelectionStart >= Math.Max(0, _output.TextLength - 80);
        }
        catch
        {
            return true;
        }
    }

    private SCROLLINFO _scrollInfo = new() { cbSize = Marshal.SizeOf<SCROLLINFO>(), fMask = SifAll };

    private const int SbVert = 1;
    private const uint SifAll = 0x17;

    [StructLayout(LayoutKind.Sequential)]
    private struct SCROLLINFO
    {
        public int cbSize;
        public uint fMask;
        public int nMin;
        public int nMax;
        public uint nPage;
        public int nPos;
        public int nTrackPos;
    }

    [DllImport("user32.dll")]
    private static extern bool GetScrollInfo(IntPtr hwnd, int bar, ref SCROLLINFO si);

    private async Task SendAsync()
    {
        var cmd = _command.Text.Trim();
        if (string.IsNullOrEmpty(cmd)) return;
        try
        {
            await _api.PostRuntimeJsonAsync($"/api/runtime/servers/{Uri.EscapeDataString(_server)}/command", new { command = cmd });
            _command.Clear();
            _pause = false;
            await PollAsync();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
