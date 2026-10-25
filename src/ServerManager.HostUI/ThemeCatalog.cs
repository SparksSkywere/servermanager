namespace ServerManager.HostUI;

internal sealed record ThemePickerOption(string Id, string Label)
{
    public override string ToString() => Label;
}

/// <summary>WinForms theme palette (eras inspired by Chronolog / WindowsPatchManager — HostUI-owned copy).</summary>
internal sealed class ThemePalette
{
    public required string Id { get; init; }
    public required string DisplayName { get; init; }
    public string Era { get; init; } = "";
    public bool IsDark { get; init; }

    public Color Face { get; init; }
    public Color Window { get; init; }
    public Color Elevated { get; init; }
    public Color Ink { get; init; }
    public Color Highlight { get; init; }
    public Color HighlightText { get; init; }
    public Color MenuBar { get; init; }
    public Color StatusBar { get; init; }
    public Color Hover { get; init; }
    public Color Border { get; init; }
    public Color MetaText { get; init; }
    public Color CategoryBack { get; init; }
    public Color RunningFore { get; init; }
    public Color HeaderBack { get; init; }

    public string Label => string.IsNullOrWhiteSpace(Era) ? DisplayName : $"{DisplayName}  ({Era})";
    public override string ToString() => Label;
}

internal static class ThemeCatalog
{
    public const string SystemId = "system";

    public static IReadOnlyList<ThemePalette> All { get; } =
    [
        P("win95", "Windows 95", "1995", false,
            face: C(192, 192, 192), window: C(255, 255, 255), elevated: C(255, 255, 255), ink: C(0, 0, 0),
            highlight: C(0, 0, 128), highlightText: C(255, 255, 255), menu: C(192, 192, 192), status: C(192, 192, 192),
            hover: C(224, 224, 224), border: C(0, 0, 0), meta: C(64, 64, 64), category: C(168, 168, 168),
            running: C(0, 100, 0), header: C(192, 192, 192)),
        P("win98", "Windows 98", "1998", false,
            face: C(192, 192, 192), window: C(255, 255, 255), elevated: C(255, 252, 240), ink: C(0, 0, 0),
            highlight: C(0, 0, 128), highlightText: C(255, 255, 255), menu: C(192, 192, 192), status: C(192, 192, 192),
            hover: C(224, 224, 224), border: C(0, 0, 0), meta: C(80, 80, 80), category: C(212, 208, 200),
            running: C(0, 100, 0), header: C(212, 208, 200)),
        P("win2000", "Windows 2000", "2000", false,
            face: C(212, 208, 200), window: C(255, 255, 255), elevated: C(255, 248, 231), ink: C(0, 0, 0),
            highlight: C(10, 36, 106), highlightText: C(255, 255, 255), menu: C(212, 208, 200), status: C(212, 208, 200),
            hover: C(232, 228, 216), border: C(64, 64, 64), meta: C(85, 85, 85), category: C(196, 192, 184),
            running: C(0, 100, 0), header: C(212, 208, 200)),
        P("winxp", "Windows XP", "2001", false,
            face: C(236, 233, 216), window: C(255, 255, 255), elevated: C(255, 255, 245), ink: C(0, 0, 0),
            highlight: C(49, 106, 197), highlightText: C(255, 255, 255), menu: C(236, 233, 216), status: C(236, 233, 216),
            hover: C(196, 216, 240), border: C(0, 60, 116), meta: C(80, 80, 80), category: C(200, 198, 182),
            running: C(0, 128, 0), header: C(236, 233, 216)),
        P("winvista", "Windows Vista", "2007", false,
            face: C(235, 240, 245), window: C(255, 255, 255), elevated: C(245, 248, 252), ink: C(30, 30, 30),
            highlight: C(51, 153, 255), highlightText: C(255, 255, 255), menu: C(235, 240, 245), status: C(235, 240, 245),
            hover: C(190, 220, 250), border: C(140, 160, 180), meta: C(80, 100, 120), category: C(220, 230, 240),
            running: C(0, 128, 64), header: C(220, 230, 240)),
        P("win7", "Windows 7", "2009", false,
            face: C(240, 240, 240), window: C(255, 255, 255), elevated: C(255, 253, 245), ink: C(0, 0, 0),
            highlight: C(51, 153, 255), highlightText: C(255, 255, 255), menu: C(240, 240, 240), status: C(240, 240, 240),
            hover: C(229, 241, 251), border: C(112, 112, 112), meta: C(80, 80, 80), category: C(220, 220, 220),
            running: C(0, 128, 0), header: C(240, 240, 240)),
        P("win8", "Windows 8", "2012", false,
            face: C(240, 240, 240), window: C(255, 255, 255), elevated: C(255, 255, 255), ink: C(0, 0, 0),
            highlight: C(0, 114, 198), highlightText: C(255, 255, 255), menu: C(255, 255, 255), status: C(240, 240, 240),
            hover: C(222, 236, 249), border: C(171, 171, 171), meta: C(102, 102, 102), category: C(230, 230, 230),
            running: C(16, 124, 16), header: C(240, 240, 240)),
        P("win10", "Windows 10", "2015", false,
            face: C(243, 243, 243), window: C(255, 255, 255), elevated: C(249, 249, 249), ink: C(32, 32, 32),
            highlight: C(0, 120, 215), highlightText: C(255, 255, 255), menu: C(243, 243, 243), status: C(243, 243, 243),
            hover: C(230, 240, 250), border: C(200, 200, 200), meta: C(96, 96, 96), category: C(245, 247, 250),
            running: C(16, 124, 16), header: C(243, 243, 243)),
        P("win11", "Windows 11", "2021", false,
            face: C(243, 243, 243), window: C(255, 255, 255), elevated: C(252, 252, 252), ink: C(28, 28, 28),
            highlight: C(0, 103, 192), highlightText: C(255, 255, 255), menu: C(243, 243, 243), status: C(249, 249, 249),
            hover: C(237, 237, 237), border: C(229, 229, 229), meta: C(96, 96, 96), category: C(237, 237, 237),
            running: C(16, 124, 16), header: C(243, 243, 243)),
        P("win11-dark", "Windows 11 Dark", "2021", true,
            face: C(32, 32, 32), window: C(40, 40, 40), elevated: C(45, 45, 45), ink: C(255, 255, 255),
            highlight: C(96, 205, 255), highlightText: C(0, 0, 0), menu: C(32, 32, 32), status: C(28, 28, 28),
            hover: C(55, 55, 55), border: C(60, 60, 60), meta: C(180, 180, 180), category: C(55, 55, 60),
            running: C(120, 220, 140), header: C(45, 45, 45)),
        // Simple aliases kept for older profiles
        P("light", "Light", "", false,
            face: C(240, 240, 240), window: C(255, 255, 255), elevated: C(250, 250, 250), ink: C(30, 30, 30),
            highlight: C(0, 120, 215), highlightText: C(255, 255, 255), menu: C(240, 240, 240), status: C(240, 240, 240),
            hover: C(229, 241, 251), border: C(180, 180, 180), meta: C(90, 90, 90), category: C(245, 247, 250),
            running: C(0, 100, 0), header: C(240, 240, 240)),
        P("dark", "Dark", "", true,
            face: C(32, 32, 32), window: C(45, 45, 45), elevated: C(50, 50, 50), ink: C(230, 230, 230),
            highlight: C(96, 205, 255), highlightText: C(0, 0, 0), menu: C(32, 32, 32), status: C(28, 28, 28),
            hover: C(55, 55, 55), border: C(70, 70, 70), meta: C(180, 180, 180), category: C(55, 55, 60),
            running: C(120, 220, 140), header: C(45, 45, 45))
    ];

    public static IReadOnlyList<ThemePalette> PickerThemes { get; } =
        All.Where(t => t.Id is not ("light" or "dark")).ToList();

    public static IReadOnlyList<ThemePickerOption> PickerOptions { get; } =
        new[] { new ThemePickerOption(SystemId, "System (follow Windows)") }
            .Concat(PickerThemes.Select(p => new ThemePickerOption(p.Id, p.Label)))
            .ToList();

    public static ThemePickerOption FindPickerOption(string? preference)
    {
        var id = NormalizeId(preference);
        return PickerOptions.FirstOrDefault(o => o.Id.Equals(id, StringComparison.OrdinalIgnoreCase))
               ?? PickerOptions[0];
    }

    public static string NormalizeId(string? id)
    {
        if (string.IsNullOrWhiteSpace(id)) return SystemId;
        var t = id.Trim();
        if (t.Equals(SystemId, StringComparison.OrdinalIgnoreCase)) return SystemId;
        if (t.Equals("Light", StringComparison.OrdinalIgnoreCase)) return "win10";
        if (t.Equals("Dark", StringComparison.OrdinalIgnoreCase)) return "win11-dark";
        return All.FirstOrDefault(p => p.Id.Equals(t, StringComparison.OrdinalIgnoreCase))?.Id ?? SystemId;
    }

    public static ThemePalette Resolve(string? preference)
    {
        var id = NormalizeId(preference);
        if (id == SystemId)
            id = IsSystemDark() ? "win11-dark" : "win11";
        return All.FirstOrDefault(p => p.Id.Equals(id, StringComparison.OrdinalIgnoreCase))
               ?? All.First(p => p.Id == "win11");
    }

    public static bool IsSystemDark()
    {
        try
        {
            using var key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(
                @"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize");
            var v = key?.GetValue("AppsUseLightTheme");
            if (v is int i) return i == 0;
        }
        catch { /* ignore */ }
        return false;
    }

    private static Color C(int r, int g, int b) => Color.FromArgb(r, g, b);

    private static ThemePalette P(
        string id, string name, string era, bool dark,
        Color face, Color window, Color elevated, Color ink,
        Color highlight, Color highlightText, Color menu, Color status,
        Color hover, Color border, Color meta, Color category, Color running, Color header)
        => new()
        {
            Id = id,
            DisplayName = name,
            Era = era,
            IsDark = dark,
            Face = face,
            Window = window,
            Elevated = elevated,
            Ink = ink,
            Highlight = highlight,
            HighlightText = highlightText,
            MenuBar = menu,
            StatusBar = status,
            Hover = hover,
            Border = border,
            MetaText = meta,
            CategoryBack = category,
            RunningFore = running,
            HeaderBack = header
        };
}
