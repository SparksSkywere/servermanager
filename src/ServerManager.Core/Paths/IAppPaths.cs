namespace ServerManager.Core.Paths;

public interface IAppPaths
{
    string Root { get; }
    string Logs { get; }
    string ComponentsLogs { get; }
    string Temp { get; }
    string Db { get; }
    string Ssl { get; }
    string Www { get; }
    string Icons { get; }
    string Config { get; }

    void EnsureDirectories();
}
