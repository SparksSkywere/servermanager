using System.Diagnostics;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using ServerManager.Core;
using ServerManager.Core.Configuration;
using ServerManager.Security;

namespace ServerManager.Steam;

/// <summary>Serializes all SteamCMD invocations (one at a time).</summary>
public sealed class SteamCmdService
{
    private readonly SemaphoreSlim _lock = new(1, 1);
    private readonly ServerManagerOptions _options;
    private readonly SecretProtector _secrets;
    private readonly ILogger<SteamCmdService> _logger;

    public SteamCmdService(IOptions<ServerManagerOptions> options, SecretProtector secrets, ILogger<SteamCmdService> logger)
    {
        _options = options.Value;
        _secrets = secrets;
        _logger = logger;
    }

    public async Task<(bool Ok, string Output)> InstallOrUpdateAsync(
        string appId,
        string installDir,
        string? username = null,
        string? protectedPassword = null,
        bool validate = true,
        CancellationToken ct = default)
    {
        await _lock.WaitAsync(ct);
        try
        {
            var steamCmd = ResolveSteamCmd();
            if (steamCmd is null)
                return (false, "SteamCMD not found. Set SteamCmdPath in config.");

            Directory.CreateDirectory(installDir);
            var loginUser = string.IsNullOrWhiteSpace(username) ? "anonymous" : username.Trim();
            string? password = null;
            if (!string.IsNullOrWhiteSpace(protectedPassword) && loginUser != "anonymous")
            {
                try { password = _secrets.Unprotect(protectedPassword); }
                catch
                {
                    // Settings UI often stores plaintext; accept either form.
                    password = protectedPassword;
                }
            }

            var args = $"+force_install_dir \"{installDir}\" +login {loginUser}";
            if (!string.IsNullOrEmpty(password) && loginUser != "anonymous")
                args += $" \"{password}\"";
            args += $" +app_update {appId}";
            if (validate) args += " validate";
            args += " +quit";

            _logger.LogInformation("SteamCMD app_update {AppId} -> {Dir}", appId, installDir);
            var psi = new ProcessStartInfo
            {
                FileName = steamCmd,
                Arguments = args,
                WorkingDirectory = Path.GetDirectoryName(steamCmd)!,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };

            using var proc = System.Diagnostics.Process.Start(psi)
                             ?? throw new InvalidOperationException("Failed to start SteamCMD");
            var stdout = await proc.StandardOutput.ReadToEndAsync(ct);
            var stderr = await proc.StandardError.ReadToEndAsync(ct);
            await proc.WaitForExitAsync(ct);
            var output = stdout + stderr;
            var ok = proc.ExitCode == 0;
            if (!ok) _logger.LogWarning("SteamCMD exit {Code}: {Out}", proc.ExitCode, output);
            return (ok, output);
        }
        finally
        {
            _lock.Release();
        }
    }

    public string? ResolveSteamCmd()
    {
        var configured = _options.SteamCmdPath;
        if (!string.IsNullOrWhiteSpace(configured))
        {
            var exe = configured.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)
                ? configured
                : Path.Combine(configured, OperatingSystem.IsWindows() ? "steamcmd.exe" : "steamcmd.sh");
            if (File.Exists(exe)) return exe;
        }

        var guesses = new[]
        {
            @"C:\SteamCMD\steamcmd.exe",
            @"C:\Program Files\SteamCMD\steamcmd.exe",
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "SteamCMD", "steamcmd.exe")
        };
        return guesses.FirstOrDefault(File.Exists);
    }
}
