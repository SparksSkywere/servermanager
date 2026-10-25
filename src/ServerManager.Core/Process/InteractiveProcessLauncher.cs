using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Extensions.Logging;

namespace ServerManager.Core.Process;

/// <summary>
/// Starts a process in the active interactive user session. Windows services run in Session 0
/// and cannot give Project Zomboid (etc.) a usable console — the game QueuedQuit()s immediately.
/// </summary>
public static class InteractiveProcessLauncher
{
    public static bool IsRunningInSession0()
    {
        try
        {
            return System.Diagnostics.Process.GetCurrentProcess().SessionId == 0;
        }
        catch
        {
            return !Environment.UserInteractive;
        }
    }

    public static int? StartInActiveSession(
        string fileName,
        string arguments,
        string workingDirectory,
        ILogger? logger = null)
    {
        if (!OperatingSystem.IsWindows())
            return null;

        var sessionId = WTSGetActiveConsoleSessionId();
        if (sessionId == 0xFFFFFFFF)
        {
            logger?.LogWarning("No active console session to launch {File}", fileName);
            return null;
        }

        if (!WTSQueryUserToken(sessionId, out var userToken))
        {
            logger?.LogWarning("WTSQueryUserToken failed for session {Session} (win32={Err})",
                sessionId, Marshal.GetLastWin32Error());
            return null;
        }

        IntPtr env = IntPtr.Zero;
        IntPtr dupToken = IntPtr.Zero;
        try
        {
            if (!DuplicateTokenEx(userToken, MaximumAllowed, IntPtr.Zero, SecurityImpersonation,
                    TokenPrimary, out dupToken))
            {
                logger?.LogWarning("DuplicateTokenEx failed (win32={Err})", Marshal.GetLastWin32Error());
                return null;
            }

            CreateEnvironmentBlock(out env, dupToken, false);

            var cmdLine = new StringBuilder();
            cmdLine.Append('"').Append(fileName).Append('"');
            if (!string.IsNullOrWhiteSpace(arguments))
                cmdLine.Append(' ').Append(arguments);

            var si = new StartupInfo
            {
                cb = Marshal.SizeOf<StartupInfo>(),
                dwFlags = StartfUseShowWindow,
                wShowWindow = SwShowMinNoActive
            };
            var pi = new ProcessInformation();

            var flags = CreateUnicodeEnvironment | CreateNewConsole;
            if (!CreateProcessAsUser(
                    dupToken,
                    null,
                    cmdLine,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    false,
                    flags,
                    env,
                    workingDirectory,
                    ref si,
                    out pi))
            {
                logger?.LogWarning("CreateProcessAsUser failed for {File} (win32={Err})",
                    fileName, Marshal.GetLastWin32Error());
                return null;
            }

            CloseHandle(pi.hThread);
            CloseHandle(pi.hProcess);
            logger?.LogInformation("Started {File} in session {Session} as PID {Pid}",
                fileName, sessionId, pi.dwProcessId);
            return unchecked((int)pi.dwProcessId);
        }
        finally
        {
            if (env != IntPtr.Zero) DestroyEnvironmentBlock(env);
            if (dupToken != IntPtr.Zero) CloseHandle(dupToken);
            CloseHandle(userToken);
        }
    }

    private const uint MaximumAllowed = 0x02000000;
    private const int SecurityImpersonation = 2;
    private const int TokenPrimary = 1;
    private const uint CreateUnicodeEnvironment = 0x00000400;
    private const uint CreateNewConsole = 0x00000010;
    private const int StartfUseShowWindow = 0x00000001;
    private const short SwShowMinNoActive = 7;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct StartupInfo
    {
        public int cb;
        public string? lpReserved;
        public string? lpDesktop;
        public string? lpTitle;
        public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute;
        public int dwFlags;
        public short wShowWindow;
        public short cbReserved2;
        public IntPtr lpReserved2;
        public IntPtr hStdInput, hStdOutput, hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct ProcessInformation
    {
        public IntPtr hProcess;
        public IntPtr hThread;
        public uint dwProcessId;
        public uint dwThreadId;
    }

    [DllImport("kernel32.dll")]
    private static extern uint WTSGetActiveConsoleSessionId();

    [DllImport("wtsapi32.dll", SetLastError = true)]
    private static extern bool WTSQueryUserToken(uint sessionId, out IntPtr phToken);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool DuplicateTokenEx(
        IntPtr hExistingToken, uint dwDesiredAccess, IntPtr lpTokenAttributes,
        int impersonationLevel, int tokenType, out IntPtr phNewToken);

    [DllImport("userenv.dll", SetLastError = true)]
    private static extern bool CreateEnvironmentBlock(out IntPtr lpEnvironment, IntPtr hToken, bool bInherit);

    [DllImport("userenv.dll", SetLastError = true)]
    private static extern bool DestroyEnvironmentBlock(IntPtr lpEnvironment);

    [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool CreateProcessAsUser(
        IntPtr hToken,
        string? lpApplicationName,
        StringBuilder lpCommandLine,
        IntPtr lpProcessAttributes,
        IntPtr lpThreadAttributes,
        bool bInheritHandles,
        uint dwCreationFlags,
        IntPtr lpEnvironment,
        string lpCurrentDirectory,
        ref StartupInfo lpStartupInfo,
        out ProcessInformation lpProcessInformation);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr hObject);
}
