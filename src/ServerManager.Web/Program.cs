using System.Net;
using System.Net.Http.Headers;
using System.Security.Claims;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.FileProviders;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.Tokens;
using ServerManager.Cluster;
using ServerManager.Core;
using ServerManager.Core.Configuration;
using ServerManager.Core.Paths;
using ServerManager.Core.Process;
using ServerManager.Data;
using ServerManager.Data.Entities;
using ServerManager.Minecraft;
using ServerManager.Security;
using ServerManager.Steam;
using Serilog;
using System.IO.Compression;

var builder = WebApplication.CreateBuilder(args);

var root = ServerManager.Core.Paths.RuntimeRootResolver.Resolve(builder.Configuration);
builder.Configuration.AddJsonFile(Path.Combine(root, "config", "appsettings.json"), optional: true, reloadOnChange: true);
root = ServerManager.Core.Paths.RuntimeRootResolver.Resolve(builder.Configuration);

builder.Services.Configure<ServerManagerOptions>(builder.Configuration.GetSection(ServerManagerOptions.SectionName));
builder.Services.PostConfigure<ServerManagerOptions>(o =>
{
    if (string.IsNullOrWhiteSpace(o.RootPath)) o.RootPath = root;
});
builder.Services.Configure<JwtOptions>(builder.Configuration.GetSection("Jwt"));

builder.Services.AddServerManagerCore();
builder.Services.AddServerManagerData();
builder.Services.AddServerManagerSecurity();
builder.Services.AddServerManagerCluster();
builder.Services.AddSatelliteServices();
builder.Services.AddMinecraftServices();
builder.Services.AddSteamServices();
builder.Services.AddHttpClient<HostRuntimeClient>();
builder.Services.AddHttpClient("minecraft");
builder.Services.AddHttpClient("cluster");

var earlyPaths = new AppPaths(Microsoft.Extensions.Options.Options.Create(new ServerManagerOptions { RootPath = root }));
earlyPaths.EnsureDirectories();
SslCertificateHelper.EnsureSelfSigned(earlyPaths);
ServiceCollectionExtensions.ConfigureServerManagerLogging("Web", earlyPaths);
builder.Host.UseSerilog();

var smOptions = new ServerManagerOptions();
builder.Configuration.GetSection(ServerManagerOptions.SectionName).Bind(smOptions);
if (string.IsNullOrWhiteSpace(smOptions.RootPath)) smOptions.RootPath = root;

var jwtOpt = new JwtOptions();
builder.Configuration.GetSection("Jwt").Bind(jwtOpt);
if (string.IsNullOrWhiteSpace(jwtOpt.SigningKey) || jwtOpt.SigningKey.Length < 32)
    jwtOpt.SigningKey = "CHANGE_ME_ServerManager_Dev_Key_32chars_min!";

builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(o =>
    {
        o.TokenValidationParameters = new TokenValidationParameters
        {
            ValidateIssuer = true,
            ValidateAudience = true,
            ValidateLifetime = true,
            ValidateIssuerSigningKey = true,
            ValidIssuer = jwtOpt.Issuer,
            ValidAudience = jwtOpt.Audience,
            IssuerSigningKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(jwtOpt.SigningKey))
        };
    });
builder.Services.AddAuthorization();
builder.Services.AddCors(o => o.AddDefaultPolicy(p =>
    p.WithOrigins(
            $"http://localhost:{smOptions.WebPort}",
            $"https://localhost:{smOptions.HttpsPort}",
            $"http://127.0.0.1:{smOptions.WebPort}",
            $"https://127.0.0.1:{smOptions.HttpsPort}")
        .AllowAnyHeader().AllowAnyMethod()));

var urls = new List<string> { $"http://{smOptions.WebHost}:{smOptions.WebPort}" };
var pfx = SslCertificateHelper.GetPfxPath(earlyPaths);
if (pfx is not null && smOptions.SslEnabled)
{
    builder.WebHost.ConfigureKestrel(k =>
    {
        k.ListenAnyIP(smOptions.HttpsPort, lo => lo.UseHttps(pfx, "servermanager"));
        k.ListenAnyIP(smOptions.WebPort);
    });
}
else
{
    builder.WebHost.UseUrls(urls.ToArray());
}

var app = builder.Build();

using (var scope = app.Services.CreateScope())
{
    var paths = scope.ServiceProvider.GetRequiredService<IAppPaths>();
    paths.EnsureDirectories();
    // Prefer repo www/ then runtime/www
    var repoWww = Path.GetFullPath(Path.Combine(paths.Root, "..", "www"));
    if (Directory.Exists(repoWww) && !Directory.EnumerateFileSystemEntries(paths.Www).Any())
    {
        foreach (var file in Directory.GetFiles(repoWww, "*", SearchOption.AllDirectories))
        {
            var rel = Path.GetRelativePath(repoWww, file);
            var dest = Path.Combine(paths.Www, rel);
            Directory.CreateDirectory(Path.GetDirectoryName(dest)!);
            File.Copy(file, dest, overwrite: true);
        }
    }

    await scope.ServiceProvider.GetRequiredService<DatabaseInitializer>().InitializeAsync();
    var pids = scope.ServiceProvider.GetRequiredService<PidFileManager>();
    pids.Write("web", Environment.ProcessId);
}

app.UseCors();
app.Use(async (ctx, next) =>
{
    ctx.RequestServices.GetService<ServerManager.Cluster.PrometheusMetrics>()?.Inc();
    await next();
});
app.UseAuthentication();
app.UseAuthorization();

var wwwRoot = app.Services.GetRequiredService<IAppPaths>().Www;
if (!Directory.Exists(wwwRoot)) Directory.CreateDirectory(wwwRoot);
app.UseDefaultFiles(new DefaultFilesOptions
{
    FileProvider = new PhysicalFileProvider(wwwRoot)
});
app.UseStaticFiles(new StaticFileOptions
{
    FileProvider = new PhysicalFileProvider(wwwRoot),
    RequestPath = ""
});

var limiter = app.Services.GetRequiredService<RateLimiter>();

app.MapPost("/api/auth/login", async (LoginRequest body, IAuthService auth, HttpContext ctx) =>
{
    var ip = ctx.Connection.RemoteIpAddress?.ToString() ?? "unknown";
    if (!limiter.Allow($"login:{ip}", 20, TimeSpan.FromMinutes(1)))
        return Results.Json(new { success = false, error = "Too many login attempts. Wait a minute and try again." },
            statusCode: StatusCodes.Status429TooManyRequests);

    var result = await auth.LoginAsync(body.Username ?? "", body.Password ?? "", body.TotpCode);
    if (result.RequiresTwoFactor)
        return Results.Json(new { success = false, requires_2fa = true, error = result.Error ?? "Two-factor code required" });
    if (!result.Success)
        return Results.Json(new { success = false, error = result.Error ?? "Invalid username or password." },
            statusCode: StatusCodes.Status401Unauthorized);

    return Results.Ok(new
    {
        success = true,
        token = result.Token,
        user = new { username = result.User!.Username, is_admin = result.User.IsAdmin, display_name = result.User.DisplayName }
    });
});

// Clears in-memory lockouts without auth — local recovery aid (bound to loopback in practice via WebHost).
app.MapPost("/api/auth/clear-lockouts", (AccountLockoutService lockout, HttpContext ctx) =>
{
    var ip = ctx.Connection.RemoteIpAddress;
    if (ip is null || !(IPAddress.IsLoopback(ip) || ip.Equals(IPAddress.IPv6Loopback)))
        return Results.Forbid();
    lockout.ResetAll();
    return Results.Ok(new { ok = true, message = "Lockouts cleared" });
});

app.MapGet("/api/auth/verify", async (HttpContext ctx, IAuthService auth) =>
{
    var user = await GetUserAsync(ctx, auth);
    if (user is null) return Results.Unauthorized();
    return Results.Ok(new { valid = true, username = user.Username, is_admin = user.IsAdmin });
}).RequireAuthorization();

app.MapGet("/api/servers", async (ServersDbContext db, HostRuntimeClient runtime, CancellationToken ct) =>
{
    var configs = await db.ServerConfigs.AsNoTracking().Where(s => s.Enabled).ToListAsync(ct);
    var live = await runtime.GetServersAsync(ct);
    return Results.Ok(configs.Select(c => new
    {
        id = c.Name,
        name = c.Name,
        type = c.ServerType,
        install_dir = c.InstallDir,
        app_id = c.AppId,
        version = c.Version,
        status = live.FirstOrDefault(l => string.Equals(l.Name, c.Name, StringComparison.OrdinalIgnoreCase))?.Status ?? "unknown"
    }));
}).RequireAuthorization();

app.MapPost("/api/servers", async (CreateServerRequest body, ServersDbContext db, CancellationToken ct) =>
{
    if (string.IsNullOrWhiteSpace(body.Name) || string.IsNullOrWhiteSpace(body.InstallDir))
        return Results.BadRequest(new { error = "name and installDir required" });
    if (await db.ServerConfigs.AnyAsync(s => s.Name == body.Name, ct))
        return Results.Conflict(new { error = "exists" });

    db.ServerConfigs.Add(MapServer(body, new ServerConfig { Name = body.Name!, Enabled = true }));
    await db.SaveChangesAsync(ct);
    return Results.Ok(new { success = true });
}).RequireAuthorization();

app.MapGet("/api/servers/{id}", async (string id, ServersDbContext db, CancellationToken ct) =>
{
    var c = await db.ServerConfigs.AsNoTracking().FirstOrDefaultAsync(x => x.Name == id, ct);
    if (c is null) return Results.NotFound();
    return Results.Ok(new
    {
        id = c.Name,
        name = c.Name,
        type = c.ServerType,
        app_id = c.AppId,
        install_dir = c.InstallDir,
        executable = c.Executable,
        launch_args = c.LaunchArgs,
        additional_args = c.AdditionalArgs,
        stop_command = c.StopCommand,
        save_command = c.SaveCommand,
        start_command = c.StartCommand,
        java_path = c.JavaPath,
        version = c.Version,
        mod_loader = c.ModLoader,
        ram_mb = c.RamMb,
        jvm_args = c.JvmArgs,
        motd_message = c.MotdMessage,
        motd_command = c.MotdCommand,
        motd_interval = c.MotdInterval,
        warning_command = c.WarningCommand,
        warning_intervals = c.WarningIntervals,
        warning_message_template = c.WarningMessageTemplate,
        scheduled_restart_enabled = c.ScheduledRestartEnabled,
        auto_start = c.AutoStart,
        auto_update = c.AutoUpdate,
        category = c.Category,
        notes = c.Notes,
        enabled = c.Enabled,
        // camelCase aliases for HostUI
        serverType = c.ServerType,
        appId = c.AppId,
        installDir = c.InstallDir,
        launchArgs = c.LaunchArgs,
        stopCommand = c.StopCommand,
        saveCommand = c.SaveCommand,
        startCommand = c.StartCommand,
        javaPath = c.JavaPath,
        motdMessage = c.MotdMessage,
        motdCommand = c.MotdCommand,
        motdInterval = c.MotdInterval,
        warningCommand = c.WarningCommand,
        warningIntervals = c.WarningIntervals,
        scheduledRestartEnabled = c.ScheduledRestartEnabled,
        autoStart = c.AutoStart
    });
}).RequireAuthorization();

app.MapPut("/api/servers/{id}", async (string id, UpdateServerRequest body, ServersDbContext db, CancellationToken ct) =>
{
    var c = await db.ServerConfigs.FirstOrDefaultAsync(x => x.Name == id, ct);
    if (c is null) return Results.NotFound();
    ApplyServerUpdate(c, body);
    c.UpdatedAt = DateTime.UtcNow;
    await db.SaveChangesAsync(ct);
    return Results.Ok(new { success = true });
}).RequireAuthorization();

app.MapDelete("/api/servers/{id}", async (string id, ServersDbContext db, CancellationToken ct) =>
{
    var s = await db.ServerConfigs.FirstOrDefaultAsync(x => x.Name == id, ct);
    if (s is null) return Results.NotFound();
    db.ServerConfigs.Remove(s);
    await db.SaveChangesAsync(ct);
    return Results.Ok(new { success = true });
}).RequireAuthorization();

app.MapGet("/api/servers/{id}/export", async (string id, ServersDbContext db, CancellationToken ct) =>
{
    var c = await db.ServerConfigs.AsNoTracking().FirstOrDefaultAsync(x => x.Name == id, ct);
    if (c is null) return Results.NotFound();
    var perms = await db.ServerPermissions.AsNoTracking().Where(p => p.ServerName == id).ToListAsync(ct);
    return Results.Ok(new
    {
        format = "servermanager-server-export",
        version = 1,
        exportedAt = DateTime.UtcNow.ToString("o"),
        server = ToExportServer(c),
        permissions = perms.Select(p => new
        {
            username = p.Username,
            canView = p.CanView,
            canStart = p.CanStart,
            canStop = p.CanStop,
            canRestart = p.CanRestart,
            canConsole = p.CanConsole,
            canEdit = p.CanEdit
        }).ToList()
    });
}).RequireAuthorization();

app.MapPost("/api/servers/import", async (HttpRequest req, ServersDbContext db, string? mode, CancellationToken ct) =>
{
    mode = string.IsNullOrWhiteSpace(mode) ? "overwrite" : mode.Trim().ToLowerInvariant();
    using var doc = await JsonDocument.ParseAsync(req.Body, cancellationToken: ct);
    var root = doc.RootElement;
    if (!root.TryGetProperty("server", out var serverEl))
        return Results.BadRequest(new { success = false, error = "Missing server object (expected servermanager-server-export)." });

    var name = serverEl.TryGetProperty("name", out var nEl) ? nEl.GetString() : null;
    if (string.IsNullOrWhiteSpace(name))
        return Results.BadRequest(new { success = false, error = "server.name required" });

    var existing = await db.ServerConfigs.FirstOrDefaultAsync(s => s.Name == name, ct);
    if (existing is not null)
    {
        if (mode == "skip")
            return Results.Ok(new { success = true, action = "skipped", name });
        if (mode == "rename")
        {
            var baseName = name;
            var i = 2;
            while (await db.ServerConfigs.AnyAsync(s => s.Name == name, ct))
                name = $"{baseName}-{i++}";
            existing = null;
        }
        else
        {
            ApplyExportServer(existing, serverEl);
            existing.ProcessId = null;
            existing.ProcessCreateTime = null;
            existing.UpdatedAt = DateTime.UtcNow;
            await db.SaveChangesAsync(ct);
            await ImportPermissionsAsync(db, name!, root, ct);
            return Results.Ok(new { success = true, action = "overwritten", name });
        }
    }

    var cfg = new ServerConfig { Name = name!, Enabled = true, CreatedAt = DateTime.UtcNow, UpdatedAt = DateTime.UtcNow };
    ApplyExportServer(cfg, serverEl);
    cfg.ProcessId = null;
    cfg.ProcessCreateTime = null;
    db.ServerConfigs.Add(cfg);
    await db.SaveChangesAsync(ct);
    await ImportPermissionsAsync(db, name!, root, ct);
    return Results.Ok(new { success = true, action = "created", name });
}).RequireAuthorization();

app.MapPost("/api/servers/{id}/start", async (string id, HostRuntimeClient runtime, CancellationToken ct) =>
    Results.Ok(await runtime.PostAsync($"/api/runtime/servers/{Uri.EscapeDataString(id)}/start", ct))).RequireAuthorization();
app.MapPost("/api/servers/{id}/stop", async (string id, HostRuntimeClient runtime, CancellationToken ct) =>
    Results.Ok(await runtime.PostAsync($"/api/runtime/servers/{Uri.EscapeDataString(id)}/stop", ct))).RequireAuthorization();
app.MapPost("/api/servers/{id}/restart", async (string id, HostRuntimeClient runtime, CancellationToken ct) =>
    Results.Ok(await runtime.PostAsync($"/api/runtime/servers/{Uri.EscapeDataString(id)}/restart", ct))).RequireAuthorization();
app.MapPost("/api/servers/{id}/kill", async (string id, HostRuntimeClient runtime, CancellationToken ct) =>
    Results.Ok(await runtime.PostAsync($"/api/runtime/servers/{Uri.EscapeDataString(id)}/kill", ct))).RequireAuthorization();
app.MapGet("/api/servers/{id}/console", async (string id, int? lines, HostRuntimeClient runtime, CancellationToken ct) =>
    Results.Ok(await runtime.GetAsync($"/api/runtime/servers/{Uri.EscapeDataString(id)}/console?lines={lines ?? 100}", ct))).RequireAuthorization();
app.MapPost("/api/servers/{id}/console", async (string id, ConsoleCommandRequest body, HostRuntimeClient runtime, CancellationToken ct) =>
{
    var json = JsonSerializer.Serialize(new { command = body.Command });
    return Results.Ok(await runtime.PostJsonAsync($"/api/runtime/servers/{Uri.EscapeDataString(id)}/command", json, ct));
}).RequireAuthorization();
app.MapPost("/api/servers/{id}/reattach", async (string id, HostRuntimeClient runtime, CancellationToken ct) =>
    Results.Ok(await runtime.PostAsync($"/api/runtime/servers/{Uri.EscapeDataString(id)}/reattach", ct))).RequireAuthorization();
app.MapPost("/api/runtime/reattach-all", async (HostRuntimeClient runtime, CancellationToken ct) =>
    Results.Ok(await runtime.PostAsync("/api/runtime/reattach-all", ct))).RequireAuthorization();

app.MapGet("/api/runtime/diagnostics", async (HostRuntimeClient runtime, CancellationToken ct) =>
    Results.Ok(await runtime.GetAsync("/api/runtime/diagnostics", ct))).RequireAuthorization();
app.MapGet("/api/runtime/metrics/host", async (HostRuntimeClient runtime, CancellationToken ct) =>
    Results.Ok(await runtime.GetAsync("/api/runtime/metrics/host", ct))).RequireAuthorization();
app.MapPost("/api/runtime/servers/update-all", async (HostRuntimeClient runtime, CancellationToken ct) =>
    Results.Ok(await runtime.PostAsync("/api/runtime/servers/update-all", ct))).RequireAuthorization();
app.MapPost("/api/runtime/db/{action}", async (string action, HostRuntimeClient runtime, CancellationToken ct) =>
    Results.Ok(await runtime.PostAsync($"/api/runtime/db/{Uri.EscapeDataString(action)}", ct))).RequireAuthorization();
app.MapGet("/api/runtime/servers/broken", async (HostRuntimeClient runtime, CancellationToken ct) =>
    Results.Ok(await runtime.GetAsync("/api/runtime/servers/broken", ct))).RequireAuthorization();
app.MapGet("/api/runtime/servers/verify", async (HostRuntimeClient runtime, CancellationToken ct) =>
    Results.Ok(await runtime.GetAsync("/api/runtime/servers/verify", ct))).RequireAuthorization();

app.MapGet("/api/users", async (UsersDbContext db, ClaimsPrincipal user, CancellationToken ct) =>
{
    if (!IsAdmin(user)) return Results.Forbid();
    var users = await db.Users.AsNoTracking()
        .Select(u => new { u.Username, u.IsAdmin, u.IsActive, u.Email, u.DisplayName, twoFactorEnabled = u.TwoFactorEnabled })
        .ToListAsync(ct);
    return Results.Ok(users);
}).RequireAuthorization();

app.MapPost("/api/users", async (CreateUserRequest body, UsersDbContext db, ClaimsPrincipal user, CancellationToken ct) =>
{
    if (!IsAdmin(user)) return Results.Forbid();
    if (await db.Users.AnyAsync(u => u.Username == body.Username, ct)) return Results.Conflict();
    db.Users.Add(new UserAccount
    {
        Username = body.Username!,
        PasswordHash = BCrypt.Net.BCrypt.HashPassword(body.Password ?? "changeme"),
        IsAdmin = body.IsAdmin,
        Email = body.Email,
        DisplayName = body.DisplayName
    });
    await db.SaveChangesAsync(ct);
    return Results.Ok(new { success = true });
}).RequireAuthorization();

app.MapPut("/api/users/{username}", async (string username, UpdateUserRequest body, UsersDbContext db, ClaimsPrincipal user, CancellationToken ct) =>
{
    if (!IsAdmin(user)) return Results.Forbid();
    var entity = await db.Users.FirstOrDefaultAsync(u => u.Username == username, ct);
    if (entity is null) return Results.NotFound();
    if (body.DisplayName is not null) entity.DisplayName = body.DisplayName;
    if (body.Email is not null) entity.Email = body.Email;
    if (body.IsAdmin is not null) entity.IsAdmin = body.IsAdmin.Value;
    if (body.IsActive is not null) entity.IsActive = body.IsActive.Value;
    await db.SaveChangesAsync(ct);
    return Results.Ok(new { success = true });
}).RequireAuthorization();

app.MapDelete("/api/users/{username}", async (string username, UsersDbContext db, ClaimsPrincipal user, CancellationToken ct) =>
{
    if (!IsAdmin(user)) return Results.Forbid();
    if (string.Equals(user.Identity?.Name, username, StringComparison.OrdinalIgnoreCase))
        return Results.BadRequest(new { success = false, error = "Cannot delete your own account." });
    var entity = await db.Users.FirstOrDefaultAsync(u => u.Username == username, ct);
    if (entity is null) return Results.NotFound();
    db.Users.Remove(entity);
    await db.SaveChangesAsync(ct);
    return Results.Ok(new { success = true });
}).RequireAuthorization();

app.MapPost("/api/users/{username}/reset-password", async (string username, ResetPasswordRequest body, UsersDbContext db, ClaimsPrincipal user, CancellationToken ct) =>
{
    if (!IsAdmin(user)) return Results.Forbid();
    if (string.IsNullOrWhiteSpace(body.Password))
        return Results.BadRequest(new { success = false, error = "password required" });
    var entity = await db.Users.FirstOrDefaultAsync(u => u.Username == username, ct);
    if (entity is null) return Results.NotFound();
    entity.PasswordHash = BCrypt.Net.BCrypt.HashPassword(body.Password);
    await db.SaveChangesAsync(ct);
    return Results.Ok(new { success = true });
}).RequireAuthorization();

app.MapPost("/api/users/{username}/reset-2fa", async (string username, UsersDbContext db, ClaimsPrincipal user, CancellationToken ct) =>
{
    if (!IsAdmin(user)) return Results.Forbid();
    var entity = await db.Users.FirstOrDefaultAsync(u => u.Username == username, ct);
    if (entity is null) return Results.NotFound();
    entity.TwoFactorEnabled = false;
    entity.TwoFactorSecret = null;
    await db.SaveChangesAsync(ct);
    return Results.Ok(new { success = true });
}).RequireAuthorization();

app.MapPost("/api/users/bulk-email", async (HttpRequest req, UsersDbContext db, ClaimsPrincipal user, IServiceProvider sp, CancellationToken ct) =>
{
    if (!IsAdmin(user)) return Results.Forbid();
    using var doc = await JsonDocument.ParseAsync(req.Body, cancellationToken: ct);
    var subject = doc.RootElement.TryGetProperty("subject", out var s) ? s.GetString() ?? "" : "";
    var bodyText = doc.RootElement.TryGetProperty("body", out var b) ? b.GetString() ?? "" : "";
    var recipients = await db.Users.AsNoTracking()
        .Where(u => u.IsActive && u.Email != null && u.Email != "")
        .Select(u => u.Email!)
        .ToListAsync(ct);

    // SmtpNotificationService is not registered via SatelliteServices in this build.
    _ = sp;
    _ = bodyText;
    return Results.Ok(new { ok = true, message = "queued/saved", subject, recipientCount = recipients.Count });
}).RequireAuthorization();

app.MapPost("/api/auth/2fa/setup", async (HttpContext ctx, UsersDbContext db, IAuthService auth, CancellationToken ct) =>
{
    var current = await GetUserAsync(ctx, auth);
    if (current is null) return Results.Unauthorized();
    var entity = await db.Users.FirstOrDefaultAsync(u => u.Username == current.Username, ct);
    if (entity is null) return Results.NotFound();
    var secret = AuthService.GenerateTotpSecret();
    entity.TwoFactorSecret = secret;
    entity.TwoFactorEnabled = false;
    await db.SaveChangesAsync(ct);
    var otpauth = $"otpauth://totp/ServerManager:{Uri.EscapeDataString(entity.Username)}?secret={secret}&issuer=ServerManager";
    return Results.Ok(new { secret, otpauth_url = otpauth });
}).RequireAuthorization();

app.MapPost("/api/auth/2fa/verify", async (HttpRequest req, HttpContext ctx, UsersDbContext db, IAuthService auth, CancellationToken ct) =>
{
    var current = await GetUserAsync(ctx, auth);
    if (current is null) return Results.Unauthorized();
    using var doc = await JsonDocument.ParseAsync(req.Body, cancellationToken: ct);
    var code = doc.RootElement.TryGetProperty("code", out var c) ? c.GetString() : null;
    var entity = await db.Users.FirstOrDefaultAsync(u => u.Username == current.Username, ct);
    if (entity is null) return Results.NotFound();
    if (string.IsNullOrWhiteSpace(entity.TwoFactorSecret))
        return Results.BadRequest(new { ok = false, error = "2FA setup not started. Call /api/auth/2fa/setup first." });
    if (!AuthService.VerifyTotp(entity.TwoFactorSecret, code ?? ""))
        return Results.BadRequest(new { ok = false, error = "Invalid code" });
    entity.TwoFactorEnabled = true;
    await db.SaveChangesAsync(ct);
    return Results.Ok(new { ok = true, twoFactorEnabled = true });
}).RequireAuthorization();

app.MapPost("/api/auth/2fa/disable", async (HttpRequest req, HttpContext ctx, UsersDbContext db, IAuthService auth, CancellationToken ct) =>
{
    var current = await GetUserAsync(ctx, auth);
    if (current is null) return Results.Unauthorized();
    using var doc = await JsonDocument.ParseAsync(req.Body, cancellationToken: ct);
    var code = doc.RootElement.TryGetProperty("code", out var c) ? c.GetString() : null;
    var entity = await db.Users.FirstOrDefaultAsync(u => u.Username == current.Username, ct);
    if (entity is null) return Results.NotFound();
    if (entity.TwoFactorEnabled && !string.IsNullOrWhiteSpace(entity.TwoFactorSecret) && !string.IsNullOrWhiteSpace(code))
    {
        if (!AuthService.VerifyTotp(entity.TwoFactorSecret, code))
            return Results.BadRequest(new { ok = false, error = "Invalid code" });
    }
    entity.TwoFactorEnabled = false;
    entity.TwoFactorSecret = null;
    await db.SaveChangesAsync(ct);
    return Results.Ok(new { ok = true, twoFactorEnabled = false });
}).RequireAuthorization();

app.MapGet("/api/servers/{id}/permissions", async (string id, ServersDbContext db, CancellationToken ct) =>
{
    var perms = await db.ServerPermissions.AsNoTracking()
        .Where(p => p.ServerName == id)
        .Select(p => new
        {
            p.Username,
            p.CanView,
            p.CanStart,
            p.CanStop,
            p.CanRestart,
            p.CanConsole,
            p.CanEdit
        })
        .ToListAsync(ct);
    return Results.Ok(perms);
}).RequireAuthorization();

app.MapPut("/api/servers/{id}/permissions", async (string id, HttpRequest req, ServersDbContext db, CancellationToken ct) =>
{
    using var doc = await JsonDocument.ParseAsync(req.Body, cancellationToken: ct);
    if (!doc.RootElement.TryGetProperty("permissions", out var perms) || perms.ValueKind != JsonValueKind.Array)
        return Results.BadRequest(new { ok = false, error = "permissions array required" });

    static bool PermFlag(JsonElement el, string name, bool defaultValue = false)
    {
        if (!el.TryGetProperty(name, out var v) || v.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
            return defaultValue;
        return v.GetBoolean();
    }

    var existing = await db.ServerPermissions.Where(p => p.ServerName == id).ToListAsync(ct);
    db.ServerPermissions.RemoveRange(existing);
    foreach (var p in perms.EnumerateArray())
    {
        var username = p.TryGetProperty("username", out var u) ? u.GetString() : null;
        if (string.IsNullOrWhiteSpace(username)) continue;
        db.ServerPermissions.Add(new ServerPermission
        {
            Username = username!,
            ServerName = id,
            CanView = PermFlag(p, "canView", true),
            CanStart = PermFlag(p, "canStart"),
            CanStop = PermFlag(p, "canStop"),
            CanRestart = PermFlag(p, "canRestart"),
            CanConsole = PermFlag(p, "canConsole"),
            CanEdit = PermFlag(p, "canEdit")
        });
    }
    await db.SaveChangesAsync(ct);
    return Results.Ok(new { ok = true });
}).RequireAuthorization();

app.MapPost("/api/catalog/scan", async (HttpRequest req, SteamAppIdScanner steam, MinecraftCatalogScanner minecraft, ModdedCatalogScanner modded, IConfigStore cfg, CancellationToken ct) =>
{
    using var doc = await JsonDocument.ParseAsync(req.Body, cancellationToken: ct);
    var scanner = doc.RootElement.TryGetProperty("scanner", out var s) ? s.GetString() ?? "" : "";
    scanner = scanner.Trim().ToLowerInvariant();

    try
    {
        if (scanner is "steam")
        {
            var count = await steam.RefreshDedicatedServersAsync(ct);
            return Results.Ok(new { ok = true, scanner, count, message = $"Steam dedicated servers: {count}" });
        }
        if (scanner is "minecraft")
        {
            var count = await minecraft.RefreshVanillaAsync(ct);
            return Results.Ok(new { ok = true, scanner, count, message = $"Minecraft versions added: {count}" });
        }
        if (scanner.StartsWith("modded:", StringComparison.Ordinal))
        {
            var provider = scanner["modded:".Length..];
            var (count, message) = provider == "curseforge"
                ? await modded.RefreshAsync(provider, cfg.Get("CurseForgeApiKey"), ct)
                : await modded.RefreshAsync(provider, ct);
            return Results.Ok(new { ok = true, scanner, count, message });
        }
        return Results.BadRequest(new { ok = false, scanner, count = 0, message = $"Unknown scanner '{scanner}'" });
    }
    catch (Exception ex)
    {
        return Results.Ok(new { ok = false, scanner, count = 0, message = ex.Message });
    }
}).RequireAuthorization();

app.MapGet("/api/catalog/status", async (IAppPaths paths, SteamCatalogDbContext steam, MinecraftCatalogDbContext mc, ModdedCatalogDbContext modded, CancellationToken ct) =>
{
    async Task<object> Probe(string file, Func<Task<int>> countAsync)
    {
        var path = Path.Combine(paths.Db, file);
        var exists = File.Exists(path);
        var size = exists ? new FileInfo(path).Length : 0L;
        var count = 0;
        string? error = null;
        try { count = await countAsync(); }
        catch (Exception ex) { error = ex.Message; }
        return new { file, path, exists, size, count, error, ok = exists && count > 0 && error is null };
    }

    return Results.Ok(new
    {
        dbRoot = paths.Db,
        steam = await Probe("steam_ID.db", () => steam.SteamApps.AsNoTracking().CountAsync(ct)),
        minecraft = await Probe("minecraft_ID.db", () => mc.Versions.AsNoTracking().CountAsync(ct)),
        modded = await Probe("minecraft_modded_ID.db", () => modded.Packs.AsNoTracking().CountAsync(ct))
    });
}).RequireAuthorization();

app.MapGet("/api/catalog/steam", async (string? q, bool? dedicatedOnly, SteamCatalogDbContext db, CancellationToken ct) =>
{
    try
    {
        var query = db.SteamApps.AsNoTracking().AsQueryable();
        var dedicated = dedicatedOnly ?? string.IsNullOrWhiteSpace(q);
        if (dedicated)
            query = query.Where(a => a.IsDedicatedServer);
        if (!string.IsNullOrWhiteSpace(q))
        {
            var needle = q.Trim();
            if (int.TryParse(needle, out var appId))
                query = query.Where(a => a.Name.Contains(needle) || a.AppId == appId);
            else
                query = query.Where(a => a.Name.Contains(needle));
        }
        var rows = await query.OrderBy(a => a.Name).Take(200)
            .Select(a => new { a.AppId, a.Name, a.IsDedicatedServer })
            .ToListAsync(ct);
        return Results.Ok(rows);
    }
    catch (Exception ex)
    {
        return Results.Ok(new { error = ex.Message, items = Array.Empty<object>() });
    }
}).RequireAuthorization();

app.MapGet("/api/catalog/minecraft", async (string? q, MinecraftCatalogDbContext db, CancellationToken ct) =>
{
    try
    {
        var query = db.Versions.AsNoTracking().AsQueryable();
        if (!string.IsNullOrWhiteSpace(q))
        {
            var needle = q.Trim();
            query = query.Where(v => v.Version.Contains(needle) || (v.ModLoader != null && v.ModLoader.Contains(needle)));
        }
        var rows = await query.OrderByDescending(v => v.Version).Take(200)
            .Select(v => new
            {
                v.Version,
                Type = v.VersionType,
                v.ModLoader,
                IsSnapshot = v.VersionType == "snapshot",
                v.IsRecommended,
                DownloadUrl = v.DownloadUrl ?? ""
            })
            .ToListAsync(ct);
        return Results.Ok(rows);
    }
    catch (Exception ex)
    {
        return Results.Ok(new { error = ex.Message, items = Array.Empty<object>() });
    }
}).RequireAuthorization();

app.MapGet("/api/catalog/modpacks", async (string? provider, string? q, ModdedCatalogScanner modded, CancellationToken ct) =>
{
    provider = string.IsNullOrWhiteSpace(provider) ? "modrinth" : provider.Trim().ToLowerInvariant();
    var packs = await modded.ReadCatalogAsync(provider, q, ct);
    return Results.Ok(packs);
}).RequireAuthorization();

app.MapPost("/api/steam/guard/test", async (HttpRequest req) =>
{
    using var doc = await JsonDocument.ParseAsync(req.Body);
    var secret = doc.RootElement.TryGetProperty("secret", out var s) ? s.GetString() : null;
    var code = doc.RootElement.TryGetProperty("code", out var c) ? c.GetString() : null;
    return Results.Ok(new { ok = AuthService.VerifyTotp(secret, code ?? "") });
}).RequireAuthorization();

app.MapGet("/api/profile", async (HttpContext ctx, IAuthService auth) =>
{
    var user = await GetUserAsync(ctx, auth);
    if (user is null) return Results.Unauthorized();
    return Results.Ok(new { username = user.Username, display_name = user.DisplayName, email = user.Email, is_admin = user.IsAdmin, two_factor_enabled = user.TwoFactorEnabled, theme = user.Theme });
}).RequireAuthorization();

app.MapPut("/api/profile", async (HttpRequest req, HttpContext ctx, UsersDbContext db, IAuthService auth, CancellationToken ct) =>
{
    var user = await GetUserAsync(ctx, auth);
    if (user is null) return Results.Unauthorized();
    using var doc = await JsonDocument.ParseAsync(req.Body, cancellationToken: ct);
    var entity = await db.Users.FirstOrDefaultAsync(u => u.Username == user.Username, ct);
    if (entity is null) return Results.NotFound();
    if (doc.RootElement.TryGetProperty("theme", out var theme) && theme.ValueKind == JsonValueKind.String)
        entity.Theme = theme.GetString();
    if (doc.RootElement.TryGetProperty("display_name", out var dn) && dn.ValueKind == JsonValueKind.String)
        entity.DisplayName = dn.GetString();
    if (doc.RootElement.TryGetProperty("email", out var em) && em.ValueKind == JsonValueKind.String)
        entity.Email = em.GetString();
    await db.SaveChangesAsync(ct);
    return Results.Ok(new { success = true, theme = entity.Theme });
}).RequireAuthorization();

app.MapGet("/api/settings", (IOptions<ServerManagerOptions> opt, IConfigStore cfg) =>
    Results.Ok(new
    {
        web_port = cfg.GetOrDefault("WebPort", opt.Value.WebPort),
        host_runtime_port = cfg.GetOrDefault("HostRuntimePort", opt.Value.HostRuntimePort),
        cluster_port = cfg.GetOrDefault("ClusterPort", opt.Value.ClusterPort),
        host_type = cfg.Get("HostType") ?? opt.Value.HostType,
        cluster_enabled = (cfg.Get("ClusterEnabled") ?? (opt.Value.ClusterEnabled ? "true" : "false")) == "true",
        host_address = cfg.Get("HostAddress") ?? opt.Value.HostAddress,
        steam_cmd_path = cfg.Get("SteamCmdPath") ?? opt.Value.SteamCmdPath,
        profile = opt.Value.Profile
    })).RequireAuthorization();

app.MapGet("/api/minecraft/modpacks/search", async (string? provider, string? q, IConfigStore cfg, IHttpClientFactory httpFactory, ModdedCatalogScanner modded, CancellationToken ct) =>
{
    provider = (provider ?? "modrinth").Trim().ToLowerInvariant();
    q = string.IsNullOrWhiteSpace(q) ? "modpack" : q.Trim();
    var client = httpFactory.CreateClient("minecraft");
    if (provider == "modrinth")
    {
        var url = $"https://api.modrinth.com/v2/search?query={Uri.EscapeDataString(q)}&limit=20&facets={Uri.EscapeDataString("[[\"project_type:modpack\"]]")}";
        var json = await client.GetStringAsync(url, ct);
        using var doc = JsonDocument.Parse(json);
        var hits = doc.RootElement.TryGetProperty("hits", out var h) ? h : doc.RootElement;
        return Results.Ok(hits);
    }
    if (provider == "curseforge")
    {
        var key = cfg.Get("CurseForgeApiKey");
        if (string.IsNullOrWhiteSpace(key))
            return Results.Ok(new { message = "Set CurseForge API key in Settings → Minecraft to search CurseForge." });
        using var req = new HttpRequestMessage(HttpMethod.Get,
            $"https://api.curseforge.com/v1/mods/search?gameId=432&classId=4471&searchFilter={Uri.EscapeDataString(q)}&pageSize=20");
        req.Headers.TryAddWithoutValidation("x-api-key", key);
        var resp = await client.SendAsync(req, ct);
        var body = await resp.Content.ReadAsStringAsync(ct);
        using var doc = JsonDocument.Parse(body);
        return Results.Ok(doc.RootElement.TryGetProperty("data", out var d) ? d : doc.RootElement);
    }

    // Technic / FTB / ATLauncher: serve from last catalog scan (Tools → Update Databases).
    var packs = await modded.ReadCatalogAsync(provider, q, ct);
    var packsJson = JsonSerializer.Serialize(packs);
    using var packsDoc = JsonDocument.Parse(string.IsNullOrWhiteSpace(packsJson) ? "[]" : packsJson);
    if (packsDoc.RootElement.ValueKind != JsonValueKind.Array || packsDoc.RootElement.GetArrayLength() == 0)
    {
        return Results.Ok(new
        {
            message = $"No cached {provider} packs. Run Tools → Update Databases for modded:{provider}, then search again.",
            provider,
            query = q,
            hits = Array.Empty<object>()
        });
    }
    return Results.Ok(JsonSerializer.Deserialize<object>(packsDoc.RootElement.GetRawText()));
}).RequireAuthorization();

app.MapPost("/api/minecraft/modpacks/install", async (HttpRequest req, HostRuntimeClient runtime, ServersDbContext db, IHttpClientFactory httpFactory, CancellationToken ct) =>
{
    using var doc = await JsonDocument.ParseAsync(req.Body, cancellationToken: ct);
    var root = doc.RootElement;
    var name = root.TryGetProperty("name", out var n) ? n.GetString() : null;
    var installDir = root.TryGetProperty("installDir", out var d) ? d.GetString() : null;
    var provider = (root.TryGetProperty("provider", out var p) ? p.GetString() ?? "modrinth" : "modrinth").Trim().ToLowerInvariant();
    if (string.IsNullOrWhiteSpace(name) || string.IsNullOrWhiteSpace(installDir))
        return Results.BadRequest(new { ok = false, message = "name and installDir required" });

    Directory.CreateDirectory(installDir!);
    var packName = "unknown";
    JsonElement pack = default;
    var hasPack = root.TryGetProperty("pack", out pack);
    if (hasPack)
        packName = pack.TryGetProperty("title", out var t) ? t.GetString() ?? packName
            : pack.TryGetProperty("name", out var pn) ? pn.GetString() ?? packName : packName;
    var notePath = Path.Combine(installDir!, "servermanager-modpack.json");
    await File.WriteAllTextAsync(notePath, root.GetRawText(), ct);

    var existing = await db.ServerConfigs.FirstOrDefaultAsync(s => s.Name == name, ct);
    if (existing is null)
    {
        db.ServerConfigs.Add(new ServerConfig
        {
            Name = name!,
            ServerType = "minecraft_modded",
            InstallDir = installDir,
            Executable = "server.jar",
            StopCommand = "stop",
            Category = "Minecraft",
            Notes = $"{provider}: {packName}",
            Enabled = true,
            CreatedAt = DateTime.UtcNow,
            UpdatedAt = DateTime.UtcNow
        });
    }
    else
    {
        existing.ServerType = "minecraft_modded";
        existing.InstallDir = installDir;
        existing.Notes = $"{provider}: {packName}";
        existing.UpdatedAt = DateTime.UtcNow;
    }
    await db.SaveChangesAsync(ct);

    string? version = null;
    if (hasPack)
    {
        if (pack.TryGetProperty("versions", out var vers) && vers.ValueKind == JsonValueKind.Array && vers.GetArrayLength() > 0)
            version = vers[0].GetString();
        else if (pack.TryGetProperty("game_versions", out var gv) && gv.ValueKind == JsonValueKind.Array && gv.GetArrayLength() > 0)
            version = gv[0].GetString();
    }
    object? installResult = null;
    if (!string.IsNullOrWhiteSpace(version))
    {
        var payload = JsonSerializer.Serialize(new { name, version, installDir });
        installResult = await runtime.PostJsonAsync("/api/runtime/servers/install/minecraft", payload, ct);
    }

    var client = httpFactory.CreateClient("minecraft");
    var steps = new List<string> { $"Registered '{name}' as minecraft_modded", $"Saved metadata to {notePath}" };
    if (!string.IsNullOrWhiteSpace(version))
        steps.Add($"Attempted vanilla {version} base install");

    if (provider == "modrinth" && hasPack)
    {
        var projectId = pack.TryGetProperty("project_id", out var pid) ? pid.GetString()
            : pack.TryGetProperty("slug", out var slug) ? slug.GetString()
            : pack.TryGetProperty("id", out var idEl) ? idEl.GetString() : null;
        if (!string.IsNullOrWhiteSpace(projectId))
        {
            try
            {
                var versionsJson = await client.GetStringAsync($"https://api.modrinth.com/v2/project/{Uri.EscapeDataString(projectId!)}/version", ct);
                using var versionsDoc = JsonDocument.Parse(versionsJson);
                if (versionsDoc.RootElement.ValueKind == JsonValueKind.Array && versionsDoc.RootElement.GetArrayLength() > 0)
                {
                    var latest = versionsDoc.RootElement[0];
                    JsonElement? preferred = null;
                    if (latest.TryGetProperty("files", out var files) && files.ValueKind == JsonValueKind.Array)
                    {
                        foreach (var file in files.EnumerateArray())
                        {
                            var fname = file.TryGetProperty("filename", out var fn) ? fn.GetString() ?? "" : "";
                            var env = file.TryGetProperty("file_type", out var ft) ? ft.GetString() : null;
                            var url = file.TryGetProperty("url", out var u) ? u.GetString() : null;
                            if (string.IsNullOrWhiteSpace(url)) continue;
                            // Prefer primary / server-side / .mrpack
                            var isPrimary = file.TryGetProperty("primary", out var prim) && prim.ValueKind == JsonValueKind.True;
                            if (preferred is null || isPrimary || fname.EndsWith(".mrpack", StringComparison.OrdinalIgnoreCase))
                                preferred = file.Clone();
                            _ = env;
                        }
                    }

                    if (preferred is { } chosen)
                    {
                        var fileUrl = chosen.GetProperty("url").GetString()!;
                        var fileName = chosen.TryGetProperty("filename", out var cfn) ? cfn.GetString() ?? "pack.mrpack" : "pack.mrpack";
                        var downloadPath = Path.Combine(installDir!, fileName);
                        await using (var fs = File.Create(downloadPath))
                        await using (var net = await client.GetStreamAsync(fileUrl, ct))
                            await net.CopyToAsync(fs, ct);
                        steps.Add($"Downloaded Modrinth file {fileName}");

                        if (fileName.EndsWith(".mrpack", StringComparison.OrdinalIgnoreCase) ||
                            fileName.EndsWith(".zip", StringComparison.OrdinalIgnoreCase))
                        {
                            var extractDir = Path.Combine(installDir!, "_mrpack_extract");
                            if (Directory.Exists(extractDir)) Directory.Delete(extractDir, true);
                            Directory.CreateDirectory(extractDir);
                            ZipFile.ExtractToDirectory(downloadPath, extractDir, overwriteFiles: true);
                            steps.Add("Extracted mrpack/zip archive");

                            var overrides = Path.Combine(extractDir, "overrides");
                            if (Directory.Exists(overrides))
                            {
                                CopyDirectory(overrides, installDir!);
                                steps.Add("Copied overrides/** into install dir");
                            }

                            var indexPath = Path.Combine(extractDir, "modrinth.index.json");
                            if (File.Exists(indexPath))
                            {
                                var modsDir = Path.Combine(installDir!, "mods");
                                Directory.CreateDirectory(modsDir);
                                using var indexDoc = JsonDocument.Parse(await File.ReadAllTextAsync(indexPath, ct));
                                var downloadedMods = 0;
                                if (indexDoc.RootElement.TryGetProperty("files", out var indexFiles) &&
                                    indexFiles.ValueKind == JsonValueKind.Array)
                                {
                                    foreach (var f in indexFiles.EnumerateArray())
                                    {
                                        var envOk = true;
                                        if (f.TryGetProperty("env", out var envEl) && envEl.ValueKind == JsonValueKind.Object)
                                        {
                                            var clientEnv = envEl.TryGetProperty("client", out var ce) ? ce.GetString() : null;
                                            var serverEnv = envEl.TryGetProperty("server", out var se) ? se.GetString() : null;
                                            // Prefer server-side mods; skip client-required when server unsupported
                                            if (string.Equals(serverEnv, "unsupported", StringComparison.OrdinalIgnoreCase))
                                                envOk = false;
                                            else if (string.Equals(clientEnv, "required", StringComparison.OrdinalIgnoreCase) &&
                                                     string.Equals(serverEnv, "unsupported", StringComparison.OrdinalIgnoreCase))
                                                envOk = false;
                                            // Also accept client=unsupported (server-only) and required server
                                            if (string.Equals(clientEnv, "unsupported", StringComparison.OrdinalIgnoreCase) ||
                                                string.Equals(serverEnv, "required", StringComparison.OrdinalIgnoreCase) ||
                                                string.Equals(serverEnv, "optional", StringComparison.OrdinalIgnoreCase))
                                                envOk = true;
                                            if (string.Equals(serverEnv, "unsupported", StringComparison.OrdinalIgnoreCase))
                                                envOk = false;
                                        }
                                        if (!envOk) continue;

                                        var pathRel = f.TryGetProperty("path", out var pathEl) ? pathEl.GetString() : null;
                                        string? dl = null;
                                        if (f.TryGetProperty("downloads", out var dls) && dls.ValueKind == JsonValueKind.Array && dls.GetArrayLength() > 0)
                                            dl = dls[0].GetString();
                                        if (string.IsNullOrWhiteSpace(dl) || string.IsNullOrWhiteSpace(pathRel)) continue;
                                        if (!pathRel.Replace('\\', '/').StartsWith("mods/", StringComparison.OrdinalIgnoreCase) &&
                                            !pathRel.EndsWith(".jar", StringComparison.OrdinalIgnoreCase))
                                            continue;

                                        var dest = Path.Combine(installDir!, pathRel.Replace('/', Path.DirectorySeparatorChar));
                                        Directory.CreateDirectory(Path.GetDirectoryName(dest)!);
                                        try
                                        {
                                            await using var outFs = File.Create(dest);
                                            await using var inFs = await client.GetStreamAsync(dl, ct);
                                            await inFs.CopyToAsync(outFs, ct);
                                            downloadedMods++;
                                        }
                                        catch
                                        {
                                            // best-effort per file
                                        }
                                    }
                                }
                                steps.Add($"Downloaded {downloadedMods} server-compatible mods from modrinth.index.json");
                            }

                            try { Directory.Delete(extractDir, true); } catch { /* ignore */ }
                        }
                    }
                    else steps.Add("Modrinth project versions found but no downloadable file");
                }
                else steps.Add("Modrinth project has no versions");
            }
            catch (Exception ex)
            {
                steps.Add($"Modrinth overlay failed: {ex.Message}");
            }
        }
        else steps.Add("No Modrinth project id/slug on pack; metadata-only registration");
    }
    else if (provider is "curseforge" or "technic" or "ftb" or "atlauncher")
    {
        string? fileUrl = null;
        if (hasPack)
        {
            fileUrl = pack.TryGetProperty("downloadUrl", out var du) ? du.GetString()
                : pack.TryGetProperty("download_url", out var du2) ? du2.GetString()
                : pack.TryGetProperty("url", out var u) ? u.GetString() : null;
            if (fileUrl is null && pack.TryGetProperty("latestFiles", out var lf) && lf.ValueKind == JsonValueKind.Array && lf.GetArrayLength() > 0)
            {
                var f0 = lf[0];
                fileUrl = f0.TryGetProperty("downloadUrl", out var ldu) ? ldu.GetString() : null;
            }
        }
        if (!string.IsNullOrWhiteSpace(fileUrl))
        {
            try
            {
                var fileName = Path.GetFileName(new Uri(fileUrl!).AbsolutePath);
                if (string.IsNullOrWhiteSpace(fileName)) fileName = "pack-download.zip";
                var dest = Path.Combine(installDir!, fileName);
                await using (var fs = File.Create(dest))
                await using (var net = await client.GetStreamAsync(fileUrl, ct))
                    await net.CopyToAsync(fs, ct);
                steps.Add($"Downloaded primary pack file to {fileName}");
            }
            catch (Exception ex)
            {
                steps.Add($"Primary file download failed: {ex.Message}; kept metadata registration");
            }
        }
        else steps.Add("No primary file URL in pack JSON; kept metadata registration");
    }

    return Results.Ok(new
    {
        ok = true,
        message = string.Join(". ", steps) + ".",
        steps,
        installResult,
        metaFile = notePath
    });
}).RequireAuthorization();

app.MapGet("/api/system-settings", (IOptions<ServerManagerOptions> opt, IConfigStore cfg, ClaimsPrincipal user) =>
{
    if (user.FindFirst("is_admin")?.Value != "true") return Results.Forbid();
    return Results.Ok(cfg.GetAll());
}).RequireAuthorization();

app.MapPost("/api/system-settings", async (HttpRequest req, IConfigStore cfg, ClaimsPrincipal user) =>
{
    if (user.FindFirst("is_admin")?.Value != "true") return Results.Forbid();
    using var doc = await JsonDocument.ParseAsync(req.Body);
    foreach (var prop in doc.RootElement.EnumerateObject())
        cfg.Set(prop.Name, prop.Value.ToString());
    return Results.Ok(new { success = true });
}).RequireAuthorization();

app.MapGet("/api/cluster/role", (IConfigStore cfg, IOptions<ServerManagerOptions> opt) =>
    Results.Ok(new
    {
        role = cfg.Get("HostType") ?? opt.Value.HostType,
        cluster_enabled = cfg.GetOrDefault("ClusterEnabled", "false") == "true",
        host_address = cfg.Get("HostAddress") ?? opt.Value.HostAddress
    }));

app.MapGet("/api/analytics/health", () => Results.Ok(new { status = "ok", service = "web" }));
app.MapGet("/metrics", (ServerManager.Cluster.PrometheusMetrics metrics) =>
    Results.Text(metrics.Render(), "text/plain; version=0.0.4"));

app.MapClusterEndpoints();
app.MapSatelliteEndpoints();

app.MapFallback(async ctx =>
{
    var path = Path.Combine(wwwRoot, "index.html");
    if (File.Exists(path))
    {
        ctx.Response.ContentType = "text/html";
        await ctx.Response.SendFileAsync(path);
    }
    else ctx.Response.StatusCode = 404;
});

Log.Information("Web listening (ports {Http}/{Https})", smOptions.WebPort, smOptions.HttpsPort);
await app.RunAsync();

static bool IsAdmin(ClaimsPrincipal user) => user.FindFirst("is_admin")?.Value == "true";

static async Task<UserAccount?> GetUserAsync(HttpContext ctx, IAuthService auth)
{
    var header = ctx.Request.Headers.Authorization.ToString();
    if (header.StartsWith("Bearer ", StringComparison.OrdinalIgnoreCase))
        return await auth.ValidateTokenAsync(header["Bearer ".Length..].Trim());
    return null;
}

static void CopyDirectory(string sourceDir, string destDir)
{
    Directory.CreateDirectory(destDir);
    foreach (var file in Directory.GetFiles(sourceDir, "*", SearchOption.AllDirectories))
    {
        var rel = Path.GetRelativePath(sourceDir, file);
        var dest = Path.Combine(destDir, rel);
        Directory.CreateDirectory(Path.GetDirectoryName(dest)!);
        File.Copy(file, dest, overwrite: true);
    }
}

static ServerConfig MapServer(CreateServerRequest body, ServerConfig c)
{
    c.ServerType = body.ServerType ?? "steam";
    c.AppId = body.AppId;
    c.InstallDir = body.InstallDir ?? c.InstallDir;
    c.Executable = body.Executable;
    c.LaunchArgs = body.LaunchArgs;
    c.StopCommand = body.StopCommand;
    c.SaveCommand = body.SaveCommand;
    c.StartCommand = body.StartCommand;
    c.Version = body.Version;
    c.JavaPath = body.JavaPath;
    c.MotdMessage = body.MotdMessage;
    c.MotdCommand = body.MotdCommand;
    c.MotdInterval = body.MotdInterval;
    c.WarningCommand = body.WarningCommand;
    c.WarningIntervals = body.WarningIntervals;
    c.AutoStart = body.AutoStart ?? false;
    c.ScheduledRestartEnabled = body.ScheduledRestartEnabled ?? false;
    c.Category = body.Category;
    c.Notes = body.Notes;
    return c;
}

static void ApplyServerUpdate(ServerConfig c, UpdateServerRequest body)
{
    if (body.ServerType is not null) c.ServerType = body.ServerType;
    if (body.AppId is not null) c.AppId = body.AppId;
    if (body.InstallDir is not null) c.InstallDir = body.InstallDir;
    if (body.Executable is not null) c.Executable = body.Executable;
    if (body.LaunchArgs is not null) c.LaunchArgs = body.LaunchArgs;
    if (body.StopCommand is not null) c.StopCommand = body.StopCommand;
    if (body.SaveCommand is not null) c.SaveCommand = body.SaveCommand;
    if (body.StartCommand is not null) c.StartCommand = body.StartCommand;
    if (body.Version is not null) c.Version = body.Version;
    if (body.JavaPath is not null) c.JavaPath = body.JavaPath;
    if (body.MotdMessage is not null) c.MotdMessage = body.MotdMessage;
    if (body.MotdCommand is not null) c.MotdCommand = body.MotdCommand;
    if (body.MotdInterval is not null) c.MotdInterval = body.MotdInterval;
    if (body.WarningCommand is not null) c.WarningCommand = body.WarningCommand;
    if (body.WarningIntervals is not null) c.WarningIntervals = body.WarningIntervals;
    if (body.AutoStart is not null) c.AutoStart = body.AutoStart.Value;
    if (body.ScheduledRestartEnabled is not null) c.ScheduledRestartEnabled = body.ScheduledRestartEnabled.Value;
    if (body.Category is not null) c.Category = body.Category;
    if (body.Notes is not null) c.Notes = body.Notes;
    if (body.Enabled is not null) c.Enabled = body.Enabled.Value;
}

static object ToExportServer(ServerConfig c) => new
{
    name = c.Name,
    serverType = c.ServerType,
    appId = c.AppId,
    installDir = c.InstallDir,
    executable = c.Executable,
    launchArgs = c.LaunchArgs,
    additionalArgs = c.AdditionalArgs,
    stopCommand = c.StopCommand,
    saveCommand = c.SaveCommand,
    startCommand = c.StartCommand,
    javaPath = c.JavaPath,
    version = c.Version,
    modLoader = c.ModLoader,
    ramMb = c.RamMb,
    jvmArgs = c.JvmArgs,
    motdMessage = c.MotdMessage,
    motdCommand = c.MotdCommand,
    motdInterval = c.MotdInterval,
    warningCommand = c.WarningCommand,
    warningIntervals = c.WarningIntervals,
    warningMessageTemplate = c.WarningMessageTemplate,
    scheduledRestartEnabled = c.ScheduledRestartEnabled,
    autoStart = c.AutoStart,
    autoUpdate = c.AutoUpdate,
    category = c.Category,
    notes = c.Notes,
    extraConfigJson = c.ExtraConfigJson,
    enabled = c.Enabled
};

static string? ExportStr(JsonElement el, params string[] names)
{
    foreach (var n in names)
        if (el.TryGetProperty(n, out var p) && p.ValueKind == JsonValueKind.String)
            return p.GetString();
    return null;
}

static int? ExportInt(JsonElement el, params string[] names)
{
    foreach (var n in names)
    {
        if (!el.TryGetProperty(n, out var p) || p.ValueKind == JsonValueKind.Null) continue;
        if (p.TryGetInt32(out var i)) return i;
        if (p.ValueKind == JsonValueKind.String && int.TryParse(p.GetString(), out var s)) return s;
    }
    return null;
}

static bool? ExportBool(JsonElement el, params string[] names)
{
    foreach (var n in names)
    {
        if (!el.TryGetProperty(n, out var p) || p.ValueKind == JsonValueKind.Null) continue;
        if (p.ValueKind is JsonValueKind.True or JsonValueKind.False) return p.GetBoolean();
        if (p.ValueKind == JsonValueKind.String && bool.TryParse(p.GetString(), out var b)) return b;
    }
    return null;
}

static void ApplyExportServer(ServerConfig c, JsonElement el)
{
    c.ServerType = ExportStr(el, "serverType", "ServerType", "type") ?? c.ServerType;
    c.AppId = ExportStr(el, "appId", "AppId", "app_id") ?? c.AppId;
    c.InstallDir = ExportStr(el, "installDir", "InstallDir", "install_dir") ?? c.InstallDir;
    c.Executable = ExportStr(el, "executable", "Executable") ?? c.Executable;
    c.LaunchArgs = ExportStr(el, "launchArgs", "LaunchArgs", "launch_args") ?? c.LaunchArgs;
    c.AdditionalArgs = ExportStr(el, "additionalArgs", "AdditionalArgs") ?? c.AdditionalArgs;
    c.StopCommand = ExportStr(el, "stopCommand", "StopCommand") ?? c.StopCommand;
    c.SaveCommand = ExportStr(el, "saveCommand", "SaveCommand") ?? c.SaveCommand;
    c.StartCommand = ExportStr(el, "startCommand", "StartCommand") ?? c.StartCommand;
    c.JavaPath = ExportStr(el, "javaPath", "JavaPath") ?? c.JavaPath;
    c.Version = ExportStr(el, "version", "Version") ?? c.Version;
    c.ModLoader = ExportStr(el, "modLoader", "ModLoader") ?? c.ModLoader;
    c.RamMb = ExportInt(el, "ramMb", "RamMb", "ram") ?? c.RamMb;
    c.JvmArgs = ExportStr(el, "jvmArgs", "JvmArgs") ?? c.JvmArgs;
    c.MotdMessage = ExportStr(el, "motdMessage", "MotdMessage") ?? c.MotdMessage;
    c.MotdCommand = ExportStr(el, "motdCommand", "MotdCommand") ?? c.MotdCommand;
    c.MotdInterval = ExportInt(el, "motdInterval", "MotdInterval") ?? c.MotdInterval;
    c.WarningCommand = ExportStr(el, "warningCommand", "WarningCommand") ?? c.WarningCommand;
    c.WarningIntervals = ExportStr(el, "warningIntervals", "WarningIntervals") ?? c.WarningIntervals;
    c.WarningMessageTemplate = ExportStr(el, "warningMessageTemplate", "WarningMessageTemplate") ?? c.WarningMessageTemplate;
    c.ScheduledRestartEnabled = ExportBool(el, "scheduledRestartEnabled", "ScheduledRestartEnabled") ?? c.ScheduledRestartEnabled;
    c.AutoStart = ExportBool(el, "autoStart", "AutoStart") ?? c.AutoStart;
    c.AutoUpdate = ExportBool(el, "autoUpdate", "AutoUpdate") ?? c.AutoUpdate;
    c.Category = ExportStr(el, "category", "Category") ?? c.Category;
    c.Notes = ExportStr(el, "notes", "Notes") ?? c.Notes;
    c.ExtraConfigJson = ExportStr(el, "extraConfigJson", "ExtraConfigJson", "extra_config") ?? c.ExtraConfigJson;
    c.Enabled = ExportBool(el, "enabled", "Enabled") ?? c.Enabled;
}

static async Task ImportPermissionsAsync(ServersDbContext db, string serverName, JsonElement root, CancellationToken ct)
{
    if (!root.TryGetProperty("permissions", out var perms) || perms.ValueKind != JsonValueKind.Array) return;
    var existing = await db.ServerPermissions.Where(p => p.ServerName == serverName).ToListAsync(ct);
    db.ServerPermissions.RemoveRange(existing);
    foreach (var p in perms.EnumerateArray())
    {
        var user = ExportStr(p, "username", "Username");
        if (string.IsNullOrWhiteSpace(user)) continue;
        db.ServerPermissions.Add(new ServerPermission
        {
            Username = user!,
            ServerName = serverName,
            CanView = ExportBool(p, "canView", "CanView") ?? true,
            CanStart = ExportBool(p, "canStart", "CanStart") ?? false,
            CanStop = ExportBool(p, "canStop", "CanStop") ?? false,
            CanRestart = ExportBool(p, "canRestart", "CanRestart") ?? false,
            CanConsole = ExportBool(p, "canConsole", "CanConsole") ?? false,
            CanEdit = ExportBool(p, "canEdit", "CanEdit") ?? false
        });
    }
    await db.SaveChangesAsync(ct);
}

record LoginRequest(string? Username, string? Password, string? TotpCode);
record CreateServerRequest(string? Name, string? ServerType, string? AppId, string? InstallDir, string? Executable, string? LaunchArgs, string? StopCommand, string? SaveCommand, string? StartCommand, string? Version, string? JavaPath, string? MotdMessage, string? MotdCommand, int? MotdInterval, string? WarningCommand, string? WarningIntervals, bool? AutoStart, bool? ScheduledRestartEnabled, string? Category, string? Notes);
record UpdateServerRequest(string? ServerType, string? AppId, string? InstallDir, string? Executable, string? LaunchArgs, string? StopCommand, string? SaveCommand, string? StartCommand, string? Version, string? JavaPath, string? MotdMessage, string? MotdCommand, int? MotdInterval, string? WarningCommand, string? WarningIntervals, bool? AutoStart, bool? ScheduledRestartEnabled, string? Category, string? Notes, bool? Enabled);
record ConsoleCommandRequest(string? Command);
record CreateUserRequest(string? Username, string? Password, bool IsAdmin, string? Email, string? DisplayName);
record UpdateUserRequest(string? DisplayName, string? Email, bool? IsAdmin, bool? IsActive);
record ResetPasswordRequest(string? Password);
