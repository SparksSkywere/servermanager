using System.Runtime.InteropServices;

namespace ServerManager.HostUI;

/// <summary>Win10/11 DWM title bar / caption colors to match the active theme.</summary>
internal static class WindowChrome
{
    private const int DwmwaUseImmersiveDarkModeBefore20H1 = 19;
    private const int DwmwaUseImmersiveDarkMode = 20;
    private const int DwmwaBorderColor = 34;
    private const int DwmwaCaptionColor = 35;
    private const int DwmwaTextColor = 36;
    private const int DwmwaColorDefault = unchecked((int)0xFFFFFFFF);

    [DllImport("dwmapi.dll", PreserveSig = true)]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int attrValue, int attrSize);

    public static void Apply(Form form)
    {
        if (form is null || !form.IsHandleCreated) return;
        ApplyToHwnd(form.Handle);
    }

    public static void ApplyToAllOpenForms()
    {
        foreach (Form form in Application.OpenForms)
        {
            if (!form.IsHandleCreated) continue;
            ApplyToHwnd(form.Handle);
        }
    }

    public static void ApplyToHwnd(IntPtr hwnd)
    {
        if (hwnd == IntPtr.Zero) return;
        try
        {
            var useDark = UiTheme.IsDark ? 1 : 0;
            if (DwmSetWindowAttribute(hwnd, DwmwaUseImmersiveDarkMode, ref useDark, sizeof(int)) != 0)
                DwmSetWindowAttribute(hwnd, DwmwaUseImmersiveDarkModeBefore20H1, ref useDark, sizeof(int));

            var caption = ColorToColorRef(UiTheme.MenuBack);
            var border = ColorToColorRef(UiTheme.Border);
            var text = ColorToColorRef(UiTheme.FormFore);
            DwmSetWindowAttribute(hwnd, DwmwaCaptionColor, ref caption, sizeof(int));
            DwmSetWindowAttribute(hwnd, DwmwaBorderColor, ref border, sizeof(int));
            DwmSetWindowAttribute(hwnd, DwmwaTextColor, ref text, sizeof(int));
        }
        catch
        {
            // DWM unavailable — ignore
        }
    }

    /// <summary>COLORREF is 0x00BBGGRR.</summary>
    private static int ColorToColorRef(Color c) => c.R | (c.G << 8) | (c.B << 16);
}
