using Microsoft.Extensions.DependencyInjection;

namespace ServerManager.Steam;

public static class SteamServiceCollectionExtensions
{
    public static IServiceCollection AddSteamServices(this IServiceCollection services)
    {
        services.AddHttpClient("steam");
        services.AddScoped<SteamAppIdScanner>();
        return services;
    }
}
