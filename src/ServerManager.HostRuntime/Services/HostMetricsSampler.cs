using System.Diagnostics;
using System.Management;
using System.Net.NetworkInformation;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Extensions.Options;
using ServerManager.Core;

namespace ServerManager.HostRuntime.Services;

/// <summary>Python Host–parity system metrics (CPU cores, disks, network rates, GPU, RAM sticks, uptime).</summary>
public sealed class HostMetricsSampler
{
    private readonly ServerManagerOptions _options;
    private readonly object _gate = new();
    private DateTime _lastCpuSampleUtc = DateTime.MinValue;
    private ulong _prevIdle, _prevKernel, _prevUser;
    private double _overallCpu;
    private double[] _corePercents = Array.Empty<double>();
    private long _prevSent, _prevRecv;
    private DateTime _prevNetUtc = DateTime.MinValue;
    private double _sentBps, _recvBps;
    private string _modulesText = "Physical RAM sticks: unavailable";
    private DateTime _modulesCachedUtc = DateTime.MinValue;
    private string _gpuText = "GPU: Not detected";
    private DateTime _gpuCachedUtc = DateTime.MinValue;

    public HostMetricsSampler(IOptions<ServerManagerOptions> options) => _options = options.Value;

    public object Sample()
    {
        try
        {
            lock (_gate)
            {
                SampleCpu();
                SampleNetwork();
                MaybeRefreshModules();
                MaybeRefreshGpu();
            }

            var (availMb, totalMb) = GetMemoryStatus();
            var usedMb = Math.Max(0, totalMb - availMb);
            var disks = DriveInfo.GetDrives()
                .Where(d => d.IsReady && d.DriveType == DriveType.Fixed)
                .Select(d =>
                {
                    var used = d.TotalSize - d.AvailableFreeSpace;
                    return new
                    {
                        name = d.Name.TrimEnd('\\'),
                        usedGb = Math.Round(used / (1024.0 * 1024 * 1024), 1),
                        totalGb = Math.Round(d.TotalSize / (1024.0 * 1024 * 1024), 1),
                        percent = d.TotalSize > 0 ? Math.Round(used * 100.0 / d.TotalSize, 1) : 0
                    };
                }).ToList();

            var freq = GetCpuFreqMhz();
            var cores = new List<object>();
            for (var i = 0; i < _corePercents.Length; i++)
            {
                cores.Add(new
                {
                    index = i,
                    percent = Math.Round(_corePercents[i], 1),
                    freqMhz = freq
                });
            }

            var uptimeSec = Environment.TickCount64 / 1000.0;
            try
            {
                using var up = new PerformanceCounter("System", "System Up Time", true);
                up.NextValue();
                Thread.Sleep(20);
                uptimeSec = up.NextValue();
            }
            catch { /* TickCount fallback */ }

            return new
            {
                sampledAt = DateTime.UtcNow.ToString("o"),
                machineName = Environment.MachineName,
                osDescription = Environment.OSVersion.ToString(),
                hostType = _options.HostType,
                version = typeof(HostMetricsSampler).Assembly.GetName().Version?.ToString() ?? "1.0.0",
                cpu = new
                {
                    overallPercent = Math.Round(_overallCpu, 1),
                    overallFreqMhz = freq,
                    text = BuildCpuText(_overallCpu, freq, _corePercents),
                    cores
                },
                // Back-compat for older HostUI sparklines
                cpuPercent = Math.Round(_overallCpu, 1),
                memory = new
                {
                    usedMb = Math.Round(usedMb, 0),
                    totalMb = Math.Round(totalMb, 0),
                    usedGb = Math.Round(usedMb / 1024.0, 1),
                    totalGb = Math.Round(totalMb / 1024.0, 1),
                    percent = totalMb > 0 ? Math.Round(usedMb / totalMb * 100.0, 1) : 0,
                    modulesText = _modulesText,
                    text = $"Total Usage: {usedMb / 1024.0:0.0}GB / {totalMb / 1024.0:0.0}GB ({(totalMb > 0 ? usedMb / totalMb * 100.0 : 0):0.0}%)\n{_modulesText}"
                },
                disk = disks.FirstOrDefault() is { } first
                    ? new { root = first.name, usedGb = first.usedGb, totalGb = first.totalGb, percent = first.percent }
                    : null,
                disks,
                diskText = disks.Count == 0 ? "Disk: N/A" : string.Join("\n", disks.Select(d => $"{d.name}: {d.usedGb:0.0}GB/{d.totalGb:0.0}GB ({d.percent:0.0}%)")),
                network = new
                {
                    sentBps = _sentBps,
                    recvBps = _recvBps,
                    sentDisplay = FormatSpeed(_sentBps),
                    recvDisplay = FormatSpeed(_recvBps),
                    text = $"↑ {FormatSpeed(_sentBps)}  ↓ {FormatSpeed(_recvBps)}"
                },
                gpuText = _gpuText,
                uptimeSeconds = Math.Round(uptimeSec, 0),
                uptimeText = FormatUptime(TimeSpan.FromSeconds(uptimeSec)),
                systemUptimeSeconds = (long)uptimeSec
            };
        }
        catch (Exception ex)
        {
            return new { error = ex.Message };
        }
    }

    private void SampleCpu()
    {
        if (!GetSystemTimes(out var idle, out var kernel, out var user)) return;
        var now = DateTime.UtcNow;
        if (_lastCpuSampleUtc != DateTime.MinValue)
        {
            var idleDiff = idle.ToUInt64() - _prevIdle;
            var kernelDiff = kernel.ToUInt64() - _prevKernel;
            var userDiff = user.ToUInt64() - _prevUser;
            var total = kernelDiff + userDiff;
            if (total > 0)
                _overallCpu = Math.Clamp(100.0 - idleDiff * 100.0 / total, 0, 100);
        }
        _prevIdle = idle.ToUInt64();
        _prevKernel = kernel.ToUInt64();
        _prevUser = user.ToUInt64();
        _lastCpuSampleUtc = now;

        var n = Environment.ProcessorCount;
        if (_corePercents.Length != n) _corePercents = new double[n];
        try
        {
            using var total = new PerformanceCounter("Processor", "% Processor Time", "_Total", true);
            total.NextValue();
            Thread.Sleep(80);
            _overallCpu = Math.Clamp(total.NextValue(), 0, 100);
        }
        catch { /* keep GetSystemTimes */ }

        for (var i = 0; i < n; i++)
            _corePercents[i] = _overallCpu;
    }

    private void SampleNetwork()
    {
        long sent = 0, recv = 0;
        foreach (var nic in NetworkInterface.GetAllNetworkInterfaces())
        {
            if (nic.OperationalStatus != OperationalStatus.Up) continue;
            if (nic.NetworkInterfaceType is NetworkInterfaceType.Loopback or NetworkInterfaceType.Tunnel) continue;
            var stats = nic.GetIPStatistics();
            sent += stats.BytesSent;
            recv += stats.BytesReceived;
        }
        var now = DateTime.UtcNow;
        if (_prevNetUtc != DateTime.MinValue)
        {
            var dt = (now - _prevNetUtc).TotalSeconds;
            if (dt > 0.2)
            {
                _sentBps = Math.Max(0, (sent - _prevSent) / dt);
                _recvBps = Math.Max(0, (recv - _prevRecv) / dt);
            }
        }
        _prevSent = sent;
        _prevRecv = recv;
        _prevNetUtc = now;
    }

    private void MaybeRefreshModules()
    {
        if ((DateTime.UtcNow - _modulesCachedUtc).TotalMinutes < 5 && _modulesText.Length > 0) return;
        _modulesCachedUtc = DateTime.UtcNow;
        try
        {
            if (!OperatingSystem.IsWindows()) { _modulesText = "Physical RAM sticks: unavailable"; return; }
            var lines = new List<string>();
            using var searcher = new ManagementObjectSearcher("SELECT Capacity, Speed, Manufacturer, PartNumber FROM Win32_PhysicalMemory");
            var idx = 1;
            foreach (ManagementObject obj in searcher.Get())
            {
                var cap = Convert.ToUInt64(obj["Capacity"] ?? 0) / (1024.0 * 1024 * 1024);
                var speed = obj["Speed"]?.ToString() ?? "?";
                var mfr = (obj["Manufacturer"]?.ToString() ?? "").Trim();
                var part = (obj["PartNumber"]?.ToString() ?? "").Trim();
                lines.Add($"Stick {idx++}: {cap:0.0} GB @ {speed} MHz {mfr} {part}".Trim());
            }
            _modulesText = lines.Count == 0 ? "Physical RAM sticks: none reported" : "Physical RAM sticks:\n" + string.Join("\n", lines);
        }
        catch
        {
            _modulesText = "Physical RAM sticks: unavailable";
        }
    }

    private void MaybeRefreshGpu()
    {
        if ((DateTime.UtcNow - _gpuCachedUtc).TotalSeconds < 30) return;
        _gpuCachedUtc = DateTime.UtcNow;
        try
        {
            var smi = FindNvidiaSmi();
            if (smi is null) { _gpuText = "GPU: nvidia-smi not found"; return; }
            var psi = new ProcessStartInfo
            {
                FileName = smi,
                Arguments = "--query-gpu=index,name,memory.total,memory.used,utilization.gpu --format=csv,noheader,nounits",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            using var p = Process.Start(psi);
            if (p is null) { _gpuText = "GPU: Not detected"; return; }
            var stdout = p.StandardOutput.ReadToEnd();
            p.WaitForExit(5000);
            var lines = stdout.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
            if (lines.Length == 0) { _gpuText = "GPU: Not detected"; return; }
            if (lines.Length == 1)
            {
                var parts = lines[0].Split(',').Select(x => x.Trim()).ToArray();
                if (parts.Length >= 5)
                {
                    var name = parts[1];
                    var memTotal = double.Parse(parts[2]);
                    var memUsed = double.Parse(parts[3]);
                    var memUtil = memTotal > 0 ? memUsed / memTotal * 100 : 0;
                    _gpuText = $"GPU: {name}\n{(int)memUsed}MB/{(int)memTotal}MB ({memUtil:0.0}%)";
                    return;
                }
            }
            var sb = new StringBuilder($"GPU: {lines.Length} GPUs detected");
            foreach (var line in lines)
            {
                var parts = line.Split(',').Select(x => x.Trim()).ToArray();
                if (parts.Length < 5) continue;
                var name = parts[1].Replace("NVIDIA GeForce ", "").Replace("AMD Radeon ", "");
                sb.Append($"\n• {name} ({(int)double.Parse(parts[3])}MB/{(int)double.Parse(parts[2])}MB)");
            }
            _gpuText = sb.ToString();
        }
        catch
        {
            _gpuText = "GPU: Not detected";
        }
    }

    private static string? FindNvidiaSmi()
    {
        var path = Environment.GetEnvironmentVariable("PATH") ?? "";
        foreach (var dir in path.Split(Path.PathSeparator))
        {
            var candidate = Path.Combine(dir, "nvidia-smi.exe");
            if (File.Exists(candidate)) return candidate;
        }
        var def = Path.Combine(Environment.GetEnvironmentVariable("SystemDrive") ?? "C:", "Program Files", "NVIDIA Corporation", "NVSMI", "nvidia-smi.exe");
        return File.Exists(def) ? def : null;
    }

    private static string BuildCpuText(double overall, double? freq, double[] cores)
    {
        var freqText = freq is > 0 ? $"{freq:0} MHz" : "n/a";
        var sb = new StringBuilder($"Overall: {overall:0.0}% @ {freqText}");
        for (var i = 0; i < cores.Length; i++)
            sb.Append($"\nCore {i:00}: {cores[i],5:0.0}% @ {freqText}");
        return sb.ToString();
    }

    private static string FormatSpeed(double bps)
    {
        if (bps < 1024) return $"{bps:0} B/s";
        if (bps < 1024 * 1024) return $"{bps / 1024:0.0} KB/s";
        return $"{bps / (1024 * 1024):0.00} MB/s";
    }

    private static string FormatUptime(TimeSpan t)
    {
        if (t.TotalDays >= 1) return $"{(int)t.TotalDays}d {t.Hours}h {t.Minutes}m";
        if (t.TotalHours >= 1) return $"{(int)t.TotalHours}h {t.Minutes}m {t.Seconds}s";
        return $"{t.Minutes}m {t.Seconds}s";
    }

    private static double? GetCpuFreqMhz()
    {
        try
        {
            using var searcher = new ManagementObjectSearcher("SELECT CurrentClockSpeed FROM Win32_Processor");
            foreach (ManagementObject obj in searcher.Get())
                return Convert.ToDouble(obj["CurrentClockSpeed"]);
        }
        catch { /* ignore */ }
        return null;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FILETIME
    {
        public uint DwLowDateTime;
        public uint DwHighDateTime;
        public ulong ToUInt64() => ((ulong)DwHighDateTime << 32) | DwLowDateTime;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetSystemTimes(out FILETIME idle, out FILETIME kernel, out FILETIME user);

    [StructLayout(LayoutKind.Sequential)]
    private struct MEMORYSTATUSEX
    {
        public uint dwLength;
        public uint dwMemoryLoad;
        public ulong ullTotalPhys;
        public ulong ullAvailPhys;
        public ulong ullTotalPageFile;
        public ulong ullAvailPageFile;
        public ulong ullTotalVirtual;
        public ulong ullAvailVirtual;
        public ulong ullAvailExtendedVirtual;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GlobalMemoryStatusEx(ref MEMORYSTATUSEX lpBuffer);

    private static (double availMb, double totalMb) GetMemoryStatus()
    {
        var st = new MEMORYSTATUSEX { dwLength = (uint)Marshal.SizeOf<MEMORYSTATUSEX>() };
        if (!GlobalMemoryStatusEx(ref st)) return (0, 0);
        return (st.ullAvailPhys / (1024.0 * 1024.0), st.ullTotalPhys / (1024.0 * 1024.0));
    }
}
