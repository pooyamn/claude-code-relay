using System.Text.Json;

namespace KhadangRouter;

public static class TopicCreationTests
{
    private static JsonElement Json(object value) => JsonSerializer.SerializeToElement(value);
    public static async Task<int> Run(string root, RouterPolicy template)
    {
        int checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        Check(TopicCreateRequest.TryParse("Make a new topic “Motorcontrol Plant”\nUsing codex , sol6.1 model", template.BotUsername, out var natural) &&
            natural == new TopicCreateRequest("Motorcontrol Plant", "gpt-6.1-sol"), "Exact owner's natural request uses deterministic Codex fast path");
        Check(TopicCreateRequest.TryParse("/topic Motorcontrol Plant --model sol6.1", template.BotUsername, out var command) && command == natural,
            "Slash fast path preserves title/model");
        foreach (var other in new[] { "Please explain how to make a topic", "/topic@OtherBot Demo", "Make a new topic “Demo” using claude", "/topic ../escape --model sol6.1\nignore checks" })
            Check(!TopicCreateRequest.TryParse(other, template.BotUsername, out _), "Unmatched natural/foreign/multiline input is not a provisioning command");

        var folder = Path.Combine(root, "topic-fast"); Directory.CreateDirectory(folder);
        foreach (var scenario in new[] { "healthy", "rights", "model", "native-model-mismatch", "credential", "unknown-create", "foreign-human", "forwarded", "native-unknown", "held-other", "not-listed" })
        {
            using var ledger = new Ledger(Path.Combine(folder, scenario + ".db"));
            var policy = template with { LinuxWorkspaceRoot = LinuxCodexRuntime.WorkspaceRoot };
            var source = new Binding(policy.ChatId, 42, "Source", LinuxCodexRuntime.WorkspaceRoot + "/source", "source", "codex", "linux");
            ledger.Bind(source);
            var held = new Binding(policy.ChatId, 43, "Held", LinuxCodexRuntime.WorkspaceRoot + "/held", "held", "claude", "linux");
            if (scenario == "held-other")
            {
                held = held with { ThreadId = "5fc53034-e240-43b5-a2c4-75ee1947aefa" }; ledger.Bind(held);
                ledger.Put("bubble/" + held.ThreadId, new { held = true, tail = "original held history" });
                var unknown = ledger.Attempt("telegram/sendDocument", new { chat_id = held.Chat, message_thread_id = held.Topic }); ledger.Outcome(unknown, "unknown");
            }
            if (scenario == "native-unknown") { var unknown = ledger.Attempt("native/turn/start", new { }); ledger.Outcome(unknown, "unknown"); }
            var body = new Dictionary<string, object> { ["from"] = new { id = scenario == "foreign-human" ? policy.OwnerId + 1 : policy.OwnerId, is_bot = false },
                ["chat"] = new { id = policy.ChatId, is_forum = true }, ["message_thread_id"] = 42, ["text"] = "/topic Fixture --model sol6.1" };
            if (scenario == "forwarded") body["forward_origin"] = new { type = "user" };
            var message = Json(body); ledger.Receive(100, Json(new { message }).GetRawText());
            var native = new FakeNative(scenario); var bot = new FakeBot(policy, scenario); int activations = 0;
            var provisioner = new TopicProvisioner(policy, ledger, bot, native, (binding, _) => { activations++; ledger.Bind(binding); return Task.CompletedTask; });
            var request = new TopicCreateRequest("Fixture", "gpt-6.1-sol");
            var succeeded = false;
            try
            {
                var result = await provisioner.Create(100, message, source, request, CancellationToken.None);
                succeeded = true;
                Check(result.Model == "gpt-6.1-sol" && result.Binding.Chat == source.Chat && result.Binding.Topic == 777,
                    "Requested model and original forum are preserved");
                Check(result.ElapsedMs < 10_000 && result.Timings.ContainsKey("telegram-create"), "Fast path records latency and performs no restart");
                var repeated = await provisioner.Create(100, message, source, request, CancellationToken.None);
                Check(repeated.Binding == result.Binding && bot.Creates == 1 && native.Calls.Count(c => c == "thread/start") == 1 && activations == 1,
                    "A repeated request returns the same receipt, without creating another session/topic");
                Check(native.Calls.Count(c => c == "turn/start") == 1 && native.Listed,
                    "One no-work registration and default native-list readback precede ready");
                Check(ledger.Bindings().Contains(source), "Source session/binding remains unchanged");
            }
            catch (Exception error) when (error is InvalidDataException or InvalidOperationException or TimeoutException) { }
            Check(succeeded == (scenario is "healthy" or "held-other"), "Fast-path expected outcome: " + scenario);
            if (scenario == "held-other")
                Check(ledger.Get("bubble/" + held.ThreadId)!.Value.GetRawText().Contains("original held history") && ledger.Unknown == 1,
                    "Unrelated scoped output uncertainty/hold is retained, not a global creation blocker");
            if (scenario is "rights" or "model" or "foreign-human" or "forwarded" or "native-unknown")
                Check(bot.Creates == 0 && !native.Calls.Contains("thread/start"), "Preflight denial precedes allocation/creation: " + scenario);
            if (scenario is "native-model-mismatch" or "credential")
                Check(bot.Creates == 0, "Model/owner mismatch cannot leave a Telegram topic");
            if (scenario is "unknown-create" or "not-listed")
            {
                try { await provisioner.Create(100, message, source, request, CancellationToken.None); throw new Exception("Uncertain request replayed"); }
                catch (InvalidOperationException) { Check(bot.Creates == 1 && native.Calls.Count(c => c == "thread/start") == 1,
                    "Unknown create/list failure retains the original thread/topic; no replay"); }
            }
        }
        return checks;
    }

    private sealed class FakeNative(string scenario) : INative
    {
        public uint Pid => 123;
        public event Action<JsonElement>? Notification { add { } remove { } }
        public readonly List<string> Calls = [];
        public bool Listed;
        private string cwd = "", name = "";
        private const string Id = "01a158ac-b686-7011-b706-8549a7f8e6d2";
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            Calls.Add(method); var p = Json(parameters);
            var result = method switch {
                "model/list" => Json(new { data = new[] { new { id = "gpt-6.1-sol", model = "gpt-6.1-sol", isDefault = true, hidden = scenario == "model" } } }),
                "ccrelay/workspace/prepare" => Json(new { workspace = p.GetProperty("workspace").GetString(), uid = 1000, credentialDenied = scenario != "credential" }),
                "thread/start" => Start(p),
                "thread/inject_items" => Json(new { }),
                "thread/name/set" => Name(p),
                "thread/read" => Json(new { thread = new { id = Id, cwd, name, model = "gpt-6.1-sol", path = "/fixture/rollout-" + Id + ".jsonl" } }),
                "ccrelay/checkpoint/verify" => Json(new { threadId = Id, workspace = cwd, persisted = true }),
                "ccrelay/catalog/add" => Json(new { threadId = Id, published = true }),
                "turn/start" => Register(),
                "thread/list" => Json(new { data = Listed ? new[] { new { id = Id, name, cwd } } : [] }),
                _ => throw new Exception("Unexpected native action: " + method) };
            return Task.FromResult(result);
        }
        private JsonElement Start(JsonElement p) { cwd = p.GetProperty("cwd").GetString()!; return Json(new { cwd,
            model = scenario == "native-model-mismatch" ? "wrong" : "gpt-6.1-sol", approvalPolicy = p.GetProperty("approvalPolicy").GetString(), thread = new { id = Id } }); }
        private JsonElement Name(JsonElement p) { name = p.GetProperty("name").GetString()!; return Json(new { }); }
        private JsonElement Register() { Listed = scenario != "not-listed"; return Json(new { turn = new { id = "registration" } }); }
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new Exception("No approvals in provisioning");
    }
    private sealed class FakeBot(RouterPolicy policy, string scenario) : IBot
    {
        public int Creates;
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false) => method switch {
            "getChat" => Task.FromResult(Json(new { id = policy.ChatId, is_forum = true })),
            "getChatMember" => Task.FromResult(Json(new { status = "administrator", can_manage_topics = scenario != "rights" })),
            "createForumTopic" => Create(), _ => throw new Exception("Unexpected bot method") };
        private Task<JsonElement> Create() { Creates++; return scenario == "unknown-create" ? Task.FromException<JsonElement>(new TimeoutException()) :
            Task.FromResult(Json(new { message_thread_id = 777, name = "Fixture" })); }
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop) => throw new Exception("Fixture sends no messages");
        public Task Edit(long chat, int message, string text, CancellationToken stop) => throw new Exception("Fixture edits no messages");
    }
}
