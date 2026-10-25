using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace ServerManager.Core.Configuration;

/// <summary>Composite: registry (Windows) + file fallback so Linux works and local overrides apply.</summary>
public sealed class CompositeConfigStore : IConfigStore
{
    private readonly IConfigStore _primary;
    private readonly IConfigStore _secondary;
    private readonly ILogger<CompositeConfigStore> _logger;

    public CompositeConfigStore(
        WindowsRegistryConfigStore registry,
        FileConfigStore file,
        IOptions<ServerManagerOptions> options,
        ILogger<CompositeConfigStore> logger)
    {
        _logger = logger;
        if (OperatingSystem.IsWindows())
        {
            _primary = registry;
            _secondary = file;
        }
        else
        {
            _primary = file;
            _secondary = file;
        }

        SeedDefaults(options.Value);
    }

    public string? Get(string key) => _primary.Get(key) ?? _secondary.Get(key);

    public void Set(string key, string value)
    {
        _primary.Set(key, value);
        _secondary.Set(key, value);
    }

    public IReadOnlyDictionary<string, string> GetAll()
    {
        var merged = new Dictionary<string, string>(_secondary.GetAll(), StringComparer.OrdinalIgnoreCase);
        foreach (var kv in _primary.GetAll())
            merged[kv.Key] = kv.Value;
        return merged;
    }

    public T GetOrDefault<T>(string key, T defaultValue)
    {
        var raw = Get(key);
        if (raw is null) return defaultValue;
        try
        {
            return (T)Convert.ChangeType(raw, typeof(T));
        }
        catch
        {
            return defaultValue;
        }
    }

    private void SeedDefaults(ServerManagerOptions options)
    {
        void Ensure(string key, string value)
        {
            if (string.IsNullOrEmpty(Get(key)))
            {
                Set(key, value);
                _logger.LogDebug("Seeded config {Key}={Value}", key, value);
            }
        }

        if (!string.IsNullOrWhiteSpace(options.RootPath))
            Ensure("Servermanagerdir", options.RootPath);
        Ensure("WebPort", options.WebPort.ToString());
        Ensure("HostRuntimePort", options.HostRuntimePort.ToString());
        Ensure("ClusterPort", options.ClusterPort.ToString());
        Ensure("HostType", options.HostType);
        Ensure("ClusterEnabled", options.ClusterEnabled ? "true" : "false");
        Ensure("SQLType", options.SqlType);
        if (!string.IsNullOrWhiteSpace(options.SteamCmdPath))
            Ensure("SteamCmdPath", options.SteamCmdPath);
    }
}
