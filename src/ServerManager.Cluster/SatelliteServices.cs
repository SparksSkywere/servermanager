using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Routing;
using Microsoft.Extensions.DependencyInjection;
using ServerManager.Core.Configuration;

namespace ServerManager.Cluster;

public sealed class PrometheusMetrics
{
    private long _requests;

    public void Inc() => Interlocked.Increment(ref _requests);
    public long Requests => Interlocked.Read(ref _requests);

    public string Render()
    {
        var sb = new StringBuilder();
        sb.AppendLine("# HELP servermanager_http_requests_total Total HTTP requests observed");
        sb.AppendLine("# TYPE servermanager_http_requests_total counter");
        sb.AppendLine($"servermanager_http_requests_total {_requests}");
        sb.AppendLine("# HELP servermanager_up 1 if process is up");
        sb.AppendLine("# TYPE servermanager_up gauge");
        sb.AppendLine("servermanager_up 1");
        return sb.ToString();
    }
}

public sealed class TemperatureService
{
    private readonly IConfigStore _cfg;
    private readonly IHttpClientFactory _httpFactory;

    public TemperatureService(IConfigStore cfg, IHttpClientFactory httpFactory)
    {
        _cfg = cfg;
        _httpFactory = httpFactory;
    }

    public async Task<object> GetTemperaturesAsync(CancellationToken ct = default)
    {
        var local = new List<object>();
        var mode = (_cfg.Get("TempMode") ?? "auto").Trim().ToLowerInvariant();
        var wantLocal = mode is "auto" or "local";
        var wantBmc = mode is "auto" or "ilo" or "idrac";

        if (wantLocal && OperatingSystem.IsWindows())
        {
            var gotReading = false;
            try
            {
                using var searcher = new System.Management.ManagementObjectSearcher(@"root\WMI", "SELECT * FROM MSAcpi_ThermalZoneTemperature");
                foreach (var obj in searcher.Get())
                {
                    var raw = Convert.ToDouble(obj["CurrentTemperature"]);
                    var celsius = (raw / 10.0) - 273.15;
                    if (celsius is < -40 or > 125) continue;
                    local.Add(new { source = "ACPI thermal zone", celsius = Math.Round(celsius, 1) });
                    gotReading = true;
                }
            }
            catch
            {
                // MSAcpi often unavailable without admin / on many PCs
            }

            // nvidia-smi GPU temps
            try
            {
                var psi = new System.Diagnostics.ProcessStartInfo
                {
                    FileName = "nvidia-smi",
                    Arguments = "--query-gpu=name,temperature.gpu --format=csv,noheader,nounits",
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                    CreateNoWindow = true
                };
                using var proc = System.Diagnostics.Process.Start(psi);
                if (proc is not null)
                {
                    var output = await proc.StandardOutput.ReadToEndAsync(ct);
                    await proc.WaitForExitAsync(ct);
                    foreach (var line in output.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
                    {
                        var parts = line.Split(',', StringSplitOptions.TrimEntries);
                        if (parts.Length >= 2 && double.TryParse(parts[^1], out var gpuC))
                        {
                            local.Add(new { source = $"GPU ({parts[0]})", celsius = gpuC });
                            gotReading = true;
                        }
                    }
                }
            }
            catch { /* nvidia-smi optional */ }

            if (!gotReading)
                local.Add(new { source = "local", note = "unavailable", message = "No local temperature sensors detected (ACPI/WMI often needs admin or is unsupported on this hardware)." });
        }

        var redfish = new List<object>();
        if (wantBmc)
        {
            foreach (var (name, hostKey, userKey, passKey) in new[]
                     {
                         ("ilo", "IloHost", "IloUser", "IloPassword"),
                         ("idrac", "IdracHost", "IdracUser", "IdracPassword")
                     })
            {
                if (mode is "ilo" && name != "ilo") continue;
                if (mode is "idrac" && name != "idrac") continue;
                var host = _cfg.Get(hostKey);
                if (string.IsNullOrWhiteSpace(host)) continue;
                try
                {
                    var client = _httpFactory.CreateClient("redfish");
                    client.Timeout = TimeSpan.FromSeconds(8);
                    var user = _cfg.Get(userKey) ?? "admin";
                    var pass = _cfg.Get(passKey) ?? "";
                    var auth = Convert.ToBase64String(Encoding.UTF8.GetBytes($"{user}:{pass}"));
                    using var req = new HttpRequestMessage(HttpMethod.Get, $"https://{host}/redfish/v1/Chassis");
                    req.Headers.Authorization = new AuthenticationHeaderValue("Basic", auth);
                    using var resp = await client.SendAsync(req, ct);
                    redfish.Add(new
                    {
                        source = name.ToUpperInvariant(),
                        host,
                        status = (int)resp.StatusCode,
                        ok = resp.IsSuccessStatusCode,
                        note = resp.IsSuccessStatusCode ? "BMC reachable" : "BMC request failed"
                    });
                }
                catch (Exception ex)
                {
                    redfish.Add(new { source = name.ToUpperInvariant(), host, error = ex.Message });
                }
            }
        }

        return new { local, redfish };
    }
}

public sealed class SmtpSettingsService
{
    private readonly IConfigStore _cfg;

    public SmtpSettingsService(IConfigStore cfg) => _cfg = cfg;

    public object Get() => new
    {
        host = _cfg.Get("SmtpHost"),
        port = _cfg.Get("SmtpPort") ?? "587",
        user = _cfg.Get("SmtpUser"),
        from = _cfg.Get("SmtpFrom"),
        tls = _cfg.GetOrDefault("SmtpTls", "true") == "true"
    };

    public object Test()
    {
        var host = _cfg.Get("SmtpHost");
        if (string.IsNullOrWhiteSpace(host))
            return new { ok = false, error = "SmtpHost not configured" };
        try
        {
            using var client = new System.Net.Sockets.TcpClient();
            var port = int.TryParse(_cfg.Get("SmtpPort"), out var p) ? p : 587;
            var ok = client.ConnectAsync(host, port).Wait(3000);
            return new { ok, host, port };
        }
        catch (Exception ex)
        {
            return new { ok = false, error = ex.Message };
        }
    }
}

public static class SatelliteEndpointExtensions
{
    public static IServiceCollection AddSatelliteServices(this IServiceCollection services)
    {
        services.AddSingleton<PrometheusMetrics>();
        services.AddSingleton<TemperatureService>();
        services.AddSingleton<SmtpSettingsService>();
        services.AddHttpClient("redfish")
            .ConfigurePrimaryHttpMessageHandler(() => new HttpClientHandler
            {
                ServerCertificateCustomValidationCallback = HttpClientHandler.DangerousAcceptAnyServerCertificateValidator
            });
        return services;
    }

    public static IEndpointRouteBuilder MapSatelliteEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/api/analytics/snmp", (PrometheusMetrics m) => Results.Ok(new
        {
            oid_prefix = "1.3.6.1.4.1.12345",
            requests = m.Requests,
            oids = new object[]
            {
                new { oid = "1.3.6.1.4.1.12345.1.1", name = "servermanager.up", value = (long)1 },
                new { oid = "1.3.6.1.4.1.12345.1.2", name = "servermanager.http_requests", value = m.Requests }
            },
            note = "SNMP OID map compatibility shim for Grafana/Prometheus scrape"
        })).RequireAuthorization();

        app.MapGet("/api/analytics/temperatures", async (TemperatureService temps, CancellationToken ct) =>
            Results.Ok(await temps.GetTemperaturesAsync(ct))).RequireAuthorization();

        app.MapGet("/api/analytics/smtp", (SmtpSettingsService smtp) => Results.Ok(smtp.Get())).RequireAuthorization();
        app.MapPost("/api/analytics/smtp/test", (SmtpSettingsService smtp) => Results.Ok(smtp.Test())).RequireAuthorization();

        app.MapGet("/api/analytics/debug", (PrometheusMetrics m, IConfigStore cfg) => Results.Ok(new
        {
            service = "web",
            requests = m.Requests,
            host_type = cfg.Get("HostType"),
            machine = Environment.MachineName,
            os = Environment.OSVersion.ToString(),
            utc = DateTime.UtcNow
        })).RequireAuthorization();

        return app;
    }
}
