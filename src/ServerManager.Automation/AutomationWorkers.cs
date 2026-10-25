using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using ServerManager.Core;
using ServerManager.Core.Configuration;
using ServerManager.Data;
using Microsoft.EntityFrameworkCore;

namespace ServerManager.Automation;

public static class AutomationServiceCollectionExtensions
{
    public static IServiceCollection AddServerManagerAutomation(this IServiceCollection services)
    {
        services.AddHostedService<MotdAutomationWorker>();
        services.AddHostedService<ScheduledUpdateWorker>();
        services.AddHttpClient("runtime");
        return services;
    }
}

public sealed class MotdAutomationWorker : BackgroundService
{
    private readonly IServiceScopeFactory _scopes;
    private readonly IHttpClientFactory _http;
    private readonly IOptions<ServerManagerOptions> _options;
    private readonly ILogger<MotdAutomationWorker> _logger;

    public MotdAutomationWorker(IServiceScopeFactory scopes, IHttpClientFactory http, IOptions<ServerManagerOptions> options, ILogger<MotdAutomationWorker> logger)
    {
        _scopes = scopes;
        _http = http;
        _options = options;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var lastSent = new Dictionary<string, DateTime>(StringComparer.OrdinalIgnoreCase);
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await using var scope = _scopes.CreateAsyncScope();
                var db = scope.ServiceProvider.GetRequiredService<ServersDbContext>();
                var servers = await db.ServerConfigs.AsNoTracking()
                    .Where(s => s.Enabled && s.MotdInterval != null && s.MotdInterval > 0 && s.MotdMessage != null)
                    .ToListAsync(stoppingToken);

                var client = _http.CreateClient("runtime");
                client.BaseAddress = new Uri(RuntimeUrls.HostRuntimeBase(_options.Value));

                foreach (var s in servers)
                {
                    var interval = TimeSpan.FromMinutes(Math.Max(1, s.MotdInterval!.Value));
                    if (lastSent.TryGetValue(s.Name, out var last) && DateTime.UtcNow - last < interval)
                        continue;

                    var cmd = string.IsNullOrWhiteSpace(s.MotdCommand)
                        ? $"say {s.MotdMessage}"
                        : s.MotdCommand.Replace("{message}", s.MotdMessage, StringComparison.OrdinalIgnoreCase);

                    var content = new StringContent(System.Text.Json.JsonSerializer.Serialize(new { command = cmd }), System.Text.Encoding.UTF8, "application/json");
                    try
                    {
                        await client.PostAsync($"/api/runtime/servers/{Uri.EscapeDataString(s.Name)}/command", content, stoppingToken);
                        lastSent[s.Name] = DateTime.UtcNow;
                    }
                    catch (Exception ex)
                    {
                        _logger.LogDebug(ex, "MOTD send failed for {Server}", s.Name);
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "MOTD worker tick failed");
            }

            await Task.Delay(TimeSpan.FromSeconds(60), stoppingToken);
        }
    }
}

public sealed class ScheduledUpdateWorker : BackgroundService
{
    private readonly IServiceScopeFactory _scopes;
    private readonly ILogger<ScheduledUpdateWorker> _logger;

    public ScheduledUpdateWorker(IServiceScopeFactory scopes, ILogger<ScheduledUpdateWorker> logger)
    {
        _scopes = scopes;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await using var scope = _scopes.CreateAsyncScope();
                var db = scope.ServiceProvider.GetRequiredService<ServersDbContext>();
                var due = await db.ServerConfigs.AsNoTracking().Where(s => s.AutoUpdate && s.Enabled).CountAsync(stoppingToken);
                _logger.LogDebug("Auto-update check: {Count} servers flagged", due);
                // Full SteamCMD update orchestration is triggered via HostRuntime install/update endpoints when scheduled windows are configured.
            }
            catch (Exception ex)
            {
                _logger.LogDebug(ex, "Update worker tick failed");
            }

            await Task.Delay(TimeSpan.FromMinutes(5), stoppingToken);
        }
    }
}
