using System;
using System.Diagnostics;
using System.Runtime.InteropServices;

[ComImport, Guid("00000016-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface ISALifecycleFilter {
    [PreserveSig] int HandleInComingCall(int type, IntPtr task, int ticks, IntPtr info);
    [PreserveSig] int RetryRejectedCall(IntPtr task, int ticks, int rejectType);
    [PreserveSig] int MessagePending(IntPtr task, int ticks, int pendingType);
}
public class SALifecycleFilter : ISALifecycleFilter {
    static ISALifecycleFilter previous;
    static Stopwatch clock;
    static double budget;
    [DllImport("ole32.dll")] static extern int CoRegisterMessageFilter(ISALifecycleFilter current, out ISALifecycleFilter old);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
    public static void Register(double seconds) {
        clock=Stopwatch.StartNew(); budget=seconds;
        CoRegisterMessageFilter(new SALifecycleFilter(), out previous);
    }
    public static void Revoke() { ISALifecycleFilter ignored; CoRegisterMessageFilter(previous, out ignored); }
    public static uint ProcessId(long hwnd) { uint pid; GetWindowThreadProcessId(new IntPtr(hwnd), out pid); return pid; }
    public int HandleInComingCall(int type, IntPtr task, int ticks, IntPtr info) { return 0; }
    public int RetryRejectedCall(IntPtr task, int ticks, int rejectType) {
        return clock.Elapsed.TotalSeconds<budget && ticks<1000 && (rejectType==1 || rejectType==2) ? 100 : -1;
    }
    public int MessagePending(IntPtr task, int ticks, int pendingType) { return 2; }
}
