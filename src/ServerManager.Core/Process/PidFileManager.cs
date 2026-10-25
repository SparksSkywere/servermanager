using System.Diagnostics;
using System.Text.Json;
using ServerManager.Core.Paths;

namespace ServerManager.Core.Process;

public sealed class PidFileManager
{
    private readonly IAppPaths _paths;

    public PidFileManager(IAppPaths paths) => _paths = paths;

    public void Write(string component, int pid)
    {
        Directory.CreateDirectory(_paths.Temp);
        var payload = JsonSerializer.Serialize(new { ProcessId = pid, Component = component, WrittenAt = DateTime.UtcNow });
        File.WriteAllText(GetPath(component), payload);
    }

    public void Remove(string component)
    {
        var path = GetPath(component);
        if (File.Exists(path)) File.Delete(path);
    }

    public int? Read(string component)
    {
        var path = GetPath(component);
        if (!File.Exists(path)) return null;
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            if (doc.RootElement.TryGetProperty("ProcessId", out var pid))
                return pid.GetInt32();
        }
        catch
        {
            // ignore corrupt
        }
        return null;
    }

    public bool IsComponentRunning(string component)
    {
        var pid = Read(component);
        if (pid is null) return false;
        try
        {
            var p = System.Diagnostics.Process.GetProcessById(pid.Value);
            return !p.HasExited;
        }
        catch
        {
            Remove(component);
            return false;
        }
    }

    public int CleanupStale()
    {
        var removed = 0;
        if (!Directory.Exists(_paths.Temp)) return 0;
        foreach (var file in Directory.GetFiles(_paths.Temp, "*.pid"))
        {
            var name = Path.GetFileNameWithoutExtension(file);
            if (!IsComponentRunning(name))
            {
                try { File.Delete(file); removed++; } catch { /* ignore */ }
            }
        }
        return removed;
    }

    public bool AnyCoreComponentRunning(params string[] exclude)
    {
        var cores = new[] { "launcher", "apphost", "hostruntime", "webserver", "web" };
        foreach (var c in cores)
        {
            if (exclude.Contains(c, StringComparer.OrdinalIgnoreCase)) continue;
            if (IsComponentRunning(c)) return true;
        }
        return false;
    }

    private string GetPath(string component) => Path.Combine(_paths.Temp, $"{component.ToLowerInvariant()}.pid");
}
