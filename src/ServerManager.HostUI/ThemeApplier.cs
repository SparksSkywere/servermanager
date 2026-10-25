using System.Runtime.CompilerServices;

namespace ServerManager.HostUI;

/// <summary>Active theme colors for HostUI chrome, list rows, and metric cards.</summary>
internal static class UiTheme
{
    public static string CurrentId { get; private set; } = ThemeCatalog.SystemId;
    public static bool IsDark { get; private set; }
    public static Color FormBack { get; private set; } = SystemColors.Control;
    public static Color FormFore { get; private set; } = SystemColors.ControlText;
    public static Color ControlBack { get; private set; } = SystemColors.Window;
    public static Color ControlFore { get; private set; } = SystemColors.WindowText;
    public static Color ElevatedBack { get; private set; } = SystemColors.ControlLightLight;
    public static Color CategoryBack { get; private set; } = Color.FromArgb(245, 247, 250);
    public static Color CategoryFore { get; private set; } = Color.FromArgb(40, 50, 70);
    public static Color RunningFore { get; private set; } = Color.DarkGreen;
    public static Color StoppedFore { get; private set; } = SystemColors.WindowText;
    public static Color OkFore { get; private set; } = Color.DarkGreen;
    public static Color ErrFore { get; private set; } = Color.Firebrick;
    public static Color SparkBack { get; private set; } = Color.FromArgb(250, 250, 252);
    public static Color MenuBack { get; private set; } = SystemColors.Control;
    public static Color StatusBack { get; private set; } = SystemColors.Control;
    public static Color HeaderBack { get; private set; } = SystemColors.Control;
    public static Color HeaderFore { get; private set; } = SystemColors.ControlText;
    public static Color HoverBack { get; private set; } = SystemColors.ControlLight;
    public static Color HighlightBack { get; private set; } = SystemColors.Highlight;
    public static Color HighlightFore { get; private set; } = SystemColors.HighlightText;
    public static Color Border { get; private set; } = SystemColors.ControlDark;
    public static Color MetaFore { get; private set; } = SystemColors.GrayText;
    public static Color TabInactive { get; private set; } = SystemColors.ControlDark;

    public static void ApplyPalette(ThemePalette p)
    {
        CurrentId = p.Id;
        IsDark = p.IsDark;
        FormBack = p.Face;
        FormFore = p.Ink;
        ControlBack = p.Window;
        ControlFore = p.Ink;
        ElevatedBack = p.Elevated;
        CategoryBack = p.CategoryBack;
        CategoryFore = p.Ink;
        RunningFore = p.RunningFore;
        StoppedFore = p.Ink;
        OkFore = p.IsDark ? Color.FromArgb(120, 220, 140) : Color.DarkGreen;
        ErrFore = p.IsDark ? Color.FromArgb(255, 120, 120) : Color.Firebrick;
        SparkBack = p.Elevated;
        MenuBack = p.MenuBar;
        StatusBack = p.StatusBar;
        HeaderBack = p.HeaderBack;
        HeaderFore = p.Ink;
        HoverBack = p.Hover;
        HighlightBack = p.Highlight;
        HighlightFore = p.HighlightText;
        Border = p.Border;
        MetaFore = p.MetaText;
        TabInactive = p.CategoryBack;
    }
}

internal static class ThemeApplier
{
    public static void Apply(string? theme)
    {
        var palette = ThemeCatalog.Resolve(theme);
        UiTheme.ApplyPalette(palette);

        foreach (Form form in Application.OpenForms)
        {
            ApplyToControl(form);
            NativeTheme.ApplyToTree(form);
            if (form.IsHandleCreated)
                WindowChrome.Apply(form);
        }
    }

    public static void ApplyToControl(Control c)
    {
        switch (c)
        {
            case MetricCard card:
                card.ApplyTheme();
                break;
            case NetworkSparkline spark:
                spark.BackColor = UiTheme.SparkBack;
                break;
            case ServerCategoryListView scl:
                scl.BackColor = UiTheme.ControlBack;
                scl.ForeColor = UiTheme.ControlFore;
                scl.ApplyThemeColors();
                break;
            case ThemedSectionPanel section:
                section.BackColor = UiTheme.FormBack;
                section.ForeColor = UiTheme.FormFore;
                section.Invalidate();
                break;
            case ThemedTabControl themedTabs:
                themedTabs.BackColor = UiTheme.FormBack;
                themedTabs.ForeColor = UiTheme.FormFore;
                themedTabs.Invalidate();
                break;
            case ListView lv:
                lv.BackColor = UiTheme.ControlBack;
                lv.ForeColor = UiTheme.ControlFore;
                lv.BorderStyle = BorderStyle.None;
                EnsureOwnerDrawHeaders(lv);
                EnsureHeaderThemer(lv);
                break;
            case TreeView tv:
                tv.BackColor = UiTheme.ControlBack;
                tv.ForeColor = UiTheme.ControlFore;
                tv.BorderStyle = BorderStyle.None;
                break;
            case DataGridView dgv:
                ThemeDataGrid(dgv);
                break;
            case Splitter or SplitterPanel:
                c.BackColor = UiTheme.FormBack;
                c.ForeColor = UiTheme.FormFore;
                break;
            case ComboBox combo:
                EnsureThemedCombo(combo);
                break;
            case TextBox or MaskedTextBox or ListBox or NumericUpDown or RichTextBox or CheckedListBox or DomainUpDown:
                c.BackColor = UiTheme.ControlBack;
                c.ForeColor = UiTheme.ControlFore;
                break;
            case DateTimePicker dtp:
                dtp.CalendarMonthBackground = UiTheme.ControlBack;
                dtp.CalendarForeColor = UiTheme.ControlFore;
                dtp.CalendarTitleBackColor = UiTheme.HeaderBack;
                dtp.CalendarTitleForeColor = UiTheme.HeaderFore;
                dtp.BackColor = UiTheme.ControlBack;
                dtp.ForeColor = UiTheme.ControlFore;
                break;
            case Button btn:
                btn.FlatStyle = FlatStyle.Flat;
                btn.FlatAppearance.BorderColor = UiTheme.Border;
                btn.FlatAppearance.MouseOverBackColor = UiTheme.HoverBack;
                btn.FlatAppearance.MouseDownBackColor = UiTheme.HighlightBack;
                btn.BackColor = UiTheme.ElevatedBack;
                btn.ForeColor = UiTheme.FormFore;
                break;
            case StatusStrip ss:
                ss.BackColor = UiTheme.StatusBack;
                ss.ForeColor = UiTheme.FormFore;
                ss.RenderMode = ToolStripRenderMode.Professional;
                ss.Renderer = new ThemeToolStripRenderer();
                foreach (ToolStripItem item in ss.Items)
                    item.ForeColor = UiTheme.FormFore;
                break;
            case ContextMenuStrip cms:
                cms.BackColor = UiTheme.MenuBack;
                cms.ForeColor = UiTheme.FormFore;
                cms.RenderMode = ToolStripRenderMode.Professional;
                cms.Renderer = new ThemeToolStripRenderer();
                break;
            case ToolStrip ts:
                ts.BackColor = UiTheme.MenuBack;
                ts.ForeColor = UiTheme.FormFore;
                ts.RenderMode = ToolStripRenderMode.Professional;
                ts.Renderer = new ThemeToolStripRenderer();
                foreach (ToolStripItem item in ts.Items)
                {
                    item.ForeColor = UiTheme.FormFore;
                    item.BackColor = UiTheme.MenuBack;
                }
                break;
            case LinkLabel link:
                link.LinkColor = UiTheme.HighlightBack;
                link.ActiveLinkColor = UiTheme.HighlightBack;
                link.VisitedLinkColor = UiTheme.MetaFore;
                link.ForeColor = UiTheme.FormFore;
                link.BackColor = Color.Transparent;
                break;
            case Label or CheckBox or RadioButton:
                c.ForeColor = UiTheme.FormFore;
                if (c.Parent is not null)
                    c.BackColor = Color.Transparent;
                break;
            case TabControl tab:
                tab.BackColor = UiTheme.FormBack;
                tab.ForeColor = UiTheme.FormFore;
                EnsureOwnerDrawTabs(tab);
                break;
            case TabPage page:
                page.BackColor = UiTheme.FormBack;
                page.ForeColor = UiTheme.FormFore;
                break;
            case GroupBox gb:
                gb.BackColor = UiTheme.FormBack;
                gb.ForeColor = UiTheme.FormFore;
                EnsureThemedGroupBox(gb);
                break;
            case ProgressBar:
                c.BackColor = UiTheme.ElevatedBack;
                break;
            case TrackBar track:
                track.BackColor = UiTheme.FormBack;
                break;
            case PropertyGrid grid:
                grid.BackColor = UiTheme.FormBack;
                grid.LineColor = UiTheme.Border;
                grid.HelpBackColor = UiTheme.ElevatedBack;
                grid.HelpForeColor = UiTheme.FormFore;
                grid.ViewBackColor = UiTheme.ControlBack;
                grid.ViewForeColor = UiTheme.ControlFore;
                grid.CategoryForeColor = UiTheme.FormFore;
                break;
            case Form form:
                form.BackColor = UiTheme.FormBack;
                form.ForeColor = UiTheme.FormFore;
                if (form.FormBorderStyle == FormBorderStyle.FixedDialog)
                    form.FormBorderStyle = FormBorderStyle.FixedSingle;
                if (form.FormBorderStyle == FormBorderStyle.Fixed3D)
                    form.FormBorderStyle = FormBorderStyle.FixedSingle;
                if (form.IsHandleCreated)
                    WindowChrome.Apply(form);
                break;
            case Panel or SplitContainer or TableLayoutPanel or FlowLayoutPanel or UserControl or ScrollableControl:
                c.BackColor = UiTheme.FormBack;
                c.ForeColor = UiTheme.FormFore;
                break;
            default:
                try
                {
                    c.BackColor = UiTheme.FormBack;
                    c.ForeColor = UiTheme.FormFore;
                }
                catch { /* some controls reject BackColor */ }
                break;
        }

        NativeTheme.Apply(c);

        foreach (Control child in c.Controls)
            ApplyToControl(child);
    }

    private static void ThemeDataGrid(DataGridView dgv)
    {
        dgv.BackgroundColor = UiTheme.ControlBack;
        dgv.GridColor = UiTheme.Border;
        dgv.DefaultCellStyle.BackColor = UiTheme.ControlBack;
        dgv.DefaultCellStyle.ForeColor = UiTheme.ControlFore;
        dgv.DefaultCellStyle.SelectionBackColor = UiTheme.HighlightBack;
        dgv.DefaultCellStyle.SelectionForeColor = UiTheme.HighlightFore;
        dgv.ColumnHeadersDefaultCellStyle.BackColor = UiTheme.HeaderBack;
        dgv.ColumnHeadersDefaultCellStyle.ForeColor = UiTheme.HeaderFore;
        dgv.ColumnHeadersDefaultCellStyle.SelectionBackColor = UiTheme.HeaderBack;
        dgv.ColumnHeadersDefaultCellStyle.SelectionForeColor = UiTheme.HeaderFore;
        dgv.EnableHeadersVisualStyles = false;
        dgv.RowHeadersDefaultCellStyle.BackColor = UiTheme.HeaderBack;
        dgv.RowHeadersDefaultCellStyle.ForeColor = UiTheme.HeaderFore;
        dgv.AlternatingRowsDefaultCellStyle.BackColor = UiTheme.ElevatedBack;
        dgv.AlternatingRowsDefaultCellStyle.ForeColor = UiTheme.ControlFore;
    }

    private static readonly ConditionalWeakTable<ListView, object> HeaderHooked = new();
    private static readonly ConditionalWeakTable<ListView, ListViewHeaderThemer> HeaderThemers = new();
    private static readonly ConditionalWeakTable<TabControl, object> TabHooked = new();
    private static readonly ConditionalWeakTable<GroupBox, object> GroupBoxHooked = new();
    private static readonly ConditionalWeakTable<ComboBox, object> ComboHooked = new();

    private static void EnsureThemedCombo(ComboBox combo)
    {
        combo.FlatStyle = FlatStyle.Flat;
        combo.BackColor = UiTheme.ControlBack;
        combo.ForeColor = UiTheme.ControlFore;
        if (ComboHooked.TryGetValue(combo, out _)) return;
        ComboHooked.Add(combo, new object());
        combo.DrawMode = DrawMode.OwnerDrawFixed;
        combo.ItemHeight = Math.Max(18, combo.Font.Height + 4);
        combo.DrawItem += OnThemedComboDrawItem;
    }

    private static void OnThemedComboDrawItem(object? sender, DrawItemEventArgs e)
    {
        if (sender is not ComboBox combo) return;
        var selected = (e.State & DrawItemState.Selected) != 0;
        var back = selected ? UiTheme.HighlightBack : UiTheme.ControlBack;
        var fore = selected ? UiTheme.HighlightFore : UiTheme.ControlFore;
        using (var brush = new SolidBrush(back))
            e.Graphics.FillRectangle(brush, e.Bounds);

        string text;
        if (e.Index >= 0 && e.Index < combo.Items.Count)
            text = combo.GetItemText(combo.Items[e.Index]) ?? "";
        else
            text = combo.Text ?? "";

        TextRenderer.DrawText(
            e.Graphics,
            text,
            combo.Font,
            Rectangle.Inflate(e.Bounds, -3, 0),
            fore,
            TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix);
    }

    private static void EnsureHeaderThemer(ListView lv)
    {
        if (lv is ServerCategoryListView) return; // already hooked in ctor
        if (HeaderThemers.TryGetValue(lv, out _)) return;
        var themer = new ListViewHeaderThemer();
        themer.Hook(lv);
        HeaderThemers.Add(lv, themer);
    }

    private static void EnsureThemedGroupBox(GroupBox gb)
    {
        if (GroupBoxHooked.TryGetValue(gb, out _)) return;
        GroupBoxHooked.Add(gb, new object());
        gb.Paint += (_, e) =>
        {
            e.Graphics.Clear(UiTheme.FormBack);
            using var pen = new Pen(UiTheme.Border);
            var rect = new Rectangle(1, 8, Math.Max(0, gb.Width - 3), Math.Max(0, gb.Height - 10));
            e.Graphics.DrawRectangle(pen, rect);
            if (string.IsNullOrWhiteSpace(gb.Text)) return;
            var size = TextRenderer.MeasureText(e.Graphics, gb.Text, gb.Font);
            var titleRect = new Rectangle(12, 0, size.Width + 6, size.Height);
            using (var bg = new SolidBrush(UiTheme.FormBack))
                e.Graphics.FillRectangle(bg, titleRect);
            TextRenderer.DrawText(e.Graphics, gb.Text, gb.Font, titleRect, UiTheme.FormFore,
                TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPrefix);
        };
        // Force owner paint of the frame; children still paint normally
        typeof(Control).GetMethod("SetStyle", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)
            ?.Invoke(gb, new object[] { ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true });
    }

    private static void EnsureOwnerDrawHeaders(ListView lv)
    {
        if (lv is ServerCategoryListView) return;
        if (HeaderHooked.TryGetValue(lv, out _)) return;
        HeaderHooked.Add(lv, new object());
        lv.OwnerDraw = true;
        lv.DrawColumnHeader += (_, e) =>
        {
            var hot = (e.State & ListViewItemStates.Hot) != 0;
            using var bg = new SolidBrush(hot ? UiTheme.HoverBack : UiTheme.HeaderBack);
            e.Graphics.FillRectangle(bg, e.Bounds);
            using var border = new Pen(UiTheme.Border);
            e.Graphics.DrawLine(border, e.Bounds.Left, e.Bounds.Bottom - 1, e.Bounds.Right, e.Bounds.Bottom - 1);
            e.Graphics.DrawLine(border, e.Bounds.Right - 1, e.Bounds.Top, e.Bounds.Right - 1, e.Bounds.Bottom);
            TextRenderer.DrawText(
                e.Graphics,
                e.Header?.Text ?? "",
                lv.Font,
                Rectangle.Inflate(e.Bounds, -4, 0),
                UiTheme.HeaderFore,
                TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
        };
        lv.DrawItem += (_, e) => e.DrawDefault = true;
        lv.DrawSubItem += (_, e) => e.DrawDefault = true;
    }

    private static void EnsureOwnerDrawTabs(TabControl tab)
    {
        if (tab is ThemedTabControl) return;
        if (TabHooked.TryGetValue(tab, out _)) return;
        TabHooked.Add(tab, new object());
        tab.DrawMode = TabDrawMode.OwnerDrawFixed;
        tab.SizeMode = TabSizeMode.Normal;
        tab.DrawItem += (_, e) =>
        {
            if (e.Index < 0 || e.Index >= tab.TabCount) return;
            var selected = e.Index == tab.SelectedIndex;
            var bounds = e.Bounds;
            using var bg = new SolidBrush(selected ? UiTheme.ElevatedBack : UiTheme.TabInactive);
            e.Graphics.FillRectangle(bg, bounds);
            using var border = new Pen(UiTheme.Border);
            e.Graphics.DrawRectangle(border, bounds.X, bounds.Y, bounds.Width - 1, bounds.Height - 1);
            TextRenderer.DrawText(
                e.Graphics,
                tab.TabPages[e.Index].Text,
                tab.Font,
                bounds,
                UiTheme.FormFore,
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter);
        };
        // Fill white strip past the last tab after each paint
        tab.Paint += (_, e) =>
        {
            var headerH = tab.ItemSize.Height + 6;
            var left = 0;
            if (tab.TabCount > 0)
            {
                try
                {
                    var first = tab.GetTabRect(0);
                    headerH = Math.Max(headerH, first.Bottom + 2);
                    left = tab.GetTabRect(tab.TabCount - 1).Right + 1;
                }
                catch { /* ignore */ }
            }
            using var brush = new SolidBrush(UiTheme.MenuBack);
            if (left < tab.Width)
                e.Graphics.FillRectangle(brush, left, 0, tab.Width - left, headerH);
            using var pen = new Pen(UiTheme.Border);
            e.Graphics.DrawLine(pen, 0, headerH - 1, tab.Width, headerH - 1);
        };
    }

    private sealed class ThemeToolStripRenderer : ToolStripProfessionalRenderer
    {
        public ThemeToolStripRenderer() : base(new ThemeColorTable())
        {
            RoundedEdges = false;
        }

        protected override void OnRenderToolStripBackground(ToolStripRenderEventArgs e)
        {
            using var b = new SolidBrush(e.ToolStrip is StatusStrip ? UiTheme.StatusBack : UiTheme.MenuBack);
            e.Graphics.FillRectangle(b, e.AffectedBounds);
        }

        protected override void OnRenderToolStripBorder(ToolStripRenderEventArgs e)
        {
            using var pen = new Pen(UiTheme.Border);
            e.Graphics.DrawLine(pen, e.AffectedBounds.Left, e.AffectedBounds.Bottom - 1,
                e.AffectedBounds.Right, e.AffectedBounds.Bottom - 1);
        }

        protected override void OnRenderButtonBackground(ToolStripItemRenderEventArgs e)
        {
            var rect = new Rectangle(Point.Empty, e.Item.Size);
            var back = e.Item.Selected || e.Item.Pressed ? UiTheme.HoverBack : (e.ToolStrip is StatusStrip ? UiTheme.StatusBack : UiTheme.MenuBack);
            using var brush = new SolidBrush(back);
            e.Graphics.FillRectangle(brush, rect);
        }

        protected override void OnRenderMenuItemBackground(ToolStripItemRenderEventArgs e)
        {
            var rect = new Rectangle(Point.Empty, e.Item.Size);
            var pressed = e.Item.Pressed;
            var hot = e.Item.Selected;
            var back = pressed ? UiTheme.HighlightBack : hot ? UiTheme.HoverBack : UiTheme.MenuBack;
            using var brush = new SolidBrush(back);
            e.Graphics.FillRectangle(brush, rect);
            e.Item.ForeColor = pressed ? UiTheme.HighlightFore : UiTheme.FormFore;
        }

        protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e)
        {
            // Never let system black text win on dark hover/selection.
            if (e.Item is ToolStripMenuItem && e.Item.Pressed)
                e.TextColor = UiTheme.HighlightFore;
            else
                e.TextColor = UiTheme.FormFore;
            base.OnRenderItemText(e);
        }

        protected override void OnRenderSeparator(ToolStripSeparatorRenderEventArgs e)
        {
            var y = e.Item.Height / 2;
            using var pen = new Pen(UiTheme.Border);
            e.Graphics.DrawLine(pen, 4, y, e.Item.Width - 4, y);
        }

        protected override void OnRenderImageMargin(ToolStripRenderEventArgs e)
        {
            using var brush = new SolidBrush(UiTheme.ElevatedBack);
            e.Graphics.FillRectangle(brush, e.AffectedBounds);
        }
    }

    private sealed class ThemeColorTable : ProfessionalColorTable
    {
        public override Color ToolStripGradientBegin => UiTheme.MenuBack;
        public override Color ToolStripGradientMiddle => UiTheme.MenuBack;
        public override Color ToolStripGradientEnd => UiTheme.MenuBack;
        public override Color MenuStripGradientBegin => UiTheme.MenuBack;
        public override Color MenuStripGradientEnd => UiTheme.MenuBack;
        public override Color StatusStripGradientBegin => UiTheme.StatusBack;
        public override Color StatusStripGradientEnd => UiTheme.StatusBack;
        public override Color ImageMarginGradientBegin => UiTheme.ElevatedBack;
        public override Color ImageMarginGradientMiddle => UiTheme.ElevatedBack;
        public override Color ImageMarginGradientEnd => UiTheme.ElevatedBack;
        public override Color MenuItemSelected => UiTheme.HoverBack;
        public override Color MenuItemSelectedGradientBegin => UiTheme.HoverBack;
        public override Color MenuItemSelectedGradientEnd => UiTheme.HoverBack;
        public override Color MenuItemBorder => UiTheme.Border;
        public override Color MenuBorder => UiTheme.Border;
        public override Color SeparatorDark => UiTheme.Border;
        public override Color SeparatorLight => UiTheme.ElevatedBack;
        public override Color ButtonSelectedBorder => UiTheme.Border;
        public override Color ButtonSelectedGradientBegin => UiTheme.HoverBack;
        public override Color ButtonSelectedGradientMiddle => UiTheme.HoverBack;
        public override Color ButtonSelectedGradientEnd => UiTheme.HoverBack;
        public override Color ButtonPressedGradientBegin => UiTheme.HoverBack;
        public override Color ButtonPressedGradientMiddle => UiTheme.HoverBack;
        public override Color ButtonPressedGradientEnd => UiTheme.HoverBack;
        public override Color OverflowButtonGradientBegin => UiTheme.MenuBack;
        public override Color OverflowButtonGradientMiddle => UiTheme.MenuBack;
        public override Color OverflowButtonGradientEnd => UiTheme.MenuBack;
        public override Color ToolStripDropDownBackground => UiTheme.MenuBack;
        public override Color CheckBackground => UiTheme.HoverBack;
        public override Color CheckSelectedBackground => UiTheme.HighlightBack;
        public override Color RaftingContainerGradientBegin => UiTheme.MenuBack;
        public override Color RaftingContainerGradientEnd => UiTheme.MenuBack;
    }
}
