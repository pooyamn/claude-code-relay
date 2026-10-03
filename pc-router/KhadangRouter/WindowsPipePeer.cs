using System.ComponentModel;
using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace KhadangRouter;

// Candidate protected component boundary, NOT company/agent role identity.
// Both endpoints are exact SYSTEM/session-0 processes. Ordinary owner agents
// cannot connect or impersonate either endpoint. Pins must come from the
// protected launcher/lease, never from a peer message or a directory name.
// No production caller selects this transport yet; no model is launched here.
public sealed record WindowsPipePin(uint Pid, long CreationTime, string Image, string Sha256)
{
    public void Validate()
    {
        RouterPolicy.WindowsPath(Image);
        if (Pid == 0 || CreationTime <= 0 || Sha256.Length != 64 || !Sha256.All(Uri.IsHexDigit))
            throw new InvalidDataException("Exact protected process generation and executable pin required");
    }
}

public sealed class WindowsPipePeer : IDisposable
{
    private readonly SafeProcessHandle process;
    private readonly FileStream image;
    private readonly SafePipeHandle pipe;
    private readonly bool serverPeer;
    public WindowsPipePin Pin { get; }
    private WindowsPipePeer(SafeProcessHandle process, FileStream image, SafePipeHandle pipe,
        bool serverPeer, WindowsPipePin pin)
    { this.process = process; this.image = image; this.pipe = pipe; this.serverPeer = serverPeer; Pin = pin; }

    public static WindowsPipePin Capture(uint pid, string executable, string sha256)
    {
        RequireSystem();
        using var process = Open(pid);
        VerifyToken(process);
        if (!ImagePath(process).Equals(executable, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Launcher process image changed");
        var pin = new WindowsPipePin(pid, Creation(process), executable, sha256); pin.Validate();
        return pin;
    }

    public static WindowsPipePeer Authenticate(PipeStream stream, bool serverPeer, WindowsPipePin expected,
        string protectedArtifactRoot)
    {
        RequireSystem(); expected.Validate();
        if (!stream.IsConnected) throw new InvalidDataException("Connected local protected pipe required");
        var pipe = stream.SafePipeHandle;
        var pid = PeerPid(pipe, serverPeer);
        if (pid != expected.Pid) throw new InvalidDataException("Kernel pipe peer does not match launcher lease");
        var process = Open(pid); FileStream? image = null;
        try
        {
            VerifyToken(process);
            if (Creation(process) != expected.CreationTime || !ImagePath(process).Equals(expected.Image, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Pipe peer process generation/image changed");
            ProtectedImage(expected.Image, protectedArtifactRoot);
            // Keep the executable locked and the kernel process handle alive.
            // A PID reused later cannot turn this grant into a different process.
            image = new FileStream(expected.Image, FileMode.Open, FileAccess.Read, FileShare.Read);
            if (!Convert.ToHexString(SHA256.HashData(image)).Equals(expected.Sha256, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Pipe peer executable bytes changed");
            var peer = new WindowsPipePeer(process, image, pipe, serverPeer, expected);
            peer.Current(); return peer;
        }
        catch { image?.Dispose(); process.Dispose(); throw; }
    }

    public static async Task<(NamedPipeClientStream Stream, WindowsPipePeer Peer)> Connect(string run,
        WindowsPipePin expectedServer, string protectedArtifactRoot, CancellationToken stop)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        RequireSystem(); expectedServer.Validate();
        // Identification SQOS: even a squatting server must NOT be able to
        // impersonate this SYSTEM caller before server authentication finishes.
        var stream = new NamedPipeClientStream(".", WindowsProtectedPipe.Name(run), PipeDirection.InOut,
            PipeOptions.Asynchronous, TokenImpersonationLevel.Identification);
        try
        {
            await stream.ConnectAsync(stop);
            return (stream, Authenticate(stream, true, expectedServer, protectedArtifactRoot));
        }
        catch { stream.Dispose(); throw; }
    }

    public void Current()
    {
        if (process.IsClosed || pipe.IsClosed || WaitForSingleObject(process, 0) != 0x102 ||
            PeerPid(pipe, serverPeer) != Pin.Pid || Creation(process) != Pin.CreationTime)
            throw new InvalidDataException("Protected pipe peer is no longer the leased live process");
        VerifyToken(process);
    }
    public void Dispose() { image.Dispose(); process.Dispose(); }

    public static void RequireSystem()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Windows kernel pipe identity required");
        using var identity = WindowsIdentity.GetCurrent();
        if (!identity.IsSystem || Process.GetCurrentProcess().SessionId != 0)
            throw new InvalidDataException("Exact SYSTEM/session-0 component required, never an owner agent or SSH administrator");
    }
    private static uint PeerPid(SafePipeHandle handle, bool serverPeer)
    {
        uint pid;
        var success = serverPeer ? GetNamedPipeServerProcessId(handle, out pid) : GetNamedPipeClientProcessId(handle, out pid);
        if (!success) throw Native();
        return pid;
    }
    private static SafeProcessHandle Open(uint pid)
    {
        var handle = OpenProcess(0x00101000, false, pid); // query-limited + synchronize; no injection/termination rights
        if (handle.IsInvalid) { handle.Dispose(); throw Native(); }
        return handle;
    }
    private static long Creation(SafeProcessHandle process)
    {
        if (!GetProcessTimes(process, out var created, out _, out _, out _)) throw Native();
        return created;
    }
    private static string ImagePath(SafeProcessHandle process)
    {
        var text = new StringBuilder(32768); uint size = 32768;
        if (!QueryFullProcessImageName(process, 0, text, ref size)) throw Native();
        return text.ToString();
    }
    private static void VerifyToken(SafeProcessHandle process)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        if (!OpenProcessToken(process, 0x8, out var token)) throw Native();
        try
        {
            using var identity = new WindowsIdentity(token);
            if (!identity.IsSystem || identity.User?.Value != "S-1-5-18" ||
                !GetTokenInformation(token, 12, out var session, 4, out _) || session != 0 ||
                !GetTokenInformation(token, 20, out var elevated, 4, out _) || elevated == 0)
                throw new InvalidDataException("Pipe peer is not the protected SYSTEM/session-0 component");
        }
        finally { CloseHandle(token); }
    }
    private static void ProtectedImage(string path, string root) => ProtectedPath(path, root, directory: false);
    internal static void ProtectedPath(string path, string root, bool directory)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        path = RouterPolicy.WindowsPath(path); root = RouterPolicy.WindowsPath(root);
        if (!path.StartsWith(root + "\\", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Peer image is outside the reviewed protected artifact root");
        for (FileSystemInfo? item = directory ? new DirectoryInfo(path) : new FileInfo(path); item != null; item = item is FileInfo file ? file.Directory : ((DirectoryInfo)item).Parent)
        {
            if (!item.Exists || (item.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("Literal protected peer artifact required");
            var acl = item is FileInfo f ? (FileSystemSecurity)f.GetAccessControl() : ((DirectoryInfo)item).GetAccessControl();
            var owner = acl.GetOwner(typeof(SecurityIdentifier))?.Value;
            if (owner is not ("S-1-5-18" or "S-1-5-32-544")) throw new InvalidDataException("Trusted artifact owner required");
            const FileSystemRights mutation = FileSystemRights.Write | FileSystemRights.Delete | FileSystemRights.DeleteSubdirectoriesAndFiles |
                FileSystemRights.ChangePermissions | FileSystemRights.TakeOwnership;
            foreach (FileSystemAccessRule rule in acl.GetAccessRules(true, true, typeof(SecurityIdentifier)))
                if (rule.AccessControlType == AccessControlType.Allow && (rule.FileSystemRights & mutation) != 0 &&
                    rule.IdentityReference.Value is not ("S-1-5-18" or "S-1-5-32-544"))
                    throw new InvalidDataException("Ordinary accounts must not mutate peer artifacts");
            if (item.FullName.TrimEnd('\\').Equals(root, StringComparison.OrdinalIgnoreCase))
            { if (!acl.AreAccessRulesProtected) throw new InvalidDataException("Protected artifact root DACL required"); break; }
        }
        // Ancestors above the protected root must not redirect the literal path.
        for (var ancestor = new DirectoryInfo(root).Parent; ancestor != null; ancestor = ancestor.Parent)
            if ((ancestor.Attributes & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Artifact ancestor reparse point refused");
    }
    private static Win32Exception Native() => new(Marshal.GetLastWin32Error(), "Kernel pipe identity check failed");
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool GetNamedPipeServerProcessId(SafePipeHandle pipe, out uint pid);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool GetNamedPipeClientProcessId(SafePipeHandle pipe, out uint pid);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern SafeProcessHandle OpenProcess(uint access, bool inherit, uint pid);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern uint WaitForSingleObject(SafeProcessHandle process, uint milliseconds);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool GetProcessTimes(SafeProcessHandle process, out long created, out long exited, out long kernel, out long user);
    [DllImport("kernel32.dll", EntryPoint = "QueryFullProcessImageNameW", CharSet = CharSet.Unicode, SetLastError = true)] private static extern bool QueryFullProcessImageName(SafeProcessHandle process, uint flags, StringBuilder path, ref uint size);
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool OpenProcessToken(SafeProcessHandle process, uint access, out IntPtr token);
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool GetTokenInformation(IntPtr token, int type, out int value, uint size, out uint required);
    [DllImport("kernel32.dll")] private static extern bool CloseHandle(IntPtr handle);
}

// Holds the FIRST instance for its whole lifetime. Disconnecting a client does
// not close the listener or grant another process the pipe name. A service/broker
// using it must independently own native stdio; this class does not do that yet.
public sealed class WindowsProtectedPipe : IDisposable
{
    public NamedPipeServerStream Stream { get; }
    public static string Name(string run)
    {
        if (!Guid.TryParseExact(run, "N", out _)) throw new InvalidDataException("Exact protected endpoint generation required");
        return "Oracova-NativeBroker-" + run;
    }
    public WindowsProtectedPipe(string run)
    {
        WindowsPipePeer.RequireSystem();
        if (!ConvertStringSecurityDescriptorToSecurityDescriptor("O:SYG:SYD:P(A;;GA;;;SY)(A;;GA;;;BA)", 1, out var descriptor, out _)) throw Native();
        try
        {
            var attributes = new SecurityAttributes { Size = Marshal.SizeOf<SecurityAttributes>(), Descriptor = descriptor };
            // Duplex, overlapped, FIRST instance; byte stream, blocking,
            // REJECT_REMOTE_CLIENTS. Only SYSTEM/admin can access either end.
            var handle = CreateNamedPipe(@"\\.\pipe\" + Name(run), 0x40080003, 0x8, 1, 8192, 8192, 0, ref attributes);
            if (handle.IsInvalid) { handle.Dispose(); throw Native(); }
            try { Stream = new NamedPipeServerStream(PipeDirection.InOut, true, false, handle); }
            catch { handle.Dispose(); throw; }
        }
        finally { LocalFree(descriptor); }
    }
    public void Dispose() => Stream.Dispose();
    private static Win32Exception Native() => new(Marshal.GetLastWin32Error(), "Protected local pipe creation failed");
    [StructLayout(LayoutKind.Sequential)] private struct SecurityAttributes { public int Size; public IntPtr Descriptor; public int Inherit; }
    [DllImport("advapi32.dll", EntryPoint = "ConvertStringSecurityDescriptorToSecurityDescriptorW", CharSet = CharSet.Unicode, SetLastError = true)] private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptor(string text, uint version, out IntPtr descriptor, out uint size);
    [DllImport("kernel32.dll", EntryPoint = "CreateNamedPipeW", CharSet = CharSet.Unicode, SetLastError = true)] private static extern SafePipeHandle CreateNamedPipe(string name, uint openMode, uint pipeMode, uint instances, uint outBuffer, uint inBuffer, uint timeout, ref SecurityAttributes attributes);
    [DllImport("kernel32.dll")] private static extern IntPtr LocalFree(IntPtr value);
}
