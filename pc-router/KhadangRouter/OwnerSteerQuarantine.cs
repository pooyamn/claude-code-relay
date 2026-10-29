using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace KhadangRouter;

public sealed partial class Ledger
{
    // Protected owner maintenance only. This is NOT a delivery ACK or retry
    // instruction. It isolates one reviewed, terminal old turn from ordinary
    // input, retaining its unknown receipt and the stricter lifecycle fence.
    internal bool OwnerSteerQuarantined(string operation, Binding binding, string payload)
    {
        if (binding.Backend != "codex" || binding.Runtime != "linux" ||
            Get("owner-steer-quarantine/" + operation) is not { } review) return false;
        try
        {
            using var document = JsonDocument.Parse(payload);
            var parameters = document.RootElement.GetProperty("parameters");
            var turn = parameters.GetProperty("expectedTurnId").GetString();
            var terminal = review.GetProperty("terminalTurn");
            return !string.IsNullOrWhiteSpace(turn) &&
                parameters.GetProperty("threadId").GetString() == binding.ThreadId &&
                review.GetProperty("schema").GetString() == "ccrelay.owner_steer_quarantine.v1" &&
                review.GetProperty("operation").GetString() == operation &&
                review.GetProperty("binding").Deserialize<Binding>() == binding &&
                review.GetProperty("payloadSha256").GetString() == Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(payload))).ToLowerInvariant() &&
                review.GetProperty("action").GetString() == "retain-unknown-no-replay" &&
                review.GetProperty("deliveryConfirmed").ValueKind == JsonValueKind.False &&
                review.GetProperty("replay").ValueKind == JsonValueKind.False &&
                terminal.GetProperty("id").GetString() == turn && terminal.GetProperty("status").GetString() == "completed" &&
                review.GetProperty("observedThread").GetString() == binding.ThreadId &&
                review.GetProperty("observedWorkspace").GetString() == binding.Workspace &&
                review.GetProperty("currentTurn").ValueKind == JsonValueKind.String &&
                !string.IsNullOrWhiteSpace(review.GetProperty("currentTurn").GetString()) &&
                review.GetProperty("currentTurn").GetString() != turn &&
                !string.IsNullOrWhiteSpace(review.GetProperty("ownerApproval").GetString()) &&
                review.GetProperty("evidenceSha256").GetString() is { Length: 64 } evidence && evidence.All(Uri.IsHexDigit);
        }
        catch (Exception error) when (error is JsonException or InvalidOperationException or KeyNotFoundException or FormatException or ArgumentException)
        { return false; }
    }
}
