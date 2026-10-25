using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using ServerManager.Core.Configuration;
using ServerManager.Data;
using ServerManager.Data.Entities;

namespace ServerManager.Steam;

public sealed class SteamAppIdScanner
{
    // Valve removed ISteamApps/GetAppList; IStoreService/GetAppList requires a Web API key.
    private const string StoreAppListUrl = "https://api.steampowered.com/IStoreService/GetAppList/v1/";
    private const int MaxDedicatedServers = 8_000;
    private const int PageSize = 50_000;

    private readonly SteamCatalogDbContext _db;
    private readonly IHttpClientFactory _http;
    private readonly IConfigStore _cfg;
    private readonly ILogger<SteamAppIdScanner> _logger;

    public SteamAppIdScanner(
        SteamCatalogDbContext db,
        IHttpClientFactory http,
        IConfigStore cfg,
        ILogger<SteamAppIdScanner> logger)
    {
        _db = db;
        _http = http;
        _cfg = cfg;
        _logger = logger;
    }

    public async Task<int> UpsertAsync(IEnumerable<(int AppId, string Name)> apps, CancellationToken ct = default)
    {
        var count = 0;
        foreach (var (appId, name) in apps)
        {
            var existing = await _db.SteamApps.FirstOrDefaultAsync(a => a.AppId == appId, ct);
            if (existing is null)
            {
                _db.SteamApps.Add(new SteamAppCatalogEntry
                {
                    AppId = appId,
                    Name = name,
                    Type = "server",
                    IsServer = true,
                    IsDedicatedServer = true,
                    AnonymousInstall = true,
                    LastUpdated = DateTime.UtcNow,
                    Source = "steam"
                });
                count++;
            }
            else if (existing.Name != name)
            {
                existing.Name = name;
                existing.IsDedicatedServer = true;
                existing.IsServer = true;
                existing.LastUpdated = DateTime.UtcNow;
                count++;
            }
            else if (!existing.IsDedicatedServer)
            {
                existing.IsDedicatedServer = true;
                existing.IsServer = true;
                existing.LastUpdated = DateTime.UtcNow;
                count++;
            }
        }
        await _db.SaveChangesAsync(ct);
        _logger.LogInformation("Steam catalog upserted {Count} changes", count);
        return count;
    }

    /// <summary>
    /// Downloads the Steam store app list (paginated), filters names containing "Dedicated Server", and upserts matches.
    /// </summary>
    public async Task<int> RefreshDedicatedServersAsync(CancellationToken ct = default)
    {
        var key = (_cfg.Get("SteamWebApiKey") ?? "").Trim();
        if (string.IsNullOrWhiteSpace(key))
        {
            throw new InvalidOperationException(
                "Steam Web API key required. Valve removed ISteamApps/GetAppList. " +
                "Set SteamWebApiKey under Settings → Steam (free key: https://steamcommunity.com/dev/apikey).");
        }

        var client = _http.CreateClient("steam");
        client.Timeout = TimeSpan.FromMinutes(10);

        var dedicated = new List<(int AppId, string Name)>();
        var seen = new HashSet<int>();
        uint lastAppId = 0;
        var page = 0;
        var haveMore = true;

        _logger.LogInformation("Downloading Steam app list via IStoreService/GetAppList");

        while (haveMore)
        {
            page++;
            var url =
                $"{StoreAppListUrl}?key={Uri.EscapeDataString(key)}" +
                "&include_games=true&include_dlc=false&include_software=true" +
                "&include_videos=false&include_hardware=false" +
                $"&max_results={PageSize}&last_appid={lastAppId}";

            using var response = await client.GetAsync(url, ct);
            if (!response.IsSuccessStatusCode)
            {
                var body = await response.Content.ReadAsStringAsync(ct);
                throw new InvalidOperationException(
                    $"Steam IStoreService/GetAppList failed: {(int)response.StatusCode} {response.ReasonPhrase}. {Truncate(body, 200)}");
            }

            await using var stream = await response.Content.ReadAsStreamAsync(ct);
            using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: ct);

            if (!doc.RootElement.TryGetProperty("response", out var resp))
            {
                _logger.LogWarning("Steam store app list missing response object (page {Page})", page);
                break;
            }

            if (resp.TryGetProperty("apps", out var apps) && apps.ValueKind == JsonValueKind.Array)
            {
                foreach (var app in apps.EnumerateArray())
                {
                    var name = app.TryGetProperty("name", out var n) ? n.GetString() : null;
                    if (string.IsNullOrWhiteSpace(name)) continue;
                    var appId = app.TryGetProperty("appid", out var idEl) && idEl.TryGetInt32(out var id) ? id : 0;
                    if (appId <= 0) continue;
                    lastAppId = (uint)appId;

                    if (name.IndexOf("Dedicated Server", StringComparison.OrdinalIgnoreCase) < 0)
                        continue;
                    if (!seen.Add(appId)) continue;
                    dedicated.Add((appId, name));
                    if (dedicated.Count >= MaxDedicatedServers) break;
                }
            }

            haveMore = resp.TryGetProperty("have_more_results", out var more) && more.ValueKind == JsonValueKind.True;
            if (resp.TryGetProperty("last_appid", out var lastEl) && lastEl.TryGetUInt32(out var lastFromApi))
                lastAppId = lastFromApi;

            _logger.LogInformation(
                "Steam store app list page {Page}: last_appid={Last}, dedicated_so_far={Count}, more={More}",
                page, lastAppId, dedicated.Count, haveMore);

            if (dedicated.Count >= MaxDedicatedServers)
                break;
            if (page > 200)
            {
                _logger.LogWarning("Steam store app list pagination stopped after {Page} pages", page);
                break;
            }
        }

        _logger.LogInformation(
            "Steam dedicated-server filter matched {Count} apps (cap {Cap})",
            dedicated.Count, MaxDedicatedServers);
        var upserted = await UpsertAsync(dedicated, ct);
        _logger.LogInformation(
            "Steam dedicated-server refresh complete: matched={Matched}, upserted={Upserted}",
            dedicated.Count, upserted);
        return dedicated.Count;
    }

    private static string Truncate(string s, int max)
        => string.IsNullOrEmpty(s) ? "" : s.Length <= max ? s : s[..max] + "…";
}
