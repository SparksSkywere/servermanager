using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace ServerManager.HostUI;

internal sealed class ServerRow
{
    public string Name { get; set; } = "";
    public string Type { get; set; } = "";
    public string Status { get; set; } = "unknown";
    public int? Pid { get; set; }
    public string? InstallDir { get; set; }
    public string? Category { get; set; }
    public double? Cpu { get; set; }
    public double? MemoryMb { get; set; }
    public string? Uptime { get; set; }
}

internal sealed class ApiClient : IDisposable
{
    private readonly HttpClient _runtime;
    private readonly HttpClient _web;
    private static readonly JsonSerializerOptions JsonOpts = new() { PropertyNameCaseInsensitive = true };

    public string? Token { get; private set; }
    public string? Username { get; private set; }
    public bool IsAdmin { get; private set; }
    public bool IsAuthenticated => !string.IsNullOrWhiteSpace(Token);
    /// <summary>Set when Web returns 401; HostUI clears the Bearer so expired JWTs stop flooding logs.</summary>
    public bool AuthExpired { get; private set; }

    public ApiClient()
    {
        var handler = new HttpClientHandler { UseProxy = false, CheckCertificateRevocationList = false };
        _runtime = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(60), BaseAddress = new Uri(PortConfig.HostRuntimeBase) };
        _web = new HttpClient(new HttpClientHandler { UseProxy = false, CheckCertificateRevocationList = false })
        {
            Timeout = TimeSpan.FromSeconds(60),
            BaseAddress = new Uri(PortConfig.WebBase)
        };
    }

    public void Dispose()
    {
        _runtime.Dispose();
        _web.Dispose();
    }

    public Task<bool> HealthRuntimeAsync(CancellationToken ct = default)
        => ProbeAsync(_runtime, "/health", ct);

    public async Task<bool> HealthWebAsync(CancellationToken ct = default)
    {
        if (await ProbeAsync(_web, "/api/analytics/health", ct)) return true;
        return await ProbeAsync(_web, "/", ct);
    }

    private static async Task<bool> ProbeAsync(HttpClient client, string path, CancellationToken ct)
    {
        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(3));
            using var req = new HttpRequestMessage(HttpMethod.Get, path);
            using var r = await client.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, cts.Token);
            return r.IsSuccessStatusCode
                   || r.StatusCode is System.Net.HttpStatusCode.Unauthorized
                       or System.Net.HttpStatusCode.Forbidden
                       or System.Net.HttpStatusCode.NotFound;
        }
        catch
        {
            return false;
        }
    }

    public async Task<(bool Ok, string? Error, bool Needs2Fa)> LoginAsync(string user, string pass, string? totp = null, CancellationToken ct = default)
    {
        var payload = JsonSerializer.Serialize(new { username = user, password = pass, totpCode = totp });
        using var content = new StringContent(payload, Encoding.UTF8, "application/json");
        HttpResponseMessage resp;
        try
        {
            resp = await _web.PostAsync("/api/auth/login", content, ct);
        }
        catch (Exception ex)
        {
            return (false, "Cannot reach Web API: " + ex.Message, false);
        }

        var body = await resp.Content.ReadAsStringAsync(ct);
        if (string.IsNullOrWhiteSpace(body))
            return (false, $"Login failed (HTTP {(int)resp.StatusCode}).", false);

        try
        {
            using var doc = JsonDocument.Parse(body);
            var root = doc.RootElement;
            if (root.TryGetProperty("requires_2fa", out var tfa) && tfa.ValueKind == JsonValueKind.True)
                return (false, root.TryGetProperty("error", out var tfaErr) ? tfaErr.GetString() : "Two-factor code required", true);
            if (!root.TryGetProperty("success", out var ok) || ok.ValueKind != JsonValueKind.True)
                return (false, root.TryGetProperty("error", out var err) ? err.GetString() : "Login failed", false);

            Token = root.GetProperty("token").GetString();
            AuthExpired = false;
            if (root.TryGetProperty("user", out var u))
            {
                Username = u.TryGetProperty("username", out var un) ? un.GetString() : user;
                IsAdmin = u.TryGetProperty("is_admin", out var ia) && ia.GetBoolean();
            }
            ApplyBearer();
            return (true, null, false);
        }
        catch (JsonException)
        {
            return (false, $"Login failed (HTTP {(int)resp.StatusCode}): {body.Trim()[..Math.Min(180, body.Trim().Length)]}", false);
        }
    }

    public async Task<List<ServerRow>> ListServersAsync(CancellationToken ct = default)
    {
        var json = await _runtime.GetStringAsync("/api/runtime/servers", ct);
        using var doc = JsonDocument.Parse(json);
        var list = new List<ServerRow>();
        foreach (var el in doc.RootElement.EnumerateArray())
        {
            list.Add(new ServerRow
            {
                Name = Str(el, "name"),
                Type = Str(el, "type"),
                Status = Str(el, "status", "unknown"),
                Pid = IntOrNull(el, "pid"),
                InstallDir = StrOrNull(el, "installDir") ?? StrOrNull(el, "install_dir"),
                Category = StrOrNull(el, "category"),
                Cpu = DoubleOrNull(el, "cpu"),
                MemoryMb = DoubleOrNull(el, "memoryMb") ?? DoubleOrNull(el, "memory_mb"),
                Uptime = StrOrNull(el, "uptime")
            });
            var row = list[^1];
            if (!string.Equals(row.Status, "running", StringComparison.OrdinalIgnoreCase))
            {
                row.Pid = null;
                row.Cpu = null;
                row.MemoryMb = null;
                row.Uptime = null;
            }
        }
        return list;
    }

    public Task<string> PostRuntimeAsync(string path, CancellationToken ct = default)
        => PostRawAsync(_runtime, path, null, ct);

    public Task<string> PostRuntimeJsonAsync(string path, object body, CancellationToken ct = default)
        => PostRawAsync(_runtime, path, JsonSerializer.Serialize(body), ct);

    public Task<string> GetWebAsync(string path, CancellationToken ct = default)
        => GetCheckedAsync(_web, path, ct);

    public Task<string> GetRuntimeAsync(string path, CancellationToken ct = default)
        => GetCheckedAsync(_runtime, path, ct);

    private async Task<string> GetCheckedAsync(HttpClient client, string path, CancellationToken ct)
    {
        using var resp = await client.GetAsync(path, ct);
        var body = await resp.Content.ReadAsStringAsync(ct);
        if (resp.IsSuccessStatusCode) return body;
        if (resp.StatusCode == System.Net.HttpStatusCode.Unauthorized && ReferenceEquals(client, _web))
            ClearExpiredSession();
        var detail = string.IsNullOrWhiteSpace(body) ? resp.ReasonPhrase : body.Trim();
        if (detail.Length > 300) detail = detail[..300] + "…";
        throw new HttpRequestException($"HTTP {(int)resp.StatusCode} {path}: {detail}");
    }

    private void ClearExpiredSession()
    {
        AuthExpired = true;
        Token = null;
        ApplyBearer();
    }

    private void ApplyBearer()
    {
        if (string.IsNullOrWhiteSpace(Token))
            _web.DefaultRequestHeaders.Authorization = null;
        else
            _web.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", Token);
    }

    public Task<string> PostWebJsonAsync(string path, object body, CancellationToken ct = default)
        => PostRawAsync(_web, path, JsonSerializer.Serialize(body), ct);

    public Task<string> PostWebRawAsync(string path, string json, CancellationToken ct = default)
        => PostRawAsync(_web, path, json, ct);

    public Task<string> PutWebJsonAsync(string path, object body, CancellationToken ct = default)
        => PutRawAsync(_web, path, JsonSerializer.Serialize(body), ct);

    public Task<string> DeleteWebAsync(string path, CancellationToken ct = default)
        => DeleteRawAsync(_web, path, ct);

    private static async Task<string> PostRawAsync(HttpClient client, string path, string? json, CancellationToken ct)
    {
        HttpContent? content = json is null ? null : new StringContent(json, Encoding.UTF8, "application/json");
        var resp = await client.PostAsync(path, content, ct);
        return await resp.Content.ReadAsStringAsync(ct);
    }

    private static async Task<string> PutRawAsync(HttpClient client, string path, string json, CancellationToken ct)
    {
        using var content = new StringContent(json, Encoding.UTF8, "application/json");
        var resp = await client.PutAsync(path, content, ct);
        return await resp.Content.ReadAsStringAsync(ct);
    }

    private static async Task<string> DeleteRawAsync(HttpClient client, string path, CancellationToken ct)
    {
        var resp = await client.DeleteAsync(path, ct);
        return await resp.Content.ReadAsStringAsync(ct);
    }

    private static string Str(JsonElement el, string name, string fallback = "")
        => el.TryGetProperty(name, out var p) ? p.GetString() ?? fallback : fallback;

    private static string? StrOrNull(JsonElement el, string name)
        => el.TryGetProperty(name, out var p) && p.ValueKind != JsonValueKind.Null ? p.GetString() : null;

    private static int? IntOrNull(JsonElement el, string name)
    {
        if (!el.TryGetProperty(name, out var p) || p.ValueKind == JsonValueKind.Null) return null;
        if (p.TryGetInt32(out var i)) return i;
        if (p.ValueKind == JsonValueKind.String && int.TryParse(p.GetString(), out var s)) return s;
        return null;
    }

    private static double? DoubleOrNull(JsonElement el, string name)
    {
        if (!el.TryGetProperty(name, out var p) || p.ValueKind == JsonValueKind.Null) return null;
        if (p.TryGetDouble(out var d)) return d;
        if (p.ValueKind == JsonValueKind.String && double.TryParse(p.GetString(), out var s)) return s;
        return null;
    }
}
