using System.Drawing;
using System.Windows.Forms;

namespace ServerManager.HostUI;

/// <summary>Shared layout helpers so dialogs scale with DPI and don't crush content into the button bar.</summary>
internal static class DialogLayout
{
    public static void ApplyFormDefaults(Form form, int minWidth, int minHeight, bool allowResize = true)
    {
        form.AutoScaleMode = AutoScaleMode.Dpi;
        form.AutoScaleDimensions = new SizeF(96f, 96f);
        form.MinimumSize = new Size(minWidth, minHeight);
        if (allowResize)
        {
            form.FormBorderStyle = FormBorderStyle.Sizable;
            form.MaximizeBox = true;
        }
        form.StartPosition = form.StartPosition == FormStartPosition.Manual
            ? FormStartPosition.CenterParent
            : form.StartPosition;
    }

    /// <summary>
    /// WinForms docks in reverse z-order: non-Fill edges must be added before Fill,
    /// otherwise the button bar gets crushed under the content panel.
    /// </summary>
    public static void Host(Form form, Control fillContent, params Control[] edgeChrome)
    {
        foreach (var c in edgeChrome)
            form.Controls.Add(c);
        form.Controls.Add(fillContent);
    }

    public static FlowLayoutPanel ButtonBar(params Button[] buttons)
    {
        var bar = new FlowLayoutPanel
        {
            Dock = DockStyle.Bottom,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            FlowDirection = FlowDirection.RightToLeft,
            Padding = new Padding(12, 8, 12, 10),
            WrapContents = true,
            MinimumSize = new Size(0, 48)
        };
        foreach (var b in buttons)
        {
            b.AutoSize = true;
            b.MinimumSize = new Size(90, 28);
            b.Margin = new Padding(6, 4, 0, 4);
            bar.Controls.Add(b);
        }
        return bar;
    }

    public static TableLayoutPanel ScrollableStack(params Control[] rows)
    {
        var panel = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            AutoScroll = true,
            Padding = new Padding(12),
            GrowStyle = TableLayoutPanelGrowStyle.AddRows
        };
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        foreach (var row in rows)
        {
            row.Dock = DockStyle.Top;
            row.Anchor = AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Top;
            panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            panel.Controls.Add(row);
        }
        return panel;
    }

    public static Control LabeledRow(string label, Control field, int labelWidth = 160, int rowHeight = 34)
    {
        field.Dock = DockStyle.Fill;
        var wrap = new TableLayoutPanel
        {
            ColumnCount = 2,
            Height = rowHeight,
            Dock = DockStyle.Top,
            Margin = new Padding(0, 4, 0, 4),
            MinimumSize = new Size(0, rowHeight)
        };
        wrap.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, labelWidth));
        wrap.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        wrap.Controls.Add(new Label
        {
            Text = label,
            AutoSize = true,
            Anchor = AnchorStyles.Left,
            Margin = new Padding(0, 8, 8, 0)
        }, 0, 0);
        wrap.Controls.Add(field, 1, 0);
        return wrap;
    }

    public static Control CheckRow(CheckBox box, int indent = 160)
    {
        var wrap = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            WrapContents = true,
            Padding = new Padding(indent, 4, 0, 4),
            Margin = new Padding(0, 2, 0, 2)
        };
        box.AutoSize = true;
        wrap.Controls.Add(box);
        return wrap;
    }

    public static Control ButtonRow(int indent, params Button[] buttons)
    {
        var wrap = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            WrapContents = true,
            Padding = new Padding(indent, 8, 0, 4),
            Margin = new Padding(0, 4, 0, 4)
        };
        foreach (var b in buttons)
        {
            b.AutoSize = true;
            b.MinimumSize = new Size(100, 28);
            b.Margin = new Padding(0, 0, 8, 4);
            wrap.Controls.Add(b);
        }
        return wrap;
    }
}
