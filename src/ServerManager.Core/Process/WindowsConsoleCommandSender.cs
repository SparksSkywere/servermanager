using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Extensions.Logging;

namespace ServerManager.Core.Process;

/// <summary>
/// Sends console input to an already-running process when we no longer hold Process.StandardInput
/// (HostRuntime restart / reattach). Dashboard never owns this — only HostRuntime.
/// </summary>
public sealed class WindowsConsoleCommandSender
{
    private readonly ILogger<WindowsConsoleCommandSender> _logger;
    private readonly object _lock = new();

    public WindowsConsoleCommandSender(ILogger<WindowsConsoleCommandSender> logger) => _logger = logger;

    public bool TrySend(int pid, string command)
    {
        if (!OperatingSystem.IsWindows()) return false;
        if (string.IsNullOrEmpty(command)) return false;

        lock (_lock)
        {
            try
            {
                // Detach from any console we might already own
                FreeConsole();

                if (!AttachConsole((uint)pid))
                {
                    var err = Marshal.GetLastWin32Error();
                    _logger.LogDebug("AttachConsole({Pid}) failed Win32={Err}", pid, err);
                    return false;
                }

                try
                {
                    var handle = GetStdHandle(STD_INPUT_HANDLE);
                    if (handle == IntPtr.Zero || handle == new IntPtr(-1))
                        return false;

                    var payload = command.EndsWith("\n", StringComparison.Ordinal) ? command : command + "\n";
                    var records = new INPUT_RECORD[payload.Length];
                    for (var i = 0; i < payload.Length; i++)
                    {
                        records[i] = new INPUT_RECORD
                        {
                            EventType = KEY_EVENT,
                            KeyEvent = new KEY_EVENT_RECORD
                            {
                                bKeyDown = true,
                                wRepeatCount = 1,
                                wVirtualKeyCode = 0,
                                wVirtualScanCode = 0,
                                UnicodeChar = payload[i],
                                dwControlKeyState = 0
                            }
                        };
                    }

                    if (!WriteConsoleInput(handle, records, (uint)records.Length, out var written) || written == 0)
                    {
                        _logger.LogDebug("WriteConsoleInput failed for PID {Pid}", pid);
                        return false;
                    }

                    _logger.LogDebug("Sent command via AttachConsole to PID {Pid}", pid);
                    return true;
                }
                finally
                {
                    // Re-hide in case AttachConsole made the console flash visible
                    try
                    {
                        var hwnd = GetConsoleWindow();
                        if (hwnd != IntPtr.Zero) ShowWindow(hwnd, 0 /* SW_HIDE */);
                    }
                    catch { /* ignore */ }
                    FreeConsole();
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "AttachConsole command send failed for PID {Pid}", pid);
                try { FreeConsole(); } catch { /* ignore */ }
                return false;
            }
        }
    }

    private const int STD_INPUT_HANDLE = -10;
    private const ushort KEY_EVENT = 0x0001;

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AttachConsole(uint dwProcessId);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool FreeConsole();

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr GetStdHandle(int nStdHandle);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool WriteConsoleInput(IntPtr hConsoleInput, INPUT_RECORD[] lpBuffer, uint nLength, out uint lpNumberOfEventsWritten);

    [DllImport("kernel32.dll")]
    private static extern IntPtr GetConsoleWindow();

    [DllImport("user32.dll")]
    private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [StructLayout(LayoutKind.Explicit)]
    private struct INPUT_RECORD
    {
        [FieldOffset(0)] public ushort EventType;
        [FieldOffset(4)] public KEY_EVENT_RECORD KeyEvent;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct KEY_EVENT_RECORD
    {
        public bool bKeyDown;
        public ushort wRepeatCount;
        public ushort wVirtualKeyCode;
        public ushort wVirtualScanCode;
        public char UnicodeChar;
        public uint dwControlKeyState;
    }
}
