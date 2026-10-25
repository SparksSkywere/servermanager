using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using ServerManager.Core.Configuration;
using ServerManager.Core.Paths;
using ServerManager.Data;

namespace ServerManager.Minecraft;

public sealed class ModdedCatalogScanner
{
    private readonly IHttpClientFactory _http;
    private readonly IAppPaths _paths;
    private readonly IConfigStore _cfg;
    private readonly ModdedCatalogDbContext _db;
    private readonly ILogger<ModdedCatalogScanner> _logger;

    public ModdedCatalogScanner(
        IHttpClientFactory http,
        IAppPaths paths,
        IConfigStore cfg,
        ModdedCatalogDbContext db,
        ILogger<ModdedCatalogScanner> logger)
    {
        _http = http;
        _paths = paths;
        _cfg = cfg;
        _db = db;
        _logger = logger;
    }

    public string CatalogPath(string provider) =>
        Path.Combine(_paths.Db, "catalog", $"{provider.Trim().ToLowerInvariant()}.json");

    public async Task<(int Count, string Message)> RefreshAsync(string provider, CancellationToken ct = default)
    {
        provider = (provider ?? "").Trim().ToLowerInvariant();
        return provider switch
        {
            "modrinth" => await RefreshModrinthAsync(ct),
            "curseforge" => await RefreshCurseForgeAsync(apiKey: null, ct),
            "technic" => await RefreshTechnicAsync(ct),
            "ftb" => await RefreshFtbAsync(ct),
            "atlauncher" => await RefreshAtLauncherAsync(ct),
            _ => (0, $"Unknown modded provider '{provider}'")
        };
    }

    public Task<(int Count, string Message)> RefreshAsync(string provider, string? apiKey, CancellationToken ct = default)
    {
        provider = (provider ?? "").Trim().ToLowerInvariant();
        if (provider == "curseforge")
            return RefreshCurseForgeAsync(apiKey, ct);
        return RefreshAsync(provider, ct);
    }

    public async Task<(int Count, string Message)> RefreshModrinthAsync(CancellationToken ct = default)
    {
        try
        {
            var client = _http.CreateClient("minecraft");
            var url = "https://api.modrinth.com/v2/search?query=modpack&limit=100&facets=" +
                      Uri.EscapeDataString("[[\"project_type:modpack\"]]");
            var json = await client.GetStringAsync(url, ct);
            using var doc = JsonDocument.Parse(json);
            var hits = doc.RootElement.TryGetProperty("hits", out var h) && h.ValueKind == JsonValueKind.Array
                ? h
                : default;
            var count = hits.ValueKind == JsonValueKind.Array ? hits.GetArrayLength() : 0;
            var payload = JsonSerializer.Serialize(new
            {
                provider = "modrinth",
                scannedAt = DateTime.UtcNow,
                count,
                packs = hits.ValueKind == JsonValueKind.Array ? hits : (object)Array.Empty<object>()
            });
            await WriteCatalogAsync("modrinth", payload, ct);
            _logger.LogInformation("Modrinth catalog wrote {Count} packs", count);
            return (count, $"Modrinth: saved {count} packs");
        }
        catch (Exception ex)
        {
            await WriteErrorStubAsync("modrinth", ex.Message, ct);
            return (0, $"Modrinth scan failed: {ex.Message}");
        }
    }

    public async Task<(int Count, string Message)> RefreshCurseForgeAsync(string? apiKey = null, CancellationToken ct = default)
    {
        apiKey ??= _cfg.Get("CurseForgeApiKey");
        if (string.IsNullOrWhiteSpace(apiKey))
        {
            await WriteErrorStubAsync("curseforge", "CurseForgeApiKey not configured", ct);
            return (0, "CurseForge: API key not configured");
        }

        try
        {
            var client = _http.CreateClient("minecraft");
            using var req = new HttpRequestMessage(HttpMethod.Get,
                "https://api.curseforge.com/v1/mods/search?gameId=432&classId=4471&pageSize=50&sortField=2&sortOrder=desc");
            req.Headers.TryAddWithoutValidation("x-api-key", apiKey);
            using var resp = await client.SendAsync(req, ct);
            var body = await resp.Content.ReadAsStringAsync(ct);
            if (!resp.IsSuccessStatusCode)
            {
                await WriteErrorStubAsync("curseforge", $"HTTP {(int)resp.StatusCode}: {Truncate(body, 200)}", ct);
                return (0, $"CurseForge scan failed: HTTP {(int)resp.StatusCode}");
            }

            using var doc = JsonDocument.Parse(body);
            var data = doc.RootElement.TryGetProperty("data", out var d) && d.ValueKind == JsonValueKind.Array
                ? d
                : default;
            var count = data.ValueKind == JsonValueKind.Array ? data.GetArrayLength() : 0;
            var payload = JsonSerializer.Serialize(new
            {
                provider = "curseforge",
                scannedAt = DateTime.UtcNow,
                count,
                packs = data.ValueKind == JsonValueKind.Array ? data : (object)Array.Empty<object>()
            });
            await WriteCatalogAsync("curseforge", payload, ct);
            _logger.LogInformation("CurseForge catalog wrote {Count} packs", count);
            return (count, $"CurseForge: saved {count} packs");
        }
        catch (Exception ex)
        {
            await WriteErrorStubAsync("curseforge", ex.Message, ct);
            return (0, $"CurseForge scan failed: {ex.Message}");
        }
    }

    public async Task<(int Count, string Message)> RefreshTechnicAsync(CancellationToken ct = default)
    {
        try
        {
            var client = _http.CreateClient("minecraft");
            var json = await client.GetStringAsync("https://api.technicpack.net/api/trending?limit=50", ct);
            using var doc = JsonDocument.Parse(json);
            var packs = NormalizeArray(doc.RootElement, "packs", "modpacks", "data");
            var count = packs.ValueKind == JsonValueKind.Array ? packs.GetArrayLength() : 0;
            var payload = JsonSerializer.Serialize(new
            {
                provider = "technic",
                scannedAt = DateTime.UtcNow,
                count,
                packs = packs.ValueKind == JsonValueKind.Array ? packs : (object)Array.Empty<object>()
            });
            await WriteCatalogAsync("technic", payload, ct);
            return (count, $"Technic: saved {count} packs");
        }
        catch (Exception ex)
        {
            await WriteErrorStubAsync("technic", ex.Message, ct);
            return (0, $"Technic scan failed: {ex.Message}");
        }
    }

    public async Task<(int Count, string Message)> RefreshFtbAsync(CancellationToken ct = default)
    {
        try
        {
            var client = _http.CreateClient("minecraft");
            var json = await client.GetStringAsync("https://api.modpacks.ch/public/modpack/all", ct);
            using var doc = JsonDocument.Parse(json);
            var packs = NormalizeArray(doc.RootElement, "packs", "modpacks", "data");
            var count = packs.ValueKind == JsonValueKind.Array ? packs.GetArrayLength() : 0;
            var payload = JsonSerializer.Serialize(new
            {
                provider = "ftb",
                scannedAt = DateTime.UtcNow,
                count,
                packs = packs.ValueKind == JsonValueKind.Array ? packs : (object)Array.Empty<object>()
            });
            await WriteCatalogAsync("ftb", payload, ct);
            return (count, $"FTB: saved {count} packs");
        }
        catch (Exception ex)
        {
            await WriteErrorStubAsync("ftb", ex.Message, ct);
            return (0, $"FTB scan failed: {ex.Message}");
        }
    }

    public async Task<(int Count, string Message)> RefreshAtLauncherAsync(CancellationToken ct = default)
    {
        try
        {
            var client = _http.CreateClient("minecraft");
            var json = await client.GetStringAsync("https://download.nodecdn.net/containers/atl/launcher/json/packsnew.json", ct);
            using var doc = JsonDocument.Parse(json);
            var packs = doc.RootElement.ValueKind == JsonValueKind.Array
                ? doc.RootElement
                : NormalizeArray(doc.RootElement, "packs", "modpacks", "data");
            var count = packs.ValueKind == JsonValueKind.Array ? packs.GetArrayLength() : 0;
            var payload = JsonSerializer.Serialize(new
            {
                provider = "atlauncher",
                scannedAt = DateTime.UtcNow,
                count,
                packs = packs.ValueKind == JsonValueKind.Array ? packs : (object)Array.Empty<object>()
            });
            await WriteCatalogAsync("atlauncher", payload, ct);
            return (count, $"ATLauncher: saved {count} packs");
        }
        catch (Exception ex)
        {
            await WriteErrorStubAsync("atlauncher", ex.Message, ct);
            return (0, $"ATLauncher scan failed: {ex.Message}");
        }
    }

    public async Task<object> ReadCatalogAsync(string provider, string? q = null, CancellationToken ct = default)
    {
        provider = (provider ?? "modrinth").Trim().ToLowerInvariant();
        var path = CatalogPath(provider);
        if (File.Exists(path))
        {
            await using var fs = File.OpenRead(path);
            using var doc = await JsonDocument.ParseAsync(fs, cancellationToken: ct);
            if (doc.RootElement.TryGetProperty("packs", out var packs) && packs.ValueKind == JsonValueKind.Array && packs.GetArrayLength() > 0)
            {
                if (string.IsNullOrWhiteSpace(q))
                    return JsonSerializer.Deserialize<object>(packs.GetRawText()) ?? Array.Empty<object>();

                var needle = q.Trim();
                using var filtered = new MemoryStream();
                await using (var writer = new Utf8JsonWriter(filtered))
                {
                    writer.WriteStartArray();
                    foreach (var pack in packs.EnumerateArray())
                    {
                        if (pack.GetRawText().Contains(needle, StringComparison.OrdinalIgnoreCase))
                            pack.WriteTo(writer);
                    }
                    writer.WriteEndArray();
                }
                return JsonSerializer.Deserialize<object>(filtered.ToArray()) ?? Array.Empty<object>();
            }
        }

        // Fall back to shipped minecraft_modded_ID.db
        try
        {
            var query = _db.Packs.AsNoTracking().Where(p => p.Launcher == provider);
            if (!string.IsNullOrWhiteSpace(q))
            {
                var needle = q.Trim();
                query = query.Where(p => p.Name.Contains(needle) || p.PackId.Contains(needle));
            }
            return await query.OrderBy(p => p.Name).Take(200)
                .Select(p => new
                {
                    id = p.PackId,
                    slug = p.PackSlug,
                    name = p.Name,
                    provider = p.Launcher,
                    mcVersion = p.McVersion,
                    modLoader = p.ModLoader,
                    version = p.PackVersion,
                    description = p.Description,
                    serverUrl = p.ServerUrl,
                    installUrl = p.InstallUrl,
                    isServerPack = p.IsServerPack
                })
                .ToListAsync(ct);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Modded SQLite catalog read failed for {Provider}", provider);
            return Array.Empty<object>();
        }
    }

    private async Task WriteCatalogAsync(string provider, string json, CancellationToken ct)
    {
        var path = CatalogPath(provider);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        await File.WriteAllTextAsync(path, json, ct);
    }

    private async Task WriteErrorStubAsync(string provider, string message, CancellationToken ct)
    {
        var payload = JsonSerializer.Serialize(new
        {
            provider,
            scannedAt = DateTime.UtcNow,
            count = 0,
            error = message,
            packs = Array.Empty<object>()
        });
        await WriteCatalogAsync(provider, payload, ct);
        _logger.LogWarning("Modded catalog {Provider} stub written: {Message}", provider, message);
    }

    private static JsonElement NormalizeArray(JsonElement root, params string[] names)
    {
        foreach (var name in names)
        {
            if (root.TryGetProperty(name, out var el) && el.ValueKind == JsonValueKind.Array)
                return el;
        }
        return root.ValueKind == JsonValueKind.Array ? root : default;
    }

    private static string Truncate(string s, int max) =>
        s.Length <= max ? s : s[..max] + "…";
}
