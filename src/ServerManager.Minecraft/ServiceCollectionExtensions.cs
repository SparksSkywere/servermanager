using System.Net.Http.Json;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace ServerManager.Minecraft;

public static class MinecraftServiceCollectionExtensions
{
    public static IServiceCollection AddMinecraftServices(this IServiceCollection services)
    {
        services.AddHttpClient("minecraft");
        services.AddSingleton<MinecraftInstaller>();
        services.AddScoped<MinecraftCatalogScanner>();
        services.AddScoped<ModdedCatalogScanner>();
        return services;
    }
}
