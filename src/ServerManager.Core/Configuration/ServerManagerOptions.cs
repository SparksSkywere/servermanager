namespace ServerManager.Core;

/// <summary>
/// Server Manager install / runtime options.
/// </summary>
public sealed class ServerManagerOptions
{
    public const string SectionName = "ServerManager";

    /// <summary>Install / data root.</summary>
    public string RootPath { get; set; } = string.Empty;

    public string RegistryPath { get; set; } = @"Software\SkywereIndustries\Servermanager";

    public string LinuxConfigPath { get; set; } = "/etc/servermanager/config.json";

    public int WebPort { get; set; } = 18080;

    public int HttpsPort { get; set; } = 18443;

    public int HostRuntimePort { get; set; } = 18091;

    public int ClusterPort { get; set; } = 15001;

    public string HostRuntimeHost { get; set; } = "127.0.0.1";

    public string WebHost { get; set; } = "127.0.0.1";

    public string HostType { get; set; } = "standalone";

    public string HostAddress { get; set; } = string.Empty;

    public bool ClusterEnabled { get; set; }

    public string SteamCmdPath { get; set; } = string.Empty;

    public string SqlType { get; set; } = "sqlite";

    public bool SslEnabled { get; set; }

    public string Profile { get; set; } = "Development";
}
