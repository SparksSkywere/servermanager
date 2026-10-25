using Microsoft.Extensions.Configuration;
using Microsoft.Win32;

namespace ServerManager.Core.Paths;

/// <summary>
/// Resolves the runtime data root (db/logs/config) for installed and development layouts.
/// Installed layout: {app}\ServerManager.exe beside {app}\runtime\.
/// </summary>
public static class RuntimeRootResolver
{
    public static string Resolve(IConfiguration? configuration = null, string? baseDirectory = null)
    {
        baseDirectory ??= AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);

        var fromConfig = configuration?["ServerManager:RootPath"];
        if (!string.IsNullOrWhiteSpace(fromConfig))
            return Path.GetFullPath(fromConfig);

        var fromEnv = Environment.GetEnvironmentVariable("ServerManager__RootPath");
        if (!string.IsNullOrWhiteSpace(fromEnv))
            return Path.GetFullPath(fromEnv);

        // Production install: exes in {app}, data in {app}\runtime
        var besideExe = Path.Combine(baseDirectory, "runtime");
        if (Directory.Exists(besideExe))
            return Path.GetFullPath(besideExe);

        var fromRegistry = TryReadRegistryRoot();
        if (!string.IsNullOrWhiteSpace(fromRegistry) && Directory.Exists(fromRegistry))
            return Path.GetFullPath(fromRegistry);

        // Dev / publish layouts
        foreach (var candidate in new[]
                 {
                     Path.GetFullPath(Path.Combine(baseDirectory, "..", "..", "..", "runtime")), // artifacts/publish/rid
                     Path.GetFullPath(Path.Combine(baseDirectory, "..", "..", "runtime")),       // dist/rid or bin/.../net8
                     Path.GetFullPath(Path.Combine(baseDirectory, "..", "runtime")),
                 })
        {
            if (Directory.Exists(candidate))
                return candidate;
        }

        Directory.CreateDirectory(besideExe);
        return Path.GetFullPath(besideExe);
    }

    public static string? TryReadInstallPath()
    {
        try
        {
            using var key = Registry.LocalMachine.OpenSubKey(@"Software\SkywereIndustries\Servermanager");
            var install = key?.GetValue("InstallPath") as string;
            if (!string.IsNullOrWhiteSpace(install) && Directory.Exists(install))
                return Path.GetFullPath(install);
        }
        catch { /* optional */ }
        return null;
    }

    private static string? TryReadRegistryRoot()
    {
        try
        {
            using var key = Registry.LocalMachine.OpenSubKey(@"Software\SkywereIndustries\Servermanager");
            var dir = key?.GetValue("Servermanagerdir") as string;
            if (!string.IsNullOrWhiteSpace(dir))
                return dir;
        }
        catch { /* optional */ }
        return null;
    }
}
