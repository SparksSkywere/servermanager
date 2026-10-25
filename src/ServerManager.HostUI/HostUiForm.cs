namespace ServerManager.HostUI;

/// <summary>Base form that paints HostUI chrome from the active theme.</summary>
internal class HostUiForm : Form
{
    public HostUiForm()
    {
        // Per-monitor DPI scaling — SystemAware bitmap-scales and looks blurry on high-DPI screens.
        AutoScaleMode = AutoScaleMode.Dpi;
        AutoScaleDimensions = new SizeF(96f, 96f);
        BackColor = UiTheme.FormBack;
        ForeColor = UiTheme.FormFore;
        // Avoid classic Fixed3D white client edge; DWM caption/border colors apply cleanly to FixedSingle
        if (FormBorderStyle == FormBorderStyle.FixedDialog)
            FormBorderStyle = FormBorderStyle.FixedSingle;
    }

    protected override CreateParams CreateParams
    {
        get
        {
            var cp = base.CreateParams;
            // Strip WS_EX_CLIENTEDGE — native white rim around dialogs
            cp.ExStyle &= ~0x00000200;
            return cp;
        }
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        try
        {
            NormalizeBorder();
            WindowChrome.Apply(this);
            NativeTheme.Apply(this);
        }
        catch { /* optional */ }
    }

    protected override void OnLoad(EventArgs e)
    {
        try
        {
            NormalizeBorder();
            BackColor = UiTheme.FormBack;
            ForeColor = UiTheme.FormFore;
            ThemeApplier.ApplyToControl(this);
            WindowChrome.Apply(this);
            NativeTheme.ApplyToTree(this);
        }
        catch { /* theme optional */ }
        base.OnLoad(e);
    }

    protected override void OnPaintBackground(PaintEventArgs e)
    {
        e.Graphics.Clear(UiTheme.FormBack);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        // Theme-colored inner rim (never system white)
        using var pen = new Pen(UiTheme.Border);
        var r = ClientRectangle;
        if (r.Width > 1 && r.Height > 1)
            e.Graphics.DrawRectangle(pen, 0, 0, r.Width - 1, r.Height - 1);
    }

    private void NormalizeBorder()
    {
        if (FormBorderStyle == FormBorderStyle.FixedDialog)
            FormBorderStyle = FormBorderStyle.FixedSingle;
        if (FormBorderStyle == FormBorderStyle.Fixed3D)
            FormBorderStyle = FormBorderStyle.FixedSingle;
    }
}
