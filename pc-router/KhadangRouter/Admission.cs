using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace KhadangRouter;

public sealed record AdmissionState(int Blocking, int InterruptedIntake, int NativeUnknown, int RetainedOutput);
internal sealed record LedgerStatusSnapshot(long Offset, int Unknown, int PresentationUnknown,
    IReadOnlyDictionary<TopicAddress, AdmissionState> Admissions);

public sealed partial class Ledger
{
    // Worker replacement/retirement is distinct from ordinary chat. Preserve
    // the independently deployed host's stricter lifecycle admission contract.
    internal int LifecycleUnknown(Binding binding)
    {
        lock (gate)
        {
            var count = InputUnknown(binding);
            foreach (var row in Rows("SELECT id,payload FROM operations WHERE status='unknown' AND kind IN ('telegram/sendMessage','telegram/sendRichMessage','telegram/sendPhoto','telegram/sendDocument')"))
                try
                {
                    using var doc = JsonDocument.Parse(row[1]!); var p = doc.RootElement;
                    if (p.GetProperty("chat_id").GetInt64() == binding.Chat && p.GetProperty("message_thread_id").GetInt32() == binding.Topic && !OutputQuarantined(row[0]!, binding, row[1]!)) count++;
                }
                catch (Exception e) when (ShapeError(e)) { }
            return count;
        }
    }
    // Explicit failure domains. Output delivery never authorizes a native retry,
    // nor does uncertainty about displaying a reply stop an unrelated input.
    public AdmissionState Admission(Binding binding)
    {
        lock (gate) return AdmissionCore(binding, ReadAdmissionEvidence());
    }
    private sealed record AdmissionEvidence(List<Binding> Bindings, List<string?[]> Updates, List<string?[]> Operations);
    private AdmissionEvidence ReadAdmissionEvidence()
    {
        var bindings = Bindings();
        var updates = Rows("SELECT id,payload FROM updates WHERE status='unknown'");
        var operations = Rows("SELECT id,kind,payload FROM operations WHERE status='unknown' AND kind<>'telegram/editMessageText'");
        // Supersession is verified once per observation, never waived or
        // cached across writes. Ordinary dispatch still takes a fresh view.
        operations.RemoveAll(row => row[1] == "native/thread/resume" && ResumeSuperseded(row[0]!, row[2]!) ||
            row[1] == "telegram/setMyCommands" && (MenuOnly(row[2]!, bindings) || MenuSuperseded(row[0]!, row[2]!)));
        return new(bindings, updates, operations);
    }
    internal LedgerStatusSnapshot StatusSnapshot(IEnumerable<Binding> targets)
    {
        lock (gate)
        {
            var evidence = ReadAdmissionEvidence();
            return new(Offset, Unknown, PresentationUnknown,
                targets.ToDictionary(b => b.Address, b => AdmissionCore(b, evidence)));
        }
    }
    private AdmissionState AdmissionCore(Binding binding, AdmissionEvidence evidence)
    {
            int intake = 0, native = 0, output = 0;
            var bindings = evidence.Bindings;
            foreach (var row in evidence.Updates)
            {
                TopicAddress? scope = null;
                try
                {
                    using var doc = JsonDocument.Parse(row[1]!);
                    var message = doc.RootElement.GetProperty("message");
                    scope = Address(message.GetProperty("chat").GetProperty("id"), message.GetProperty("message_thread_id"));
                    if (!bindings.Any(b => b.Address == scope)) scope = null;
                    if (Get("intake/" + row[0]) is { } journal && journal.GetProperty("Binding").Deserialize<Binding>() is { } pin &&
                        !bindings.Contains(pin)) scope = null; // A repoint cannot waive an old identity.
                }
                catch (Exception e) when (ShapeError(e)) { }
                if (scope == null || scope == binding.Address) intake++;
            }
            foreach (var row in evidence.Operations)
            {
                var kind = row[1]!;
                try
                {
                    using var doc = JsonDocument.Parse(row[2]!); var value = doc.RootElement;
                    if (kind is "telegram/sendMessage" or "telegram/sendRichMessage" or "telegram/sendPhoto" or "telegram/sendDocument")
                    {
                        var hasTopic = value.TryGetProperty("message_thread_id", out var topic);
                        var scope = Address(value.GetProperty("chat_id"), hasTopic ? topic : JsonSerializer.SerializeToElement(0), general: !hasTopic);
                        if (scope != null) { if (scope == binding.Address) output++; continue; }
                    }
                    else if (kind.StartsWith("native/", StringComparison.Ordinal) || kind.StartsWith("claude/", StringComparison.Ordinal))
                    {
                        var parameters = value.TryGetProperty("parameters", out var p) ? p : value;
                        var id = parameters.TryGetProperty("threadId", out var t) ? t : parameters.GetProperty("SessionId");
                        if (id.ValueKind == JsonValueKind.String)
                        {
                            var matches = bindings.Where(b => b.ThreadId == id.GetString()).ToArray();
                            if (matches.Length == 1 && matches[0].Address != binding.Address) continue;
                        }
                    }
                }
                catch (Exception e) when (ShapeError(e)) { }
                native++; // Malformed, unregistered or own-session mutation stays fenced.
            }
            return new(intake + native, intake, native, output);
    }
    private static TopicAddress? Address(JsonElement chat, JsonElement topic, bool general = false) =>
        chat.TryGetInt64(out var c) && c < 0 && topic.TryGetInt32(out var t) && (t > 0 || general && t == 0) ? new(c, t) : null;
    private static bool ShapeError(Exception e) => e is JsonException or InvalidOperationException or KeyNotFoundException or ArgumentException or FormatException;

    private static bool MenuOnly(string payload, IReadOnlyList<Binding> bindings)
    {
        try
        {
            using var doc = JsonDocument.Parse(payload); var value = doc.RootElement;
            if (value.EnumerateObject().Count() != 2) return false;
            var scope = value.GetProperty("scope"); var commands = value.GetProperty("commands");
            if (scope.EnumerateObject().Count() != 3 || scope.GetProperty("type").GetString() != "chat_member" ||
                !scope.GetProperty("chat_id").TryGetInt64(out var chat) || !bindings.Any(b => b.Chat == chat) ||
                !scope.GetProperty("user_id").TryGetInt64(out var user) || user <= 0 ||
                commands.ValueKind != JsonValueKind.Array || commands.GetArrayLength() > 100) return false;
            return commands.EnumerateArray().All(c => c.ValueKind == JsonValueKind.Object && c.EnumerateObject().Count() == 2 &&
                c.TryGetProperty("command", out var command) && command.ValueKind == JsonValueKind.String &&
                c.TryGetProperty("description", out var description) && description.ValueKind == JsonValueKind.String);
        }
        catch (Exception error) when (ShapeError(error)) { return false; }
    }

    private sealed record InputIntent(long UpdateId, Binding Binding, string PayloadSha256, string? Operation, string? Kind);
    private sealed record InputScope(Ledger Ledger, long UpdateId);
    private static readonly AsyncLocal<InputScope?> inputScope = new();
    private sealed class Scope(Action dispose) : IDisposable { public void Dispose() => dispose(); }
    private static string Digest(string text) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(text)));
    internal IDisposable TrackInput(long updateId, Binding binding)
    {
        Transaction(() =>
        {
            var rows = Rows("SELECT payload FROM updates WHERE id=? AND status='dispatching'", updateId);
            if (rows.Count != 1 || !Bindings().Contains(binding)) throw new InvalidDataException("Exact claimed input and binding required");
            if (Get("intake/" + updateId) != null) throw new InvalidDataException("Input tracking cannot be restarted");
            Put("intake/" + updateId, new InputIntent(updateId, binding, Digest(rows[0][0]!), null, null));
        });
        var previous = inputScope.Value; inputScope.Value = new(this, updateId);
        return new Scope(() => inputScope.Value = previous);
    }
    private void RecordInputIntent(string operation, string kind)
    {
        if (inputScope.Value is not { } scope || !ReferenceEquals(scope.Ledger, this) ||
            !kind.StartsWith("native/", StringComparison.Ordinal) && !kind.StartsWith("claude/", StringComparison.Ordinal)) return;
        var key = "intake/" + scope.UpdateId;
        var prior = Get(key)!.Value.Deserialize<InputIntent>()!;
        if (prior.Operation != null) throw new InvalidDataException("Multiple native mutations in one ordinary input are not supported");
        Put(key, prior with { Operation = operation, Kind = kind });
    }
    internal void ReconcileInputReceipt(string operation) => RecoverInputIntents(operation);
    private void RecoverInputIntents(string? confirmedOperation = null)
    {
        // Runs only under the router's exclusive startup custody. Never inspect
        // or repair a live writer by opening another writable Ledger instance.
        foreach (var row in Rows("SELECT id,payload FROM updates WHERE status='unknown'"))
        {
            try
            {
                if (Get("intake/" + row[0]) is not { } saved) continue;
                var intent = saved.Deserialize<InputIntent>();
                if (intent == null || intent.UpdateId.ToString() != row[0] || intent.PayloadSha256 != Digest(row[1]!) || !Bindings().Contains(intent.Binding)) continue;
                if (confirmedOperation != null && intent.Operation != confirmedOperation) continue;
                string? status = confirmedOperation == null && intent.Operation == null && intent.Kind == null ? "retained-unsubmitted" : null;
                if (ConfirmedInput(intent)) status = "accepted-late";
                if (status == null) continue;
                Transaction(() =>
                {
                    Put("intake-reconciled/" + row[0], new { previous = "unknown", status, input = intent, replayed = false, at = DateTimeOffset.UtcNow });
                    Exec("UPDATE updates SET status=? WHERE id=? AND status='unknown'", status, long.Parse(row[0]!));
                });
            }
            catch (Exception e) when (ShapeError(e)) { /* Preserve opaque uncertain legacy data. */ }
        }
    }
    private bool ConfirmedInput(InputIntent intent)
    {
        if (intent.Operation == null || intent.Kind is not ("native/turn/start" or "native/turn/steer" or "claude/user/send-now")) return false;
        var rows = Rows("SELECT payload,result FROM operations WHERE id=? AND kind=? AND status='confirmed'", intent.Operation, intent.Kind);
        if (rows.Count != 1) return false;
        try
        {
            using var payload = JsonDocument.Parse(rows[0][0]!); using var result = JsonDocument.Parse(rows[0][1]!);
            if (intent.Kind == "claude/user/send-now")
                return payload.RootElement.GetProperty("SessionId").GetString() == intent.Binding.ThreadId &&
                    ClaudeDelivery.Confirmed(this, intent.Operation, intent.Binding.ThreadId, payload.RootElement.GetProperty("uuid").GetString()!);
            var parameters = payload.RootElement.GetProperty("parameters");
            if (parameters.GetProperty("threadId").GetString() != intent.Binding.ThreadId) return false;
            if (intent.Kind == "native/turn/steer")
            { NativeEventView.VerifySteer(result.RootElement, parameters.GetProperty("expectedTurnId").GetString()!); return true; }
            var turn = result.RootElement.GetProperty("turn").GetProperty("id").GetString();
            return !string.IsNullOrWhiteSpace(turn) && turn.Length <= 200 && !turn.Any(char.IsControl);
        }
        catch (Exception e) when (ShapeError(e) || e is InvalidDataException) { return false; }
    }
}
