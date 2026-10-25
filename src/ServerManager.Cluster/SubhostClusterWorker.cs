using System.Text.Json;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using ServerManager.Core;
using ServerManager.Core.Configuration;

namespace ServerManager.Cluster;

/// <summary>
/// When HostType=subhost and ClusterEnabled, requests join (once) and heartbeats to the host.
/// </summary>
public sealed class SubhostClusterWorker : BackgroundService
{
    private readonly IConfigStore _cfg;
    private readonly ServerManagerOptions _options;
    private readonly IHttpClientFactory _http;
    private readonly ILogger<SubhostClusterWorker> _logger;
    private string? _nodeId;
    private string? _token;
    private bool _joinRequested;

    public SubhostClusterWorker(IConfigStore cfg, IOptions<ServerManagerOptions> options, IHttpClientFactory http, ILogger<SubhostClusterWorker> logger)
    {
        _cfg = cfg;
        _options = options.Value;
        _http = http;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        await Task.Delay(TimeSpan.FromSeconds(3), stoppingToken);
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                if (!IsSubhostEnabled())
                {
                    await Task.Delay(TimeSpan.FromSeconds(15), stoppingToken);
                    continue;
                }

                _nodeId ??= _cfg.Get("ClusterNodeId") ?? Guid.NewGuid().ToString("N");
                _cfg.Set("ClusterNodeId", _nodeId);
                _token ??= _cfg.Get("ClusterToken");

                var hostUrl = ResolveHostBaseUrl();
                if (string.IsNullOrWhiteSpace(hostUrl))
                {
                    _logger.LogWarning("Subhost mode enabled but HostAddress is empty");
                    await Task.Delay(TimeSpan.FromSeconds(20), stoppingToken);
                    continue;
                }

                var client = _http.CreateClient("cluster");
                if (string.IsNullOrWhiteSpace(_token) && !_joinRequested)
                {
                    var body = JsonSerializer.Serialize(new
                    {
                        subhostId = _nodeId,
                        machineName = Environment.MachineName,
                        address = _cfg.Get("AdvertiseAddress") ?? Environment.MachineName
                    });
                    using var content = new StringContent(body, System.Text.Encoding.UTF8, "application/json");
                    var resp = await client.PostAsync($"{hostUrl.TrimEnd('/')}/api/cluster/request-join", content, stoppingToken);
                    _joinRequested = resp.IsSuccessStatusCode;
                    _logger.LogInformation("Join request sent to {Host}: {Status}", hostUrl, resp.StatusCode);
                }

                if (string.IsNullOrWhiteSpace(_token))
                    await TryPullTokenAsync(client, hostUrl!, stoppingToken);

                if (!string.IsNullOrWhiteSpace(_token))
                {
                    var hb = JsonSerializer.Serialize(new { nodeId = _nodeId, token = _token });
                    using var content = new StringContent(hb, System.Text.Encoding.UTF8, "application/json");
                    await client.PostAsync($"{hostUrl!.TrimEnd('/')}/api/cluster/heartbeat", content, stoppingToken);
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogDebug(ex, "Subhost cluster loop error");
            }

            await Task.Delay(TimeSpan.FromSeconds(10), stoppingToken);
        }
    }

    private bool IsSubhostEnabled()
    {
        var enabled = (_cfg.Get("ClusterEnabled") ?? (_options.ClusterEnabled ? "true" : "false")) == "true";
        var role = (_cfg.Get("HostType") ?? _options.HostType).Trim();
        return enabled && role.Equals("subhost", StringComparison.OrdinalIgnoreCase);
    }

    private string? ResolveHostBaseUrl()
    {
        var addr = _cfg.Get("HostAddress") ?? _options.HostAddress;
        if (string.IsNullOrWhiteSpace(addr)) return null;
        if (addr.StartsWith("http://", StringComparison.OrdinalIgnoreCase) || addr.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
            return addr.TrimEnd('/');
        var port = _cfg.GetOrDefault("HostWebPort", _options.WebPort);
        if (int.TryParse(_cfg.Get("WebPort"), out var wp)) port = wp;
        return $"http://{addr}:{port}";
    }

    private async Task TryPullTokenAsync(HttpClient client, string hostUrl, CancellationToken ct)
    {
        try
        {
            var json = await client.GetStringAsync($"{hostUrl.TrimEnd('/')}/api/cluster/join-status/{Uri.EscapeDataString(_nodeId!)}", ct);
            using var doc = JsonDocument.Parse(json);
            if (doc.RootElement.TryGetProperty("token", out var t) && t.ValueKind == JsonValueKind.String)
            {
                var token = t.GetString();
                if (!string.IsNullOrWhiteSpace(token))
                {
                    _token = token;
                    _cfg.Set("ClusterToken", token);
                    _logger.LogInformation("Cluster join approved; token stored");
                }
            }
            else if (doc.RootElement.TryGetProperty("status", out var st) && st.GetString() == "rejected")
            {
                _joinRequested = false;
                _logger.LogWarning("Cluster join was rejected");
            }
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Join-status poll failed");
        }
    }
}
