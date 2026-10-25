using System.Text.Json;

namespace ServerManager.HostUI;

/// <summary>Python Host–parity System Information panel (header + 2×4 metric cards).</summary>
internal sealed class SystemInformationPanel : UserControl
{
    private readonly Label _machine = new() { AutoSize = true, Font = new Font(SystemFonts.MessageBoxFont!.FontFamily, 12f, FontStyle.Bold) };
    private readonly Label _os = new() { AutoSize = true };
    private readonly Label _meta = new() { AutoSize = true };
    private readonly Label _web = new() { AutoSize = true, Text = "Web Server: …" };
    private readonly Label _runtime = new() { AutoSize = true, Text = "Host Runtime: …" };
    private readonly MetricCard _cpu = new("CPU");
    private readonly MetricCard _memory = new("Memory");
    private readonly MetricCard _disk = new("Disk Space");
    private readonly NetworkMetricCard _network = new("Network");
    private readonly MetricCard _gpu = new("GPU");
    private readonly MetricCard _uptime = new("System Uptime");
    private readonly MetricCard _temp = new("Temperature");

    public SystemInformationPanel()
    {
        Dock = DockStyle.Fill;
        Padding = new Padding(4);
        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 2
        };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        var header = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            FlowDirection = FlowDirection.TopDown,
            WrapContents = false,
            Padding = new Padding(4)
        };
        header.Controls.Add(_machine);
        header.Controls.Add(_os);
        header.Controls.Add(_meta);
        header.Controls.Add(_web);
        header.Controls.Add(_runtime);

        var grid = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 4,
            Padding = new Padding(2)
        };
        for (var i = 0; i < 2; i++) grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        for (var i = 0; i < 4; i++) grid.RowStyles.Add(new RowStyle(SizeType.Percent, 25));

        grid.Controls.Add(_cpu, 0, 0);
        grid.Controls.Add(_memory, 1, 0);
        grid.Controls.Add(_disk, 0, 1);
        grid.Controls.Add(_network, 1, 1);
        grid.Controls.Add(_gpu, 0, 2);
        grid.Controls.Add(_uptime, 1, 2);
        grid.Controls.Add(_temp, 0, 3);
        grid.SetColumnSpan(_temp, 2);

        root.Controls.Add(header, 0, 0);
        root.Controls.Add(grid, 0, 1);
        Controls.Add(root);

        _machine.Text = Environment.MachineName;
        _os.Text = Environment.OSVersion.ToString();
    }

    public void SetConnectionStatus(bool webOk, bool runtimeOk, int webPort, int runtimePort)
    {
        _web.Text = $"Web Server: {(webOk ? "Connected" : "Disconnected")} (:{webPort})";
        _web.ForeColor = webOk ? UiTheme.OkFore : UiTheme.ErrFore;
        _runtime.Text = $"Host Runtime: {(runtimeOk ? "Connected" : "Disconnected")} (:{runtimePort})";
        _runtime.ForeColor = runtimeOk ? UiTheme.OkFore : UiTheme.ErrFore;
    }

    public void ApplyMetrics(JsonElement e)
    {
        if (e.TryGetProperty("machineName", out var mn)) _machine.Text = mn.GetString() ?? Environment.MachineName;
        if (e.TryGetProperty("osDescription", out var os)) _os.Text = os.GetString() ?? "";
        var ver = e.TryGetProperty("version", out var v) ? v.GetString() : "?";
        var ht = e.TryGetProperty("hostType", out var h) ? h.GetString() : "standalone";
        _meta.Text = $"Version: {ver} | Host Type: {ht}";

        if (e.TryGetProperty("cpu", out var cpu) && cpu.TryGetProperty("text", out var ct))
            _cpu.SetText(ct.GetString() ?? "");
        else if (e.TryGetProperty("cpuPercent", out var cp))
            _cpu.SetText($"Overall: {cp.GetDouble():0.0}%");

        if (e.TryGetProperty("memory", out var mem))
        {
            if (mem.TryGetProperty("text", out var mt)) _memory.SetText(mt.GetString() ?? "");
            else
            {
                var used = mem.TryGetProperty("usedGb", out var ug) ? ug.GetDouble() : 0;
                var total = mem.TryGetProperty("totalGb", out var tg) ? tg.GetDouble() : 0;
                var pct = mem.TryGetProperty("percent", out var p) ? p.GetDouble() : 0;
                _memory.SetText($"Total Usage: {used:0.0}GB / {total:0.0}GB ({pct:0.0}%)");
            }
        }

        if (e.TryGetProperty("diskText", out var dt)) _disk.SetText(dt.GetString() ?? "");
        else if (e.TryGetProperty("disk", out var disk) && disk.ValueKind != JsonValueKind.Null)
        {
            var root = disk.TryGetProperty("root", out var r) ? r.GetString() : "?";
            var used = disk.TryGetProperty("usedGb", out var ug) ? ug.GetDouble() : 0;
            var total = disk.TryGetProperty("totalGb", out var tg) ? tg.GetDouble() : 0;
            var pct = disk.TryGetProperty("percent", out var p) ? p.GetDouble() : 0;
            _disk.SetText($"{root}: {used:0.0}GB/{total:0.0}GB ({pct:0.0}%)");
        }

        if (e.TryGetProperty("network", out var net))
        {
            var sent = net.TryGetProperty("sentBps", out var s) ? s.GetDouble() : 0;
            var recv = net.TryGetProperty("recvBps", out var rv) ? rv.GetDouble() : 0;
            var text = net.TryGetProperty("text", out var nt) ? nt.GetString() : $"↑ {sent:0}  ↓ {recv:0}";
            _network.Push(sent, recv, text ?? "");
        }

        if (e.TryGetProperty("gpuText", out var gt)) _gpu.SetText(gt.GetString() ?? "GPU: N/A");
        if (e.TryGetProperty("uptimeText", out var ut)) _uptime.SetText("Uptime: " + (ut.GetString() ?? "N/A"));
        else if (e.TryGetProperty("uptimeSeconds", out var us))
            _uptime.SetText("Uptime: " + TimeSpan.FromSeconds(us.GetDouble()).ToString(@"d\d\ h\h\ m\m"));
    }

    public void SetTemperature(string text) => _temp.SetText(string.IsNullOrWhiteSpace(text) ? "Temperature sensors not available" : text);
}

internal class MetricCard : Panel
{
    protected readonly TextBox Body = new()
    {
        Multiline = true,
        ReadOnly = true,
        BorderStyle = BorderStyle.None,
        Dock = DockStyle.Fill,
        ScrollBars = ScrollBars.Vertical,
        Font = new Font("Segoe UI", 8.5f),
        BackColor = UiTheme.ControlBack,
        ForeColor = UiTheme.ControlFore
    };

    protected readonly Label TitleLabel = new()
    {
        Dock = DockStyle.Top,
        Height = 22,
        Font = new Font(SystemFonts.MessageBoxFont!.FontFamily, 9f, FontStyle.Bold),
        TextAlign = ContentAlignment.MiddleLeft,
        Padding = new Padding(4, 0, 0, 0)
    };

    public MetricCard(string title)
    {
        SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint | ControlStyles.ResizeRedraw | ControlStyles.UserPaint, true);
        Dock = DockStyle.Fill;
        Padding = new Padding(6, 4, 6, 6);
        Margin = new Padding(3);
        TitleLabel.Text = title;
        Controls.Add(Body);
        Controls.Add(TitleLabel);
        Body.Text = "Loading…";
        Paint += (_, e) =>
        {
            e.Graphics.Clear(UiTheme.ElevatedBack);
            using var pen = new Pen(UiTheme.Border);
            e.Graphics.DrawRectangle(pen, 0, 0, Width - 1, Height - 1);
        };
        ApplyTheme();
    }

    public virtual void ApplyTheme()
    {
        BackColor = UiTheme.ElevatedBack;
        ForeColor = UiTheme.FormFore;
        TitleLabel.ForeColor = UiTheme.FormFore;
        TitleLabel.BackColor = UiTheme.ElevatedBack;
        Body.BackColor = UiTheme.ControlBack;
        Body.ForeColor = UiTheme.ControlFore;
        Invalidate();
    }

    public void SetText(string text) => Body.Text = text;
}

internal sealed class NetworkMetricCard : MetricCard
{
    private readonly NetworkSparkline _spark = new() { Dock = DockStyle.Top, Height = 72 };
    private readonly Label _summary = new() { Dock = DockStyle.Bottom, Height = 22, AutoSize = false };

    public NetworkMetricCard(string title) : base(title)
    {
        Controls.Clear();
        Controls.Add(Body);
        Controls.Add(_summary);
        Controls.Add(_spark);
        Controls.Add(TitleLabel);
        Body.Visible = false;
        _summary.Text = "Loading network graph…";
        ApplyTheme();
    }

    public override void ApplyTheme()
    {
        base.ApplyTheme();
        _summary.ForeColor = UiTheme.FormFore;
        _summary.BackColor = UiTheme.FormBack;
        _spark.BackColor = UiTheme.SparkBack;
    }

    public void Push(double sentBps, double recvBps, string text)
    {
        _spark.Push(sentBps, recvBps);
        _summary.Text = text;
    }
}

internal sealed class NetworkSparkline : Panel
{
    private readonly Queue<double> _up = new();
    private readonly Queue<double> _down = new();
    private const int Capacity = 60;

    public NetworkSparkline()
    {
        DoubleBuffered = true;
        BackColor = UiTheme.SparkBack;
        Paint += (_, e) => Draw(e.Graphics);
    }

    public void Push(double up, double down)
    {
        _up.Enqueue(up);
        _down.Enqueue(down);
        while (_up.Count > Capacity) _up.Dequeue();
        while (_down.Count > Capacity) _down.Dequeue();
        Invalidate();
    }

    private void Draw(Graphics g)
    {
        g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
        var rect = ClientRectangle;
        if (rect.Width < 4 || rect.Height < 4) return;
        var up = _up.ToArray();
        var down = _down.ToArray();
        var max = Math.Max(1, Math.Max(up.DefaultIfEmpty(0).Max(), down.DefaultIfEmpty(0).Max()));
        DrawSeries(g, up, max, Color.SteelBlue, rect);
        DrawSeries(g, down, max, Color.SeaGreen, rect);
    }

    private static void DrawSeries(Graphics g, double[] data, double max, Color color, Rectangle rect)
    {
        if (data.Length < 2) return;
        using var pen = new Pen(color, 1.5f);
        var pts = new PointF[data.Length];
        for (var i = 0; i < data.Length; i++)
        {
            var x = rect.Left + i * (rect.Width - 1f) / Math.Max(1, data.Length - 1);
            var y = rect.Bottom - 2 - (float)(data[i] / max * (rect.Height - 4));
            pts[i] = new PointF(x, y);
        }
        g.DrawLines(pen, pts);
    }
}
