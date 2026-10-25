using Microsoft.Extensions.Options;
using ServerManager.Core;
using ServerManager.Core.Configuration;
using ServerManager.Core.Paths;
using ServerManager.Core.Process;
using ServerManager.Data;
using ServerManager.HostRuntime.Services;
using ServerManager.Minecraft;
using ServerManager.Security;
using ServerManager.Steam;
using Serilog;

var builder = WebApplication.CreateBuilder(args);

var root = ServerManager.Core.Paths.RuntimeRootResolver.Resolve(builder.Configuration);
builder.Configuration.AddJsonFile(Path.Combine(root, "config", "appsettings.json"), optional: true, reloadOnChange: true);
root = ServerManager.Core.Paths.RuntimeRootResolver.Resolve(builder.Configuration);

builder.Services.Configure<ServerManagerOptions>(builder.Configuration.GetSection(ServerManagerOptions.SectionName));
builder.Services.PostConfigure<ServerManagerOptions>(o =>
{
    if (string.IsNullOrWhiteSpace(o.RootPath)) o.RootPath = root;
});

builder.Services.AddServerManagerCore();
builder.Services.AddServerManagerData();
builder.Services.AddServerManagerSecurity();
builder.Services.AddHttpClient("minecraft");
builder.Services.AddSingleton<SteamCmdService>();
builder.Services.AddSingleton<MinecraftInstaller>();
builder.Services.AddSingleton<IGameServerHost, GameServerHost>();
builder.Services.AddSingleton<GameServerHost>(sp => (GameServerHost)sp.GetRequiredService<IGameServerHost>());
builder.Services.AddSingleton<HostMetricsSampler>();
builder.Services.AddHostedService<ServerReattachHostedService>();

var earlyPaths = new AppPaths(Options.Create(new ServerManagerOptions { RootPath = root }));
earlyPaths.EnsureDirectories();
ServiceCollectionExtensions.ConfigureServerManagerLogging("HostRuntime", earlyPaths);
builder.Host.UseSerilog();

var tmpOptions = new ServerManagerOptions();
builder.Configuration.GetSection(ServerManagerOptions.SectionName).Bind(tmpOptions);
if (string.IsNullOrWhiteSpace(tmpOptions.RootPath)) tmpOptions.RootPath = root;
var bind = $"http://{tmpOptions.HostRuntimeHost}:{tmpOptions.HostRuntimePort}";
builder.WebHost.UseUrls(bind);

var app = builder.Build();

using (var scope = app.Services.CreateScope())
{
    var paths = scope.ServiceProvider.GetRequiredService<IAppPaths>();
    paths.EnsureDirectories();
    await scope.ServiceProvider.GetRequiredService<DatabaseInitializer>().InitializeAsync();
    var pids = scope.ServiceProvider.GetRequiredService<PidFileManager>();
    pids.CleanupStale();
    pids.Write("hostruntime", Environment.ProcessId);
}

var host = app.Services.GetRequiredService<IGameServerHost>();
var lifetime = app.Services.GetRequiredService<IHostApplicationLifetime>();
lifetime.ApplicationStopping.Register(() =>
{
    try { app.Services.GetRequiredService<PidFileManager>().Remove("hostruntime"); } catch { /* ignore */ }
});

app.MapGet("/health", () => Results.Ok(new { status = "ok", service = "host_runtime" }));
app.MapGet("/api/runtime/diagnostics", () => Results.Ok(host.Diagnostics()));
app.MapGet("/api/runtime/servers", async (CancellationToken ct) => Results.Ok(await host.ListServersAsync(ct)));
app.MapGet("/api/runtime/servers/{name}/status", async (string name, CancellationToken ct) =>
{
    try { return Results.Ok(await host.GetStatusAsync(name, ct)); }
    catch (KeyNotFoundException) { return Results.NotFound(); }
});
app.MapPost("/api/runtime/servers/{name}/start", async (string name, CancellationToken ct) =>
{
    try { return Results.Ok(await host.StartAsync(name, ct)); }
    catch (KeyNotFoundException) { return Results.NotFound(); }
});
app.MapPost("/api/runtime/servers/{name}/stop", async (string name, CancellationToken ct) =>
{
    try { return Results.Ok(await host.StopAsync(name, ct)); }
    catch (KeyNotFoundException) { return Results.NotFound(); }
});
app.MapPost("/api/runtime/servers/{name}/restart", async (string name, CancellationToken ct) =>
{
    try { return Results.Ok(await host.RestartAsync(name, ct)); }
    catch (KeyNotFoundException) { return Results.NotFound(); }
});
app.MapPost("/api/runtime/servers/{name}/kill", async (string name, CancellationToken ct) =>
{
    try { return Results.Ok(await host.KillAsync(name, ct)); }
    catch (KeyNotFoundException) { return Results.NotFound(); }
});
app.MapPost("/api/runtime/servers/{name}/clear", async (string name, CancellationToken ct) =>
{
    try { return Results.Ok(await host.ClearAsync(name, ct)); }
    catch (KeyNotFoundException) { return Results.NotFound(); }
});
app.MapGet("/api/runtime/servers/{name}/process", async (string name, CancellationToken ct) =>
{
    try { return Results.Ok(await host.GetProcessDetailsAsync(name, ct)); }
    catch (KeyNotFoundException) { return Results.NotFound(); }
});
app.MapGet("/api/runtime/servers/broken", async (CancellationToken ct) => Results.Ok(await host.FindBrokenAsync(ct)));
app.MapGet("/api/runtime/servers/verify", async (CancellationToken ct) => Results.Ok(await host.VerifyServersAsync(ct)));
app.MapPost("/api/runtime/db/{action}", async (string action, CancellationToken ct) =>
    Results.Ok(await host.DbMaintenanceAsync(action, ct)));
app.MapGet("/api/runtime/metrics/host", (HostMetricsSampler metrics) => Results.Ok(metrics.Sample()));
app.MapPost("/api/runtime/servers/{name}/update", async (string name, CancellationToken ct) =>
{
    try { return Results.Ok(await host.UpdateServerAsync(name, ct)); }
    catch (KeyNotFoundException) { return Results.NotFound(); }
});
app.MapPost("/api/runtime/servers/update-all", async (CancellationToken ct) => Results.Ok(await host.UpdateAllAsync(ct)));
app.MapGet("/api/runtime/servers/{name}/console", async (string name, int? lines, CancellationToken ct) =>
{
    try { return Results.Ok(await host.GetConsoleAsync(name, lines ?? 100, ct)); }
    catch (KeyNotFoundException) { return Results.NotFound(); }
});
app.MapPost("/api/runtime/servers/{name}/command", async (string name, HttpRequest req, CancellationToken ct) =>
{
    using var doc = await System.Text.Json.JsonDocument.ParseAsync(req.Body, cancellationToken: ct);
    var command = doc.RootElement.TryGetProperty("command", out var c) ? c.GetString() : null;
    if (string.IsNullOrWhiteSpace(command)) return Results.BadRequest(new { error = "command required" });
    try { return Results.Ok(await host.SendCommandAsync(name, command, ct)); }
    catch (KeyNotFoundException) { return Results.NotFound(); }
});
app.MapPost("/api/runtime/servers/{name}/reattach", async (string name, CancellationToken ct) =>
{
    try { return Results.Ok(await host.ReattachAsync(name, ct)); }
    catch (KeyNotFoundException) { return Results.NotFound(); }
});
app.MapPost("/api/runtime/reattach-all", async (CancellationToken ct) => Results.Ok(await host.ReattachAllAsync(ct)));
app.MapPost("/api/runtime/servers/install/steam", async (GameServerHost gsh, HttpRequest req, CancellationToken ct) =>
{
    using var doc = await System.Text.Json.JsonDocument.ParseAsync(req.Body, cancellationToken: ct);
    var name = doc.RootElement.GetProperty("name").GetString()!;
    var appId = doc.RootElement.GetProperty("appId").GetString()!;
    var installDir = doc.RootElement.GetProperty("installDir").GetString()!;
    return Results.Ok(await gsh.InstallSteamAsync(name, appId, installDir, ct));
});
app.MapPost("/api/runtime/servers/install/minecraft", async (GameServerHost gsh, HttpRequest req, CancellationToken ct) =>
{
    using var doc = await System.Text.Json.JsonDocument.ParseAsync(req.Body, cancellationToken: ct);
    var name = doc.RootElement.GetProperty("name").GetString()!;
    var version = doc.RootElement.GetProperty("version").GetString()!;
    var installDir = doc.RootElement.GetProperty("installDir").GetString()!;
    return Results.Ok(await gsh.InstallMinecraftAsync(name, version, installDir, ct));
});
app.MapPost("/api/runtime/shutdown", (IHostApplicationLifetime appLife) =>
{
    _ = Task.Run(async () =>
    {
        await Task.Delay(200);
        appLife.StopApplication();
    });
    return Results.Ok(new { ok = true });
});

Log.Information("HostRuntime listening on {Url}", bind);
await app.RunAsync();
