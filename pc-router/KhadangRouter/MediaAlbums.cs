using System.Text.Json;

namespace KhadangRouter;

public sealed partial class Router
{
    private sealed record AlbumPart(long Id, JsonElement Message);
    private sealed record AlbumKey(TopicAddress Address, long Sender, string Group, Binding Binding);
    private readonly Dictionary<AlbumKey, (int Count, long Since)> collectingAlbums = new();

    private AlbumKey? AlbumIdentity(JsonElement update)
    {
        if (update.ValueKind != JsonValueKind.Object || !update.TryGetProperty("message", out var m) ||
            m.ValueKind != JsonValueKind.Object || !m.TryGetProperty("media_group_id", out var group) ||
            group.ValueKind != JsonValueKind.String || group.GetString() is not { Length: > 0 and <= 128 } id ||
            !m.TryGetProperty("message_id", out var mid) || mid.ValueKind != JsonValueKind.Number || !mid.TryGetInt64(out _) ||
            !policy.TryAddress(m, out var address) || !sessions.TryGetValue(address, out var session) ||
            !TopicConversationAccess.Allows(policy, ledger, m)) return null;
        return new(address, m.GetProperty("from").GetProperty("id").GetInt64(), id, session.Binding);
    }

    private void DispatchPending(CancellationToken stop)
    {
        var groups = ledger.Pending().ToLookup(item => AlbumIdentity(item.Payload));
        foreach (var missing in collectingAlbums.Keys.Where(key => !groups.Contains(key)).ToArray())
            collectingAlbums.Remove(missing);
        foreach (var group in groups)
        {
            if (group.Key is not { } key)
            {
                foreach (var item in group)
                    if (ledger.Claim(item.Id)) handlers[item.Id] = Handle(item.Id, item.Payload, stop);
                continue;
            }
            var parts = group.Select(item => new AlbumPart(item.Id, item.Payload.GetProperty("message")))
                .OrderBy(part => part.Message.GetProperty("message_id").GetInt64()).ToArray();
            // The Bot API has no album terminator. Gather across polls for a
            // quiet second. A later part still gets an independent delivery.
            var now = Environment.TickCount64;
            if (!collectingAlbums.TryGetValue(key, out var window) || parts.Length != window.Count)
                collectingAlbums[key] = window = (parts.Length, now);
            if (parts.Length < 10 && now - window.Since < 1000) continue;
            collectingAlbums.Remove(key);
            var first = group.First(item => item.Id == parts[0].Id);
            ledger.Transaction(() => {
                foreach (var part in parts)
                    if (!ledger.Claim(part.Id)) throw new InvalidOperationException("Album claim changed");
                // One native intent for the group. Followers point to its
                // durable result, including unknown/late ACK after a restart.
                foreach (var part in parts.Skip(1))
                    ledger.Finish(part.Id, "album-member/" + first.Id);
            });
            handlers[first.Id] = HandleInput(first.Id, first.Payload, stop, parts, key.Binding);
        }
    }

    private static string AlbumCaption(IReadOnlyList<AlbumPart> parts)
    {
        if (parts.Count > 10) throw new AttachmentFailure("Telegram album exceeds ten members");
        var captions = new List<string>();
        foreach (var part in parts)
        {
            var message = part.Message;
            if (Attachments.References(message).Count != 1 || message.TryGetProperty("text", out _))
                throw new AttachmentFailure("Unsupported album member");
            if (!message.TryGetProperty("caption", out var caption)) continue;
            if (caption.ValueKind != JsonValueKind.String) throw new AttachmentFailure("Invalid album caption");
            if (!string.IsNullOrEmpty(caption.GetString()))
                captions.Add($"Message {message.GetProperty("message_id").GetInt64()}: {caption.GetString()}");
        }
        return string.Join("\n", captions);
    }

    private async Task<IReadOnlyList<StagedAttachment>> StageInput(long id, JsonElement message, Binding binding,
        IReadOnlyList<AlbumPart>? album, CancellationToken stop)
    {
        if (album == null) return await attachmentStore.Stage(message, binding, id, stop);
        var files = new List<StagedAttachment>(album.Count);
        foreach (var part in album)
        {
            var staged = await attachmentStore.Stage(part.Message, binding, part.Id, stop);
            if (staged.Count != 1) throw new AttachmentFailure("Album member did not stage completely");
            files.Add(staged[0]);
        }
        return files;
    }
}
