using System.Diagnostics;

namespace ServerManager.HostUI;

internal static class LocalMetrics
{
    public static string Snapshot()
    {
        try
        {
            var drive = new DriveInfo(Path.GetPathRoot(Environment.SystemDirectory) ?? "C:\\");
            var proc = Process.GetCurrentProcess();
            return $"""
Machine: {Environment.MachineName}
OS: {Environment.OSVersion}
Processors: {Environment.ProcessorCount}
Uptime (ms tick): {Environment.TickCount64}
Process WS: {proc.WorkingSet64 / (1024 * 1024)} MB
Disk {drive.Name}: {(drive.TotalSize - drive.AvailableFreeSpace) / (1024 * 1024 * 1024)} / {drive.TotalSize / (1024 * 1024 * 1024)} GB used
""";
        }
        catch (Exception ex)
        {
            return "Local metrics unavailable: " + ex.Message;
        }
    }
}
