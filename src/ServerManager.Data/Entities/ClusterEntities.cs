namespace ServerManager.Data.Entities;

public class MainConfigEntry
{
    public int Id { get; set; }
    public string Key { get; set; } = string.Empty;
    public string Value { get; set; } = string.Empty;
    public string ValueType { get; set; } = "string";
}

public class ClusterNode
{
    public int Id { get; set; }
    public string NodeId { get; set; } = string.Empty;
    public string NodeType { get; set; } = "subhost";
    public string? DisplayName { get; set; }
    public string? Address { get; set; }
    public int? Port { get; set; }
    public string Status { get; set; } = "pending";
    public DateTime? LastHeartbeat { get; set; }
    public string? Token { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

public class PendingJoinRequest
{
    public int Id { get; set; }
    public string SubhostId { get; set; } = string.Empty;
    public string? MachineName { get; set; }
    public string? Address { get; set; }
    public string Status { get; set; } = "pending";
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}

public class SteamCredential
{
    public int Id { get; set; }
    public string Username { get; set; } = string.Empty;
    public string ProtectedPassword { get; set; } = string.Empty;
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;
}

public class HostRuntimeEvent
{
    public long Id { get; set; }
    public DateTime EventTimestamp { get; set; } = DateTime.UtcNow;
    public string EventType { get; set; } = string.Empty;
    public int? ProcessId { get; set; }
    public string? FieldKey { get; set; }
    public string? FieldValue { get; set; }
}

public class SteamAppCatalogEntry
{
    /// <summary>Steam AppID (primary key — matches Python steam_apps.appid).</summary>
    public int AppId { get; set; }
    public string Name { get; set; } = string.Empty;
    public string? Type { get; set; }
    public bool IsServer { get; set; }
    public bool IsDedicatedServer { get; set; } = true;
    public bool RequiresSubscription { get; set; }
    public bool AnonymousInstall { get; set; } = true;
    public string? Publisher { get; set; }
    public string? ReleaseDate { get; set; }
    public string? Description { get; set; }
    public string? Tags { get; set; }
    public string? Price { get; set; }
    public string? Platforms { get; set; }
    public DateTime? LastUpdated { get; set; }
    public string? Source { get; set; }
}

public class MinecraftVersionEntry
{
    public int Id { get; set; }
    /// <summary>Maps to minecraft_servers.version_id.</summary>
    public string Version { get; set; } = string.Empty;
    public string? VersionType { get; set; }
    public string? ModLoader { get; set; }
    public string? ModLoaderVersion { get; set; }
    public int? JavaRequirement { get; set; }
    public string? DownloadUrl { get; set; }
    public string? InstallerUrl { get; set; }
    public string? ReleaseDate { get; set; }
    public string? Description { get; set; }
    public bool IsDedicatedServer { get; set; }
    public bool IsRecommended { get; set; }
    public DateTime? LastUpdated { get; set; }
    public string? Source { get; set; }

    [System.ComponentModel.DataAnnotations.Schema.NotMapped]
    public bool IsSnapshot =>
        string.Equals(VersionType, "snapshot", StringComparison.OrdinalIgnoreCase);
}

public class ModdedPackEntry
{
    public int Id { get; set; }
    public string PackId { get; set; } = string.Empty;
    public string? PackSlug { get; set; }
    public string Name { get; set; } = string.Empty;
    public string? Launcher { get; set; }
    public string? Description { get; set; }
    public string? Authors { get; set; }
    public string? McVersion { get; set; }
    public string? ModLoader { get; set; }
    public string? PackVersion { get; set; }
    public string? ThumbnailUrl { get; set; }
    public string? ServerUrl { get; set; }
    public string? InstallUrl { get; set; }
    public int? PlayCount { get; set; }
    public bool IsServerPack { get; set; }
    public DateTime? LastUpdated { get; set; }
}

public class ConsoleStateEntry
{
    public int Id { get; set; }
    public string ServerName { get; set; } = string.Empty;
    public string BufferJson { get; set; } = "[]";
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;
}
