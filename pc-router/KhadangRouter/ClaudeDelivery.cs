using System.Text.Json;
using System.Text.Json.Nodes;

namespace KhadangRouter;

public sealed class ClaudeDeliveryTimeout(string operation, string session, string uuid)
    : TimeoutException("Claude input acknowledgement timed out; awaiting exact receipt, never replay")
{
    public string Operation { get; } = operation;
    public string Session { get; } = session;
    public string Uuid { get; } = uuid;
}

// Only a matching native primary-user echo can resolve an uncertain send.
// This is receipt reconciliation, not a retry or an arbitrary ledger confirm.
internal static class ClaudeDelivery
{
    internal static string Key(string operation) => "claude/delivery/" + operation;
    internal static string? ConfirmReplay(Ledger ledger, string session, JsonElement frame)
    {
        if (!frame.TryGetProperty("type", out var type) || type.GetString() != "user" ||
            !frame.TryGetProperty("uuid", out var uuid) || uuid.ValueKind != JsonValueKind.String ||
            !Guid.TryParseExact(uuid.GetString(), "D", out _) ||
            !frame.TryGetProperty("session_id", out var pin) || pin.GetString() != session ||
            !frame.TryGetProperty("parent_tool_use_id", out var parent) || parent.ValueKind != JsonValueKind.Null ||
            !frame.TryGetProperty("message", out var message) || !message.TryGetProperty("role", out var role) || role.GetString() != "user" ||
            !message.TryGetProperty("content", out var content)) return null;
        string? operation = null;
        ledger.Transaction(() => {
            var rows = ledger.Query("SELECT id,payload,status FROM operations WHERE kind='claude/user/send-now' AND status IN ('attempting','unknown','confirmed') AND json_extract(payload,'$.SessionId')=? AND json_extract(payload,'$.uuid')=?", session, uuid.GetString());
            if (rows.Count == 0) return; // App input or an already-confirmed echo.
            if (rows.Count != 1) throw new InvalidDataException("Ambiguous Claude input receipt");
            using var expected = JsonDocument.Parse(rows[0][1]!);
            if (!JsonNode.DeepEquals(JsonNode.Parse(expected.RootElement.GetProperty("content").GetRawText()), JsonNode.Parse(content.GetRawText())))
                throw new InvalidDataException("Claude input receipt content changed");
            operation = rows[0][0]!;
            if (rows[0][2] == "confirmed")
            {
                if (!Confirmed(ledger, operation, session, uuid.GetString()!)) operation = null;
                return;
            }
            var receipt = JsonSerializer.SerializeToElement(new { SessionId = session, uuid = uuid.GetString(), receipt = "native-user-replay", late = rows[0][2] == "unknown", at = DateTimeOffset.UtcNow });
            ledger.Exec("UPDATE operations SET status='confirmed',result=? WHERE id=? AND kind='claude/user/send-now' AND status IN ('attempting','unknown')", receipt.GetRawText(), operation);
            ledger.Put(Key(operation), receipt);
        });
        return operation;
    }
    internal static bool Confirmed(Ledger ledger, string operation, string session, string uuid) =>
        ledger.Get(Key(operation)) is { } proof && proof.GetProperty("SessionId").GetString() == session &&
        proof.GetProperty("uuid").GetString() == uuid && proof.GetProperty("receipt").GetString() == "native-user-replay" &&
        ledger.Query("SELECT id FROM operations WHERE id=? AND kind='claude/user/send-now' AND status='confirmed' AND json_extract(payload,'$.SessionId')=? AND json_extract(payload,'$.uuid')=?", operation, session, uuid).Count == 1;
}
