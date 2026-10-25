using System.Diagnostics;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.Extensions.Logging;

namespace ServerManager.Minecraft;

public sealed class MinecraftInstaller
{
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly ILogger<MinecraftInstaller> _logger;

    public MinecraftInstaller(IHttpClientFactory httpClientFactory, ILogger<MinecraftInstaller> logger)
    {
        _httpClientFactory = httpClientFactory;
        _logger = logger;
    }

    public async Task<(bool Ok, string Message)> InstallVanillaAsync(string installDir, string version, string? javaPath = null, CancellationToken ct = default)
    {
        Directory.CreateDirectory(installDir);
        var client = _httpClientFactory.CreateClient("minecraft");
        var manifest = await client.GetFromJsonAsync<JsonElement>("https://launchermeta.mojang.com/mc/game/version_manifest_v2.json", ct);
        string? versionUrl = null;
        foreach (var v in manifest.GetProperty("versions").EnumerateArray())
        {
            if (v.GetProperty("id").GetString() == version)
            {
                versionUrl = v.GetProperty("url").GetString();
                break;
            }
        }
        if (versionUrl is null) return (false, $"Version {version} not found");

        var versionJson = await client.GetFromJsonAsync<JsonElement>(versionUrl, ct);
        var jarUrl = versionJson.GetProperty("downloads").GetProperty("server").GetProperty("url").GetString();
        if (jarUrl is null) return (false, "Server jar URL missing");

        var jarPath = Path.Combine(installDir, "server.jar");
        await using (var fs = File.Create(jarPath))
        {
            var stream = await client.GetStreamAsync(jarUrl, ct);
            await stream.CopyToAsync(fs, ct);
        }

        await File.WriteAllTextAsync(Path.Combine(installDir, "eula.txt"), "eula=true\n", ct);
        WriteLaunchScript(installDir, javaPath);
        _logger.LogInformation("Installed Minecraft {Version} to {Dir}", version, installDir);
        return (true, jarPath);
    }

    public static void WriteLaunchScript(string installDir, string? javaPath = null)
    {
        var java = string.IsNullOrWhiteSpace(javaPath) ? "java" : $"\"{javaPath}\"";
        if (OperatingSystem.IsWindows())
        {
            File.WriteAllText(Path.Combine(installDir, "start_server.bat"),
                $"@echo off\r\n{java} -Xmx1024M -Xms1024M -jar server.jar nogui\r\n");
        }
        else
        {
            var sh = Path.Combine(installDir, "start_server.sh");
            File.WriteAllText(sh, $"#!/bin/sh\n{java} -Xmx1024M -Xms1024M -jar server.jar nogui\n");
        }
    }

    public static string? DetectJava()
    {
        var javaHome = Environment.GetEnvironmentVariable("JAVA_HOME");
        if (!string.IsNullOrWhiteSpace(javaHome))
        {
            var exe = Path.Combine(javaHome, "bin", OperatingSystem.IsWindows() ? "java.exe" : "java");
            if (File.Exists(exe)) return exe;
        }

        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = OperatingSystem.IsWindows() ? "where" : "which",
                Arguments = "java",
                RedirectStandardOutput = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            using var p = System.Diagnostics.Process.Start(psi);
            var line = p?.StandardOutput.ReadLine();
            p?.WaitForExit(5000);
            if (!string.IsNullOrWhiteSpace(line) && File.Exists(line)) return line.Trim();
        }
        catch { /* ignore */ }
        return null;
    }

    public static int RecommendedJavaMajor(string version)
    {
        if (Version.TryParse(version.Split('-')[0], out var v))
        {
            if (v.Major == 1 && v.Minor <= 16) return 8;
            if (v.Major == 1 && v.Minor == 17) return 16;
            if (v.Major == 1 && v.Minor <= 20) return 17;
            return 21;
        }
        return 21;
    }
}
