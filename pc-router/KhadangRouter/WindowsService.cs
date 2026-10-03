using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;

namespace KhadangRouter;

public static class WindowsService
{
    public const string Name = "KhadangRouter";
    public static void Run(Func<CancellationToken, Task> run)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        using var identity = WindowsIdentity.GetCurrent();
        if (!identity.IsSystem || System.Diagnostics.Process.GetCurrentProcess().SessionId != 0)
            throw new InvalidOperationException("Use the SYSTEM Windows service, never run the router as an agent");
        using var stop = new CancellationTokenSource();
        IntPtr handle = IntPtr.Zero;
        void Status(uint state, uint error = 0)
        {
            var value = new ServiceStatus { Type = 0x10, State = state, Accepted = state == 4 ? 5u : 0,
                Exit = error, WaitHint = state is 2 or 3 ? 30000u : 0 };
            if (!SetServiceStatus(handle, ref value)) throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        Handler control = (code, _, _, _) => { if (code is 1 or 5) stop.Cancel(); return 0; };
        Main callback = (_, _) =>
        {
            handle = RegisterServiceCtrlHandlerEx(Name, control, IntPtr.Zero);
            if (handle == IntPtr.Zero) return;
            try
            {
                Status(2); Status(4);
                run(stop.Token).GetAwaiter().GetResult();
                Status(3); Status(1);
            }
            catch (OperationCanceledException) when (stop.IsCancellationRequested) { Status(3); Status(1); }
            catch { Status(1, 1); } // Never let privileged errors reveal URLs or secrets.
        };
        if (!StartServiceCtrlDispatcher([new ServiceEntry { Name = Name, Callback = callback }, new()]))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        GC.KeepAlive(callback); GC.KeepAlive(control);
    }
    public static string Credential(string path)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        var encrypted = File.ReadAllBytes(path);
        var entropy = Encoding.UTF8.GetBytes("khadang-pc-router-v1");
        var data = new Blob { Size = encrypted.Length, Data = Marshal.AllocHGlobal(encrypted.Length) };
        var salt = new Blob { Size = entropy.Length, Data = Marshal.AllocHGlobal(entropy.Length) };
        try
        {
            Marshal.Copy(encrypted, 0, data.Data, encrypted.Length); Marshal.Copy(entropy, 0, salt.Data, entropy.Length);
            if (!CryptUnprotectData(ref data, IntPtr.Zero, ref salt, IntPtr.Zero, IntPtr.Zero, 1, out var output))
                throw new InvalidDataException("Protected PC credential cannot be decrypted");
            try
            {
                var raw = new byte[output.Size]; Marshal.Copy(output.Data, raw, 0, raw.Length);
                try { return Encoding.UTF8.GetString(raw).Trim(); }
                finally { Array.Clear(raw); }
            }
            finally { LocalFree(output.Data); }
        }
        finally { Marshal.FreeHGlobal(data.Data); Marshal.FreeHGlobal(salt.Data); }
    }
    [StructLayout(LayoutKind.Sequential)] private struct Blob { public int Size; public IntPtr Data; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] private struct ServiceEntry { public string? Name; public Main? Callback; }
    [StructLayout(LayoutKind.Sequential)] private struct ServiceStatus { public uint Type, State, Accepted, Exit, SpecificExit, Checkpoint, WaitHint; }
    private delegate void Main(uint count, IntPtr args);
    private delegate uint Handler(uint control, uint eventType, IntPtr data, IntPtr context);
    [DllImport("advapi32.dll", EntryPoint = "StartServiceCtrlDispatcherW", SetLastError = true)] private static extern bool StartServiceCtrlDispatcher([In] ServiceEntry[] table);
    [DllImport("advapi32.dll", EntryPoint = "RegisterServiceCtrlHandlerExW", CharSet = CharSet.Unicode, SetLastError = true)] private static extern IntPtr RegisterServiceCtrlHandlerEx(string name, Handler handler, IntPtr context);
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool SetServiceStatus(IntPtr handle, ref ServiceStatus status);
    [DllImport("crypt32.dll", SetLastError = true)] private static extern bool CryptUnprotectData(ref Blob input, IntPtr description, ref Blob entropy, IntPtr reserved, IntPtr prompt, uint flags, out Blob output);
    [DllImport("kernel32.dll")] private static extern IntPtr LocalFree(IntPtr memory);
}
