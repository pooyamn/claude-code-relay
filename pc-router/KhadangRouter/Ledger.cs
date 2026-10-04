using System.Runtime.InteropServices;
using System.Text.Json;

namespace KhadangRouter;

// The OS supplies SQLite: winsqlite3 on Windows, system sqlite3 for tests.
// No copied Python runtime, user site-packages or third-party native DLL search.
public sealed class Ledger : IDisposable
{
    private readonly object gate = new();
    private IntPtr db;
    static Ledger()
    {
        NativeLibrary.SetDllImportResolver(typeof(Ledger).Assembly, (name, _, _) => name != "router_sqlite" ? IntPtr.Zero :
            NativeLibrary.Load(OperatingSystem.IsWindows() ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "winsqlite3.dll") :
                OperatingSystem.IsLinux() ? "libsqlite3.so.0" : "/usr/lib/libsqlite3.dylib"));
    }
    public Ledger(string path)
    {
        if (sqlite3_open_v2(path, out db, 2 | 4 | 0x10000, IntPtr.Zero) != 0) throw new IOException("Cannot open router ledger");
        Exec("PRAGMA journal_mode=WAL"); Exec("PRAGMA synchronous=FULL");
        Exec("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)");
        Exec("CREATE TABLE IF NOT EXISTS updates (id INTEGER PRIMARY KEY,payload TEXT NOT NULL,status TEXT NOT NULL)");
        Exec("CREATE TABLE IF NOT EXISTS bindings (chat INTEGER NOT NULL,topic INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(chat,topic))");
        Exec("CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,result TEXT)");
        // A restarted process must not replay a possibly accepted operation.
        Exec("UPDATE operations SET status='unknown' WHERE status='attempting'");
        Exec("UPDATE updates SET status='unknown' WHERE status='dispatching'");
    }
    public long Offset => long.Parse(Rows("SELECT COALESCE(MAX(id)+1,0) FROM updates")[0][0]!);
    public bool Receive(long id, string payload)
    {
        lock (gate)
        {
            var existing = Rows("SELECT payload FROM updates WHERE id=?", id);
            if (existing.Count > 0)
            {
                if (existing[0][0] != payload) throw new InvalidDataException("Update ID payload changed");
                return false;
            }
            Exec("INSERT INTO updates VALUES (?,?,'received')", id, payload); return true;
        }
    }
    public bool Claim(long id)
    {
        lock (gate)
        {
            Exec("UPDATE updates SET status='dispatching' WHERE id=? AND status='received'", id);
            return sqlite3_changes(db) == 1;
        }
    }
    public void Finish(long id, string status) => Exec("UPDATE updates SET status=? WHERE id=? AND status='dispatching'", status, id);
    public List<(long Id, JsonElement Payload)> Pending() => Rows("SELECT id,payload FROM updates WHERE status='received' ORDER BY id")
        .Select(row => (long.Parse(row[0]!), JsonDocument.Parse(row[1]!).RootElement.Clone())).ToList();
    public int Unknown => int.Parse(Rows("SELECT COUNT(*) FROM updates WHERE status='unknown'")[0][0]!) +
        int.Parse(Rows("SELECT COUNT(*) FROM operations WHERE status='unknown' AND kind<>'telegram/editMessageText'")[0][0]!);
    // An edit addresses an existing Telegram message. Its uncertain display
    // outcome must remain visible, but cannot duplicate a model/external action
    // or justify stopping input to every unrelated native conversation.
    // Unknown sends, native writes and incoming dispatches still fail closed.
    public int PresentationUnknown => int.Parse(Rows("SELECT COUNT(*) FROM operations WHERE kind='telegram/editMessageText' AND status IN ('unknown','unknown-presentation')")[0][0]!);
    public string Attempt(string kind, object payload)
    {
        var id = Guid.NewGuid().ToString("N");
        Exec("INSERT INTO operations VALUES (?,?,?,'attempting',NULL)", id, kind, JsonSerializer.Serialize(payload)); return id;
    }
    public void Confirm(string id, JsonElement result) => Exec("UPDATE operations SET status='confirmed',result=? WHERE id=? AND status='attempting'", result.GetRawText(), id);
    public void Outcome(string id, string status) => Exec("UPDATE operations SET status=? WHERE id=? AND status='attempting'", status, id);
    public void Reject(string id, JsonElement error) => Exec("UPDATE operations SET status='rejected',result=? WHERE id=? AND status='attempting'", error.GetRawText(), id);
    public void Bind(Binding binding)
    {
        lock (gate)
        {
            var prior = Rows("SELECT payload FROM bindings WHERE chat=? AND topic=?", binding.Chat, binding.Topic);
            var payload = JsonSerializer.Serialize(binding);
            if (prior.Count > 0 && JsonSerializer.Deserialize<Binding>(prior[0][0]!) != binding)
                throw new InvalidDataException("Topic already has a different native binding");
            Exec("INSERT OR IGNORE INTO bindings VALUES (?,?,?)", binding.Chat, binding.Topic, payload);
        }
    }
    public List<Binding> Bindings() => Rows("SELECT payload FROM bindings").Select(row => JsonSerializer.Deserialize<Binding>(row[0]!)!).ToList();
    internal void ReplaceBinding(Binding expected, Binding replacement, Action? committed = null)
    {
        if (expected.Address != replacement.Address || expected.Workspace != replacement.Workspace || expected.Runtime != replacement.Runtime)
            throw new InvalidDataException("A tool switch cannot move the topic or workspace");
        Transaction(() => {
            var rows = Rows("SELECT payload FROM bindings WHERE chat=? AND topic=?", expected.Chat, expected.Topic);
            if (rows.Count != 1 || JsonSerializer.Deserialize<Binding>(rows[0][0]!) != expected)
                throw new InvalidDataException("Topic changed during tool switch");
            Exec("UPDATE bindings SET payload=? WHERE chat=? AND topic=?", JsonSerializer.Serialize(replacement), expected.Chat, expected.Topic);
            committed?.Invoke();
        });
    }
    public void Put(string key, object value) => Exec("INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", key, JsonSerializer.Serialize(value));
    public JsonElement? Get(string key)
    {
        var rows = Rows("SELECT value FROM meta WHERE key=?", key);
        return rows.Count == 0 ? null : JsonDocument.Parse(rows[0][0]!).RootElement.Clone();
    }
    public void Exec(string sql, params object?[] args) { lock (gate) { _ = Rows(sql, args); } }
    // Candidate component journals use the same OS SQLite and serialized FULL
    // commit boundary. No public SQL endpoint or live broker is exposed.
    internal List<string?[]> Query(string sql, params object?[] args) => Rows(sql, args);
    internal void Transaction(Action operation)
    {
        lock (gate)
        {
            Exec("BEGIN IMMEDIATE");
            try { operation(); Exec("COMMIT"); }
            catch { Exec("ROLLBACK"); throw; }
        }
    }
    private List<string?[]> Rows(string sql, params object?[] args)
    {
        lock (gate)
        {
            if (sqlite3_prepare_v2(db, sql, -1, out var statement, IntPtr.Zero) != 0) throw new IOException("SQLite prepare failed");
            try
            {
                for (int i = 0; i < args.Length; i++)
                {
                    var value = args[i];
                    int code = value == null ? sqlite3_bind_null(statement, i + 1) : value is int or long ?
                        sqlite3_bind_int64(statement, i + 1, Convert.ToInt64(value)) :
                        sqlite3_bind_text(statement, i + 1, Convert.ToString(value)!, -1, new IntPtr(-1));
                    if (code != 0) throw new IOException("SQLite binding failed");
                }
                var rows = new List<string?[]>();
                int rc;
                while ((rc = sqlite3_step(statement)) == 100)
                    rows.Add(Enumerable.Range(0, sqlite3_column_count(statement)).Select(index => Marshal.PtrToStringUTF8(sqlite3_column_text(statement, index))).ToArray());
                if (rc != 101) throw new IOException("SQLite statement failed");
                return rows;
            }
            finally { sqlite3_finalize(statement); }
        }
    }
    public void Dispose() { if (db != IntPtr.Zero) { sqlite3_close_v2(db); db = IntPtr.Zero; } }
    [DllImport("router_sqlite")] private static extern int sqlite3_open_v2([MarshalAs(UnmanagedType.LPUTF8Str)] string name, out IntPtr db, int flags, IntPtr vfs);
    [DllImport("router_sqlite")] private static extern int sqlite3_prepare_v2(IntPtr db, [MarshalAs(UnmanagedType.LPUTF8Str)] string sql, int length, out IntPtr statement, IntPtr tail);
    [DllImport("router_sqlite")] private static extern int sqlite3_step(IntPtr statement);
    [DllImport("router_sqlite")] private static extern int sqlite3_changes(IntPtr db);
    [DllImport("router_sqlite")] private static extern int sqlite3_bind_null(IntPtr statement, int index);
    [DllImport("router_sqlite")] private static extern int sqlite3_bind_int64(IntPtr statement, int index, long value);
    [DllImport("router_sqlite")] private static extern int sqlite3_bind_text(IntPtr statement, int index, [MarshalAs(UnmanagedType.LPUTF8Str)] string value, int length, IntPtr destructor);
    [DllImport("router_sqlite")] private static extern int sqlite3_column_count(IntPtr statement);
    [DllImport("router_sqlite")] private static extern IntPtr sqlite3_column_text(IntPtr statement, int index);
    [DllImport("router_sqlite")] private static extern int sqlite3_finalize(IntPtr statement);
    [DllImport("router_sqlite")] private static extern int sqlite3_close_v2(IntPtr db);
}
