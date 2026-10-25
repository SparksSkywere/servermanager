using System.Text.Json;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using ServerManager.Core.Paths;

namespace ServerManager.Core.Configuration;

/// <summary>Linux / portable JSON file config under runtime/config or /etc/servermanager.</summary>
public sealed class FileConfigStore : IConfigStore
{
    private readonly string _path;
    private readonly object _lock = new();
    private Dictionary<string, string> _values = new(StringComparer.OrdinalIgnoreCase);

    public FileConfigStore(IAppPaths paths, IOptions<ServerManagerOptions> options, ILogger<FileConfigStore> logger)
    {
        var configured = options.Value.LinuxConfigPath;
        _path = OperatingSystem.IsWindows()
            ? Path.Combine(paths.Config, "servermanager.json")
            : (File.Exists(configured) ? configured : Path.Combine(paths.Config, "servermanager.json"));

        Load();
        logger.LogInformation("File config store at {Path}", _path);
    }

    public string? Get(string key)
    {
        lock (_lock)
        {
            return _values.TryGetValue(key, out var v) ? v : null;
        }
    }

    public void Set(string key, string value)
    {
        lock (_lock)
        {
            _values[key] = value;
            Save();
        }
    }

    public IReadOnlyDictionary<string, string> GetAll()
    {
        lock (_lock)
        {
            return new Dictionary<string, string>(_values, StringComparer.OrdinalIgnoreCase);
        }
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

    private void Load()
    {
        if (!File.Exists(_path))
        {
            _values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            return;
        }

        var json = File.ReadAllText(_path);
        _values = JsonSerializer.Deserialize<Dictionary<string, string>>(json)
                  ?? new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    }

    private void Save()
    {
        Directory.CreateDirectory(Path.GetDirectoryName(_path)!);
        var json = JsonSerializer.Serialize(_values, new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(_path, json);
    }
}
