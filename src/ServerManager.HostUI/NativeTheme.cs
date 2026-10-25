using System.Runtime.InteropServices;

namespace ServerManager.HostUI;

/// <summary>
/// Applies Windows visual styles so scrollbars / edit frames follow dark/light chrome.
/// </summary>
internal static class NativeTheme
{
    [DllImport("uxtheme.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    private static extern int SetWindowTheme(IntPtr hWnd, string? pszSubAppName, string? pszSubIdList);

    private const int DwmwaUseImmersiveDarkMode = 20;
    private const int DwmwaUseImmersiveDarkModeBefore20H1 = 19;

    [DllImport("dwmapi.dll", PreserveSig = true)]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int attrValue, int attrSize);

    public static void ApplyToTree(Control root)
    {
        Apply(root);
        foreach (Control child in root.Controls)
            ApplyToTree(child);
    }

    public static void Apply(Control c)
    {
        if (c is null) return;
        if (!c.IsHandleCreated)
        {
            void OnCreated(object? s, EventArgs e)
            {
                c.HandleCreated -= OnCreated;
                Apply(c);
            }
            c.HandleCreated += OnCreated;
            return;
        }

        try
        {
            if (UiTheme.IsDark)
                SetWindowTheme(c.Handle, "DarkMode_Explorer", null);
            else
                SetWindowTheme(c.Handle, "Explorer", null);

            var useDark = UiTheme.IsDark ? 1 : 0;
            if (DwmSetWindowAttribute(c.Handle, DwmwaUseImmersiveDarkMode, ref useDark, sizeof(int)) != 0)
                DwmSetWindowAttribute(c.Handle, DwmwaUseImmersiveDarkModeBefore20H1, ref useDark, sizeof(int));
        }
        catch
        {
            // theme APIs unavailable — ignore
        }
    }
}

/// <summary>
/// TabControl that owner-draws tabs and fills the unused header strip
/// (the white bar to the right of the last tab).
/// </summary>
internal sealed class ThemedTabControl : TabControl
{
    public ThemedTabControl()
    {
        DrawMode = TabDrawMode.OwnerDrawFixed;
        SizeMode = TabSizeMode.Normal;
        ItemSize = new Size(96, 24);
        BackColor = UiTheme.FormBack;
        ForeColor = UiTheme.FormFore;
        SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
        DrawItem += OnDrawTab;
        HandleCreated += (_, _) => NativeTheme.Apply(this);
    }

    private void OnDrawTab(object? sender, DrawItemEventArgs e)
    {
        if (e.Index < 0 || e.Index >= TabCount) return;
        var selected = e.Index == SelectedIndex;
        var bounds = e.Bounds;

        // Fill tab face
        using (var bg = new SolidBrush(selected ? UiTheme.ElevatedBack : UiTheme.TabInactive))
            e.Graphics.FillRectangle(bg, bounds);

        // Selected: accent underline and open bottom edge into content (no closed box)
        if (selected)
        {
            using var accent = new Pen(UiTheme.HighlightBack, 2);
            e.Graphics.DrawLine(accent, bounds.Left + 2, bounds.Bottom - 2, bounds.Right - 3, bounds.Bottom - 2);
            using var side = new Pen(UiTheme.Border);
            e.Graphics.DrawLine(side, bounds.Left, bounds.Top, bounds.Right - 1, bounds.Top);
            e.Graphics.DrawLine(side, bounds.Left, bounds.Top, bounds.Left, bounds.Bottom - 1);
            e.Graphics.DrawLine(side, bounds.Right - 1, bounds.Top, bounds.Right - 1, bounds.Bottom - 1);
        }
        else
        {
            using var pen = new Pen(UiTheme.Border);
            e.Graphics.DrawRectangle(pen, bounds.X, bounds.Y, bounds.Width - 1, bounds.Height - 1);
        }

        TextRenderer.DrawText(
            e.Graphics,
            TabPages[e.Index].Text,
            Font,
            bounds,
            UiTheme.FormFore,
            TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix);
    }

    protected override void WndProc(ref Message m)
    {
        base.WndProc(ref m);
        if (m.Msg is 0x000F or 0x0014 or 0x0085)
            PaintChrome();
    }

    private void PaintChrome()
    {
        if (!IsHandleCreated || Width <= 0 || Height <= 0) return;
        using var g = Graphics.FromHwnd(Handle);

        var headerH = ItemSize.Height + 6;
        if (TabCount > 0)
        {
            try
            {
                var r = GetTabRect(0);
                headerH = Math.Max(headerH, r.Bottom + 2);
            }
            catch { /* ignore */ }
        }

        var left = 0;
        if (TabCount > 0)
        {
            try { left = GetTabRect(TabCount - 1).Right + 1; }
            catch { left = 0; }
        }

        using (var brush = new SolidBrush(UiTheme.MenuBack))
        {
            if (left < Width)
                g.FillRectangle(brush, left, 0, Width - left, headerH);
            g.FillRectangle(brush, 0, 0, Math.Min(4, Width), headerH);
        }

        using var pen = new Pen(UiTheme.Border);
        g.DrawLine(pen, 0, headerH - 1, Width, headerH - 1);
        g.DrawRectangle(pen, 0, 0, Width - 1, Height - 1);
    }
}
