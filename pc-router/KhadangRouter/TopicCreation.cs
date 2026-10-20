using System.Diagnostics;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace KhadangRouter;

public sealed record TopicCreateRequest(string Name, string? Model)
{
    public static bool TryParse(string text, string bot, out TopicCreateRequest? request)
    {
        request = null;
        var value = text.Trim();
        // Intentionally narrow natural-language shortcut. Other requests still
        // reach the agent; arbitrary quoted/forwarded instructions are not commands.
        var natural = Regex.Match(value, "\\AMake\\s+(?:a\\s+)?(?:new\\s+)?topic\\s+[\"“](?<name>[^\"”]+)[\"”]\\s+(?:Using\\s+)?codex\\s*,?\\s*(?:(?<model>[a-zA-Z0-9.-]+)\\s+model)?\\s*\\z", RegexOptions.IgnoreCase);
        string name, model;
        if (natural.Success) { name = natural.Groups["name"].Value; model = natural.Groups["model"].Value; }
        else
        {
            var command = Regex.Match(value, @"\A/topic(?:@(?<bot>[A-Za-z0-9_]+))?\s+(?<body>[^\r\n]+)\z", RegexOptions.IgnoreCase);
            if (!command.Success || command.Groups["bot"].Success && !command.Groups["bot"].Value.Equals(bot, StringComparison.OrdinalIgnoreCase)) return false;
            var body = command.Groups["body"].Value;
            var settings = Regex.Match(body, @"\s+--model\s+(?<model>[a-zA-Z0-9.-]+)\s*\z");
            model = settings.Groups["model"].Value;
            name = (settings.Success ? body[..settings.Index] : body).Trim().Trim('"', '“', '”');
        }
        if (name.Length is < 1 or > 128 || name.Any(char.IsControl) || name.Contains("--", StringComparison.Ordinal)) return false;
        request = new(name, model.Length == 0 ? null : model.Equals("sol6.1", StringComparison.OrdinalIgnoreCase) ? "gpt-6.1-sol" : model);
        return true;
    }
    public string Slug => Regex.Replace(Name.ToLowerInvariant(), "[^a-z0-9]+", "-").Trim('-');
}

public sealed record TopicCreateResult(string Phase, Binding Binding, string Model, double ElapsedMs,
    Dictionary<string, double> Timings)
{
    public string Link => "https://t.me/c/" + Binding.Chat.ToString()[4..] + "/" + Binding.Topic;
}

// Runs inside the existing credential-owning router and its ALREADY attested
// limited-owner native transport. No SSH, new privilege broker, service restart,
// account login, project-work turn, tool switch or competing Telegram poller.
// One minimal ready-and-wait turn registers a genuinely listable native thread.
public sealed class TopicProvisioner(RouterPolicy policy, Ledger ledger, IBot bot, INative native,
    Func<Binding, CancellationToken, Task> activate)
{
    private readonly SemaphoreSlim gate = new(1, 1);
    public async Task<TopicCreateResult> Create(long updateId, JsonElement message, Binding source,
        TopicCreateRequest request, CancellationToken stop)
    {
        if (updateId < 0 || !policy.OwnerMessage(message) || !policy.TryAddress(message, out var address) || address != source.Address ||
            !policy.TryChat(address.Chat, out var forum) || !forum || policy.LinuxWorkspaceRoot != LinuxCodexRuntime.WorkspaceRoot ||
            request.Name.Length is < 1 or > 128 || request.Name.Any(char.IsControl) || request.Slug.Length is < 1 or > 128)
            throw new InvalidDataException("Exact owner, requesting forum and project name required");
        // Prove the actual retained owner update, not an assertion by an agent.
        var rows = ledger.Query("SELECT payload FROM updates WHERE id=?", updateId);
        if (rows.Count != 1 || JsonDocument.Parse(rows[0][0]!).RootElement.GetProperty("message").GetRawText() != message.GetRawText())
            throw new InvalidDataException("Original owner update differs");
        await gate.WaitAsync(stop);
        var watch = Stopwatch.StartNew(); var timings = new Dictionary<string, double>();
        var key = "topic-create/" + address.Chat + "/" + updateId;
        var workspace = LinuxCodexRuntime.WorkspaceRoot + "/" + request.Slug;
        string? thread = null; int? topic = null;
        void Save(string phase) => ledger.Put(key, new { phase, source, request, workspace, thread, topic,
            elapsedMs = watch.Elapsed.TotalMilliseconds, timings, at = DateTimeOffset.UtcNow });
        async Task<JsonElement> Native(string phase, string method, object parameters, bool effect = true)
        {
            Save(phase); var before = watch.Elapsed.TotalMilliseconds;
            var result = await native.Call(method, parameters, stop, effect);
            timings[phase] = watch.Elapsed.TotalMilliseconds - before; return result;
        }
        try
        {
            if (ledger.Get(key) is { } retained)
            {
                if (retained.GetProperty("phase").GetString() == "ready")
                    return retained.GetProperty("result").Deserialize<TopicCreateResult>()!;
                throw new InvalidOperationException("Retained topic request needs reconciliation; no creation retry");
            }
            var existing = ledger.Bindings(); policy.ValidateBindings(existing);
            if (!existing.Contains(source)) throw new InvalidDataException("Source binding changed");
            var matches = existing.Where(b => b.Chat == address.Chat && b.Name == request.Name).ToArray();
            if (matches.Length > 0)
            {
                if (matches.Length != 1 || matches[0].Backend != "codex" || matches[0].Workspace != workspace)
                    throw new InvalidDataException("Existing topic differs; no rebind or duplicate");
                var read = await native.Call("thread/read", new { threadId = matches[0].ThreadId, includeTurns = false }, stop, effect: false);
                var model = read.GetProperty("thread").GetProperty("model").GetString()!;
                if (request.Model != null && request.Model != model) throw new InvalidDataException("Existing topic has another model; no implicit switch");
                return new("ready-existing", matches[0], model, watch.Elapsed.TotalMilliseconds, timings);
            }
            if (existing.Any(b => b.Workspace == workspace)) throw new InvalidDataException("Project folder already belongs to another topic");
            // Ignore scoped output holds in OTHER topics; never ignore unknown
            // native mutations, intake or unclassified/unscoped effects.
            if (ledger.InputUnknown(source with { Topic = int.MaxValue }) != 0)
                throw new InvalidOperationException("Uncertain native/intake effect; preserve receipts");
            Save("preflight");
            var before = watch.Elapsed.TotalMilliseconds;
            var chatTask = bot.Call("getChat", new { chat_id = address.Chat }, stop);
            var rightsTask = bot.Call("getChatMember", new { chat_id = address.Chat, user_id = policy.BotId }, stop);
            var modelsTask = native.Call("model/list", new { }, stop, effect: false);
            await Task.WhenAll(chatTask, rightsTask, modelsTask);
            var chat = await chatTask; var rights = await rightsTask;
            if (chat.GetProperty("id").GetInt64() != address.Chat || !chat.GetProperty("is_forum").GetBoolean() ||
                rights.GetProperty("status").GetString() != "administrator" || !rights.GetProperty("can_manage_topics").GetBoolean())
                throw new InvalidDataException("Exact forum and Manage Topics required");
            var models = (await modelsTask).GetProperty("data").EnumerateArray().ToArray();
            var selected = request.Model == null ? models.FirstOrDefault(m => m.TryGetProperty("isDefault", out var d) && d.ValueKind == JsonValueKind.True) :
                models.FirstOrDefault(m => m.GetProperty("model").GetString() == request.Model || m.GetProperty("id").GetString() == request.Model);
            if (selected.ValueKind == JsonValueKind.Undefined || selected.TryGetProperty("hidden", out var hidden) && hidden.ValueKind == JsonValueKind.True)
                throw new InvalidDataException("Requested model absent from the live native catalog");
            var selectedModel = selected.GetProperty("model").GetString()!;
            timings["preflight"] = watch.Elapsed.TotalMilliseconds - before;
            var prepared = await Native("workspace", "ccrelay/workspace/prepare", new { workspace });
            if (prepared.GetProperty("workspace").GetString() != workspace || prepared.GetProperty("uid").GetInt32() != 1000 ||
                !prepared.GetProperty("credentialDenied").GetBoolean()) throw new InvalidDataException("Limited-owner workspace attestation required");
            var started = await Native("starting-native", "thread/start", new { cwd = workspace, model = selectedModel,
                approvalPolicy = policy.NativeApprovalPolicy, approvalsReviewer = "user", permissions = policy.NativePermissionProfile,
                allowProviderModelFallback = false });
            thread = started.GetProperty("thread").GetProperty("id").GetString();
            if (!Guid.TryParseExact(thread, "D", out _) || started.GetProperty("cwd").GetString() != workspace ||
                started.GetProperty("model").GetString() != selectedModel || started.GetProperty("approvalPolicy").GetString() != policy.NativeApprovalPolicy)
                throw new InvalidDataException("Fresh native identity/model/permissions mismatch");
            var checkpoint = "[Enrollment checkpoint; not a request to start work.] Owner requested a fresh Codex session for " + request.Name +
                " in forum " + address.Chat + ". Workspace: " + workspace + ". Wait for the next human input. Do not start project work or a goal.";
            await Native("checkpointing", "thread/inject_items", new { threadId = thread, items = new[] { new {
                type = "message", role = "user", content = new[] { new { type = "input_text", text = checkpoint } } } } });
            await Native("naming-native", "thread/name/set", new { threadId = thread, name = request.Name });
            var readback = (await Native("reading-native", "thread/read", new { threadId = thread, includeTurns = false }, effect: false)).GetProperty("thread");
            if (readback.GetProperty("id").GetString() != thread || readback.GetProperty("cwd").GetString() != workspace ||
                readback.GetProperty("model").GetString() != selectedModel) throw new InvalidDataException("Exact native readback required");
            var persisted = await Native("verifying-checkpoint", "ccrelay/checkpoint/verify", new { workspace, threadId = thread,
                path = readback.GetProperty("path").GetString(), checkpoint }, effect: false);
            if (!persisted.GetProperty("persisted").GetBoolean() || persisted.GetProperty("threadId").GetString() != thread ||
                persisted.GetProperty("workspace").GetString() != workspace) throw new InvalidDataException("Durable inert checkpoint required");
            Save("creating-topic"); before = watch.Elapsed.TotalMilliseconds;
            var created = await bot.Call("createForumTopic", new { chat_id = address.Chat, name = request.Name }, stop, effect: true);
            topic = created.GetProperty("message_thread_id").GetInt32();
            timings["telegram-create"] = watch.Elapsed.TotalMilliseconds - before;
            if (topic <= 0 || created.GetProperty("name").GetString() != request.Name) throw new InvalidDataException("Telegram topic identity differs");
            Save("topic-created");
            var binding = new Binding(address.Chat, topic.Value, request.Name, workspace, thread!, "codex", "linux");
            // Activation owns the single protected ledger commit and the live
            // in-memory registration. It must not touch existing sessions.
            await activate(binding, stop);
            var published = await Native("publishing-catalog", "ccrelay/catalog/add", binding, effect: false);
            if (!published.GetProperty("published").GetBoolean() || published.GetProperty("threadId").GetString() != thread)
                throw new InvalidDataException("Routing catalog publication unconfirmed; retain binding");
            // A raw history checkpoint is resumable but is NOT a user-turn
            // event; native Remote lists omit such empty threads. A minimal
            // owner-authorized registration turn makes the SAME session visible.
            await Native("registering-remote", "turn/start", new { threadId = thread, input = new[] { new {
                type = "text", text = "Topic registration for Pouya: " + request.Name + ". Folder and Telegram binding are ready. " +
                    "Reply only that this topic is ready, then wait for my next message. Do not use tools, start a goal, delegate, or perform project work." } } });
            bool listed = false;
            for (int check = 0; check < 10; check++)
            {
                var list = await Native("verifying-remote-list", "thread/list", new { cwd = workspace, limit = 30, useStateDbOnly = true }, effect: false);
                listed = list.GetProperty("data").EnumerateArray().Any(t => t.GetProperty("id").GetString() == thread &&
                    t.GetProperty("name").GetString() == request.Name && t.GetProperty("cwd").GetString() == workspace);
                if (listed) break;
                await Task.Delay(200, stop); // Repeatable reads only, never another registration turn.
            }
            if (!listed) throw new InvalidOperationException("Topic bound, but remote-list visibility unconfirmed; do not recreate");
            var answer = new TopicCreateResult("ready", binding, selectedModel, watch.Elapsed.TotalMilliseconds, timings);
            ledger.Put(key, new { phase = "ready", source, request, result = answer, at = DateTimeOffset.UtcNow });
            return answer;
        }
        catch
        {
            // Preserve the last exact phase, thread/topic and effect receipts.
            // Caller can report the retained request; no automatic replay.
            throw;
        }
        finally { gate.Release(); }
    }
}
