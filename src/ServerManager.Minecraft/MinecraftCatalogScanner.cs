using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using ServerManager.Data;
using ServerManager.Data.Entities;

namespace ServerManager.Minecraft;

public sealed class MinecraftCatalogScanner
{
    private readonly MinecraftCatalogDbContext _db;
    private readonly IHttpClientFactory _http;
    private readonly ILogger<MinecraftCatalogScanner> _logger;

    public MinecraftCatalogScanner(MinecraftCatalogDbContext db, IHttpClientFactory http, ILogger<MinecraftCatalogScanner> logger)
    {
        _db = db;
        _http = http;
        _logger = logger;
    }

    public async Task<int> RefreshVanillaAsync(CancellationToken ct = default)
    {
        var client = _http.CreateClient("minecraft");
        client.Timeout = TimeSpan.FromMinutes(5);
        using var doc = System.Text.Json.JsonDocument.Parse(
            await client.GetStringAsync("https://launchermeta.mojang.com/mc/game/version_manifest_v2.json", ct));

        // version_id is UNIQUE — upsert by Version only (ignore ModLoader filter mismatches).
        var byVersion = await _db.Versions.ToDictionaryAsync(x => x.Version, StringComparer.OrdinalIgnoreCase, ct);
        var count = 0;
        var pending = 0;

        foreach (var v in doc.RootElement.GetProperty("versions").EnumerateArray())
        {
            var id = v.GetProperty("id").GetString();
            if (string.IsNullOrWhiteSpace(id)) continue;
            var type = v.GetProperty("type").GetString() ?? "release";

            if (!byVersion.TryGetValue(id, out var existing))
            {
                existing = new MinecraftVersionEntry
                {
                    Version = id,
                    VersionType = type,
                    ModLoader = "vanilla",
                    IsDedicatedServer = true,
                    IsRecommended = false,
                    LastUpdated = DateTime.UtcNow,
                    Source = "mojang"
                };
                _db.Versions.Add(existing);
                byVersion[id] = existing;
                count++;
                pending++;
            }
            else
            {
                var changed = false;
                if (!string.Equals(existing.VersionType, type, StringComparison.OrdinalIgnoreCase))
                {
                    existing.VersionType = type;
                    changed = true;
                }
                if (string.IsNullOrWhiteSpace(existing.ModLoader))
                {
                    existing.ModLoader = "vanilla";
                    changed = true;
                }
                if (string.IsNullOrWhiteSpace(existing.Source))
                {
                    existing.Source = "mojang";
                    changed = true;
                }
                if (changed)
                {
                    existing.LastUpdated = DateTime.UtcNow;
                    count++;
                    pending++;
                }
            }

            if (pending >= 100)
            {
                await _db.SaveChangesAsync(ct);
                pending = 0;
            }
        }

        if (pending > 0)
            await _db.SaveChangesAsync(ct);

        _logger.LogInformation("Minecraft catalog added/updated {Count} versions (total tracked {Total})", count, byVersion.Count);
        return count;
    }
}
