// Small native service host for the reviewed Python MTProto server only.
// Child death terminates this service process, so SCM observes failure even
// under LocalService. No SCM database access, privileges or restart loop.
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.ServiceProcess;
using System.Text;

sealed class MtprotoService : ServiceBase
{
    readonly string release = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
    readonly string python = @"C:\ProgramData\OracovaVPN-20261003-FA9g4b\python\python.exe";
    Process child;
    IntPtr job;
    volatile bool stopping;
    readonly object logGate = new object();

    MtprotoService(string name) { ServiceName = name; CanStop = true; AutoLog = false; }
    static int Main(string[] args)
    {
        if (args.Length != 1 || (args[0] != "OracovaMTProto" && args[0] != "OracovaMTProto8443")) return 2;
        using (var identity = WindowsIdentity.GetCurrent())
            if (identity.User == null || identity.User.Value != "S-1-5-19") return 3;
        ServiceBase.Run(new MtprotoService(args[0]));
        return 0;
    }
    protected override void OnStart(string[] args)
    {
        job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero) throw new InvalidOperationException("Child job creation failed");
        var limits = new JobLimits();
        limits.Basic.Flags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if (!SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf(typeof(JobLimits))))
            throw new InvalidOperationException("Child job policy failed");
        var info = new ProcessStartInfo(python, "-I -B -u \"" + Path.Combine(release, "server.py") + "\" " + ServiceName);
        info.WorkingDirectory = release;
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        info.RedirectStandardOutput = true;
        info.RedirectStandardError = true;
        child = new Process { StartInfo = info, EnableRaisingEvents = true };
        child.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { Log("stdout", e.Data); };
        child.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { Log("stderr", e.Data); };
        child.Exited += delegate {
            if (!stopping) {
                Log("host", "Proxy exited; reporting process failure to SCM");
                // Abrupt service-process exit is intentional: SCM applies its
                // configured failure action without WinSW's privileged query.
                Environment.Exit(child.ExitCode == 0 ? 1 : child.ExitCode);
            }
        };
        if (!child.Start()) throw new InvalidOperationException("Proxy start failed");
        if (!AssignProcessToJobObject(job, child.Handle)) {
            child.Kill();
            throw new InvalidOperationException("Proxy containment failed");
        }
        child.BeginOutputReadLine();
        child.BeginErrorReadLine();
        Log("host", "Started child PID " + child.Id);
    }
    protected override void OnStop()
    {
        stopping = true;
        if (job != IntPtr.Zero) { CloseHandle(job); job = IntPtr.Zero; }
        if (child != null) { child.WaitForExit(10000); child.Dispose(); }
        Log("host", "Stopped");
    }
    void Log(string stream, string line)
    {
        if (line == null) return;
        // Upstream's link printer is disabled in the reviewed launcher. Logs
        // are writable only by LocalService/Admins/SYSTEM and remain bounded.
        lock (logGate) {
            var path = Path.Combine(release, "logs", ServiceName + "." + stream + ".log");
            if (File.Exists(path) && new FileInfo(path).Length > 1048576) {
                for (int i = 2; i >= 1; --i) {
                    var next = path + "." + (i + 1);
                    var old = path + "." + i;
                    if (File.Exists(next)) File.Delete(next);
                    if (File.Exists(old)) File.Move(old, next);
                }
                if (File.Exists(path + ".1")) File.Delete(path + ".1");
                File.Move(path, path + ".1");
            }
            File.AppendAllText(path, DateTime.UtcNow.ToString("o") + " " + line + Environment.NewLine, new UTF8Encoding(false));
        }
    }
    [StructLayout(LayoutKind.Sequential)] struct BasicLimits {
        public long ProcessTime, JobTime; public uint Flags; public UIntPtr MinWorkingSet, MaxWorkingSet;
        public uint Active; public UIntPtr Affinity; public uint Priority, Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] struct JobLimits {
        public BasicLimits Basic; public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes;
        public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetInformationJobObject(IntPtr handle, int kind, ref JobLimits limits, uint length);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
}
