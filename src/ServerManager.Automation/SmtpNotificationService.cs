using System.Net;
using System.Net.Mail;
using Microsoft.Extensions.Logging;

namespace ServerManager.Automation;

public sealed class SmtpNotificationService
{
    private readonly ILogger<SmtpNotificationService> _logger;

    public SmtpNotificationService(ILogger<SmtpNotificationService> logger) => _logger = logger;

    public async Task SendAsync(SmtpSettings settings, string to, string subject, string body, bool html = true, CancellationToken ct = default)
    {
        using var client = new SmtpClient(settings.Host, settings.Port)
        {
            EnableSsl = settings.UseSsl,
            Credentials = string.IsNullOrWhiteSpace(settings.Username)
                ? CredentialCache.DefaultNetworkCredentials
                : new NetworkCredential(settings.Username, settings.Password)
        };
        using var msg = new MailMessage(settings.From, to, subject, body) { IsBodyHtml = html };
        await client.SendMailAsync(msg, ct);
        _logger.LogInformation("Sent mail to {To}: {Subject}", to, subject);
    }
}

public sealed class SmtpSettings
{
    public string Host { get; set; } = "localhost";
    public int Port { get; set; } = 25;
    public bool UseSsl { get; set; }
    public string From { get; set; } = "servermanager@localhost";
    public string? Username { get; set; }
    public string? Password { get; set; }
}
