using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using ServerManager.Core.Paths;
using ServerManager.Data.Entities;

namespace ServerManager.Data;

public static class DataServiceCollectionExtensions
{
    public static IServiceCollection AddServerManagerData(this IServiceCollection services)
    {
        services.AddDbContext<ClusterDbContext>((sp, o) =>
        {
            var paths = sp.GetRequiredService<IAppPaths>();
            paths.EnsureDirectories();
            o.UseSqlite($"Data Source={Path.Combine(paths.Db, "servermanager.db")}");
        });
        services.AddDbContext<UsersDbContext>((sp, o) =>
        {
            var paths = sp.GetRequiredService<IAppPaths>();
            o.UseSqlite($"Data Source={Path.Combine(paths.Db, "servermanager_users.db")}");
        });
        services.AddDbContext<ServersDbContext>((sp, o) =>
        {
            var paths = sp.GetRequiredService<IAppPaths>();
            o.UseSqlite($"Data Source={Path.Combine(paths.Db, "servermanager_servers.db")};Cache=Shared");
        });
        services.AddDbContext<SteamCatalogDbContext>((sp, o) =>
        {
            var paths = sp.GetRequiredService<IAppPaths>();
            o.UseSqlite($"Data Source={Path.Combine(paths.Db, "steam_ID.db")}");
        });
        services.AddDbContext<MinecraftCatalogDbContext>((sp, o) =>
        {
            var paths = sp.GetRequiredService<IAppPaths>();
            o.UseSqlite($"Data Source={Path.Combine(paths.Db, "minecraft_ID.db")}");
        });
        services.AddDbContext<ModdedCatalogDbContext>((sp, o) =>
        {
            var paths = sp.GetRequiredService<IAppPaths>();
            o.UseSqlite($"Data Source={Path.Combine(paths.Db, "minecraft_modded_ID.db")}");
        });
        services.AddDbContext<ConsoleDbContext>((sp, o) =>
        {
            var paths = sp.GetRequiredService<IAppPaths>();
            o.UseSqlite($"Data Source={Path.Combine(paths.Db, "console_states.db")}");
        });

        services.AddScoped<DatabaseInitializer>();
        return services;
    }
}

public sealed class DatabaseInitializer
{
    private readonly UsersDbContext _users;
    private readonly ClusterDbContext _cluster;
    private readonly ServersDbContext _servers;
    private readonly SteamCatalogDbContext _steam;
    private readonly MinecraftCatalogDbContext _mc;
    private readonly ModdedCatalogDbContext _modded;
    private readonly ConsoleDbContext _console;
    private readonly IAppPaths _paths;

    public DatabaseInitializer(
        UsersDbContext users,
        ClusterDbContext cluster,
        ServersDbContext servers,
        SteamCatalogDbContext steam,
        MinecraftCatalogDbContext mc,
        ModdedCatalogDbContext modded,
        ConsoleDbContext console,
        IAppPaths paths)
    {
        _users = users;
        _cluster = cluster;
        _servers = servers;
        _steam = steam;
        _mc = mc;
        _modded = modded;
        _console = console;
        _paths = paths;
    }

    public async Task InitializeAsync(CancellationToken ct = default)
    {
        CatalogDbSeeder.EnsureSeeded(_paths);

        await _cluster.Database.EnsureCreatedAsync(ct);
        await _users.Database.EnsureCreatedAsync(ct);
        await _servers.Database.EnsureCreatedAsync(ct);
        await _steam.Database.EnsureCreatedAsync(ct);
        await _mc.Database.EnsureCreatedAsync(ct);
        await _modded.Database.EnsureCreatedAsync(ct);
        await _console.Database.EnsureCreatedAsync(ct);
        await AlignConsoleStatesSchemaAsync(_console, ct);
        await ApplySqlitePragmasAsync(_servers, ct);
        await ApplySqlitePragmasAsync(_console, ct);

        if (!await _users.Users.AnyAsync(ct))
        {
            _users.Users.Add(new UserAccount
            {
                Username = "admin",
                PasswordHash = BCrypt.Net.BCrypt.HashPassword("admin"),
                IsAdmin = true,
                IsActive = true,
                DisplayName = "Administrator"
            });
            await _users.SaveChangesAsync(ct);
        }
    }

    private static async Task ApplySqlitePragmasAsync(DbContext db, CancellationToken ct)
    {
        try
        {
            await db.Database.ExecuteSqlRawAsync("PRAGMA journal_mode=WAL;", ct);
            await db.Database.ExecuteSqlRawAsync("PRAGMA busy_timeout=8000;", ct);
        }
        catch { /* best effort */ }
    }

    /// <summary>
    /// console_states.db may be a legacy Python schema (output_buffer) or an early EF schema (BufferJson).
    /// Normalize toward the mapped legacy column names.
    /// </summary>
    private static async Task AlignConsoleStatesSchemaAsync(ConsoleDbContext db, CancellationToken ct)
    {
        await db.Database.OpenConnectionAsync(ct);
        try
        {
            var conn = db.Database.GetDbConnection();
            var cols = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            await using (var cmd = conn.CreateCommand())
            {
                cmd.CommandText = "SELECT name FROM pragma_table_info('console_states')";
                await using var reader = await cmd.ExecuteReaderAsync(ct);
                while (await reader.ReadAsync(ct))
                    cols.Add(reader.GetString(0));
            }

            if (cols.Count == 0)
                return;

            async Task ExecAsync(string sql)
            {
                await using var cmd = conn.CreateCommand();
                cmd.CommandText = sql;
                await cmd.ExecuteNonQueryAsync(ct);
            }

            if (cols.Contains("BufferJson") && !cols.Contains("output_buffer"))
                await ExecAsync("ALTER TABLE console_states RENAME COLUMN BufferJson TO output_buffer");
            if (cols.Contains("ServerName") && !cols.Contains("server_name"))
                await ExecAsync("ALTER TABLE console_states RENAME COLUMN \"ServerName\" TO server_name");
            if (cols.Contains("UpdatedAt") && !cols.Contains("timestamp"))
                await ExecAsync("ALTER TABLE console_states RENAME COLUMN \"UpdatedAt\" TO timestamp");
            if (cols.Contains("Id") && !cols.Contains("id"))
                await ExecAsync("ALTER TABLE console_states RENAME COLUMN \"Id\" TO id");

            // Refresh cols after renames
            cols.Clear();
            await using (var cmd = conn.CreateCommand())
            {
                cmd.CommandText = "SELECT name FROM pragma_table_info('console_states')";
                await using var reader = await cmd.ExecuteReaderAsync(ct);
                while (await reader.ReadAsync(ct))
                    cols.Add(reader.GetString(0));
            }

            if (!cols.Contains("output_buffer"))
                await ExecAsync("ALTER TABLE console_states ADD COLUMN output_buffer TEXT");
            if (!cols.Contains("server_name") && !cols.Contains("ServerName"))
                await ExecAsync("ALTER TABLE console_states ADD COLUMN server_name TEXT");
            if (!cols.Contains("timestamp") && !cols.Contains("UpdatedAt"))
                await ExecAsync("ALTER TABLE console_states ADD COLUMN timestamp TEXT");
        }
        catch
        {
            // Best-effort; queries still use mapped columns when schema already matches.
        }
        finally
        {
            await db.Database.CloseConnectionAsync();
        }
    }
}

/// <summary>
/// Copies shipped catalog SQLite files into runtime\db when missing or empty.
/// Looks beside the app under seed\db, then under the repo/runtime seed folder.
/// </summary>
public static class CatalogDbSeeder
{
    private static readonly string[] CatalogFiles =
    [
        "steam_ID.db",
        "minecraft_ID.db",
        "minecraft_modded_ID.db"
    ];

    public static void EnsureSeeded(IAppPaths paths)
    {
        paths.EnsureDirectories();
        foreach (var name in CatalogFiles)
        {
            var dest = Path.Combine(paths.Db, name);
            if (File.Exists(dest) && new FileInfo(dest).Length > 64_000)
                continue;

            foreach (var candidate in SeedCandidates(paths, name))
            {
                if (!File.Exists(candidate)) continue;
                try
                {
                    Directory.CreateDirectory(paths.Db);
                    File.Copy(candidate, dest, overwrite: true);
                    break;
                }
                catch
                {
                    // ignore seed copy failures
                }
            }
        }
    }

    private static IEnumerable<string> SeedCandidates(IAppPaths paths, string name)
    {
        yield return Path.Combine(AppContext.BaseDirectory, "seed", "db", name);
        yield return Path.Combine(AppContext.BaseDirectory, "db", name);
        yield return Path.Combine(paths.Root, "seed", "db", name);
        yield return Path.Combine(paths.Db, name);
        // Legacy Python Host catalog location
        yield return Path.Combine(@"D:\SteamCMD\Servermanager2\db", name);
        yield return Path.Combine(@"D:\SteamCMD\ServerManager\runtime\db", name);
        var repoRuntime = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "runtime", "db", name));
        yield return repoRuntime;
    }
}
