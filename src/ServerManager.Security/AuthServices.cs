using System.Collections.Concurrent;
using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Text;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.Tokens;
using OtpNet;
using ServerManager.Core.Paths;
using ServerManager.Data;
using ServerManager.Data.Entities;

namespace ServerManager.Security;

public sealed class JwtOptions
{
    public string Issuer { get; set; } = "ServerManager";
    public string Audience { get; set; } = "ServerManager";
    public string SigningKey { get; set; } = "CHANGE_ME_ServerManager_Dev_Key_32chars_min!";
    /// <summary>HostUI stays open for days; short tokens caused constant expired-JWT log spam.</summary>
    public int ExpiryHours { get; set; } = 168; // 7 days
}

public interface IAuthService
{
    Task<AuthResult> LoginAsync(string username, string password, string? totpCode = null, CancellationToken ct = default);
    Task<UserAccount?> ValidateTokenAsync(string token, CancellationToken ct = default);
    ClaimsPrincipal? ValidateTokenPrincipal(string token);
}

public sealed record AuthResult(bool Success, string? Token, string? Error, bool RequiresTwoFactor = false, UserAccount? User = null);

public sealed class AuthService : IAuthService
{
    private readonly UsersDbContext _db;
    private readonly JwtOptions _jwt;
    private readonly ILogger<AuthService> _logger;
    private readonly AccountLockoutService _lockout;

    public AuthService(UsersDbContext db, IOptions<JwtOptions> jwt, AccountLockoutService lockout, ILogger<AuthService> logger)
    {
        _db = db;
        _jwt = jwt.Value;
        _lockout = lockout;
        _logger = logger;
    }

    public async Task<AuthResult> LoginAsync(string username, string password, string? totpCode = null, CancellationToken ct = default)
    {
        if (_lockout.IsLocked(username))
            return new AuthResult(false, null, "Account locked. Try again later.");

        var user = await _db.Users.FirstOrDefaultAsync(u => u.Username == username, ct);
        if (user is null || !user.IsActive || !BCrypt.Net.BCrypt.Verify(password, user.PasswordHash))
        {
            _lockout.RegisterFailure(username);
            return new AuthResult(false, null, "Invalid username or password.");
        }

        if (user.TwoFactorEnabled)
        {
            if (string.IsNullOrWhiteSpace(totpCode))
                return new AuthResult(false, null, "Two-factor code required.", RequiresTwoFactor: true, User: user);

            if (!VerifyTotp(user.TwoFactorSecret, totpCode))
            {
                _lockout.RegisterFailure(username);
                return new AuthResult(false, null, "Invalid two-factor code.", RequiresTwoFactor: true);
            }
        }

        _lockout.Reset(username);
        user.LastLoginAt = DateTime.UtcNow;
        await _db.SaveChangesAsync(ct);
        var token = CreateToken(user);
        _logger.LogInformation("User {User} logged in", username);
        return new AuthResult(true, token, null, User: user);
    }

    public ClaimsPrincipal? ValidateTokenPrincipal(string token)
    {
        var handler = new JwtSecurityTokenHandler();
        try
        {
            return handler.ValidateToken(token, TokenValidationParameters(), out _);
        }
        catch
        {
            return null;
        }
    }

    public async Task<UserAccount?> ValidateTokenAsync(string token, CancellationToken ct = default)
    {
        var principal = ValidateTokenPrincipal(token);
        var name = principal?.Identity?.Name;
        if (name is null) return null;
        return await _db.Users.FirstOrDefaultAsync(u => u.Username == name && u.IsActive, ct);
    }

    private string CreateToken(UserAccount user)
    {
        var claims = new List<Claim>
        {
            new(ClaimTypes.Name, user.Username),
            new(ClaimTypes.NameIdentifier, user.Id.ToString()),
            new("is_admin", user.IsAdmin ? "true" : "false")
        };
        if (user.IsAdmin) claims.Add(new Claim(ClaimTypes.Role, "Admin"));

        var key = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(_jwt.SigningKey));
        var creds = new SigningCredentials(key, SecurityAlgorithms.HmacSha256);
        var token = new JwtSecurityToken(
            issuer: _jwt.Issuer,
            audience: _jwt.Audience,
            claims: claims,
            expires: DateTime.UtcNow.AddHours(_jwt.ExpiryHours),
            signingCredentials: creds);
        return new JwtSecurityTokenHandler().WriteToken(token);
    }

    public TokenValidationParameters TokenValidationParameters() => new()
    {
        ValidateIssuer = true,
        ValidateAudience = true,
        ValidateLifetime = true,
        ValidateIssuerSigningKey = true,
        ValidIssuer = _jwt.Issuer,
        ValidAudience = _jwt.Audience,
        IssuerSigningKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(_jwt.SigningKey))
    };

    public static bool VerifyTotp(string? secret, string code)
    {
        if (string.IsNullOrWhiteSpace(secret)) return false;
        var totp = new Totp(Base32Encoding.ToBytes(secret));
        return totp.VerifyTotp(code.Trim(), out _, new VerificationWindow(1, 1));
    }

    public static string GenerateTotpSecret() => Base32Encoding.ToString(KeyGeneration.GenerateRandomKey(20));
}

public sealed class AccountLockoutService
{
    private readonly ConcurrentDictionary<string, (int Failures, DateTime? LockedUntil)> _state = new(StringComparer.OrdinalIgnoreCase);
    private const int MaxFailures = 5;
    private static readonly TimeSpan LockDuration = TimeSpan.FromMinutes(15);

    public bool IsLocked(string username)
    {
        if (!_state.TryGetValue(username, out var s) || s.LockedUntil is null) return false;
        if (DateTime.UtcNow >= s.LockedUntil)
        {
            _state.TryRemove(username, out _);
            return false;
        }
        return true;
    }

    public void RegisterFailure(string username)
    {
        _state.AddOrUpdate(username,
            _ => (1, null),
            (_, cur) =>
            {
                var failures = cur.Failures + 1;
                DateTime? locked = failures >= MaxFailures ? DateTime.UtcNow.Add(LockDuration) : cur.LockedUntil;
                return (failures, locked);
            });
    }

    public void Reset(string username) => _state.TryRemove(username, out _);

    /// <summary>Clears all in-memory lockouts (e.g. after admin recovery).</summary>
    public void ResetAll() => _state.Clear();
}

public sealed class SecretProtector
{
    private readonly IDataProtector _protector;

    public SecretProtector(IDataProtectionProvider provider)
    {
        _protector = provider.CreateProtector("ServerManager.SteamCredentials");
    }

    public string Protect(string plaintext) => _protector.Protect(plaintext);
    public string Unprotect(string protectedData) => _protector.Unprotect(protectedData);
}

public sealed class RateLimiter
{
    private readonly ConcurrentDictionary<string, Queue<DateTime>> _hits = new();

    public bool Allow(string key, int maxPerWindow, TimeSpan window)
    {
        var q = _hits.GetOrAdd(key, _ => new Queue<DateTime>());
        lock (q)
        {
            var now = DateTime.UtcNow;
            while (q.Count > 0 && now - q.Peek() > window) q.Dequeue();
            if (q.Count >= maxPerWindow) return false;
            q.Enqueue(now);
            return true;
        }
    }
}

public static class SecurityServiceCollectionExtensions
{
    public static IServiceCollection AddServerManagerSecurity(this IServiceCollection services)
    {
        services.AddDataProtection()
            .PersistKeysToFileSystem(new DirectoryInfo(Path.Combine(AppContext.BaseDirectory, "dpkeys")))
            .SetApplicationName("ServerManager");

        services.Configure<JwtOptions>(_ => { });
        services.AddSingleton<AccountLockoutService>();
        services.AddSingleton<RateLimiter>();
        services.AddSingleton<SecretProtector>();
        services.AddScoped<IAuthService, AuthService>();
        services.AddScoped<AuthService>();
        return services;
    }
}

public static class SslCertificateHelper
{
    public static (string CertPath, string KeyPath) EnsureSelfSigned(IAppPaths paths, string commonName = "localhost")
    {
        paths.EnsureDirectories();
        var certPath = Path.Combine(paths.Ssl, "server.crt");
        var keyPath = Path.Combine(paths.Ssl, "server.key");
        var pfxPath = Path.Combine(paths.Ssl, "server.pfx");

        if (File.Exists(pfxPath)) return (certPath, keyPath);

        // Generate via openssl if available; otherwise create a development certificate note file.
        try
        {
            using var rsa = System.Security.Cryptography.RSA.Create(2048);
            var req = new System.Security.Cryptography.X509Certificates.CertificateRequest(
                $"CN={commonName}", rsa, System.Security.Cryptography.HashAlgorithmName.SHA256,
                System.Security.Cryptography.RSASignaturePadding.Pkcs1);
            req.CertificateExtensions.Add(
                new System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension(false, false, 0, false));
            using var cert = req.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddYears(5));
            var pfx = cert.Export(System.Security.Cryptography.X509Certificates.X509ContentType.Pfx, "servermanager");
            File.WriteAllBytes(pfxPath, pfx);
            File.WriteAllText(certPath, "PFX generated at server.pfx (password: servermanager)");
            File.WriteAllText(keyPath, "See server.pfx");
        }
        catch
        {
            File.WriteAllText(Path.Combine(paths.Ssl, "README.txt"), "Place server.pfx here for HTTPS.");
        }

        return (certPath, keyPath);
    }

    public static string? GetPfxPath(IAppPaths paths)
    {
        var pfx = Path.Combine(paths.Ssl, "server.pfx");
        return File.Exists(pfx) ? pfx : null;
    }
}
