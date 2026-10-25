using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using ServerManager.Data;

namespace ServerManager.Cluster;

/// <summary>Marks cluster nodes offline when heartbeats go stale.</summary>
public sealed class ClusterStaleNodeWatcher : BackgroundService
{
    private readonly IServiceScopeFactory _scopes;
    private readonly ILogger<ClusterStaleNodeWatcher> _logger;

    public ClusterStaleNodeWatcher(IServiceScopeFactory scopes, ILogger<ClusterStaleNodeWatcher> logger)
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
                var db = scope.ServiceProvider.GetRequiredService<ClusterDbContext>();
                var cutoff = DateTime.UtcNow.AddSeconds(-45);
                var stale = await db.ClusterNodes.Where(n => n.LastHeartbeat != null && n.LastHeartbeat < cutoff && n.Status != "offline").ToListAsync(stoppingToken);
                foreach (var n in stale)
                {
                    n.Status = "offline";
                    _logger.LogInformation("Cluster node {Id} marked offline (stale heartbeat)", n.NodeId);
                }
                if (stale.Count > 0) await db.SaveChangesAsync(stoppingToken);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogDebug(ex, "Stale node watcher error");
            }

            await Task.Delay(TimeSpan.FromSeconds(15), stoppingToken);
        }
    }
}
