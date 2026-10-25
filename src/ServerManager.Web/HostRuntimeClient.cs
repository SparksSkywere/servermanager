using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Options;
using ServerManager.Core;
using ServerManager.Core.Configuration;

public sealed class RuntimeServerDto
{
    public string Name { get; set; } = "";
    public string Status { get; set; } = "unknown";
}

public sealed class HostRuntimeClient
{
    private readonly HttpClient _http;
    private readonly ServerManagerOptions _options;

    public HostRuntimeClient(HttpClient http, IOptions<ServerManagerOptions> options)
    {
        _http = http;
        _options = options.Value;
        _http.BaseAddress = new Uri(RuntimeUrls.HostRuntimeBase(_options));
        _http.Timeout = TimeSpan.FromSeconds(60);
    }

    public async Task<List<RuntimeServerDto>> GetServersAsync(CancellationToken ct)
    {
        try
        {
            var json = await _http.GetStringAsync("/api/runtime/servers", ct);
            using var doc = JsonDocument.Parse(json);
            var list = new List<RuntimeServerDto>();
            foreach (var el in doc.RootElement.EnumerateArray())
            {
                list.Add(new RuntimeServerDto
                {
                    Name = el.TryGetProperty("name", out var n) ? n.GetString() ?? "" : "",
                    Status = el.TryGetProperty("status", out var s) ? s.GetString() ?? "unknown" : "unknown"
                });
            }
            return list;
        }
        catch
        {
            return new List<RuntimeServerDto>();
        }
    }

    public async Task<object?> GetAsync(string path, CancellationToken ct)
    {
        var resp = await _http.GetAsync(path, ct);
        var body = await resp.Content.ReadAsStringAsync(ct);
        return JsonSerializer.Deserialize<object>(body);
    }

    public async Task<object?> PostAsync(string path, CancellationToken ct)
    {
        var resp = await _http.PostAsync(path, null, ct);
        var body = await resp.Content.ReadAsStringAsync(ct);
        return JsonSerializer.Deserialize<object>(body);
    }

    public async Task<object?> PostJsonAsync(string path, string json, CancellationToken ct)
    {
        using var content = new StringContent(json, Encoding.UTF8, "application/json");
        var resp = await _http.PostAsync(path, content, ct);
        var body = await resp.Content.ReadAsStringAsync(ct);
        return JsonSerializer.Deserialize<object>(body);
    }
}
