using Microsoft.Extensions.Options;
using ServerManager.Core.Configuration;

namespace ServerManager.Core.Paths;

public sealed class AppPaths : IAppPaths
{
    public AppPaths(IOptions<ServerManagerOptions> options)
    {
        var root = options.Value.RootPath;
        if (string.IsNullOrWhiteSpace(root))
        {
            root = Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "runtime");
            root = Path.GetFullPath(root);
        }

        Root = root;
        Logs = Path.Combine(Root, "logs");
        ComponentsLogs = Path.Combine(Logs, "components");
        Temp = Path.Combine(Root, "temp");
        Db = Path.Combine(Root, "db");
        Ssl = Path.Combine(Root, "ssl");
        Www = Path.Combine(Root, "www");
        Icons = Path.Combine(Root, "icons");
        Config = Path.Combine(Root, "config");
    }

    public string Root { get; }
    public string Logs { get; }
    public string ComponentsLogs { get; }
    public string Temp { get; }
    public string Db { get; }
    public string Ssl { get; }
    public string Www { get; }
    public string Icons { get; }
    public string Config { get; }

    public void EnsureDirectories()
    {
        foreach (var path in new[] { Root, Logs, ComponentsLogs, Temp, Db, Ssl, Www, Icons, Config, Path.Combine(Temp, "command_queues") })
        {
            Directory.CreateDirectory(path);
        }
    }
}
