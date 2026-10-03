using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace KhadangRouter;

// Privileged code launches ONLY the reviewed native executable, as the actual
// signed-in owner's non-elevated token. No agent ever runs as SYSTEM or receives
// the router credential. An unavailable console identity is a hard failure.
public sealed class WindowsOwnerProcess : IDisposable
{
    public StreamReader Output { get; private set; } = null!;
    public StreamReader Error { get; private set; } = null!;
    public StreamWriter Input { get; private set; } = null!;
    public uint Pid { get; private set; }
    private IntPtr process, job;
    private string ownerSid = "";
    private uint ownerSession;

    public OwnerProcessObservation ObserveOwner()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        if (process == IntPtr.Zero || WaitForSingleObject(process, 0) != 0x102 || !OpenProcessToken(process, 8, out var token)) throw Native();
        try
        {
            using var identity = new WindowsIdentity(token);
            if (identity.IsSystem || identity.User?.Value != ownerSid ||
                !GetTokenInformation(token, 20, out var elevated, 4, out _) || elevated != 0 ||
                !GetTokenInformation(token, 12, out var session, 4, out _) || session != ownerSession ||
                !GetProcessTimes(process, out var creation, out _, out _, out _))
                throw new InvalidDataException("Owned native process token/generation mismatch");
            return new(Pid, ownerSid, session, false, creation);
        }
        finally { CloseHandle(token); }
    }

    public static WindowsOwnerProcess Start(RouterPolicy policy, string workspace) => StartCore(policy, workspace, null);
    public static WindowsOwnerProcess StartLinuxCodex(RouterPolicy policy, string windowsWorkspace, IReadOnlyList<string> workspaces)
    {
        policy.Validate();
        var runtime = policy.LinuxCodex ?? throw new InvalidDataException("Protected Linux Codex runtime required");
        // A fixed WSL/Python connector, never caller-selected commands, shells,
        // executables, distro identities or native daemon startup.
        var arguments = runtime.Arguments(workspaces);
        return StartCore(policy, windowsWorkspace, null, runtime, arguments);
    }
    // One-shot acceptance only: an empty child-only credential home. Never copy
    // production credentials, change global defaults or launch a model as SYSTEM.
    public static WindowsOwnerProcess StartDiagnostic(RouterPolicy policy, string workspace, string emptyHome)
    {
        policy.Workspace(emptyHome);
        if (Directory.EnumerateFileSystemEntries(emptyHome).Any()) throw new InvalidDataException("Empty diagnostic native home required");
        return StartCore(policy, workspace, emptyHome);
    }
    private static WindowsOwnerProcess StartCore(RouterPolicy policy, string workspace, string? diagnosticHome,
        LinuxCodexRuntime? linux = null, string? linuxArguments = null)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        using var current = WindowsIdentity.GetCurrent();
        if (!current.IsSystem || Process.GetCurrentProcess().SessionId != 0)
            throw new InvalidOperationException("Owner launcher requires the SYSTEM service, not an agent or SSH session");
        policy.Workspace(workspace);
        using var package = linux?.OpenPinnedPackage();
        var image = linux == null ? policy.CodexExecutable : LinuxCodexRuntime.WslExecutable;
        var digest = linux == null ? policy.CodexSha256 : linux.WslSha256;
        if (linux != null)
        {
            if (!Environment.SystemDirectory.Equals(@"C:\Windows\System32", StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Exact PC Windows system image root required");
            for (FileSystemInfo? item = new FileInfo(image); item != null; item = item is FileInfo f ? f.Directory : ((DirectoryInfo)item).Parent)
                if (!item.Exists || (item.Attributes & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidDataException("Literal pinned WSL system image required");
        }
        using var executable = new FileStream(image, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (!Convert.ToHexString(SHA256.HashData(executable)).Equals(digest, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Pinned native launch executable changed");
        if ((File.GetAttributes(image) & FileAttributes.ReparsePoint) != 0)
            throw new InvalidDataException("Native executable cannot be a reparse point");
        EnablePrivileges();
        var result = new WindowsOwnerProcess();
        IntPtr token = IntPtr.Zero, environment = IntPtr.Zero, diagnosticEnvironment = IntPtr.Zero, thread = IntPtr.Zero;
        var handles = new List<IntPtr>();
        try
        {
            var session = WTSGetActiveConsoleSessionId();
            if (session is 0 or uint.MaxValue || !WTSQueryUserToken(session, out token))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "No signed-in physical-console owner");
            using var identity = new WindowsIdentity(token);
            if (identity.User?.Value != policy.OwnerSid || identity.IsSystem)
                throw new InvalidOperationException("Physical console belongs to a different account");
            if (!GetTokenInformation(token, 20, out var elevated, 4, out _) || elevated != 0)
                throw new InvalidOperationException("Native agents require a non-elevated owner token");
            if (linux != null) VerifyCredentialDenied(token, policy.CredentialFile);
            result.ownerSid = policy.OwnerSid; result.ownerSession = session;
            if (!CreateEnvironmentBlock(out environment, token, false)) throw Native();
            if (diagnosticHome != null || linux != null) diagnosticEnvironment = CleanOwnerEnvironment(environment, diagnosticHome);
            var stdin = Pipe(handles, parentWrites: true);
            var stdout = Pipe(handles, parentWrites: false);
            var stderr = Pipe(handles, parentWrites: false);
            result.job = CreateJobObject(IntPtr.Zero, null);
            if (result.job == IntPtr.Zero) throw Native();
            var limits = new JobLimits { Basic = new BasicLimits { Flags = 0x2000 } };
            if (!SetInformationJobObject(result.job, 9, ref limits, (uint)Marshal.SizeOf<JobLimits>())) throw Native();
            var startup = new StartupInfo { Size = Marshal.SizeOf<StartupInfo>(), Desktop = "winsta0\\default",
                Flags = 0x100, Input = stdin.Child, Output = stdout.Child, Error = stderr.Child };
            var command = new StringBuilder(linux != null ? Quote(image) + " " + linuxArguments :
                Quote(image) + " -c windows.sandbox=elevated" +
                (diagnosticHome == null ? "" : " -c cli_auth_credentials_store=\"file\"") + " app-server --listen stdio://");
            // Only our three explicitly inheritable pipe ends are inherited.
            // Router file/socket/token handles are non-inheritable.
            if (!CreateProcessAsUser(token, image, command, IntPtr.Zero, IntPtr.Zero, true,
                0x08000404, diagnosticEnvironment == IntPtr.Zero ? environment : diagnosticEnvironment, workspace, ref startup, out var info)) throw Native();
            result.process = info.Process; thread = info.Thread; result.Pid = info.Pid;
            if (!AssignProcessToJobObject(result.job, result.process)) throw Native();
            if (ResumeThread(thread) == uint.MaxValue) throw Native();
            result.Input = new StreamWriter(new FileStream(new SafeFileHandle(stdin.Parent, true), FileAccess.Write), new UTF8Encoding(false)) { AutoFlush = true };
            handles.Remove(stdin.Parent);
            result.Output = new StreamReader(new FileStream(new SafeFileHandle(stdout.Parent, true), FileAccess.Read), new UTF8Encoding(false, true));
            handles.Remove(stdout.Parent);
            result.Error = new StreamReader(new FileStream(new SafeFileHandle(stderr.Parent, true), FileAccess.Read), Encoding.UTF8);
            handles.Remove(stderr.Parent);
            return result;
        }
        catch { result.Dispose(); throw; }
        finally
        {
            foreach (var handle in handles) CloseHandle(handle);
            if (thread != IntPtr.Zero) CloseHandle(thread);
            if (environment != IntPtr.Zero) DestroyEnvironmentBlock(environment);
            if (diagnosticEnvironment != IntPtr.Zero) Marshal.FreeHGlobal(diagnosticEnvironment);
            if (token != IntPtr.Zero) CloseHandle(token);
        }
    }
    private static void VerifyCredentialDenied(IntPtr token, string credential)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        // Actual open/close as the same limited Windows token, NOT SYSTEM and
        // NOT a provider sandbox. Unexpected success never reads any bytes.
        if (!File.Exists(credential)) throw new InvalidDataException("Protected router credential is missing");
        if (!DuplicateTokenEx(token, 0x02000000, IntPtr.Zero, 2, 2, out var probeToken)) throw Native();
        using (probeToken)
        {
            var denied = WindowsIdentity.RunImpersonated(probeToken, () => {
                try { using var opened = File.Open(credential, FileMode.Open, FileAccess.Read, FileShare.ReadWrite); return false; }
                catch (UnauthorizedAccessException) { return true; }
            });
            if (!denied) throw new InvalidDataException("Limited Windows owner can open the protected router credential");
        }
    }
    private static IntPtr CleanOwnerEnvironment(IntPtr block, string? home)
    {
        // Never log or copy the owner's provider/CLI credential environment.
        // This replacement belongs solely to the child. In particular WSLENV,
        // provider keys and router credentials never cross into the connector.
        var values = new SortedDictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (var offset = 0; ;)
        {
            var line = Marshal.PtrToStringUni(IntPtr.Add(block, offset))!;
            if (line.Length == 0) break;
            offset += (line.Length + 1) * 2;
            var separator = line.IndexOf('=', 1);
            if (separator < 1) throw new InvalidDataException("Malformed native owner environment block");
            var key = line[..separator];
            if (!AllowedDiagnosticVariable(key)) continue;
            values[key] = line[(separator + 1)..];
        }
        if (home != null) values["CODEX_HOME"] = home;
        return Marshal.StringToHGlobalUni(string.Join('\0', values.Select(pair => pair.Key + "=" + pair.Value)) + "\0\0");
    }
    internal static bool AllowedDiagnosticVariable(string key) => new[] {
        "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)",
        "COMSPEC", "SYSTEMDRIVE", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "PATHEXT", "USERPROFILE", "USERNAME", "USERDOMAIN",
        "USERDOMAIN_ROAMINGPROFILE", "HOMEDRIVE", "HOMEPATH", "COMPUTERNAME", "OS", "NUMBER_OF_PROCESSORS", "SESSIONNAME"
    }.Contains(key, StringComparer.OrdinalIgnoreCase);
    private static (IntPtr Parent, IntPtr Child) Pipe(List<IntPtr> handles, bool parentWrites)
    {
        var attributes = new SecurityAttributes { Size = Marshal.SizeOf<SecurityAttributes>(), Inherit = 1 };
        if (!CreatePipe(out var read, out var write, ref attributes, 0)) throw Native();
        handles.Add(read); handles.Add(write);
        var parent = parentWrites ? write : read;
        if (!SetHandleInformation(parent, 1, 0)) throw Native();
        return (parent, parentWrites ? read : write);
    }
    private static void EnablePrivileges()
    {
        if (!OpenProcessToken(GetCurrentProcess(), 0x28, out var token)) throw Native();
        try
        {
            foreach (var name in new[] { "SeTcbPrivilege", "SeAssignPrimaryTokenPrivilege", "SeIncreaseQuotaPrivilege" })
            {
                if (!LookupPrivilegeValue(null, name, out var luid)) throw Native();
                var privileges = new TokenPrivileges { Count = 1, Luid = luid, Attributes = 2 };
                if (!AdjustTokenPrivileges(token, false, ref privileges, 0, IntPtr.Zero, IntPtr.Zero) || Marshal.GetLastWin32Error() != 0) throw Native();
            }
        }
        finally { CloseHandle(token); }
    }
    private static string Quote(string path)
    {
        if (path.Any(c => c is '"' or '\r' or '\n') || path.EndsWith('\\')) throw new InvalidDataException("Unsafe process path");
        return '"' + path + '"';
    }
    public void Dispose()
    {
        Input?.Dispose();
        if (process != IntPtr.Zero && WaitForSingleObject(process, 3000) == 0x102) TerminateProcess(process, 1);
        if (job != IntPtr.Zero) { CloseHandle(job); job = IntPtr.Zero; }
        Output?.Dispose(); Error?.Dispose();
        if (process != IntPtr.Zero) { CloseHandle(process); process = IntPtr.Zero; }
    }
    private static Win32Exception Native() => new(Marshal.GetLastWin32Error());
    [StructLayout(LayoutKind.Sequential)] private struct SecurityAttributes { public int Size; public IntPtr Descriptor; public int Inherit; }
    [StructLayout(LayoutKind.Sequential)] private struct Luid { public uint Low; public int High; }
    [StructLayout(LayoutKind.Sequential)] private struct TokenPrivileges { public uint Count; public Luid Luid; public uint Attributes; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] private struct StartupInfo
    {
        public int Size; public string? Reserved, Desktop, Title;
        public uint X, Y, Width, Height, XCount, YCount, Fill, Flags;
        public ushort Show, ReservedSize; public IntPtr ReservedPointer, Input, Output, Error;
    }
    [StructLayout(LayoutKind.Sequential)] private struct ProcessInfo { public IntPtr Process, Thread; public uint Pid, Tid; }
    [StructLayout(LayoutKind.Sequential)] private struct BasicLimits
    { public long ProcessTime, JobTime; public uint Flags; public UIntPtr MinWorkingSet, MaxWorkingSet; public uint Active; public UIntPtr Affinity; public uint Priority, Scheduling; }
    [StructLayout(LayoutKind.Sequential)] private struct JobLimits
    { public BasicLimits Basic; public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes; public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory; }
    [DllImport("kernel32.dll")] private static extern uint WTSGetActiveConsoleSessionId();
    [DllImport("wtsapi32.dll", SetLastError = true)] private static extern bool WTSQueryUserToken(uint session, out IntPtr token);
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool GetTokenInformation(IntPtr token, int information, out int value, uint length, out uint required);
    [DllImport("userenv.dll", SetLastError = true)] private static extern bool CreateEnvironmentBlock(out IntPtr environment, IntPtr token, bool inherit);
    [DllImport("userenv.dll")] private static extern bool DestroyEnvironmentBlock(IntPtr environment);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool CreatePipe(out IntPtr read, out IntPtr write, ref SecurityAttributes attributes, uint size);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool SetHandleInformation(IntPtr handle, uint mask, uint flags);
    [DllImport("advapi32.dll", EntryPoint = "CreateProcessAsUserW", CharSet = CharSet.Unicode, SetLastError = true)] private static extern bool CreateProcessAsUser(IntPtr token, string executable, StringBuilder command, IntPtr processAttributes, IntPtr threadAttributes, bool inherit, uint flags, IntPtr environment, string directory, ref StartupInfo startup, out ProcessInfo process);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern IntPtr CreateJobObject(IntPtr attributes, string? name);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool SetInformationJobObject(IntPtr job, int information, ref JobLimits limits, uint length);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool GetProcessTimes(IntPtr process, out long created, out long exited, out long kernel, out long user);
    [DllImport("kernel32.dll")] private static extern uint WaitForSingleObject(IntPtr handle, uint wait);
    [DllImport("kernel32.dll")] private static extern bool TerminateProcess(IntPtr process, uint code);
    [DllImport("kernel32.dll")] private static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll")] private static extern IntPtr GetCurrentProcess();
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool DuplicateTokenEx(IntPtr existing, uint access,
        IntPtr attributes, int impersonationLevel, int tokenType, out SafeAccessTokenHandle token);
    [DllImport("advapi32.dll", EntryPoint = "LookupPrivilegeValueW", CharSet = CharSet.Unicode, SetLastError = true)] private static extern bool LookupPrivilegeValue(string? system, string name, out Luid luid);
    [DllImport("advapi32.dll", SetLastError = true)] private static extern bool AdjustTokenPrivileges(IntPtr token, bool disableAll, ref TokenPrivileges privileges, uint length, IntPtr previous, IntPtr required);
}

public sealed record OwnerProcessObservation(uint Pid, string Sid, int Session, bool Elevated, long CreationTime);
