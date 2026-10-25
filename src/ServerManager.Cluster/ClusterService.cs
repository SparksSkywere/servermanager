using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Routing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;
using ServerManager.Core;
using ServerManager.Core.Configuration;
using ServerManager.Data;
using ServerManager.Data.Entities;

namespace ServerManager.Cluster;

public static class ClusterServiceCollectionExtensions
{
    public static IServiceCollection AddServerManagerCluster(this IServiceCollection services)
    {
        services.AddSingleton<ClusterNetworkGuard>();
        services.AddScoped<ClusterService>();
        services.AddHttpClient("cluster");
        services.AddHostedService<SubhostClusterWorker>();
        services.AddHostedService<ClusterStaleNodeWatcher>();
        return services;
    }
}

public sealed class ClusterNetworkGuard
{
    public bool IsAllowed(string? ip)
    {
        if (string.IsNullOrWhiteSpace(ip)) return false;
        if (ip is "127.0.0.1" or "::1" or "localhost") return true;
        if (ip.StartsWith("10.", StringComparison.Ordinal)) return true;
        if (ip.StartsWith("192.168.", StringComparison.Ordinal)) return true;
        if (ip.StartsWith("172."))
        {
            var parts = ip.Split('.');
            if (parts.Length > 1 && int.TryParse(parts[1], out var second) && second is >= 16 and <= 31)
                return true;
        }
        return false;
    }
}

public sealed class ClusterService
{
    private readonly ClusterDbContext _db;
    private readonly IConfigStore _cfg;
    private readonly ServerManagerOptions _options;
    private readonly IHttpClientFactory _httpClientFactory;

    public ClusterService(ClusterDbContext db, IConfigStore cfg, IOptions<ServerManagerOptions> options, IHttpClientFactory httpClientFactory)
    {
        _db = db;
        _cfg = cfg;
        _options = options.Value;
        _httpClientFactory = httpClientFactory;
    }

    public string Role => _cfg.Get("HostType") ?? _options.HostType;
    public bool Enabled => (_cfg.Get("ClusterEnabled") ?? (_options.ClusterEnabled ? "true" : "false")) == "true";
    public int ClusterPort => _cfg.GetOrDefault("ClusterPort", _options.ClusterPort);

    public async Task<object> RequestJoinAsync(string subhostId, string? machineName, string? address, CancellationToken ct)
    {
        _db.PendingRequests.Add(new PendingJoinRequest
        {
            SubhostId = subhostId,
            MachineName = machineName,
            Address = address,
            Status = "pending"
        });
        await _db.SaveChangesAsync(ct);
        return new { success = true, status = "pending" };
    }

    public async Task<List<PendingJoinRequest>> ListPendingAsync(CancellationToken ct)
        => await _db.PendingRequests.Where(p => p.Status == "pending").OrderByDescending(p => p.CreatedAt).ToListAsync(ct);

    public async Task<object?> ApproveAsync(int id, CancellationToken ct)
    {
        var req = await _db.PendingRequests.FirstOrDefaultAsync(p => p.Id == id, ct);
        if (req is null) return null;
        req.Status = "approved";
        var token = Guid.NewGuid().ToString("N");
        _db.ClusterNodes.Add(new ClusterNode
        {
            NodeId = req.SubhostId,
            NodeType = "subhost",
            DisplayName = req.MachineName,
            Address = req.Address,
            Port = ClusterPort,
            Status = "approved",
            Token = token,
            LastHeartbeat = DateTime.UtcNow
        });
        await _db.SaveChangesAsync(ct);
        return new { success = true, token, node_id = req.SubhostId };
    }

    public async Task<object?> RejectAsync(int id, CancellationToken ct)
    {
        var req = await _db.PendingRequests.FirstOrDefaultAsync(p => p.Id == id, ct);
        if (req is null) return null;
        req.Status = "rejected";
        await _db.SaveChangesAsync(ct);
        return new { success = true };
    }

    public async Task<object> HeartbeatAsync(string nodeId, string? token, CancellationToken ct)
    {
        var node = await _db.ClusterNodes.FirstOrDefaultAsync(n => n.NodeId == nodeId, ct);
        if (node is null) return new { success = false, error = "unknown node" };
        if (!string.IsNullOrWhiteSpace(token) && !string.Equals(node.Token, token, StringComparison.Ordinal))
            return new { success = false, error = "invalid token" };
        node.LastHeartbeat = DateTime.UtcNow;
        node.Status = "online";
        await _db.SaveChangesAsync(ct);
        return new { success = true };
    }

    public async Task<object> JoinStatusAsync(string subhostId, CancellationToken ct)
    {
        var pending = await _db.PendingRequests.AsNoTracking()
            .Where(p => p.SubhostId == subhostId)
            .OrderByDescending(p => p.CreatedAt)
            .FirstOrDefaultAsync(ct);
        if (pending is null)
            return new { status = "unknown" };
        if (pending.Status == "pending")
            return new { status = "pending", requestId = pending.Id };
        if (pending.Status == "rejected")
            return new { status = "rejected" };
        var node = await _db.ClusterNodes.AsNoTracking().FirstOrDefaultAsync(n => n.NodeId == subhostId, ct);
        if (node is null)
            return new { status = "approved", token = (string?)null };
        return new { status = "approved", token = node.Token, nodeId = node.NodeId, address = node.Address };
    }

    public async Task<List<ClusterNode>> ListNodesAsync(CancellationToken ct)
        => await _db.ClusterNodes.AsNoTracking().ToListAsync(ct);

    public async Task<bool> RemoveNodeAsync(string nodeId, CancellationToken ct)
    {
        var node = await _db.ClusterNodes.FirstOrDefaultAsync(n => n.NodeId == nodeId, ct);
        if (node is null) return false;
        _db.ClusterNodes.Remove(node);
        await _db.SaveChangesAsync(ct);
        return true;
    }

    public async Task<object?> ForwardToSubhostAsync(string nodeId, string relativePath, HttpMethod method, string? json, CancellationToken ct)
    {
        var node = await _db.ClusterNodes.FirstOrDefaultAsync(n => n.NodeId == nodeId, ct);
        if (node?.Address is null) return null;
        var port = node.Port ?? ClusterPort;
        // Subhosts expose the same Web API; use standardized cluster/web port.
        var baseUrl = $"http://{node.Address}:{port}";
        var client = _httpClientFactory.CreateClient("cluster");
        using var req = new HttpRequestMessage(method, $"{baseUrl.TrimEnd('/')}/{relativePath.TrimStart('/')}");
        if (json is not null) req.Content = new StringContent(json, System.Text.Encoding.UTF8, "application/json");
        if (!string.IsNullOrEmpty(node.Token))
            req.Headers.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", node.Token);
        var resp = await client.SendAsync(req, ct);
        var body = await resp.Content.ReadAsStringAsync(ct);
        return new { status = (int)resp.StatusCode, body };
    }
}

public static class ClusterEndpointExtensions
{
    public static IEndpointRouteBuilder MapClusterEndpoints(this IEndpointRouteBuilder app)
    {
        var g = app.MapGroup("/api/cluster");

        g.MapPost("/request-join", async (JoinRequest body, ClusterService cluster, ClusterNetworkGuard guard, HttpContext ctx) =>
        {
            if (!cluster.Enabled) return Results.Json(new { success = false, error = "Cluster is disabled on this host." }, statusCode: StatusCodes.Status403Forbidden);
            var ip = ctx.Connection.RemoteIpAddress?.ToString();
            if (!guard.IsAllowed(ip)) return Results.StatusCode(StatusCodes.Status403Forbidden);
            return Results.Ok(await cluster.RequestJoinAsync(body.SubhostId ?? Guid.NewGuid().ToString("N"), body.MachineName, body.Address ?? ip, ctx.RequestAborted));
        });

        g.MapGet("/pending", async (ClusterService cluster, CancellationToken ct) =>
        {
            if (!cluster.Enabled) return Results.Json(new { error = "Cluster disabled" }, statusCode: StatusCodes.Status403Forbidden);
            return Results.Ok(await cluster.ListPendingAsync(ct));
        }).RequireAuthorization();
        g.MapGet("/requests", async (ClusterService cluster, CancellationToken ct) =>
        {
            if (!cluster.Enabled) return Results.Json(new { error = "Cluster disabled" }, statusCode: StatusCodes.Status403Forbidden);
            return Results.Ok(await cluster.ListPendingAsync(ct));
        }).RequireAuthorization();
        g.MapPost("/approve/{id:int}", async (int id, ClusterService cluster, CancellationToken ct) =>
        {
            if (!cluster.Enabled) return Results.Json(new { error = "Cluster disabled" }, statusCode: StatusCodes.Status403Forbidden);
            var r = await cluster.ApproveAsync(id, ct);
            return r is null ? Results.NotFound() : Results.Ok(r);
        }).RequireAuthorization();
        g.MapPost("/reject/{id:int}", async (int id, ClusterService cluster, CancellationToken ct) =>
        {
            if (!cluster.Enabled) return Results.Json(new { error = "Cluster disabled" }, statusCode: StatusCodes.Status403Forbidden);
            var r = await cluster.RejectAsync(id, ct);
            return r is null ? Results.NotFound() : Results.Ok(r);
        }).RequireAuthorization();
        g.MapPost("/heartbeat", async (HeartbeatRequest body, ClusterService cluster, CancellationToken ct) =>
        {
            if (!cluster.Enabled) return Results.Json(new { success = false, error = "Cluster disabled" }, statusCode: StatusCodes.Status403Forbidden);
            return Results.Ok(await cluster.HeartbeatAsync(body.NodeId ?? "", body.Token, ct));
        });
        g.MapGet("/join-status/{subhostId}", async (string subhostId, ClusterService cluster, CancellationToken ct) =>
        {
            if (!cluster.Enabled) return Results.Json(new { status = "disabled" }, statusCode: StatusCodes.Status403Forbidden);
            return Results.Ok(await cluster.JoinStatusAsync(subhostId, ct));
        });
        g.MapGet("/nodes", async (ClusterService cluster, CancellationToken ct) =>
        {
            if (!cluster.Enabled) return Results.Json(Array.Empty<object>(), statusCode: StatusCodes.Status200OK);
            return Results.Ok(await cluster.ListNodesAsync(ct));
        }).RequireAuthorization();
        g.MapDelete("/nodes/{id}", async (string id, ClusterService cluster, CancellationToken ct) =>
        {
            if (!cluster.Enabled) return Results.Json(new { error = "Cluster disabled" }, statusCode: StatusCodes.Status403Forbidden);
            var ok = await cluster.RemoveNodeAsync(id, ct);
            return ok ? Results.Ok(new { success = true }) : Results.NotFound();
        }).RequireAuthorization();
        g.MapGet("/subhosts", async (ClusterService cluster, CancellationToken ct) =>
            Results.Ok((await cluster.ListNodesAsync(ct)).Where(n => n.NodeType == "subhost"))).RequireAuthorization();
        g.MapGet("/status", (ClusterService cluster) => Results.Ok(new
        {
            role = cluster.Role,
            enabled = cluster.Enabled,
            port = cluster.ClusterPort,
            note = cluster.Enabled
                ? "Cluster uses the Web API port; ClusterPort is the advertised peer contact port."
                : "Enable ClusterEnabled in Settings to use join/approve/heartbeat."
        }));

        g.MapGet("/subhost/{id}/servers", async (string id, ClusterService cluster, CancellationToken ct) =>
        {
            var r = await cluster.ForwardToSubhostAsync(id, "/api/servers", HttpMethod.Get, null, ct);
            return r is null ? Results.NotFound(new { ok = false, error = "node not found" }) : Results.Ok(r);
        }).RequireAuthorization();
        g.MapPost("/subhost/{id}/ping", async (string id, ClusterService cluster, CancellationToken ct) =>
        {
            var r = await cluster.ForwardToSubhostAsync(id, "/api/analytics/health", HttpMethod.Get, null, ct);
            return r is null ? Results.NotFound(new { ok = false, error = "node not found" }) : Results.Ok(r);
        }).RequireAuthorization();
        g.MapPost("/subhost/{id}/servers/{server}/start", async (string id, string server, ClusterService cluster, CancellationToken ct) =>
        {
            var r = await cluster.ForwardToSubhostAsync(id, $"/api/servers/{Uri.EscapeDataString(server)}/start", HttpMethod.Post, null, ct);
            return r is null ? Results.NotFound() : Results.Ok(r);
        }).RequireAuthorization();
        g.MapPost("/subhost/{id}/servers/{server}/stop", async (string id, string server, ClusterService cluster, CancellationToken ct) =>
        {
            var r = await cluster.ForwardToSubhostAsync(id, $"/api/servers/{Uri.EscapeDataString(server)}/stop", HttpMethod.Post, null, ct);
            return r is null ? Results.NotFound() : Results.Ok(r);
        }).RequireAuthorization();
        g.MapPost("/subhost/{id}/servers/{server}/restart", async (string id, string server, ClusterService cluster, CancellationToken ct) =>
        {
            var r = await cluster.ForwardToSubhostAsync(id, $"/api/servers/{Uri.EscapeDataString(server)}/restart", HttpMethod.Post, null, ct);
            return r is null ? Results.NotFound() : Results.Ok(r);
        }).RequireAuthorization();

        return app;
    }
}

public record JoinRequest(string? SubhostId, string? MachineName, string? Address);
public record HeartbeatRequest(string? NodeId, string? Token);
