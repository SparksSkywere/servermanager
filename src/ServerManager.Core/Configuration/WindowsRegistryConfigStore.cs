using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Microsoft.Win32;

namespace ServerManager.Core.Configuration;

/// <summary>Windows HKLM registry adapter for Server Manager configuration.</summary>
public sealed class WindowsRegistryConfigStore : IConfigStore
{
    private readonly string _subKey;
    private readonly ILogger<WindowsRegistryConfigStore> _logger;

    public WindowsRegistryConfigStore(IOptions<ServerManagerOptions> options, ILogger<WindowsRegistryConfigStore> logger)
    {
        _subKey = options.Value.RegistryPath;
        _logger = logger;
    }

    public string? Get(string key)
    {
        if (!OperatingSystem.IsWindows()) return null;
        try
        {
            using var reg = Registry.LocalMachine.OpenSubKey(_subKey);
            return reg?.GetValue(key)?.ToString();
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Registry get failed for {Key}", key);
            return null;
        }
    }

    public void Set(string key, string value)
    {
        if (!OperatingSystem.IsWindows()) return;
        try
        {
            using var reg = Registry.LocalMachine.CreateSubKey(_subKey);
            reg?.SetValue(key, value);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Registry set failed for {Key}", key);
        }
    }

    public IReadOnlyDictionary<string, string> GetAll()
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (!OperatingSystem.IsWindows()) return result;
        try
        {
            using var reg = Registry.LocalMachine.OpenSubKey(_subKey);
            if (reg is null) return result;
            foreach (var name in reg.GetValueNames())
            {
                var v = reg.GetValue(name)?.ToString();
                if (v is not null) result[name] = v;
            }
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Registry GetAll failed");
        }
        return result;
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
}
