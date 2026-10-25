using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Serilog;
using Serilog.Events;
using ServerManager.Core.Configuration;
using ServerManager.Core.Paths;
using ServerManager.Core.Process;

namespace ServerManager.Core;

public static class ServiceCollectionExtensions
{
    public static IServiceCollection AddServerManagerCore(this IServiceCollection services)
    {
        services.AddSingleton<IAppPaths, AppPaths>();
        services.AddSingleton<WindowsRegistryConfigStore>();
        services.AddSingleton<FileConfigStore>();
        services.AddSingleton<IConfigStore, CompositeConfigStore>();
        services.AddSingleton<PidFileManager>();
        services.AddSingleton<ProcessIdentityService>();
        services.AddSingleton<WindowsConsoleCommandSender>();
        return services;
    }

    public static void ConfigureServerManagerLogging(string componentName, IAppPaths paths)
    {
        paths.EnsureDirectories();
        PruneComponentLogs(paths.ComponentsLogs);

        var logFile = Path.Combine(paths.ComponentsLogs, $"{componentName}.log");
        Log.Logger = new LoggerConfiguration()
            .MinimumLevel.Information()
            .MinimumLevel.Override("Microsoft", LogEventLevel.Warning)
            .MinimumLevel.Override("Microsoft.EntityFrameworkCore", LogEventLevel.Warning)
            .MinimumLevel.Override("Microsoft.AspNetCore", LogEventLevel.Warning)
            .MinimumLevel.Override("Microsoft.AspNetCore.Authentication", LogEventLevel.Warning)
            .MinimumLevel.Override("System", LogEventLevel.Warning)
            .Enrich.FromLogContext()
            .WriteTo.Console()
            .WriteTo.File(
                logFile,
                rollingInterval: RollingInterval.Day,
                retainedFileCountLimit: 7,
                fileSizeLimitBytes: 64L * 1024 * 1024,
                rollOnFileSizeLimit: true,
                shared: true)
            .CreateLogger();
    }

    /// <summary>Delete old / oversized component logs so a week of Debug EF spam cannot fill the disk.</summary>
    public static void PruneComponentLogs(string componentsLogsDir, int retainDays = 7, long maxFileBytes = 80L * 1024 * 1024)
    {
        try
        {
            if (!Directory.Exists(componentsLogsDir)) return;
            var cutoff = DateTime.UtcNow.AddDays(-retainDays);
            foreach (var file in Directory.EnumerateFiles(componentsLogsDir, "*.log*", SearchOption.TopDirectoryOnly))
            {
                try
                {
                    var info = new FileInfo(file);
                    if (info.LastWriteTimeUtc < cutoff || info.Length > maxFileBytes)
                        info.Delete();
                }
                catch { /* file locked */ }
            }
        }
        catch { /* best effort */ }
    }

    public static ILoggingBuilder AddServerManagerSerilog(this ILoggingBuilder builder)
    {
        builder.ClearProviders();
        builder.AddSerilog(dispose: true);
        return builder;
    }
}
