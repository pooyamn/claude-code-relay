using System.Security.AccessControl;
using System.Security.Principal;

namespace KhadangRouter;

// Private candidate broker journal custody, not a role grant or public database
// endpoint. The kernel lease is acquired BEFORE SQLite's constructor recovery
// writes, and retained until native work/reader shutdown has actually settled.
internal sealed class NativeBrokerJournal : IDisposable
{
    private readonly FileStream lease;
    public Ledger Ledger { get; }
    private bool disposed;
    private NativeBrokerJournal(FileStream lease, Ledger ledger) { this.lease = lease; Ledger = ledger; }
    public static NativeBrokerJournal Open(string directory, string protectedRoot)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        WindowsPipePeer.RequireSystem();
        directory = RouterPolicy.WindowsPath(directory);
        WindowsPipePeer.ProtectedPath(directory, protectedRoot, directory: true);
        var info = new DirectoryInfo(directory);
        if (!info.GetAccessControl().AreAccessRulesProtected) throw new InvalidDataException("Private journal root DACL required");
        Private(info);
        foreach (var name in new[] { "broker.lease", "broker.db", "broker.db-wal", "broker.db-shm" })
        {
            var path = Path.Combine(directory, name);
            if (Directory.Exists(path)) throw new InvalidDataException("Journal component must be a literal file");
            if (File.Exists(path)) Private(new FileInfo(path));
        }
        return Acquire(directory);
    }
    internal static NativeBrokerJournal Fixture(string testDirectory) => Acquire(testDirectory);
    private static NativeBrokerJournal Acquire(string directory)
    {
        // OpenOrCreate never truncates/deletes a retained lock. A stale filename
        // does not mean a live holder: only the kernel's held handle decides.
        var lease = new FileStream(Path.Combine(directory, "broker.lease"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
        try { return new(lease, new Ledger(Path.Combine(directory, "broker.db"))); }
        catch { lease.Dispose(); throw; }
    }
    private static void Private(FileSystemInfo item)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        if ((item.Attributes & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Journal reparse refused");
        var acl = item is FileInfo f ? (FileSystemSecurity)f.GetAccessControl() : ((DirectoryInfo)item).GetAccessControl();
        if (acl.GetOwner(typeof(SecurityIdentifier))?.Value is not ("S-1-5-18" or "S-1-5-32-544"))
            throw new InvalidDataException("Trusted journal owner required");
        foreach (FileSystemAccessRule rule in acl.GetAccessRules(true, true, typeof(SecurityIdentifier)))
            if (rule.AccessControlType == AccessControlType.Allow && rule.FileSystemRights != 0 &&
                rule.IdentityReference.Value is not ("S-1-5-18" or "S-1-5-32-544"))
                throw new InvalidDataException("Journal data must be SYSTEM/Administrators-only");
    }
    public void Dispose()
    {
        if (disposed) return; disposed = true;
        // Closing SQLite precedes releasing the lease. The broker calls this
        // only after draining its native calls/replies and stopping its reader.
        try { Ledger.Dispose(); } finally { lease.Dispose(); }
    }
}
