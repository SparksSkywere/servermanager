using Microsoft.EntityFrameworkCore;
using ServerManager.Data.Entities;

namespace ServerManager.Data;

public class ClusterDbContext : DbContext
{
    public ClusterDbContext(DbContextOptions<ClusterDbContext> options) : base(options) { }

    public DbSet<MainConfigEntry> MainConfig => Set<MainConfigEntry>();
    public DbSet<ClusterNode> ClusterNodes => Set<ClusterNode>();
    public DbSet<PendingJoinRequest> PendingRequests => Set<PendingJoinRequest>();
    public DbSet<SteamCredential> SteamCredentials => Set<SteamCredential>();
    public DbSet<HostRuntimeEvent> HostRuntimeEvents => Set<HostRuntimeEvent>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<MainConfigEntry>(e =>
        {
            e.ToTable("main_config");
            e.HasIndex(x => x.Key).IsUnique();
        });
        modelBuilder.Entity<ClusterNode>(e =>
        {
            e.ToTable("cluster_nodes");
            e.HasIndex(x => x.NodeId).IsUnique();
        });
        modelBuilder.Entity<PendingJoinRequest>().ToTable("pending_requests");
        modelBuilder.Entity<SteamCredential>().ToTable("steam_credentials");
        modelBuilder.Entity<HostRuntimeEvent>().ToTable("host_runtime_events");
    }
}

public class UsersDbContext : DbContext
{
    public UsersDbContext(DbContextOptions<UsersDbContext> options) : base(options) { }

    public DbSet<UserAccount> Users => Set<UserAccount>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<UserAccount>(e =>
        {
            e.ToTable("users");
            e.HasIndex(x => x.Username).IsUnique();
        });
    }
}

public class ServersDbContext : DbContext
{
    public ServersDbContext(DbContextOptions<ServersDbContext> options) : base(options) { }

    public DbSet<ServerConfig> ServerConfigs => Set<ServerConfig>();
    public DbSet<ServerPermission> ServerPermissions => Set<ServerPermission>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<ServerConfig>(e =>
        {
            e.ToTable("server_configs");
            e.HasIndex(x => x.Name).IsUnique();
        });
        modelBuilder.Entity<ServerPermission>().ToTable("server_permissions");
    }
}

public class SteamCatalogDbContext : DbContext
{
    public SteamCatalogDbContext(DbContextOptions<SteamCatalogDbContext> options) : base(options) { }
    public DbSet<SteamAppCatalogEntry> SteamApps => Set<SteamAppCatalogEntry>();
    protected override void OnModelCreating(ModelBuilder b)
    {
        b.Entity<SteamAppCatalogEntry>(e =>
        {
            e.ToTable("steam_apps");
            e.HasKey(x => x.AppId);
            e.Property(x => x.AppId).HasColumnName("appid");
            e.Property(x => x.Name).HasColumnName("name");
            e.Property(x => x.Type).HasColumnName("type");
            e.Property(x => x.IsServer).HasColumnName("is_server");
            e.Property(x => x.IsDedicatedServer).HasColumnName("is_dedicated_server");
            e.Property(x => x.RequiresSubscription).HasColumnName("requires_subscription");
            e.Property(x => x.AnonymousInstall).HasColumnName("anonymous_install");
            e.Property(x => x.Publisher).HasColumnName("publisher");
            e.Property(x => x.ReleaseDate).HasColumnName("release_date");
            e.Property(x => x.Description).HasColumnName("description");
            e.Property(x => x.Tags).HasColumnName("tags");
            e.Property(x => x.Price).HasColumnName("price");
            e.Property(x => x.Platforms).HasColumnName("platforms");
            e.Property(x => x.LastUpdated).HasColumnName("last_updated");
            e.Property(x => x.Source).HasColumnName("source");
        });
    }
}

public class MinecraftCatalogDbContext : DbContext
{
    public MinecraftCatalogDbContext(DbContextOptions<MinecraftCatalogDbContext> options) : base(options) { }
    public DbSet<MinecraftVersionEntry> Versions => Set<MinecraftVersionEntry>();
    protected override void OnModelCreating(ModelBuilder b)
    {
        b.Entity<MinecraftVersionEntry>(e =>
        {
            e.ToTable("minecraft_servers");
            e.HasKey(x => x.Id);
            e.Property(x => x.Id).HasColumnName("id");
            e.Property(x => x.Version).HasColumnName("version_id");
            e.Property(x => x.VersionType).HasColumnName("version_type");
            e.Property(x => x.ModLoader).HasColumnName("modloader");
            e.Property(x => x.ModLoaderVersion).HasColumnName("modloader_version");
            e.Property(x => x.JavaRequirement).HasColumnName("java_requirement");
            e.Property(x => x.DownloadUrl).HasColumnName("download_url");
            e.Property(x => x.InstallerUrl).HasColumnName("installer_url");
            e.Property(x => x.ReleaseDate).HasColumnName("release_date");
            e.Property(x => x.Description).HasColumnName("description");
            e.Property(x => x.IsDedicatedServer).HasColumnName("is_dedicated_server");
            e.Property(x => x.IsRecommended).HasColumnName("is_recommended");
            e.Property(x => x.LastUpdated).HasColumnName("last_updated");
            e.Property(x => x.Source).HasColumnName("source");
        });
    }
}

public class ModdedCatalogDbContext : DbContext
{
    public ModdedCatalogDbContext(DbContextOptions<ModdedCatalogDbContext> options) : base(options) { }
    public DbSet<ModdedPackEntry> Packs => Set<ModdedPackEntry>();
    protected override void OnModelCreating(ModelBuilder b)
    {
        b.Entity<ModdedPackEntry>(e =>
        {
            e.ToTable("modded_packs");
            e.HasKey(x => x.Id);
            e.Property(x => x.Id).HasColumnName("id");
            e.Property(x => x.PackId).HasColumnName("pack_id");
            e.Property(x => x.PackSlug).HasColumnName("pack_slug");
            e.Property(x => x.Name).HasColumnName("name");
            e.Property(x => x.Launcher).HasColumnName("launcher");
            e.Property(x => x.Description).HasColumnName("description");
            e.Property(x => x.Authors).HasColumnName("authors");
            e.Property(x => x.McVersion).HasColumnName("mc_version");
            e.Property(x => x.ModLoader).HasColumnName("modloader");
            e.Property(x => x.PackVersion).HasColumnName("pack_version");
            e.Property(x => x.ThumbnailUrl).HasColumnName("thumbnail_url");
            e.Property(x => x.ServerUrl).HasColumnName("server_url");
            e.Property(x => x.InstallUrl).HasColumnName("install_url");
            e.Property(x => x.PlayCount).HasColumnName("play_count");
            e.Property(x => x.IsServerPack).HasColumnName("is_server_pack");
            e.Property(x => x.LastUpdated).HasColumnName("last_updated");
        });
    }
}

public class ConsoleDbContext : DbContext
{
    public ConsoleDbContext(DbContextOptions<ConsoleDbContext> options) : base(options) { }
    public DbSet<ConsoleStateEntry> ConsoleStates => Set<ConsoleStateEntry>();
    protected override void OnModelCreating(ModelBuilder b)
    {
        // Legacy Python Host schema (snake_case). Map so EnsureCreated DBs and old installs both work.
        b.Entity<ConsoleStateEntry>(e =>
        {
            e.ToTable("console_states");
            e.HasKey(x => x.Id);
            e.Property(x => x.Id).HasColumnName("id");
            e.Property(x => x.ServerName).HasColumnName("server_name").IsRequired();
            e.Property(x => x.BufferJson).HasColumnName("output_buffer");
            e.Property(x => x.UpdatedAt).HasColumnName("timestamp");
            e.HasIndex(x => x.ServerName).IsUnique();
        });
    }
}
