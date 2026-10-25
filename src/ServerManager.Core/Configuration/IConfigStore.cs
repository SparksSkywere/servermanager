namespace ServerManager.Core.Configuration;

public interface IConfigStore
{
    string? Get(string key);
    void Set(string key, string value);
    IReadOnlyDictionary<string, string> GetAll();
    T GetOrDefault<T>(string key, T defaultValue);
}
