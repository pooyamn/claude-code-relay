using System.Text.Json;
using System.Text.Json.Serialization;

namespace KhadangRouter;

// Protected local authorization, not a new shared native-host policy schema.
// Pin the existing topic AND workspace, retaining access across owner tool
// switches but never transferring it to a different project/folder.
internal sealed record TopicConversationAccess(string Schema, long OwnerId, long Chat, int Topic, string Workspace, long[] ParticipantIds)
{
    internal const string Version = "ccrelay.topic_conversation_access.v1";
    internal static string Key(TopicAddress address) => $"topic-participants/{address.Chat}/{address.Topic}";
    internal static bool Allows(RouterPolicy policy, Ledger ledger, JsonElement message)
    {
        if (policy.ConversationMessage(message)) return true;
        if (!policy.TryAddress(message, out var address) || address.Topic <= 0) return false;
        var binding = ledger.Bindings().SingleOrDefault(b => b.Address == address);
        if (binding == null || ledger.Get(Key(address)) is not { } value) return false;
        try
        {
            var grant = value.Deserialize<TopicConversationAccess>(new JsonSerializerOptions { UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow });
            if (grant == null || grant.Schema != Version || grant.OwnerId != policy.OwnerId || grant.Chat != address.Chat ||
                grant.Topic != address.Topic || grant.Workspace != binding.Workspace || grant.ParticipantIds == null ||
                grant.ParticipantIds.Length > 64 || grant.ParticipantIds.Any(id => id <= 0 || id > 4_503_599_627_370_495L || id == policy.OwnerId) ||
                grant.ParticipantIds.Distinct().Count() != grant.ParticipantIds.Length) return false;
            return policy.ConversationMessage(message, grant.ParticipantIds);
        }
        catch (Exception error) when (error is JsonException or InvalidOperationException or KeyNotFoundException or ArgumentException) { return false; }
    }
}
