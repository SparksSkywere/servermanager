using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Extensions.Logging;

namespace ServerManager.Core.Process;

public sealed class ProcessIdentityService
{
    private readonly ILogger<ProcessIdentityService> _logger;

    public ProcessIdentityService(ILogger<ProcessIdentityService> logger) => _logger = logger;

    public bool IsRunning(int pid)
    {
        // PID 0/4 are idle/system on Windows; never treat as a game server.
        if (pid <= 4) return false;
        try
        {
            var p = System.Diagnostics.Process.GetProcessById(pid);
            return !p.HasExited;
        }
        catch
        {
            return false;
        }
    }

    public DateTime? GetCreateTime(int pid)
    {
        try
        {
            return System.Diagnostics.Process.GetProcessById(pid).StartTime.ToUniversalTime();
        }
        catch
        {
            return null;
        }
    }

    public bool BelongsToServer(int pid, DateTime? expectedCreateTime, string? installDir, string? expectedExe)
    {
        if (pid <= 4) return false;
        try
        {
            var p = System.Diagnostics.Process.GetProcessById(pid);
            if (p.HasExited) return false;

            if (expectedCreateTime.HasValue)
            {
                var delta = (p.StartTime.ToUniversalTime() - expectedCreateTime.Value).Duration();
                if (delta > TimeSpan.FromSeconds(5)) return false;
            }

            if (!string.IsNullOrWhiteSpace(expectedExe))
            {
                try
                {
                    var file = p.MainModule?.FileName;
                    if (file is not null && !file.Contains(expectedExe, StringComparison.OrdinalIgnoreCase)
                        && !Path.GetFileName(file).Equals(expectedExe, StringComparison.OrdinalIgnoreCase))
                    {
                        // allow java children
                        if (!IsJavaProcess(p)) return false;
                    }
                }
                catch (Exception ex)
                {
                    _logger.LogDebug(ex, "Could not read MainModule for PID {Pid}", pid);
                }
            }

            if (!string.IsNullOrWhiteSpace(installDir))
            {
                try
                {
                    var exePath = "";
                    try { exePath = p.MainModule?.FileName ?? ""; } catch { /* ignore */ }

                    var install = Path.GetFullPath(installDir).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                    var matchesInstall =
                        !string.IsNullOrWhiteSpace(exePath)
                        && exePath.StartsWith(install, StringComparison.OrdinalIgnoreCase);

                    // JVM lives under Program Files / Temurin — match via command line (jar + install dir)
                    // or process working directory (NeoForge/Fabric use relative @user_jvm_args.txt).
                    if (!matchesInstall && IsJavaProcess(p))
                    {
                        var cmd = GetCommandLine(p);
                        matchesInstall = !string.IsNullOrWhiteSpace(cmd)
                                         && (cmd.Contains(install, StringComparison.OrdinalIgnoreCase)
                                             || (!string.IsNullOrWhiteSpace(expectedExe)
                                                 && cmd.Contains(expectedExe, StringComparison.OrdinalIgnoreCase)));
                        if (!matchesInstall)
                        {
                            var cwd = GetWorkingDirectory(p);
                            matchesInstall = !string.IsNullOrWhiteSpace(cwd)
                                             && Path.GetFullPath(cwd).TrimEnd('\\', '/')
                                                 .Equals(install, StringComparison.OrdinalIgnoreCase);
                        }
                    }
                    else if (!matchesInstall && string.IsNullOrWhiteSpace(exePath))
                    {
                        var cmd = GetCommandLine(p);
                        matchesInstall = !string.IsNullOrWhiteSpace(cmd)
                                         && cmd.Contains(install, StringComparison.OrdinalIgnoreCase);
                        if (!matchesInstall && cmd is null && !expectedCreateTime.HasValue)
                            return false;
                    }

                    if (!matchesInstall)
                        return false;
                }
                catch { /* best effort */ }
            }

            // Require at least one strong signal when create-time is unknown.
            if (!expectedCreateTime.HasValue
                && string.IsNullOrWhiteSpace(expectedExe)
                && string.IsNullOrWhiteSpace(installDir))
                return false;

            return true;
        }
        catch
        {
            return false;
        }
    }

    public int? FindJavaChild(int launcherPid)
    {
        try
        {
            var children = GetChildProcesses(launcherPid)
                .Where(IsJavaProcess)
                .OrderByDescending(p =>
                {
                    try { return p.WorkingSet64; } catch { return 0L; }
                })
                .FirstOrDefault();
            return children?.Id;
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "FindJavaChild failed for {Pid}", launcherPid);
            return null;
        }
    }

    /// <summary>
    /// Prefer the heaviest non-helper process in the launcher tree (game/JVM),
    /// not cmd/steamcmd wrappers that report a few MB and ~0% CPU.
    /// </summary>
    public int? PromoteToPrimaryProcess(int rootPid, string? installDir = null, string? expectedExe = null)
    {
        if (!IsRunning(rootPid)) return null;
        try
        {
            var scored = new List<(int Pid, long Ws, bool Helper)>();
            foreach (var pid in EnumerateProcessTree(rootPid))
            {
                try
                {
                    var p = System.Diagnostics.Process.GetProcessById(pid);
                    if (p.HasExited) continue;
                    scored.Add((pid, SafeWorkingSet(p), IsHelperProcess(p)));
                }
                catch { /* access denied */ }
            }

            if (scored.Count == 0) return rootPid;

            var gameLike = scored.Where(s => !s.Helper).ToList();
            var pool = gameLike.Count > 0 ? gameLike : scored;
            var best = pool.OrderByDescending(s => s.Ws).First();

            // Only fall back to an install-dir scan when the tree primary is a helper or tiny.
            if ((best.Helper || best.Ws < 48L * 1024 * 1024) && !string.IsNullOrWhiteSpace(installDir))
            {
                var scanned = FindBestMatchingProcess(installDir, expectedExe);
                if (scanned is int alt && alt != best.Pid)
                {
                    try
                    {
                        var altWs = SafeWorkingSet(System.Diagnostics.Process.GetProcessById(alt));
                        if (altWs > best.Ws * 2)
                            return alt;
                    }
                    catch { /* ignore */ }
                }
            }

            return best.Pid;
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "PromoteToPrimaryProcess failed for {Pid}", rootPid);
            return rootPid;
        }
    }

    /// <summary>
    /// Find the heaviest java/javaw process whose command line references this install or jar.
    /// Only scans Java processes (cheap) — needed because JVM binaries live outside the server folder.
    /// </summary>
    public int? FindJavaForServer(string? installDir, string? jarOrExe)
    {
        if (string.IsNullOrWhiteSpace(installDir) && string.IsNullOrWhiteSpace(jarOrExe))
            return null;
        try
        {
            var install = string.IsNullOrWhiteSpace(installDir)
                ? ""
                : Path.GetFullPath(installDir).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            var jar = string.IsNullOrWhiteSpace(jarOrExe) ? "" : Path.GetFileName(jarOrExe);
            var scored = new List<(int Pid, long Ws)>();

            foreach (var name in new[] { "java", "javaw" })
            {
                foreach (var p in System.Diagnostics.Process.GetProcessesByName(name))
                {
                    try
                    {
                        if (p.HasExited) continue;
                        var cmd = GetCommandLine(p) ?? "";
                        var cwd = GetWorkingDirectory(p) ?? "";
                        var jarName = string.IsNullOrEmpty(jar) ? "" : jar;
                        // Ignore .bat/.cmd "executables" — they never appear on the JVM command line.
                        if (jarName.EndsWith(".bat", StringComparison.OrdinalIgnoreCase)
                            || jarName.EndsWith(".cmd", StringComparison.OrdinalIgnoreCase))
                            jarName = "";

                        var ok = (!string.IsNullOrEmpty(install) && cmd.Contains(install, StringComparison.OrdinalIgnoreCase))
                                 || (!string.IsNullOrEmpty(jarName) && cmd.Contains(jarName, StringComparison.OrdinalIgnoreCase))
                                 || (!string.IsNullOrEmpty(install) && !string.IsNullOrEmpty(cwd)
                                     && Path.GetFullPath(cwd).TrimEnd('\\', '/')
                                         .Equals(install, StringComparison.OrdinalIgnoreCase));
                        if (!ok) continue;
                        scored.Add((p.Id, SafeWorkingSet(p)));
                    }
                    catch { /* access */ }
                }
            }

            return scored.Count == 0 ? null : scored.OrderByDescending(s => s.Ws).First().Pid;
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "FindJavaForServer failed for {Dir}", installDir);
            return null;
        }
    }

    /// <summary>Pick the largest WorkingSet process that belongs to this server install.</summary>
    public int? FindBestMatchingProcess(string? installDir, string? expectedExe)
    {
        if (string.IsNullOrWhiteSpace(installDir)) return null;
        try
        {
            // Minecraft / jar servers: resolve via JVM command lines first
            if (!string.IsNullOrWhiteSpace(expectedExe)
                && expectedExe.EndsWith(".jar", StringComparison.OrdinalIgnoreCase))
            {
                var jvm = FindJavaForServer(installDir, expectedExe);
                if (jvm is int j) return j;
            }

            var install = Path.GetFullPath(installDir).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            var scored = new List<(int Pid, long Ws, bool Helper)>();
            foreach (var p in System.Diagnostics.Process.GetProcesses())
            {
                try
                {
                    if (p.HasExited) continue;
                    string? exePath = null;
                    try { exePath = p.MainModule?.FileName; } catch { /* access denied */ }

                    var matches = !string.IsNullOrWhiteSpace(exePath)
                                  && exePath.StartsWith(install, StringComparison.OrdinalIgnoreCase);
                    if (!matches && !string.IsNullOrWhiteSpace(expectedExe) && !string.IsNullOrWhiteSpace(exePath))
                    {
                        matches = Path.GetFileName(exePath).Equals(expectedExe, StringComparison.OrdinalIgnoreCase)
                                  || exePath.Contains(expectedExe, StringComparison.OrdinalIgnoreCase);
                    }
                    if (!matches && !string.IsNullOrWhiteSpace(expectedExe))
                    {
                        var want = Path.GetFileNameWithoutExtension(expectedExe);
                        if (!string.IsNullOrWhiteSpace(want)
                            && p.ProcessName.Equals(want, StringComparison.OrdinalIgnoreCase))
                            matches = true;
                    }
                    // Never fall back to per-process WMI here — that freezes ListServers on busy hosts.
                    if (!matches) continue;

                    scored.Add((p.Id, SafeWorkingSet(p), IsHelperProcess(p)));
                }
                catch { /* access denied */ }
            }

            if (scored.Count == 0)
            {
                // Last resort for modpacks that launch java without a .jar Executable field
                return FindJavaForServer(installDir, expectedExe);
            }
            var gameLike = scored.Where(s => !s.Helper).ToList();
            var pool = gameLike.Count > 0 ? gameLike : scored;
            return pool.OrderByDescending(s => s.Ws).First().Pid;
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "FindBestMatchingProcess failed for {Dir}", installDir);
            return null;
        }
    }

    public static bool IsHelperProcess(System.Diagnostics.Process p)
    {
        try
        {
            return IsHelperProcessName(p.ProcessName);
        }
        catch
        {
            return false;
        }
    }

    public static bool IsHelperProcessName(string? name)
    {
        if (string.IsNullOrWhiteSpace(name)) return false;
        return name.Equals("cmd", StringComparison.OrdinalIgnoreCase)
               || name.Equals("powershell", StringComparison.OrdinalIgnoreCase)
               || name.Equals("pwsh", StringComparison.OrdinalIgnoreCase)
               || name.Equals("conhost", StringComparison.OrdinalIgnoreCase)
               || name.Equals("steamcmd", StringComparison.OrdinalIgnoreCase)
               || name.Equals("steam", StringComparison.OrdinalIgnoreCase)
               || name.Equals("steamerrorreporter", StringComparison.OrdinalIgnoreCase)
               || name.Equals("WerFault", StringComparison.OrdinalIgnoreCase)
               || name.Equals("crashpad_handler", StringComparison.OrdinalIgnoreCase);
    }

    private static long SafeWorkingSet(System.Diagnostics.Process p)
    {
        try { return p.WorkingSet64; } catch { return 0L; }
    }

    /// <summary>All PIDs in the process tree rooted at <paramref name="rootPid"/> (including root).</summary>
    public IEnumerable<int> EnumerateDescendantPids(int rootPid)
        => EnumerateProcessTree(rootPid);

    private IEnumerable<int> EnumerateProcessTree(int rootPid)
    {
        var seen = new HashSet<int>();
        var queue = new Queue<int>();
        queue.Enqueue(rootPid);
        while (queue.Count > 0)
        {
            var pid = queue.Dequeue();
            if (!seen.Add(pid)) continue;
            yield return pid;
            foreach (var child in GetChildProcesses(pid))
            {
                try { queue.Enqueue(child.Id); } catch { /* ignore */ }
            }
        }
    }

    public static bool IsJavaProcess(System.Diagnostics.Process p)
    {
        try
        {
            var name = p.ProcessName;
            return name.Equals("java", StringComparison.OrdinalIgnoreCase)
                   || name.Equals("javaw", StringComparison.OrdinalIgnoreCase);
        }
        catch
        {
            return false;
        }
    }

    private static IEnumerable<System.Diagnostics.Process> GetChildProcesses(int parentPid)
    {
        if (!OperatingSystem.IsWindows())
            yield break;

        // One WMI query for children — do NOT scan every process with a per-PID parent lookup.
        List<int> childIds = new();
        try
        {
            using var searcher = new System.Management.ManagementObjectSearcher(
                $"SELECT ProcessId FROM Win32_Process WHERE ParentProcessId = {parentPid}");
            foreach (var obj in searcher.Get())
            {
                try { childIds.Add(Convert.ToInt32(obj["ProcessId"])); }
                catch { /* ignore */ }
            }
        }
        catch
        {
            yield break;
        }

        foreach (var id in childIds)
        {
            System.Diagnostics.Process? child = null;
            try { child = System.Diagnostics.Process.GetProcessById(id); }
            catch { continue; }
            if (child is not null)
                yield return child;
        }
    }

    private static string? GetWorkingDirectory(System.Diagnostics.Process p)
    {
        if (!OperatingSystem.IsWindows()) return null;
        try
        {
            var handle = OpenProcess(ProcessQueryInformation | ProcessVmRead, false, p.Id);
            if (handle == IntPtr.Zero) return null;
            try
            {
                var pbi = new ProcessBasicInformation();
                var status = NtQueryInformationProcess(handle, 0, ref pbi, Marshal.SizeOf<ProcessBasicInformation>(), out _);
                if (status != 0 || pbi.PebBaseAddress == IntPtr.Zero) return null;

                // PEB -> ProcessParameters
                if (!ReadProcessMemory(handle, pbi.PebBaseAddress + (IntPtr.Size == 8 ? 0x20 : 0x10),
                        out var processParams, (UIntPtr)IntPtr.Size, out _))
                    return null;
                if (processParams == IntPtr.Zero) return null;

                // RTL_USER_PROCESS_PARAMETERS.CurrentDirectory.DosPath (UNICODE_STRING)
                var cwdOffset = IntPtr.Size == 8 ? 0x38 : 0x24;
                var uni = new UnicodeString();
                if (!ReadProcessMemoryStruct(handle, processParams + cwdOffset, ref uni, Marshal.SizeOf<UnicodeString>()))
                    return null;
                if (uni.Buffer == IntPtr.Zero || uni.Length == 0) return null;

                var bytes = new byte[uni.Length];
                if (!ReadProcessMemoryBytes(handle, uni.Buffer, bytes, (UIntPtr)bytes.Length, out _))
                    return null;
                return Encoding.Unicode.GetString(bytes).TrimEnd('\\', '/', '\0');
            }
            finally
            {
                CloseHandle(handle);
            }
        }
        catch
        {
            return null;
        }
    }

    private const uint ProcessQueryInformation = 0x0400;
    private const uint ProcessVmRead = 0x0010;

    [StructLayout(LayoutKind.Sequential)]
    private struct ProcessBasicInformation
    {
        public IntPtr Reserved1;
        public IntPtr PebBaseAddress;
        public IntPtr Reserved2_0;
        public IntPtr Reserved2_1;
        public IntPtr UniqueProcessId;
        public IntPtr Reserved3;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct UnicodeString
    {
        public ushort Length;
        public ushort MaximumLength;
        public IntPtr Buffer;
    }

    [DllImport("ntdll.dll")]
    private static extern int NtQueryInformationProcess(
        IntPtr processHandle, int processInformationClass,
        ref ProcessBasicInformation processInformation, int processInformationLength, out int returnLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(uint dwDesiredAccess, bool bInheritHandle, int dwProcessId);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr hObject);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool ReadProcessMemory(
        IntPtr hProcess, IntPtr lpBaseAddress, out IntPtr lpBuffer, UIntPtr nSize, out UIntPtr lpNumberOfBytesRead);

    private static bool ReadProcessMemoryStruct<T>(IntPtr hProcess, IntPtr address, ref T buffer, int size)
        where T : struct
    {
        var ptr = Marshal.AllocHGlobal(size);
        try
        {
            if (!ReadProcessMemoryBytes(hProcess, address, ptr, (UIntPtr)size, out _))
                return false;
            buffer = Marshal.PtrToStructure<T>(ptr)!;
            return true;
        }
        finally
        {
            Marshal.FreeHGlobal(ptr);
        }
    }

    [DllImport("kernel32.dll", EntryPoint = "ReadProcessMemory", SetLastError = true)]
    private static extern bool ReadProcessMemoryBytes(
        IntPtr hProcess, IntPtr lpBaseAddress, byte[] lpBuffer, UIntPtr nSize, out UIntPtr lpNumberOfBytesRead);

    [DllImport("kernel32.dll", EntryPoint = "ReadProcessMemory", SetLastError = true)]
    private static extern bool ReadProcessMemoryBytes(
        IntPtr hProcess, IntPtr lpBaseAddress, IntPtr lpBuffer, UIntPtr nSize, out UIntPtr lpNumberOfBytesRead);

    private static string? GetCommandLine(System.Diagnostics.Process p)
    {
        if (!OperatingSystem.IsWindows()) return null;
        try
        {
            using var searcher = new System.Management.ManagementObjectSearcher(
                $"SELECT CommandLine FROM Win32_Process WHERE ProcessId = {p.Id}");
            foreach (var obj in searcher.Get())
                return obj["CommandLine"]?.ToString();
        }
        catch { /* ignore */ }
        return null;
    }

    private static int? GetParentProcessId(int pid)
    {
        if (!OperatingSystem.IsWindows()) return null;
        try
        {
            using var searcher = new System.Management.ManagementObjectSearcher(
                $"SELECT ParentProcessId FROM Win32_Process WHERE ProcessId = {pid}");
            foreach (var obj in searcher.Get())
                return Convert.ToInt32(obj["ParentProcessId"]);
        }
        catch { /* ignore */ }
        return null;
    }

    public void KillTree(int pid, bool force = true)
    {
        try
        {
            if (OperatingSystem.IsWindows() && force)
            {
                var psi = new ProcessStartInfo
                {
                    FileName = "taskkill",
                    Arguments = $"/F /T /PID {pid}",
                    CreateNoWindow = true,
                    UseShellExecute = false
                };
                System.Diagnostics.Process.Start(psi)?.WaitForExit(15000);
                return;
            }

            var p = System.Diagnostics.Process.GetProcessById(pid);
            p.Kill(entireProcessTree: true);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "KillTree failed for {Pid}", pid);
        }
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GenerateConsoleCtrlEvent(uint dwCtrlEvent, uint dwProcessGroupId);

    public bool SendCtrlC(int pid)
    {
        if (!OperatingSystem.IsWindows()) return false;
        try
        {
            return GenerateConsoleCtrlEvent(0 /* CTRL_C */, (uint)pid);
        }
        catch
        {
            return false;
        }
    }
}
