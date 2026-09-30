using System;
using System.Runtime.InteropServices;

[ComImport, Guid("00000016-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface ICadMessageFilter {
    [PreserveSig] int HandleInComingCall(int type,IntPtr task,int ticks,IntPtr info);
    [PreserveSig] int RetryRejectedCall(IntPtr task,int ticks,int rejectType);
    [PreserveSig] int MessagePending(IntPtr task,int ticks,int pendingType);
}
public class CadMessageFilter : ICadMessageFilter {
    private static ICadMessageFilter previous;
    [DllImport("ole32.dll")] private static extern int CoRegisterMessageFilter(ICadMessageFilter current,out ICadMessageFilter old);
    public static void Register() { CoRegisterMessageFilter(new CadMessageFilter(),out previous); }
    public static void Revoke() { ICadMessageFilter ignored; CoRegisterMessageFilter(previous,out ignored); }
    public int HandleInComingCall(int type,IntPtr task,int ticks,IntPtr info) { return 0; }
    public int RetryRejectedCall(IntPtr task,int ticks,int rejectType) { return (ticks<30000 && (rejectType==1 || rejectType==2)) ? 200 : -1; }
    public int MessagePending(IntPtr task,int ticks,int pendingType) { return 2; }
}
