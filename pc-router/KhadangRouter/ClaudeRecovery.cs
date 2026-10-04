using System.Text.Json;

namespace KhadangRouter;

// Protected owner opt-in only. Renew history evidence, never replay a turn,
// permission answer, external action or initial Telegram send. A failed launch
// remains stopped across supervisor generations until explicit reconciliation.
public sealed partial class LinuxClaudeTopics
{
    internal static string RecoveryKey(Binding binding) => "claude/recovery/" + binding.ThreadId;
    private async Task<IClaudeNative> Recover(Binding binding, CancellationToken stop)
    {
        lock (attempted)
            if (!attempted.Add(binding.ThreadId)) throw new InvalidOperationException("Claude recovery already attempted in this generation");
        var prior = ledger.Get(RecoveryKey(binding)) ?? ledger.Get(CheckpointKey(binding));
        string digest; string? model;
        if (prior is { } saved)
        {
            if (saved.GetProperty("binding").Deserialize<Binding>() != binding)
                throw new InvalidDataException("Recovery checkpoint belongs to another binding");
            if (ledger.Get(RecoveryKey(binding)) != null && saved.GetProperty("state").GetString() != "connected")
                throw new InvalidOperationException("Unconfirmed Claude recovery launch; reconcile, never retry automatically");
            digest = saved.GetProperty("sha256").GetString()!;
            model = saved.TryGetProperty("model", out var selectedModel) ? selectedModel.GetString() : null;
        }
        else { var checkpoint = runtime!.For(binding); digest = checkpoint.Sha256; model = checkpoint.Model; }
        RequireRecoverable(binding);
        var renewed = await renew(binding, digest, model, stop);
        if (!LinuxClaudeRuntime.Digest(renewed)) throw new InvalidDataException("Exact renewed checkpoint digest required");
        // Recheck and commit intent before launch. If the file write and receipt
        // are interrupted, the pinned hash mismatch also fails closed.
        ledger.Transaction(() => {
            RequireRecoverable(binding);
            ledger.Put(RecoveryKey(binding), new { binding, sha256 = renewed, model, previousSha256 = digest,
                state = "launch-attempted", at = DateTimeOffset.UtcNow });
        });
        var channel = await openRenewed(binding, renewed, model, stop);
        try
        {
            var native = new ClaudeNativeStream(channel, ledger, binding.ThreadId);
            ledger.Put(RecoveryKey(binding), new { binding, sha256 = renewed, model, previousSha256 = digest,
                state = "connected", at = DateTimeOffset.UtcNow });
            return native;
        }
        catch { await channel.DisposeAsync(); throw; }
    }
    private void RequireRecoverable(Binding binding)
    {
        if (ledger.Unknown != 0 || ledger.Query("SELECT id FROM operations WHERE status='attempting' AND kind<>'telegram/editMessageText'").Count != 0 ||
            ledger.Query("SELECT id FROM updates WHERE status='dispatching'").Count != 0 || ledger.Get("claude/reset/" + binding.ThreadId) != null ||
            ledger.Query("SELECT key FROM meta WHERE substr(key,1,?)=? AND json_extract(value,'$.status')='pending'",
                ("claude/request/" + binding.ThreadId + "/").Length, "claude/request/" + binding.ThreadId + "/").Count != 0)
            throw new InvalidOperationException("Uncertain action, pending approval or reset; Claude recovery held without replay");
        if (ledger.Get("bubble/" + binding.ThreadId) is not { } bubble) return;
        if (bubble.GetProperty("chat").GetInt64() != binding.Chat || bubble.GetProperty("topic").GetInt32() != binding.Topic ||
            bubble.GetProperty("backend").GetString() != "claude" || bubble.GetProperty("runtime").GetString() != "linux")
            throw new InvalidDataException("Recovery bubble belongs to another binding");
        if (bubble.GetProperty("busy").GetBoolean() || bubble.GetProperty("sendUnknown").GetBoolean() ||
            bubble.GetProperty("held").GetBoolean() && bubble.GetProperty("status").GetString() != "Held — Claude stream disconnected" ||
            bubble.TryGetProperty("claudeState", out var state) && state.GetString() != "idle" ||
            bubble.TryGetProperty("pendingResponses", out var responses) && responses.GetArrayLength() != 0 ||
            bubble.TryGetProperty("pendingAnswers", out var answers) && answers.GetArrayLength() != 0 ||
            bubble.TryGetProperty("finalAnswer", out var answer) && answer.GetProperty("Parts").EnumerateArray().Any(p => p.GetProperty("SendUnknown").GetBoolean()))
            throw new InvalidOperationException("Interrupted work or uncertain response; Claude recovery held without replay");
    }
    private async Task<string> RenewCheckpoint(Binding target, string digest, string? model, CancellationToken stop)
    {
        var oldRuntime = For(target, digest, model);
        using var process = WindowsOwnerProcess.StartLinuxClaude(policy with { LinuxClaude = oldRuntime }, policy.WorkspaceRoot + "\\lg-magic", target, snapshot: true);
        var owner = process.ObserveOwner(); LinuxClaudeChannel.ValidateOwner(owner, policy.OwnerSid);
        var line = await process.Output.ReadLineAsync(stop).AsTask().WaitAsync(TimeSpan.FromSeconds(15), stop)
            ?? throw new IOException("Native Claude recovery observation missing");
        if (line.Length > 65536 || process.ObserveOwner() != owner) throw new InvalidDataException("Claude recovery owner/generation changed");
        var history = RecoveryHistory(line, target);
        return WriteCheckpoint(runtime!.PackageRoot + "\\handoff-" + target.ThreadId + ".json", new {
            schema = "ccrelay.personal_claude_handoff.v1", session_id = target.ThreadId, workspace = target.Workspace,
            source_writer = "quiesced", uncertain_actions = Array.Empty<string>(), history, profile = "/Users/pouya/.claude"
        }, create: false);
    }
    internal static JsonElement RecoveryHistory(string frame, Binding target)
    {
        using var document = JsonDocument.Parse(frame); var value = document.RootElement;
        var fields = new[] { "type", "uid", "session_id", "workspace", "source_writer", "model_inference", "history", "history_quiescent" };
        if (value.ValueKind != JsonValueKind.Object || !value.EnumerateObject().Select(p => p.Name).Order().SequenceEqual(fields.Order()) ||
            value.GetProperty("type").GetString() != "ccrelay_claude_snapshot" || value.GetProperty("uid").GetInt32() != 1000 ||
            value.GetProperty("session_id").GetString() != target.ThreadId || value.GetProperty("workspace").GetString() != target.Workspace ||
            value.GetProperty("source_writer").GetString() != "quiesced" || value.GetProperty("model_inference").ValueKind != JsonValueKind.False ||
            value.GetProperty("history_quiescent").ValueKind != JsonValueKind.True || value.GetProperty("history").ValueKind != JsonValueKind.Object)
            throw new InvalidDataException("Exact idle native history required for recovery; no fresh fallback");
        var history = value.GetProperty("history");
        var path = "/Users/pouya/.claude/projects/" + System.Text.RegularExpressions.Regex.Replace(target.Workspace, "[/\\.]", "-") + "/" + target.ThreadId + ".jsonl";
        if (!history.EnumerateObject().Select(p => p.Name).Order().SequenceEqual(new[] { "bytes", "path", "sha256" }) ||
            history.GetProperty("path").GetString() != path || !history.GetProperty("bytes").TryGetInt64(out var bytes) || bytes <= 0 ||
            !LinuxClaudeRuntime.Digest(history.GetProperty("sha256").GetString())) throw new InvalidDataException("Exact existing transcript bytes required");
        return history.Clone();
    }
}
