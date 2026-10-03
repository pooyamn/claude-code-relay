using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace KhadangRouter;

// Inactive candidate custody core. The protected broker, NOT an attached router,
// owns this native connection. No discovery, listener enrollment, production
// policy, role/admission grant, automatic reconnect or action replay is here.
// Own acquires a private journal lease before SQLite/native startup. Never pass
// the live router ledger or reopen it to inspect a running broker.
public sealed class NativeBroker : IAsyncDisposable
{
    private readonly INative native;
    private readonly IAsyncDisposable owner;
    private readonly Ledger ledger;
    private readonly NativeBrokerJournal? journal;
    private readonly object gate = new();
    private readonly CancellationTokenSource stop = new();
    private readonly Dictionary<string, Task<JsonElement>> running = [];
    private readonly Dictionary<string, Task> replying = [];
    private readonly Task initialized;
    private Task? shutdown;
    private long position;
    private bool closed, captureFailed;
    public string Epoch { get; } = Guid.NewGuid().ToString("N");
    public Task Ready => initialized;
    public uint Pid => native.Pid;
    public long Position { get { lock (gate) return position; } }
    public int Unknown => int.Parse(ledger.Query("SELECT (SELECT COUNT(*) FROM broker_calls WHERE status='unknown') + (SELECT COUNT(*) FROM broker_replies WHERE status='unknown')")[0][0]!);

    public static NativeBroker Own(string stateDirectory, string protectedRoot, Func<Ledger, NativeRpc> launchNative)
    {
        WindowsPipePeer.RequireSystem(); ArgumentNullException.ThrowIfNull(launchNative);
        var journal = NativeBrokerJournal.Open(stateDirectory, protectedRoot); NativeRpc? native = null;
        try
        {
            // Only a reviewed same-process protected launcher supplies this
            // delegate. No RPC client chooses a path, executable or callback.
            native = launchNative(journal.Ledger);
            return new(native, native, journal.Ledger, () => native.Initialize(CancellationToken.None), journal);
        }
        catch
        {
            try { native?.DisposeAsync().AsTask().GetAwaiter().GetResult(); }
            finally { journal.Dispose(); }
            throw;
        }
    }
    internal static NativeBroker Fixture(INative native, IAsyncDisposable owner, Ledger privateLedger, Func<Task> initialize, NativeBrokerJournal? journal = null) =>
        new(native, owner, privateLedger, initialize, journal);
    private NativeBroker(INative native, IAsyncDisposable owner, Ledger ledger, Func<Task> initialize, NativeBrokerJournal? journal)
    {
        this.native = native; this.owner = owner; this.ledger = ledger; this.journal = journal;
        ledger.Transaction(() => {
            ledger.Exec("CREATE TABLE IF NOT EXISTS broker_calls (intent TEXT PRIMARY KEY,epoch TEXT NOT NULL,method TEXT NOT NULL,fingerprint TEXT NOT NULL,status TEXT NOT NULL,result TEXT)");
            ledger.Exec("CREATE TABLE IF NOT EXISTS broker_events (epoch TEXT NOT NULL,position INTEGER NOT NULL,frame TEXT NOT NULL,PRIMARY KEY(epoch,position))");
            ledger.Exec("CREATE TABLE IF NOT EXISTS broker_requests (epoch TEXT NOT NULL,id TEXT NOT NULL,thread TEXT NOT NULL,turn TEXT,frame TEXT,fingerprint TEXT,status TEXT NOT NULL,PRIMARY KEY(epoch,id))");
            ledger.Exec("CREATE TABLE IF NOT EXISTS broker_replies (epoch TEXT NOT NULL,id TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,PRIMARY KEY(epoch,id))");
            ledger.Exec("UPDATE broker_calls SET status='unknown' WHERE status='attempting'");
            ledger.Exec("UPDATE broker_replies SET status='unknown' WHERE status IN ('attempting','submitted')");
            ledger.Exec("UPDATE broker_requests SET status='old-connection' WHERE status IN ('pending','replying','reply-submitted')");
            ledger.Put("broker/current-epoch", new { epoch = Epoch, pid = Pid });
        });
        native.Notification += Capture;
        // Exactly once for the broker's owned native transport. Attaching or
        // losing a UI client never initializes or disposes it again.
        initialized = Task.Run(initialize);
    }
    public NativeBrokerSession Attach(WindowsPipePeer peer)
    { peer.Current(); return new(this, peer.Current); }
    // Same-process protected supervisor, not an unauthenticated wire endpoint.
    // Live callers still need reviewed authorization/admission policy wiring.
    public async Task<JsonElement> ControllerCall(string intent, string method, object parameters, CancellationToken controllerStop)
    {
        WindowsPipePeer.RequireSystem(); await Ready.WaitAsync(controllerStop); Current();
        return await Call(intent, method, parameters).WaitAsync(controllerStop);
    }
    public IReadOnlyList<BrokerEvent> ControllerEvents(long cursor, int maximum = 100)
    { WindowsPipePeer.RequireSystem(); return Events(cursor, maximum); }
    // Account/attestation/time requests belong to the protected connection
    // controller, never the forum's thread approval UI. No credential issuer or
    // automatic handler is wired here; native-managed sign-in stays unchanged.
    public IReadOnlyList<BrokerRequest> ControllerConnectionRequests()
    { WindowsPipePeer.RequireSystem(); return Requests(connection: true); }
    public Task ControllerConnectionReply(BrokerRequest reviewed, object result)
    { WindowsPipePeer.RequireSystem(); return Reply(reviewed, result, connection: true); }
    internal NativeBrokerSession AttachFixture(Action current) => new(this, current);
    internal void Current()
    {
        lock (gate)
            if (closed || captureFailed || native is NativeRpc rpc && !rpc.Connected)
                throw new IOException("Native broker custody unavailable; no reconnect or replay");
    }
    internal Task<JsonElement> Call(string intent, string method, object parameters)
    {
        if (!Guid.TryParseExact(intent, "N", out _) || string.IsNullOrEmpty(method) || method.Length > 128 ||
            method.Any(c => !char.IsAsciiLetterOrDigit(c) && c is not ('/' or '_')) || method is "initialize" or "initialized")
            throw new InvalidDataException("Stable intent and native method required; initialization belongs to broker");
        var payload = JsonSerializer.Serialize(parameters);
        using (var document = JsonDocument.Parse(payload))
            if (document.RootElement.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Native parameters must be an object");
        if (Encoding.UTF8.GetByteCount(payload) > WebSocketNativeChannel.MaximumFrameBytes)
            throw new InvalidDataException("Broker native input exceeds complete-frame bound");
        var fingerprint = Hash(method + "\n" + payload);
        lock (gate)
        {
            Current();
            if (!initialized.IsCompletedSuccessfully) throw new InvalidOperationException("Native broker initialization is not ready");
            var prior = ledger.Query("SELECT fingerprint,status,result,method FROM broker_calls WHERE intent=?", intent);
            if (prior.Count != 0)
            {
                var row = prior[0];
                if (row[0] != fingerprint || row[3] != method) throw new InvalidDataException("Stable intent payload changed");
                if (row[1] == "confirmed") return Task.FromResult(JsonDocument.Parse(row[2]!).RootElement.Clone());
                if (row[1] == "rejected") return Task.FromException<JsonElement>(new NativeRejected(method));
                if (row[1] == "attempting" && running.TryGetValue(intent, out var existing)) return existing;
                return Task.FromException<JsonElement>(new IOException("Native intent outcome unconfirmed; inspect evidence, never replay"));
            }
            if (running.Count >= 16) throw new InvalidOperationException("Broker outstanding-call ceiling reached");
            if (Unknown != 0 && !ReadOnly(method)) throw new InvalidOperationException("Unknown native outcome holds new mutations");
            ledger.Exec("INSERT INTO broker_calls VALUES (?,?,?,?,'attempting',NULL)", intent, Epoch, method, fingerprint);
            // Cancellation belongs to the broker lifetime, not the UI waiter.
            // Queue behind initialization only; no action retry is performed.
            var work = Task.Run(async () => {
                try
                {
                    await initialized; Current();
                    var result = await native.Call(method, JsonDocument.Parse(payload).RootElement.Clone(), stop.Token);
                    lock (gate) ledger.Exec("UPDATE broker_calls SET status='confirmed',result=? WHERE intent=? AND status='attempting'", result.GetRawText(), intent);
                    return result;
                }
                catch (NativeRejected)
                { lock (gate) ledger.Exec("UPDATE broker_calls SET status='rejected' WHERE intent=? AND status='attempting'", intent); throw; }
                catch
                { lock (gate) ledger.Exec("UPDATE broker_calls SET status='unknown' WHERE intent=? AND status='attempting'", intent); throw; }
                finally { lock (gate) running.Remove(intent); }
            });
            running.Add(intent, work); return work;
        }
    }
    private static bool ReadOnly(string method) => method is "account/read" or "account/rateLimits/read" or "remoteControl/status/read" or
        "thread/read" or "thread/list" or "thread/loaded/list" or "thread/goal/get" or "model/list";
    private static string Hash(string payload) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(payload)));
    private static string RequestKey(JsonElement id)
    {
        if (id.ValueKind == JsonValueKind.Number && id.TryGetInt64(out _) || id.ValueKind == JsonValueKind.String &&
            id.GetString() is { Length: > 0 and <= 200 } text && !text.Any(char.IsControl)) return id.GetRawText();
        throw new InvalidDataException("Bounded typed native request ID required");
    }
    private void Capture(JsonElement message)
    {
        lock (gate)
        {
            try
            {
                // Keep collecting native cleanup while shutdown drains writes.
                // The owner stops the reader before this journal is disposed.
                if (captureFailed) throw new IOException("Native event custody unavailable");
                var frame = message.GetRawText();
                if (Encoding.UTF8.GetByteCount(frame) > WebSocketNativeChannel.MaximumFrameBytes) throw new InvalidDataException("Broker event frame exceeds bound");
                var next = position + 1;
                ledger.Transaction(() => {
                    ledger.Exec("INSERT INTO broker_events VALUES (?,?,?)", Epoch, next, frame);
                    if (!message.TryGetProperty("method", out var method)) return; // late unmatched native response: evidence, not silent reconciliation
                    if (message.TryGetProperty("id", out var id))
                    {
                        var parameters = message.TryGetProperty("params", out var p) ? p : JsonSerializer.SerializeToElement(new { });
                        if (parameters.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Native request parameters must be an object");
                        var name = method.GetString() ?? throw new InvalidDataException("Native request method required");
                        var key = RequestKey(id);
                        var thread = parameters.TryGetProperty("threadId", out var threadId) && threadId.ValueKind != JsonValueKind.Null ? threadId.GetString() : null;
                        var turn = parameters.TryGetProperty("turnId", out var turnId) && turnId.ValueKind != JsonValueKind.Null ? turnId.GetString() : null;
                        if (thread != null && !BoundedScope(thread) || turn != null && (!BoundedScope(turn) || thread == null) ||
                            thread == null && name is ("item/commandExecution/requestApproval" or "item/fileChange/requestApproval" or
                                "item/tool/requestUserInput" or "item/permissions/requestApproval" or "item/tool/call" or "mcpServer/elicitation/request") ||
                            thread != null && name is ("account/chatgptAuthTokens/refresh" or "attestation/generate" or "currentTime/read"))
                            throw new InvalidDataException("Native request has missing or mixed thread/connection scope");
                        // Empty SQL thread is an explicit connection scope in
                        // the existing NOT NULL schema, never an empty thread ID.
                        thread ??= "";
                        ledger.Exec("INSERT INTO broker_requests VALUES (?,?,?,?,?,?,'pending')", Epoch, key, thread, turn, frame, Hash(frame));
                    }
                    else if (method.GetString() == "serverRequest/resolved")
                    {
                        var parameters = message.GetProperty("params");
                        var key = RequestKey(parameters.GetProperty("requestId")); var thread = parameters.GetProperty("threadId").GetString();
                        if (string.IsNullOrWhiteSpace(thread)) throw new InvalidDataException("Resolved native request thread required");
                        var prior = ledger.Query("SELECT thread FROM broker_requests WHERE epoch=? AND id=?", Epoch, key);
                        if (prior.Count > 0 && prior[0][0] != thread) throw new InvalidDataException("Resolved request belongs to a different thread");
                        ledger.Exec("INSERT INTO broker_requests VALUES (?,?,?,NULL,NULL,NULL,'resolved') ON CONFLICT(epoch,id) DO UPDATE SET status='resolved'", Epoch, key, thread);
                        // Cleanup proves the request ended, not which client
                        // answered it or whether this particular decision ran.
                        ledger.Exec("UPDATE broker_replies SET status='resolved-unattributed' WHERE epoch=? AND id=? AND status='submitted'", Epoch, key);
                    }
                });
                position = next;
            }
            catch { captureFailed = true; throw; }
        }
    }
    internal IReadOnlyList<BrokerEvent> Events(long cursor, int maximum)
    {
        lock (gate)
        {
            Current();
            if (cursor < 0 || cursor > position || maximum is < 1 or > 100) throw new InvalidDataException("Current epoch cursor and bounded batch required");
            var rows = ledger.Query("SELECT position,frame FROM broker_events WHERE epoch=? AND position>? ORDER BY position LIMIT ?", Epoch, cursor, maximum);
            var events = new List<BrokerEvent>();
            foreach (var row in rows)
            {
                if (long.Parse(row[0]!) != ++cursor) throw new InvalidDataException("Native event custody has a gap");
                events.Add(new(Epoch, cursor, JsonDocument.Parse(row[1]!).RootElement.Clone()));
            }
            return events;
        }
    }
    private static bool BoundedScope(string value) => !string.IsNullOrWhiteSpace(value) && value.Length <= 200 && !value.Any(char.IsControl);
    internal IReadOnlyList<BrokerRequest> Requests(bool connection = false)
    {
        lock (gate)
        {
            Current();
            return ledger.Query("SELECT id,thread,turn,frame,fingerprint FROM broker_requests WHERE epoch=? AND status='pending' AND thread" + (connection ? "=''" : "<>''"), Epoch)
                .Select(r => new BrokerRequest(Epoch, JsonDocument.Parse(r[0]!).RootElement.Clone(), r[1] == "" ? null : r[1], r[2], r[4]!, JsonDocument.Parse(r[3]!).RootElement.Clone())).ToList();
        }
    }
    internal Task Reply(BrokerRequest reviewed, object result, bool connection = false)
    {
        var key = RequestKey(reviewed.Id);
        var payload = JsonSerializer.Serialize(new { id = reviewed.Id, result });
        if (Encoding.UTF8.GetByteCount(payload) > WebSocketNativeChannel.MaximumFrameBytes) throw new InvalidDataException("Broker reply exceeds complete-frame bound");
        lock (gate)
        {
            Current(); var row = ledger.Query("SELECT thread,turn,fingerprint,status FROM broker_requests WHERE epoch=? AND id=?", Epoch, key);
            if (connection != (reviewed.Thread == null) || reviewed.Epoch != Epoch || row.Count != 1 || row[0][0] != (reviewed.Thread ?? "") ||
                row[0][1] != reviewed.Turn || row[0][2] != reviewed.Fingerprint || row[0][3] != "pending" ||
                Hash(reviewed.Frame.GetRawText()) != reviewed.Fingerprint || RequestKey(reviewed.Frame.GetProperty("id")) != key)
                throw new InvalidDataException("Native request is resolved, stale, changed or already consumed");
            if (replying.Count >= 16) throw new InvalidOperationException("Broker outstanding-reply ceiling reached");
            ledger.Transaction(() => {
                ledger.Exec("INSERT INTO broker_replies VALUES (?,?,?,'attempting')", Epoch, key, payload);
                ledger.Exec("UPDATE broker_requests SET status='replying' WHERE epoch=? AND id=? AND status='pending'", Epoch, key);
            });
            // Register before releasing gate: shutdown cannot miss a reply
            // between its durable attempt and its native write/settlement.
            var work = Task.Run(async () => {
                var enteredNativeWrite = false;
                try
                {
                    lock (gate)
                    {
                        Current();
                        if (ledger.Query("SELECT status FROM broker_requests WHERE epoch=? AND id=?", Epoch, key).Single()[0] != "replying")
                            throw new InvalidDataException("Native request ended before reply submission");
                        enteredNativeWrite = true;
                    }
                    using var document = JsonDocument.Parse(payload);
                    await native.Reply(reviewed.Id, document.RootElement.GetProperty("result").Clone(), stop.Token);
                    // A successful write isn't acceptance. Native cleanup may
                    // arrive during shutdown or before this delayed settlement.
                    lock (gate) ledger.Transaction(() => {
                        ledger.Exec("UPDATE broker_requests SET status='reply-submitted' WHERE epoch=? AND id=? AND status='replying'", Epoch, key);
                        ledger.Exec("UPDATE broker_replies SET status=CASE WHEN EXISTS (SELECT 1 FROM broker_requests WHERE epoch=? AND id=? AND status='resolved') THEN 'resolved-unattributed' ELSE 'submitted' END WHERE epoch=? AND id=? AND status='attempting'", Epoch, key, Epoch, key);
                    });
                }
                catch
                {
                    lock (gate) ledger.Transaction(() => {
                        ledger.Exec("UPDATE broker_requests SET status=? WHERE epoch=? AND id=? AND status='replying'", enteredNativeWrite ? "reply-unknown" : "reply-not-submitted", Epoch, key);
                        ledger.Exec("UPDATE broker_replies SET status=? WHERE epoch=? AND id=? AND status='attempting'", enteredNativeWrite ? "unknown" : "not-submitted", Epoch, key);
                    });
                    throw;
                }
                finally { lock (gate) replying.Remove(key); }
            });
            replying.Add(key, work); return work;
        }
    }
    public ValueTask DisposeAsync()
    {
        lock (gate)
        {
            if (shutdown != null) return new(shutdown);
            closed = true;
            var pending = running.Values.Cast<Task>().Concat(replying.Values).Append(initialized).ToArray();
            shutdown = Task.Run(async () => {
                stop.Cancel();
                async Task Settle() { try { await Task.WhenAll(pending); } catch (Exception) { /* persisted unknown/rejected evidence remains */ } }
                async Task StopOwner() { await owner.DisposeAsync(); }
                try { await Task.WhenAll(StopOwner(), Settle()); }
                finally
                {
                    native.Notification -= Capture;
                    try { if (journal != null) journal.Dispose(); else ledger.Dispose(); }
                    finally { stop.Dispose(); }
                }
            });
            return new(shutdown); // Every disposal waiter joins the same drain.
        }
    }
}

public sealed record BrokerEvent(string Epoch, long Position, JsonElement Frame);
public sealed record BrokerRequest(string Epoch, JsonElement Id, string? Thread, string? Turn, string Fingerprint, JsonElement Frame);
public sealed class NativeBrokerSession : IDisposable
{
    private readonly NativeBroker broker;
    private readonly Action currentPeer;
    private bool closed;
    internal NativeBrokerSession(NativeBroker broker, Action currentPeer) { this.broker = broker; this.currentPeer = currentPeer; Current(); }
    public uint Pid => broker.Pid;
    public string Epoch => broker.Epoch;
    public async Task<BrokerWireStatus> Status(CancellationToken stop)
    { Current(); await broker.Ready.WaitAsync(stop); Current(); return new(Epoch, Pid, broker.Position); }
    private void Current() { if (closed) throw new IOException("Broker client detached"); currentPeer(); broker.Current(); }
    public async Task<JsonElement> Call(string intent, string method, object parameters, CancellationToken clientStop)
    {
        clientStop.ThrowIfCancellationRequested(); Current(); await broker.Ready.WaitAsync(clientStop); Current();
        var response = await broker.Call(intent, method, parameters).WaitAsync(clientStop);
        Current(); return response;
    }
    public IReadOnlyList<BrokerEvent> Events(long cursor, int maximum = 100) { Current(); return broker.Events(cursor, maximum); }
    public IReadOnlyList<BrokerRequest> Requests() { Current(); return broker.Requests(); }
    public Task Reply(BrokerRequest reviewed, object result) { Current(); return broker.Reply(reviewed, result); }
    public void Dispose() { closed = true; } // NEVER cancel/dispose broker/native on a client disconnect.
}
