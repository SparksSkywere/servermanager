using Microsoft.Win32;

namespace ServerManager.HostUI;

internal static class PortConfig
{
    public static int WebPort { get; private set; } = 18080;
    public static int HostRuntimePort { get; private set; } = 18091;
    public static int ClusterPort { get; private set; } = 15001;
    public static string WebHost { get; private set; } = "127.0.0.1";
    public static string HostRuntimeHost { get; private set; } = "127.0.0.1";

    public static string WebBase => $"http://{WebHost}:{WebPort}";
    public static string HostRuntimeBase => $"http://{HostRuntimeHost}:{HostRuntimePort}";

    public static void Load()
    {
        WebPort = ReadInt("ServerManager__WebPort", "WebPort", 18080);
        HostRuntimePort = ReadInt("ServerManager__HostRuntimePort", "HostRuntimePort", 18091);
        ClusterPort = ReadInt("ServerManager__ClusterPort", "ClusterPort", 15001);
        WebHost = Environment.GetEnvironmentVariable("ServerManager__WebHost") ?? "127.0.0.1";
        HostRuntimeHost = Environment.GetEnvironmentVariable("ServerManager__HostRuntimeHost") ?? "127.0.0.1";
    }

    private static int ReadInt(string envName, string regName, int fallback)
    {
        var env = Environment.GetEnvironmentVariable(envName);
        if (int.TryParse(env, out var ep)) return ep;
        try
        {
            using var key = Registry.LocalMachine.OpenSubKey(@"Software\SkywereIndustries\Servermanager");
            if (int.TryParse(key?.GetValue(regName)?.ToString(), out var rp)) return rp;
        }
        catch { /* optional */ }
        return fallback;
    }
}
