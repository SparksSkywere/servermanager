namespace ServerManager.Data.Entities;

public class ServerConfig
{
    public int Id { get; set; }
    public string Name { get; set; } = string.Empty;
    public string ServerType { get; set; } = "steam";
    public string? AppId { get; set; }
    public string InstallDir { get; set; } = string.Empty;
    public string? Executable { get; set; }
    public string? LaunchArgs { get; set; }
    public string? AdditionalArgs { get; set; }
    public string? StopCommand { get; set; }
    public string? SaveCommand { get; set; }
    public string? StartCommand { get; set; }
    public string? JavaPath { get; set; }
    public string? Version { get; set; }
    public string? ModLoader { get; set; }
    public int? RamMb { get; set; }
    public string? JvmArgs { get; set; }
    public int? ProcessId { get; set; }
    public DateTime? ProcessCreateTime { get; set; }
    public string? MotdMessage { get; set; }
    public string? MotdCommand { get; set; }
    /// <summary>MOTD interval in minutes (0 = disabled). Matches legacy schema.</summary>
    public int? MotdInterval { get; set; }
    public string? WarningCommand { get; set; }
    public string? WarningIntervals { get; set; }
    public string? WarningMessageTemplate { get; set; }
    public bool ScheduledRestartEnabled { get; set; }
    public bool AutoStart { get; set; }
    public bool AutoUpdate { get; set; }
    public string? Category { get; set; }
    public string? Notes { get; set; }
    public string ExtraConfigJson { get; set; } = "{}";
    public bool Enabled { get; set; } = true;
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime UpdatedAt { get; set; } = DateTime.UtcNow;
}

public class ServerPermission
{
    public int Id { get; set; }
    public string Username { get; set; } = string.Empty;
    public string ServerName { get; set; } = string.Empty;
    public bool CanView { get; set; } = true;
    public bool CanStart { get; set; }
    public bool CanStop { get; set; }
    public bool CanRestart { get; set; }
    public bool CanConsole { get; set; }
    public bool CanEdit { get; set; }
}
