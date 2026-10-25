using System.CommandLine;
using Microsoft.Data.Sqlite;
using BCrypt.Net;

static string DefaultRuntimeRoot()
{
    // Prefer SERVERMANAGER_ROOT, then sibling ../runtime from the tools folder, else cwd/runtime.
    var env = Environment.GetEnvironmentVariable("SERVERMANAGER_ROOT")
           ?? Environment.GetEnvironmentVariable("ServerManager__RootPath");
    if (!string.IsNullOrWhiteSpace(env)) return env;

    var baseDir = AppContext.BaseDirectory;
    foreach (var candidate in new[]
             {
                 Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "..", "runtime")),
                 Path.GetFullPath(Path.Combine(Directory.GetCurrentDirectory(), "runtime")),
                 Path.Combine(Directory.GetCurrentDirectory())
             })
    {
        if (Directory.Exists(Path.Combine(candidate, "db")) || File.Exists(Path.Combine(candidate, "db", "servermanager_users.db")))
            return candidate;
    }

    return Path.Combine(Directory.GetCurrentDirectory(), "runtime");
}

var rootOption = new Option<string>("--root", DefaultRuntimeRoot, "Server Manager runtime root (contains db\\)");
var userOption = new Option<string>("--user", () => "admin", "Username");
var passOption = new Option<string>("--password") { IsRequired = true };
var reset2fa = new Option<bool>("--reset-2fa", () => false);

var rootCommand = new RootCommand("Reset Server Manager admin password / 2FA");
rootCommand.AddOption(rootOption);
rootCommand.AddOption(userOption);
rootCommand.AddOption(passOption);
rootCommand.AddOption(reset2fa);

rootCommand.SetHandler((string root, string user, string password, bool clear2fa) =>
{
    var db = Path.Combine(root, "db", "servermanager_users.db");
    if (!File.Exists(db)) throw new FileNotFoundException(db);
    var hash = BCrypt.Net.BCrypt.HashPassword(password);
    using var conn = new SqliteConnection($"Data Source={db}");
    conn.Open();
    using var cmd = conn.CreateCommand();
    cmd.CommandText = clear2fa
        ? "UPDATE users SET PasswordHash=$p, TwoFactorEnabled=0, TwoFactorSecret=NULL WHERE Username=$u"
        : "UPDATE users SET PasswordHash=$p WHERE Username=$u";
    cmd.Parameters.AddWithValue("$p", hash);
    cmd.Parameters.AddWithValue("$u", user);
    var n = cmd.ExecuteNonQuery();
    Console.WriteLine(n > 0 ? $"Updated {user}" : "User not found");
}, rootOption, userOption, passOption, reset2fa);

return await rootCommand.InvokeAsync(args);
