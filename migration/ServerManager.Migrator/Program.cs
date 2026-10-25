using System.CommandLine;
using System.CommandLine.Invocation;
using System.Globalization;
using System.Text.Json;
using Microsoft.Data.Sqlite;

var sourceOption = new Option<DirectoryInfo>("--source", "Legacy Server Manager install root (contains db\\)") { IsRequired = true };
var destOption = new Option<DirectoryInfo>("--dest", "Target Server Manager runtime root (will contain db\\)") { IsRequired = true };
var dryRunOption = new Option<bool>("--dry-run", () => false, "Report actions without writing");
var copySslOption = new Option<bool>("--copy-ssl", () => true, "Copy ssl\\ certificate files");
var clearDestOption = new Option<bool>("--clear-dest-db", () => false, "Delete existing destination SQLite DBs before migrate");
var remapOption = new Option<FileInfo?>("--path-remap", "Optional JSON map of old *install folder* path prefixes to new ones (not server config)");
var skipUsersOption = new Option<bool>("--skip-users", () => false, "Skip users database");
var skipServersOption = new Option<bool>("--skip-servers", () => false, "Skip server configs");
var skipClusterOption = new Option<bool>("--skip-cluster", () => false, "Skip cluster/main config database");
var skipCatalogsOption = new Option<bool>("--skip-catalogs", () => false, "Skip steam/minecraft catalog DBs (file copy)");
var skipJsonServersOption = new Option<bool>("--skip-json-servers", () => false, "Skip importing legacy servers\\*.json into SQL");

var root = new RootCommand("Migrate legacy Server Manager data into SQLite databases. Server configs live in SQL (not JSON files).");
root.AddOption(sourceOption);
root.AddOption(destOption);
root.AddOption(dryRunOption);
root.AddOption(copySslOption);
root.AddOption(clearDestOption);
root.AddOption(remapOption);
root.AddOption(skipUsersOption);
root.AddOption(skipServersOption);
root.AddOption(skipClusterOption);
root.AddOption(skipCatalogsOption);
root.AddOption(skipJsonServersOption);

root.SetHandler((InvocationContext inv) =>
{
    var source = inv.ParseResult.GetValueForOption(sourceOption)!;
    var dest = inv.ParseResult.GetValueForOption(destOption)!;
    var dryRun = inv.ParseResult.GetValueForOption(dryRunOption);
    var copySsl = inv.ParseResult.GetValueForOption(copySslOption);
    var clearDest = inv.ParseResult.GetValueForOption(clearDestOption);
    var remapFile = inv.ParseResult.GetValueForOption(remapOption);
    var skipUsers = inv.ParseResult.GetValueForOption(skipUsersOption);
    var skipServers = inv.ParseResult.GetValueForOption(skipServersOption);
    var skipCluster = inv.ParseResult.GetValueForOption(skipClusterOption);
    var skipCatalogs = inv.ParseResult.GetValueForOption(skipCatalogsOption);
    var skipJsonServers = inv.ParseResult.GetValueForOption(skipJsonServersOption);

    var remaps = LoadRemaps(remapFile);
    var ctx = new MigrateContext(source.FullName, dest.FullName, dryRun, remaps);
    Directory.CreateDirectory(ctx.DestDb);
    if (copySsl) Directory.CreateDirectory(Path.Combine(ctx.DestRoot, "ssl"));

    Console.WriteLine($"Source : {ctx.SourceRoot}");
    Console.WriteLine($"Dest   : {ctx.DestRoot}");
    Console.WriteLine($"DryRun : {dryRun}");
    Console.WriteLine("Note   : All server configs are written to SQLite (servermanager_servers.db).");

    if (clearDest && !dryRun)
    {
        foreach (var f in Directory.Exists(ctx.DestDb) ? Directory.GetFiles(ctx.DestDb, "*.db") : Array.Empty<string>())
        {
            File.Delete(f);
            Console.WriteLine($"Cleared {Path.GetFileName(f)}");
        }
    }

    EnsureDestSchemas(ctx);

    if (!skipServers) MigrateServers(ctx);
    if (!skipServers && !skipJsonServers) MigrateServersFromJsonFiles(ctx);
    if (!skipUsers) MigrateUsers(ctx);
    if (!skipCluster) MigrateCluster(ctx);
    if (!skipCatalogs) CopyCatalogDatabases(ctx);
    if (copySsl) CopySsl(ctx);

    WriteSummary(ctx);
});

return await root.InvokeAsync(args);

static Dictionary<string, string> LoadRemaps(FileInfo? file)
{
    var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    if (file is null || !file.Exists) return map;
    using var doc = JsonDocument.Parse(File.ReadAllText(file.FullName));
    if (doc.RootElement.TryGetProperty("pathRemap", out var remap))
    {
        foreach (var p in remap.EnumerateObject())
            map[p.Name] = p.Value.GetString() ?? "";
    }
    else
    {
        foreach (var p in doc.RootElement.EnumerateObject())
            map[p.Name] = p.Value.GetString() ?? "";
    }
    return map;
}

static void EnsureDestSchemas(MigrateContext ctx)
{
    Exec(ctx, Path.Combine(ctx.DestDb, "servermanager_servers.db"), @"
CREATE TABLE IF NOT EXISTS server_configs (
  Id INTEGER PRIMARY KEY AUTOINCREMENT,
  Name TEXT NOT NULL UNIQUE,
  ServerType TEXT NOT NULL,
  AppId TEXT NULL,
  InstallDir TEXT NOT NULL,
  Executable TEXT NULL,
  LaunchArgs TEXT NULL,
  AdditionalArgs TEXT NULL,
  StopCommand TEXT NULL,
  SaveCommand TEXT NULL,
  StartCommand TEXT NULL,
  JavaPath TEXT NULL,
  Version TEXT NULL,
  ModLoader TEXT NULL,
  RamMb INTEGER NULL,
  JvmArgs TEXT NULL,
  ProcessId INTEGER NULL,
  ProcessCreateTime TEXT NULL,
  MotdMessage TEXT NULL,
  MotdCommand TEXT NULL,
  MotdInterval INTEGER NULL,
  WarningCommand TEXT NULL,
  WarningIntervals TEXT NULL,
  WarningMessageTemplate TEXT NULL,
  ScheduledRestartEnabled INTEGER NOT NULL DEFAULT 0,
  AutoStart INTEGER NOT NULL DEFAULT 0,
  AutoUpdate INTEGER NOT NULL DEFAULT 0,
  Category TEXT NULL,
  Notes TEXT NULL,
  ExtraConfigJson TEXT NOT NULL DEFAULT '{}',
  Enabled INTEGER NOT NULL DEFAULT 1,
  CreatedAt TEXT NOT NULL,
  UpdatedAt TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS server_permissions (
  Id INTEGER PRIMARY KEY AUTOINCREMENT,
  Username TEXT NOT NULL,
  ServerName TEXT NOT NULL,
  CanView INTEGER NOT NULL DEFAULT 1,
  CanStart INTEGER NOT NULL DEFAULT 0,
  CanStop INTEGER NOT NULL DEFAULT 0,
  CanRestart INTEGER NOT NULL DEFAULT 0,
  CanConsole INTEGER NOT NULL DEFAULT 0,
  CanEdit INTEGER NOT NULL DEFAULT 0
);");

    Exec(ctx, Path.Combine(ctx.DestDb, "servermanager_users.db"), @"
CREATE TABLE IF NOT EXISTS users (
  Id INTEGER PRIMARY KEY AUTOINCREMENT,
  Username TEXT NOT NULL UNIQUE,
  PasswordHash TEXT NOT NULL,
  Email TEXT NULL,
  DisplayName TEXT NULL,
  IsAdmin INTEGER NOT NULL DEFAULT 0,
  IsActive INTEGER NOT NULL DEFAULT 1,
  TwoFactorEnabled INTEGER NOT NULL DEFAULT 0,
  TwoFactorSecret TEXT NULL,
  AvatarPath TEXT NULL,
  Bio TEXT NULL,
  Timezone TEXT NULL,
  Theme TEXT NULL,
  CreatedAt TEXT NOT NULL,
  LastLoginAt TEXT NULL
);");

    Exec(ctx, Path.Combine(ctx.DestDb, "servermanager.db"), @"
CREATE TABLE IF NOT EXISTS main_config (
  Id INTEGER PRIMARY KEY AUTOINCREMENT,
  Key TEXT NOT NULL UNIQUE,
  Value TEXT NOT NULL,
  ValueType TEXT NOT NULL DEFAULT 'string'
);
CREATE TABLE IF NOT EXISTS cluster_nodes (
  Id INTEGER PRIMARY KEY AUTOINCREMENT,
  NodeId TEXT NOT NULL UNIQUE,
  NodeType TEXT NOT NULL,
  DisplayName TEXT NULL,
  Address TEXT NULL,
  Port INTEGER NULL,
  Status TEXT NOT NULL,
  LastHeartbeat TEXT NULL,
  Token TEXT NULL,
  CreatedAt TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_requests (
  Id INTEGER PRIMARY KEY AUTOINCREMENT,
  SubhostId TEXT NOT NULL,
  MachineName TEXT NULL,
  Address TEXT NULL,
  Status TEXT NOT NULL,
  CreatedAt TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS steam_credentials (
  Id INTEGER PRIMARY KEY AUTOINCREMENT,
  Username TEXT NOT NULL,
  ProtectedPassword TEXT NOT NULL,
  UpdatedAt TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS host_runtime_events (
  Id INTEGER PRIMARY KEY AUTOINCREMENT,
  EventTimestamp TEXT NOT NULL,
  EventType TEXT NOT NULL,
  ProcessId INTEGER NULL,
  FieldKey TEXT NULL,
  FieldValue TEXT NULL
);");
}

static void MigrateServers(MigrateContext ctx)
{
    var src = Path.Combine(ctx.SourceDb, "servermanager_servers.db");
    if (!File.Exists(src))
    {
        Console.WriteLine("skip servers: source DB missing");
        return;
    }

    var dest = Path.Combine(ctx.DestDb, "servermanager_servers.db");
    using var sconn = Open(src, readOnly: true);
    using var dconn = Open(dest, readOnly: false);

    var servers = Query(sconn, "SELECT * FROM server_configs");
    Console.WriteLine($"servers: {servers.Count} row(s)");

    foreach (var row in servers)
    {
        if (UpsertServerRow(ctx, dconn, row, fromJson: false))
            ctx.ServersMigrated++;
    }

    // Permissions: legacy uses server_id FK
    var perms = Query(sconn, @"
SELECT p.*, s.name AS server_name
FROM server_permissions p
LEFT JOIN server_configs s ON s.id = p.server_id");
    Console.WriteLine($"permissions: {perms.Count} row(s)");
    foreach (var row in perms)
    {
        var serverName = Coalesce(Str(row, "server_name"), Str(row, "ServerName"));
        var username = Str(row, "username");
        if (string.IsNullOrWhiteSpace(serverName) || string.IsNullOrWhiteSpace(username)) continue;
        if (ctx.DryRun) { ctx.PermissionsMigrated++; continue; }

        using (var del = dconn.CreateCommand())
        {
            del.CommandText = "DELETE FROM server_permissions WHERE Username=$u AND ServerName=$s";
            del.Parameters.AddWithValue("$u", username);
            del.Parameters.AddWithValue("$s", serverName);
            del.ExecuteNonQuery();
        }

        using var cmd = dconn.CreateCommand();
        cmd.CommandText = @"
INSERT INTO server_permissions (Username, ServerName, CanView, CanStart, CanStop, CanRestart, CanConsole, CanEdit)
VALUES ($u,$s,$v,$st,$sp,$r,$c,$e);";
        cmd.Parameters.AddWithValue("$u", username);
        cmd.Parameters.AddWithValue("$s", serverName);
        cmd.Parameters.AddWithValue("$v", Bool(row, "can_view", true) ? 1 : 0);
        cmd.Parameters.AddWithValue("$st", Bool(row, "can_start", false) ? 1 : 0);
        cmd.Parameters.AddWithValue("$sp", Bool(row, "can_stop", false) ? 1 : 0);
        cmd.Parameters.AddWithValue("$r", Bool(row, "can_restart", false) ? 1 : 0);
        cmd.Parameters.AddWithValue("$c", Bool(row, "can_console", false) ? 1 : 0);
        cmd.Parameters.AddWithValue("$e", Bool(row, "can_edit", false) ? 1 : 0);
        cmd.ExecuteNonQuery();
        ctx.PermissionsMigrated++;
    }
}

/// <summary>
/// Import legacy per-server JSON files (servers\*.json) into SQLite so SQL is the only source of truth.
/// </summary>
static void MigrateServersFromJsonFiles(MigrateContext ctx)
{
    var dirs = new[]
    {
        Path.Combine(ctx.SourceRoot, "servers"),
        Path.Combine(ctx.SourceRoot, "data", "servers"),
        Path.Combine(ctx.SourceRoot, "config", "servers")
    }.Where(Directory.Exists).ToArray();

    if (dirs.Length == 0)
    {
        Console.WriteLine("json servers: no servers\\ folder (OK if already in SQLite)");
        return;
    }

    var files = dirs.SelectMany(d => Directory.GetFiles(d, "*.json", SearchOption.TopDirectoryOnly)).ToList();
    Console.WriteLine($"json servers: {files.Count} file(s) → SQL");
    if (files.Count == 0) return;

    var dest = Path.Combine(ctx.DestDb, "servermanager_servers.db");
    using var dconn = Open(dest, readOnly: false);

    foreach (var file in files)
    {
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(file));
            var el = doc.RootElement;
            // Support single object or array of servers
            IEnumerable<JsonElement> items = el.ValueKind == JsonValueKind.Array
                ? el.EnumerateArray()
                : new[] { el };

            foreach (var item in items)
            {
                var row = JsonServerToRow(item, Path.GetFileNameWithoutExtension(file));
                var name = Str(row, "name");
                if (string.IsNullOrWhiteSpace(name)) continue;

                // Skip if already present from SQLite migrate unless JSON has richer install_dir
                if (!ctx.DryRun && ServerExists(dconn, name))
                {
                    Console.WriteLine($"  skip JSON (already in SQL): {name}");
                    continue;
                }

                if (UpsertServerRow(ctx, dconn, row, fromJson: true))
                {
                    ctx.JsonServersMigrated++;
                    Console.WriteLine($"  {(ctx.DryRun ? "[dry-run] " : "")}JSON → SQL: {name}");
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"  warn {Path.GetFileName(file)}: {ex.Message}");
        }
    }
}

static bool ServerExists(SqliteConnection dconn, string name)
{
    using var cmd = dconn.CreateCommand();
    cmd.CommandText = "SELECT 1 FROM server_configs WHERE Name=$n LIMIT 1";
    cmd.Parameters.AddWithValue("$n", name);
    return cmd.ExecuteScalar() is not null;
}

static Dictionary<string, object?> JsonServerToRow(JsonElement el, string fallbackName)
{
    string Pick(params string[] keys)
    {
        foreach (var k in keys)
            if (el.TryGetProperty(k, out var p) && p.ValueKind != JsonValueKind.Null)
                return p.ValueKind == JsonValueKind.String ? (p.GetString() ?? "") : p.ToString();
        return "";
    }

    object? PickObj(params string[] keys)
    {
        foreach (var k in keys)
        {
            if (!el.TryGetProperty(k, out var p) || p.ValueKind == JsonValueKind.Null) continue;
            return p.ValueKind switch
            {
                JsonValueKind.String => p.GetString(),
                JsonValueKind.Number => p.TryGetInt64(out var l) ? l : p.GetDouble(),
                JsonValueKind.True => true,
                JsonValueKind.False => false,
                _ => p.ToString()
            };
        }
        return null;
    }

    var name = Pick("Name", "name");
    if (string.IsNullOrWhiteSpace(name)) name = fallbackName;

    var row = new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase)
    {
        ["name"] = name,
        ["server_type"] = Pick("Type", "type", "ServerType", "server_type"),
        ["app_id"] = Pick("AppID", "AppId", "app_id", "appid"),
        ["install_dir"] = Pick("InstallDir", "install_dir"),
        ["executable_path"] = Pick("ExecutablePath", "executable_path", "Executable", "executable"),
        ["startup_args"] = Pick("StartupArgs", "startup_args", "LaunchArgs", "launch_args"),
        ["additional_args"] = Pick("AdditionalArgs", "additional_args"),
        ["stop_command"] = Pick("StopCommand", "stop_command"),
        ["save_command"] = Pick("SaveCommand", "save_command"),
        ["start_command"] = Pick("StartCommand", "start_command"),
        ["java_path"] = Pick("JavaPath", "java_path"),
        ["version"] = Pick("Version", "version"),
        ["mod_loader"] = Pick("ModLoader", "mod_loader"),
        ["ram"] = PickObj("RAM", "ram", "RamMb"),
        ["jvm_args"] = Pick("JVMArgs", "jvm_args"),
        ["motd_message"] = Pick("MotdMessage", "motd_message"),
        ["motd_command"] = Pick("MotdCommand", "motd_command"),
        ["motd_interval"] = PickObj("MotdInterval", "motd_interval"),
        ["warning_command"] = Pick("WarningCommand", "warning_command"),
        ["warning_intervals"] = Pick("WarningIntervals", "warning_intervals"),
        ["warning_message_template"] = Pick("WarningMessageTemplate", "warning_message_template"),
        ["scheduled_restart_enabled"] = PickObj("ScheduledRestartEnabled", "scheduled_restart_enabled"),
        ["auto_start"] = PickObj("AutoStart", "auto_start"),
        ["category"] = Pick("Category", "category"),
        ["notes"] = Pick("Notes", "notes"),
        ["is_active"] = PickObj("IsActive", "is_active", "Enabled") ?? true,
        ["use_config_file"] = PickObj("UseConfigFile", "use_config_file"),
        ["config_file_path"] = Pick("ConfigFilePath", "config_file_path"),
        ["config_argument"] = Pick("ConfigArgument", "config_argument"),
        ["imported"] = true,
        ["extra_config"] = el.TryGetProperty("ExtraConfig", out var ec) ? ec.ToString()
            : el.TryGetProperty("extra_config", out var ec2) ? ec2.ToString() : "{}"
    };
    return row;
}

static bool UpsertServerRow(MigrateContext ctx, SqliteConnection dconn, Dictionary<string, object?> row, bool fromJson)
{
    var name = Str(row, "name");
    if (string.IsNullOrWhiteSpace(name)) return false;

    var installDir = Remap(ctx, Str(row, "install_dir"));
    var executable = Remap(ctx, Coalesce(Str(row, "executable_path"), Str(row, "executable")));
    var javaPath = Remap(ctx, Str(row, "java_path"));

    var enabled = Bool(row, "is_active", true);
    if (row.ContainsKey("Enabled") || row.ContainsKey("enabled"))
        enabled = Bool(row, "enabled", enabled);

    var now = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture);
    var created = Coalesce(Str(row, "created_at"), now);
    var updated = Coalesce(Str(row, "updated_at"), now);

    var extra = new Dictionary<string, object?>();
    var existingExtra = Str(row, "extra_config");
    if (!string.IsNullOrWhiteSpace(existingExtra) && existingExtra.TrimStart().StartsWith('{'))
    {
        try
        {
            using var doc = JsonDocument.Parse(existingExtra);
            foreach (var p in doc.RootElement.EnumerateObject())
                extra[p.Name] = p.Value.ValueKind switch
                {
                    JsonValueKind.String => p.Value.GetString(),
                    JsonValueKind.Number => p.Value.GetRawText(),
                    JsonValueKind.True => true,
                    JsonValueKind.False => false,
                    JsonValueKind.Null => null,
                    _ => p.Value.GetRawText()
                };
        }
        catch { /* ignore */ }
    }
    foreach (var key in new[] { "use_config_file", "config_file_path", "config_argument", "imported", "synced_by", "log_stdout", "log_stderr" })
    {
        if (row.ContainsKey(key) && row[key] is not null && row[key] is not DBNull)
        {
            var v = row[key]?.ToString();
            if (key.Contains("path", StringComparison.OrdinalIgnoreCase) || key.Contains("log_", StringComparison.OrdinalIgnoreCase))
                v = Remap(ctx, v);
            extra[key] = v;
        }
    }
    if (fromJson) extra["imported_from_json"] = true;

    if (ctx.DryRun)
    {
        Console.WriteLine($"  [dry-run] server {name} -> {installDir}");
        return true;
    }

    using (var del = dconn.CreateCommand())
    {
        del.CommandText = "DELETE FROM server_configs WHERE Name = $n";
        del.Parameters.AddWithValue("$n", name);
        del.ExecuteNonQuery();
    }

    using var cmd = dconn.CreateCommand();
    cmd.CommandText = @"
INSERT INTO server_configs (
  Name, ServerType, AppId, InstallDir, Executable, LaunchArgs, AdditionalArgs,
  StopCommand, SaveCommand, StartCommand, JavaPath, Version, ModLoader, RamMb, JvmArgs,
  ProcessId, ProcessCreateTime, MotdMessage, MotdCommand, MotdInterval,
  WarningCommand, WarningIntervals, WarningMessageTemplate, ScheduledRestartEnabled,
  AutoStart, AutoUpdate, Category, Notes, ExtraConfigJson, Enabled, CreatedAt, UpdatedAt
) VALUES (
  $Name, $ServerType, $AppId, $InstallDir, $Executable, $LaunchArgs, $AdditionalArgs,
  $StopCommand, $SaveCommand, $StartCommand, $JavaPath, $Version, $ModLoader, $RamMb, $JvmArgs,
  NULL, NULL, $MotdMessage, $MotdCommand, $MotdInterval,
  $WarningCommand, $WarningIntervals, $WarningMessageTemplate, $ScheduledRestartEnabled,
  $AutoStart, $AutoUpdate, $Category, $Notes, $ExtraConfigJson, $Enabled, $CreatedAt, $UpdatedAt
);";
    cmd.Parameters.AddWithValue("$Name", name);
    cmd.Parameters.AddWithValue("$ServerType", NormalizeServerType(Str(row, "server_type")));
    cmd.Parameters.AddWithValue("$AppId", (object?)NullIfEmpty(Str(row, "app_id")) ?? DBNull.Value);
    cmd.Parameters.AddWithValue("$InstallDir", installDir ?? "");
    cmd.Parameters.AddWithValue("$Executable", (object?)NullIfEmpty(executable) ?? DBNull.Value);
    cmd.Parameters.AddWithValue("$LaunchArgs", (object?)NullIfEmpty(Coalesce(Str(row, "startup_args"), Str(row, "launch_args"))) ?? DBNull.Value);
    cmd.Parameters.AddWithValue("$AdditionalArgs", (object?)NullIfEmpty(Str(row, "additional_args")) ?? DBNull.Value);
    cmd.Parameters.AddWithValue("$StopCommand", (object?)NullIfEmpty(Str(row, "stop_command")) ?? DBNull.Value);
    cmd.Parameters.AddWithValue("$SaveCommand", (object?)NullIfEmpty(Str(row, "save_command")) ?? DBNull.Value);
    cmd.Parameters.AddWithValue("$StartCommand", (object?)NullIfEmpty(Str(row, "start_command")) ?? DBNull.Value);
    cmd.Parameters.AddWithValue("$JavaPath", (object?)NullIfEmpty(javaPath) ?? DBNull.Value);
    cmd.Parameters.AddWithValue("$Version", (object?)NullIfEmpty(Str(row, "version")) ?? DBNull.Value);
    cmd.Parameters.AddWithValue("$ModLoader", (object?)NullIfEmpty(Str(row, "mod_loader")) ?? DBNull.Value);
    cmd.Parameters.AddWithValue("$RamMb", IntOrDbNull(row, "ram"));
    cmd.Parameters.AddWithValue("$JvmArgs", (object?)NullIfEmpty(Str(row, "jvm_args")) ?? DBNull.Value);
    cmd.Parameters.AddWithValue("$MotdMessage", (object?)NullIfEmpty(Str(row, "motd_message")) ?? DBNull.Value);
    cmd.Parameters.AddWithValue("$MotdCommand", (object?)NullIfEmpty(Str(row, "motd_command")) ?? DBNull.Value);
    cmd.Parameters.AddWithValue("$MotdInterval", IntOrDbNull(row, "motd_interval"));
    cmd.Parameters.AddWithValue("$WarningCommand", (object?)NullIfEmpty(Str(row, "warning_command")) ?? DBNull.Value);
    cmd.Parameters.AddWithValue("$WarningIntervals", (object?)NullIfEmpty(Str(row, "warning_intervals")) ?? DBNull.Value);
    cmd.Parameters.AddWithValue("$WarningMessageTemplate", (object?)NullIfEmpty(Str(row, "warning_message_template")) ?? DBNull.Value);
    cmd.Parameters.AddWithValue("$ScheduledRestartEnabled", Bool(row, "scheduled_restart_enabled", false) ? 1 : 0);
    cmd.Parameters.AddWithValue("$AutoStart", Bool(row, "auto_start", false) ? 1 : 0);
    cmd.Parameters.AddWithValue("$AutoUpdate", 0);
    cmd.Parameters.AddWithValue("$Category", (object?)NullIfEmpty(Str(row, "category")) ?? DBNull.Value);
    cmd.Parameters.AddWithValue("$Notes", (object?)NullIfEmpty(Str(row, "notes")) ?? DBNull.Value);
    cmd.Parameters.AddWithValue("$ExtraConfigJson", JsonSerializer.Serialize(extra));
    cmd.Parameters.AddWithValue("$Enabled", enabled ? 1 : 0);
    cmd.Parameters.AddWithValue("$CreatedAt", created);
    cmd.Parameters.AddWithValue("$UpdatedAt", updated);
    cmd.ExecuteNonQuery();
    return true;
}

static void MigrateUsers(MigrateContext ctx)
{
    var src = Path.Combine(ctx.SourceDb, "servermanager_users.db");
    if (!File.Exists(src))
    {
        Console.WriteLine("skip users: source DB missing");
        return;
    }

    var dest = Path.Combine(ctx.DestDb, "servermanager_users.db");
    using var sconn = Open(src, readOnly: true);
    using var dconn = Open(dest, readOnly: false);

    var users = Query(sconn, "SELECT * FROM users");
    Console.WriteLine($"users: {users.Count} row(s)");
    foreach (var row in users)
    {
        var username = Str(row, "username");
        if (string.IsNullOrWhiteSpace(username)) continue;
        var hash = Coalesce(Str(row, "password"), Str(row, "PasswordHash"), Str(row, "password_hash"));
        if (string.IsNullOrWhiteSpace(hash)) continue;

        var display = Coalesce(Str(row, "display_name"),
            string.Join(' ', new[] { Str(row, "first_name"), Str(row, "last_name") }.Where(s => !string.IsNullOrWhiteSpace(s))));
        var now = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture);

        if (ctx.DryRun)
        {
            Console.WriteLine($"  [dry-run] user {username}");
            ctx.UsersMigrated++;
            continue;
        }

        using (var del = dconn.CreateCommand())
        {
            del.CommandText = "DELETE FROM users WHERE Username=$u";
            del.Parameters.AddWithValue("$u", username);
            del.ExecuteNonQuery();
        }

        using var cmd = dconn.CreateCommand();
        cmd.CommandText = @"
INSERT INTO users (Username, PasswordHash, Email, DisplayName, IsAdmin, IsActive, TwoFactorEnabled, TwoFactorSecret, CreatedAt, LastLoginAt)
VALUES ($u,$p,$e,$d,$a,$active,$tfa,$secret,$c,$l);";
        cmd.Parameters.AddWithValue("$u", username);
        cmd.Parameters.AddWithValue("$p", hash);
        cmd.Parameters.AddWithValue("$e", (object?)NullIfEmpty(Str(row, "email")) ?? DBNull.Value);
        cmd.Parameters.AddWithValue("$d", (object?)NullIfEmpty(display) ?? DBNull.Value);
        cmd.Parameters.AddWithValue("$a", Bool(row, "is_admin", false) ? 1 : 0);
        cmd.Parameters.AddWithValue("$active", Bool(row, "is_active", true) ? 1 : 0);
        cmd.Parameters.AddWithValue("$tfa", Bool(row, "two_factor_enabled", false) ? 1 : 0);
        cmd.Parameters.AddWithValue("$secret", (object?)NullIfEmpty(Str(row, "two_factor_secret")) ?? DBNull.Value);
        cmd.Parameters.AddWithValue("$c", Coalesce(Str(row, "created_at"), now));
        cmd.Parameters.AddWithValue("$l", (object?)NullIfEmpty(Coalesce(Str(row, "last_login"), Str(row, "LastLoginAt"))) ?? DBNull.Value);
        cmd.ExecuteNonQuery();
        ctx.UsersMigrated++;
    }
}

static void MigrateCluster(MigrateContext ctx)
{
    var src = Path.Combine(ctx.SourceDb, "servermanager.db");
    if (!File.Exists(src))
    {
        Console.WriteLine("skip cluster: source DB missing");
        return;
    }

    var dest = Path.Combine(ctx.DestDb, "servermanager.db");
    using var sconn = Open(src, readOnly: true);
    using var dconn = Open(dest, readOnly: false);

    UpsertConfigTable(ctx, sconn, dconn, "main_config", keyCol: "config_key", valueCol: "config_value", typeCol: "config_type");
    UpsertConfigTable(ctx, sconn, dconn, "dashboard_config", keyCol: "config_key", valueCol: "config_value", typeCol: "config_type", keyPrefix: "dashboard.");
    UpsertConfigTable(ctx, sconn, dconn, "update_config", keyCol: "config_key", valueCol: "config_value", typeCol: "config_type", keyPrefix: "update.");

    if (TableExists(sconn, "cluster_config"))
    {
        var rows = Query(sconn, "SELECT * FROM cluster_config LIMIT 1");
        if (rows.Count > 0)
        {
            var row = rows[0];
            UpsertConfig(ctx, dconn, "cluster.host_type", Str(row, "host_type"), "string");
            UpsertConfig(ctx, dconn, "cluster.cluster_name", Str(row, "cluster_name"), "string");
            UpsertConfig(ctx, dconn, "cluster.cluster_secret", Str(row, "cluster_secret"), "string");
            UpsertConfig(ctx, dconn, "cluster.master_ip", Remap(ctx, Str(row, "master_ip")) ?? Str(row, "master_ip"), "string");
        }
    }

    if (TableExists(sconn, "cluster_nodes"))
    {
        var rows = Query(sconn, "SELECT * FROM cluster_nodes");
        Console.WriteLine($"cluster_nodes: {rows.Count} row(s)");
        foreach (var row in rows)
        {
            var nodeId = Coalesce(Str(row, "node_id"), Str(row, "NodeId"), Str(row, "name"));
            if (string.IsNullOrWhiteSpace(nodeId)) continue;
            var address = Remap(ctx, Coalesce(Str(row, "address"), Str(row, "Address"), Str(row, "ip_address"))) ?? "";
            var now = DateTime.UtcNow.ToString("o");
            if (ctx.DryRun) { ctx.ClusterMigrated++; continue; }

            using (var del = dconn.CreateCommand())
            {
                del.CommandText = "DELETE FROM cluster_nodes WHERE NodeId=$id";
                del.Parameters.AddWithValue("$id", nodeId);
                del.ExecuteNonQuery();
            }
            using var cmd = dconn.CreateCommand();
            cmd.CommandText = @"
INSERT INTO cluster_nodes (NodeId, NodeType, DisplayName, Address, Port, Status, LastHeartbeat, Token, CreatedAt)
VALUES ($NodeId,$NodeType,$DisplayName,$Address,$Port,$Status,$LastHeartbeat,$Token,$CreatedAt);";
            cmd.Parameters.AddWithValue("$NodeId", nodeId);
            cmd.Parameters.AddWithValue("$NodeType", Coalesce(Str(row, "node_type"), Str(row, "NodeType"), "subhost"));
            cmd.Parameters.AddWithValue("$DisplayName", (object?)NullIfEmpty(Coalesce(Str(row, "display_name"), Str(row, "DisplayName"), Str(row, "hostname"), Str(row, "name"))) ?? DBNull.Value);
            cmd.Parameters.AddWithValue("$Address", (object?)NullIfEmpty(address) ?? DBNull.Value);
            cmd.Parameters.AddWithValue("$Port", IntOrDbNull(row, "port"));
            cmd.Parameters.AddWithValue("$Status", Coalesce(Str(row, "status"), Str(row, "Status"), "unknown"));
            cmd.Parameters.AddWithValue("$LastHeartbeat", (object?)NullIfEmpty(Coalesce(Str(row, "last_heartbeat"), Str(row, "LastHeartbeat"), Str(row, "last_ping"))) ?? DBNull.Value);
            cmd.Parameters.AddWithValue("$Token", (object?)NullIfEmpty(Coalesce(Str(row, "token"), Str(row, "Token"), Str(row, "cluster_token"))) ?? DBNull.Value);
            cmd.Parameters.AddWithValue("$CreatedAt", Coalesce(Str(row, "created_at"), Str(row, "CreatedAt"), Str(row, "added_at"), now));
            cmd.ExecuteNonQuery();
            ctx.ClusterMigrated++;
        }
    }

    if (TableExists(sconn, "pending_requests"))
    {
        var rows = Query(sconn, "SELECT * FROM pending_requests");
        Console.WriteLine($"pending_requests: {rows.Count} row(s)");
        foreach (var row in rows)
        {
            var subhostId = Coalesce(Str(row, "subhost_id"), Str(row, "SubhostId"), Str(row, "node_name"));
            if (string.IsNullOrWhiteSpace(subhostId)) continue;
            var address = Remap(ctx, Coalesce(Str(row, "address"), Str(row, "Address"), Str(row, "ip_address"))) ?? "";
            var now = DateTime.UtcNow.ToString("o");
            if (ctx.DryRun) { ctx.ClusterMigrated++; continue; }

            using var cmd = dconn.CreateCommand();
            cmd.CommandText = @"
INSERT INTO pending_requests (SubhostId, MachineName, Address, Status, CreatedAt)
VALUES ($SubhostId,$MachineName,$Address,$Status,$CreatedAt);";
            cmd.Parameters.AddWithValue("$SubhostId", subhostId);
            cmd.Parameters.AddWithValue("$MachineName", (object?)NullIfEmpty(Coalesce(Str(row, "machine_name"), Str(row, "MachineName"))) ?? DBNull.Value);
            cmd.Parameters.AddWithValue("$Address", (object?)NullIfEmpty(address) ?? DBNull.Value);
            cmd.Parameters.AddWithValue("$Status", Coalesce(Str(row, "status"), Str(row, "Status"), "pending"));
            cmd.Parameters.AddWithValue("$CreatedAt", Coalesce(Str(row, "created_at"), Str(row, "CreatedAt"), Str(row, "requested_at"), now));
            cmd.ExecuteNonQuery();
            ctx.ClusterMigrated++;
        }
    }

    // Steam credentials: XOR ciphertext from legacy will NOT decrypt under Data Protection — copy username only tip
    if (TableExists(sconn, "steam_credentials"))
    {
        var rows = Query(sconn, "SELECT * FROM steam_credentials");
        Console.WriteLine($"steam_credentials: {rows.Count} row(s) (username copied; re-enter password in UI — encryption differs)");
        foreach (var row in rows)
        {
            var username = Coalesce(Str(row, "username"), Str(row, "Username"));
            if (string.IsNullOrWhiteSpace(username)) continue;
            if (ctx.DryRun) continue;

            using (var del = dconn.CreateCommand())
            {
                del.CommandText = "DELETE FROM steam_credentials WHERE Username=$u";
                del.Parameters.AddWithValue("$u", username);
                del.ExecuteNonQuery();
            }
            using var cmd = dconn.CreateCommand();
            cmd.CommandText = @"INSERT INTO steam_credentials (Username, ProtectedPassword, UpdatedAt)
VALUES ($u,$p,$t);";
            cmd.Parameters.AddWithValue("$u", username);
            // Do not copy legacy XOR blob as ProtectedPassword — it is incompatible
            cmd.Parameters.AddWithValue("$p", "");
            cmd.Parameters.AddWithValue("$t", DateTime.UtcNow.ToString("o"));
            cmd.ExecuteNonQuery();
        }
    }
}

static void UpsertConfigTable(MigrateContext ctx, SqliteConnection sconn, SqliteConnection dconn, string table,
    string keyCol, string valueCol, string typeCol, string keyPrefix = "")
{
    if (!TableExists(sconn, table)) return;
    var rows = Query(sconn, $"SELECT * FROM {table}");
    Console.WriteLine($"{table}: {rows.Count} row(s)");
    foreach (var row in rows)
    {
        var key = Coalesce(Str(row, keyCol), Str(row, "key"), Str(row, "Key"));
        if (string.IsNullOrWhiteSpace(key)) continue;
        key = keyPrefix + key;
        var value = Coalesce(Str(row, valueCol), Str(row, "value"), Str(row, "Value"));
        var type = Coalesce(Str(row, typeCol), Str(row, "value_type"), Str(row, "ValueType"), "string");

        if (key.Contains("path", StringComparison.OrdinalIgnoreCase)
            || key.Contains("dir", StringComparison.OrdinalIgnoreCase)
            || key.Contains("steam_cmd", StringComparison.OrdinalIgnoreCase))
        {
            value = Remap(ctx, value) ?? value;
        }

        UpsertConfig(ctx, dconn, key, value, type);
    }
}

static void UpsertConfig(MigrateContext ctx, SqliteConnection dconn, string key, string? value, string type)
{
    if (string.IsNullOrWhiteSpace(key)) return;
    if (ctx.DryRun) { ctx.ConfigMigrated++; return; }

    using (var del = dconn.CreateCommand())
    {
        del.CommandText = "DELETE FROM main_config WHERE Key=$k";
        del.Parameters.AddWithValue("$k", key);
        del.ExecuteNonQuery();
    }
    using var cmd = dconn.CreateCommand();
    cmd.CommandText = "INSERT INTO main_config (Key, Value, ValueType) VALUES ($k,$v,$t)";
    cmd.Parameters.AddWithValue("$k", key);
    cmd.Parameters.AddWithValue("$v", value ?? "");
    cmd.Parameters.AddWithValue("$t", string.IsNullOrWhiteSpace(type) ? "string" : type);
    cmd.ExecuteNonQuery();
    ctx.ConfigMigrated++;
}

static void CopyCatalogDatabases(MigrateContext ctx)
{
    foreach (var name in new[] { "steam_ID.db", "minecraft_ID.db", "minecraft_modded_ID.db", "console_states.db" })
    {
        var src = Path.Combine(ctx.SourceDb, name);
        if (!File.Exists(src)) continue;
        var dest = Path.Combine(ctx.DestDb, name);
        Console.WriteLine($"catalog copy: {name}");
        if (!ctx.DryRun) File.Copy(src, dest, overwrite: true);
        ctx.FilesCopied++;
    }
}

static void CopySsl(MigrateContext ctx)
{
    var src = Path.Combine(ctx.SourceRoot, "ssl");
    var dest = Path.Combine(ctx.DestRoot, "ssl");
    if (!Directory.Exists(src)) return;
    Console.WriteLine("copying ssl\\");
    if (ctx.DryRun) return;
    Directory.CreateDirectory(dest);
    foreach (var file in Directory.GetFiles(src))
    {
        File.Copy(file, Path.Combine(dest, Path.GetFileName(file)), overwrite: true);
        ctx.FilesCopied++;
    }
}

static void WriteSummary(MigrateContext ctx)
{
    Console.WriteLine();
    Console.WriteLine("Migration summary");
    Console.WriteLine($"  Servers (SQL) : {ctx.ServersMigrated}");
    Console.WriteLine($"  Servers (JSON→SQL): {ctx.JsonServersMigrated}");
    Console.WriteLine($"  Permissions  : {ctx.PermissionsMigrated}");
    Console.WriteLine($"  Users        : {ctx.UsersMigrated}");
    Console.WriteLine($"  Config rows  : {ctx.ConfigMigrated}");
    Console.WriteLine($"  Cluster rows : {ctx.ClusterMigrated}");
    Console.WriteLine($"  Files copied : {ctx.FilesCopied}");
    Console.WriteLine();
    Console.WriteLine("Notes:");
    Console.WriteLine("  - Server configs are stored only in SQLite (db\\servermanager_servers.db).");
    Console.WriteLine("  - Legacy servers\\*.json (if any) were imported into that database.");
    Console.WriteLine("  - Process IDs were not migrated; start servers from the new HostRuntime.");
    Console.WriteLine("  - Steam usernames are copied; re-enter the Steam password in settings (legacy XOR != Data Protection).");
    Console.WriteLine("  - Optional --path-remap only rewrites install-folder prefixes; it is not a server config file.");
}

static string NormalizeServerType(string? raw)
{
    var t = (raw ?? "").Trim().ToLowerInvariant();
    if (t.Contains("minecraft") && t.Contains("mod")) return "minecraft_modded";
    if (t.Contains("minecraft")) return "minecraft";
    if (string.IsNullOrWhiteSpace(t) || t is "unknown") return "steam";
    return t;
}

static string? Remap(MigrateContext ctx, string? path)
{
    if (string.IsNullOrWhiteSpace(path)) return path;
    foreach (var kv in ctx.PathRemap.OrderByDescending(k => k.Key.Length))
    {
        if (path.StartsWith(kv.Key, StringComparison.OrdinalIgnoreCase))
            return kv.Value + path[kv.Key.Length..];
    }
    return path;
}

static void Exec(MigrateContext ctx, string dbPath, string sql)
{
    if (ctx.DryRun) return;
    Directory.CreateDirectory(Path.GetDirectoryName(dbPath)!);
    using var conn = Open(dbPath, readOnly: false);
    using var cmd = conn.CreateCommand();
    cmd.CommandText = sql;
    cmd.ExecuteNonQuery();
}

static SqliteConnection Open(string path, bool readOnly)
{
    var cs = new SqliteConnectionStringBuilder
    {
        DataSource = path,
        Mode = readOnly ? SqliteOpenMode.ReadOnly : SqliteOpenMode.ReadWriteCreate
    }.ToString();
    var conn = new SqliteConnection(cs);
    conn.Open();
    return conn;
}

static bool TableExists(SqliteConnection conn, string table)
{
    using var cmd = conn.CreateCommand();
    cmd.CommandText = "SELECT 1 FROM sqlite_master WHERE type='table' AND name=$n LIMIT 1";
    cmd.Parameters.AddWithValue("$n", table);
    return cmd.ExecuteScalar() is not null;
}

static List<Dictionary<string, object?>> Query(SqliteConnection conn, string sql)
{
    var list = new List<Dictionary<string, object?>>();
    using var cmd = conn.CreateCommand();
    cmd.CommandText = sql;
    using var r = cmd.ExecuteReader();
    while (r.Read())
    {
        var row = new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase);
        for (var i = 0; i < r.FieldCount; i++)
            row[r.GetName(i)] = r.IsDBNull(i) ? null : r.GetValue(i);
        list.Add(row);
    }
    return list;
}

static string Str(Dictionary<string, object?> row, string key)
    => row.TryGetValue(key, out var v) && v is not null ? Convert.ToString(v, CultureInfo.InvariantCulture) ?? "" : "";

static string Coalesce(params string?[] values)
    => values.FirstOrDefault(v => !string.IsNullOrWhiteSpace(v)) ?? "";

static string? NullIfEmpty(string? s) => string.IsNullOrWhiteSpace(s) ? null : s;

static bool Bool(Dictionary<string, object?> row, string key, bool defaultValue)
{
    if (!row.TryGetValue(key, out var v) || v is null) return defaultValue;
    if (v is bool b) return b;
    if (v is long l) return l != 0;
    if (v is int i) return i != 0;
    var s = Convert.ToString(v, CultureInfo.InvariantCulture);
    if (bool.TryParse(s, out var pb)) return pb;
    if (int.TryParse(s, out var pi)) return pi != 0;
    return defaultValue;
}

static object IntOrDbNull(Dictionary<string, object?> row, string key)
{
    if (!row.TryGetValue(key, out var v) || v is null || v is DBNull) return DBNull.Value;
    if (v is int i) return i;
    if (v is long l) return (int)l;
    if (int.TryParse(Convert.ToString(v, CultureInfo.InvariantCulture), out var p)) return p;
    return DBNull.Value;
}

sealed class MigrateContext
{
    public MigrateContext(string sourceRoot, string destRoot, bool dryRun, Dictionary<string, string> remap)
    {
        SourceRoot = Path.GetFullPath(sourceRoot);
        DestRoot = Path.GetFullPath(destRoot);
        DryRun = dryRun;
        PathRemap = remap;
        SourceDb = Path.Combine(SourceRoot, "db");
        DestDb = Path.Combine(DestRoot, "db");
    }

    public string SourceRoot { get; }
    public string DestRoot { get; }
    public string SourceDb { get; }
    public string DestDb { get; }
    public bool DryRun { get; }
    public Dictionary<string, string> PathRemap { get; }
    public int ServersMigrated { get; set; }
    public int JsonServersMigrated { get; set; }
    public int PermissionsMigrated { get; set; }
    public int UsersMigrated { get; set; }
    public int ConfigMigrated { get; set; }
    public int ClusterMigrated { get; set; }
    public int FilesCopied { get; set; }
}
