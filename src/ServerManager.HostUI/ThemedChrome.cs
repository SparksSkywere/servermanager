using System.Runtime.InteropServices;

namespace ServerManager.HostUI;

/// <summary>GroupBox replacement that paints face + border from UiTheme (no white chrome).</summary>
internal sealed class ThemedSectionPanel : Panel
{
    private string _title = "";

    public ThemedSectionPanel()
    {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw | ControlStyles.UserPaint, true);
        Padding = new Padding(10, 24, 10, 10);
        BackColor = UiTheme.FormBack;
        ForeColor = UiTheme.FormFore;
    }

    public string Title
    {
        get => _title;
        set
        {
            _title = value ?? "";
            Invalidate();
        }
    }

    /// <summary>Compat with GroupBox.Text usage sites.</summary>
    public override string Text
    {
        get => Title;
        set => Title = value ?? "";
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics;
        g.Clear(UiTheme.FormBack);

        var borderRect = new Rectangle(1, 10, Math.Max(0, Width - 3), Math.Max(0, Height - 12));
        using (var face = new SolidBrush(UiTheme.FormBack))
            g.FillRectangle(face, ClientRectangle);
        using (var pen = new Pen(UiTheme.Border))
            g.DrawRectangle(pen, borderRect);

        if (!string.IsNullOrWhiteSpace(_title))
        {
            var size = TextRenderer.MeasureText(g, _title, Font);
            var titleRect = new Rectangle(14, 1, size.Width + 6, size.Height);
            using (var bg = new SolidBrush(UiTheme.FormBack))
                g.FillRectangle(bg, titleRect);
            TextRenderer.DrawText(g, _title, Font, titleRect, UiTheme.FormFore,
                TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix);
        }
    }

    protected override void OnPaintBackground(PaintEventArgs e)
    {
        // fully handled in OnPaint
    }
}

/// <summary>Fills only the unused ListView header strip past the last column.</summary>
internal sealed class ListViewHeaderThemer : NativeWindow
{
    private ListView? _list;
    private readonly EventHandler _onHandle;

    public ListViewHeaderThemer()
    {
        _onHandle = (_, _) => Attach();
    }

    public void Hook(ListView list)
    {
        if (_list is not null)
            _list.HandleCreated -= _onHandle;
        _list = list;
        list.HandleCreated += _onHandle;
        if (list.IsHandleCreated)
            Attach();
    }

    private void Attach()
    {
        if (_list is null || !_list.IsHandleCreated) return;
        var header = SendMessage(_list.Handle, LvmGetHeader, IntPtr.Zero, IntPtr.Zero);
        if (header == IntPtr.Zero) return;
        if (Handle == header) return;
        ReleaseHandle();
        AssignHandle(header);
    }

    protected override void WndProc(ref Message m)
    {
        base.WndProc(ref m);

        // Only patch the trailing gap after the header has painted columns
        if (m.Msg is WmPaint or WmSize or WmEraseBkgnd)
            PaintGapOnly();
    }

    private void PaintGapOnly()
    {
        if (_list is null || Handle == IntPtr.Zero) return;
        var filled = 0;
        foreach (ColumnHeader col in _list.Columns)
            filled += col.Width;
        GetClientRect(Handle, out var rc);
        var width = rc.Right - rc.Left;
        var height = rc.Bottom - rc.Top;
        if (filled >= width) return;

        using var g = Graphics.FromHwnd(Handle);
        using var brush = new SolidBrush(UiTheme.HeaderBack);
        g.FillRectangle(brush, filled, 0, width - filled, height);
        using var pen = new Pen(UiTheme.Border);
        g.DrawLine(pen, filled, height - 1, width, height - 1);
    }

    private const int LvmGetHeader = 0x101F;
    private const int WmEraseBkgnd = 0x0014;
    private const int WmPaint = 0x000F;
    private const int WmSize = 0x0005;

    [DllImport("user32.dll")]
    private static extern IntPtr SendMessage(IntPtr hWnd, int msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool GetClientRect(IntPtr hWnd, out RECT lpRect);

    [StructLayout(LayoutKind.Sequential)]
    private struct RECT
    {
        public int Left, Top, Right, Bottom;
    }
}
