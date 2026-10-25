using ServerManager.Core.Configuration;

namespace ServerManager.Core;

public static class RuntimeUrls
{
    public static string HostRuntimeBase(ServerManagerOptions o)
        => $"http://{o.HostRuntimeHost}:{o.HostRuntimePort}";

    public static string HostRuntime(ServerManagerOptions o, string path)
    {
        if (!path.StartsWith('/')) path = "/" + path;
        return HostRuntimeBase(o) + path;
    }

    public static string WebBase(ServerManagerOptions o, bool https = false)
        => https
            ? $"https://{o.WebHost}:{o.HttpsPort}"
            : $"http://{o.WebHost}:{o.WebPort}";
}
