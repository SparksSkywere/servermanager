namespace ServerManager.HostUI;

/// <summary>Simple sparkline chart for host metrics.</summary>
internal sealed class SparklinePanel : Panel
{
    private readonly Queue<double> _values = new();
    private readonly int _capacity;
    private readonly string _title;
    private readonly Color _line;

    public SparklinePanel(string title, Color line, int capacity = 60)
    {
        _title = title;
        _line = line;
        _capacity = capacity;
        DoubleBuffered = true;
        Height = 72;
        Dock = DockStyle.Top;
        Padding = new Padding(4);
        Margin = new Padding(0, 4, 0, 4);
    }

    public string ValueLabel { get; set; } = "";

    public void Push(double value)
    {
        _values.Enqueue(Math.Clamp(value, 0, 100));
        while (_values.Count > _capacity) _values.Dequeue();
        Invalidate();
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        var g = e.Graphics;
        g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
        using var bg = new SolidBrush(Color.FromArgb(245, 247, 250));
        g.FillRectangle(bg, ClientRectangle);
        using var titleFont = new Font(Font.FontFamily, 8f, FontStyle.Bold);
        g.DrawString($"{_title}  {ValueLabel}", titleFont, Brushes.DimGray, 4, 2);

        var pts = _values.ToArray();
        if (pts.Length < 2) return;
        var plot = new Rectangle(8, 20, Width - 16, Height - 28);
        if (plot.Width < 10 || plot.Height < 10) return;
        using var pen = new Pen(_line, 1.8f);
        var step = plot.Width / (double)(_capacity - 1);
        PointF? prev = null;
        for (var i = 0; i < pts.Length; i++)
        {
            var x = plot.Left + (float)(i * step);
            var y = plot.Bottom - (float)(pts[i] / 100.0 * plot.Height);
            var p = new PointF(x, y);
            if (prev is not null) g.DrawLine(pen, prev.Value, p);
            prev = p;
        }
        using var axis = new Pen(Color.FromArgb(210, 214, 220));
        g.DrawRectangle(axis, plot);
    }
}
