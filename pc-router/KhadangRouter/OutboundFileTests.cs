using System.Reflection;
using System.Text.Json;

namespace KhadangRouter;

public static class OutboundFileTests
{
    public static async Task<int> Run(string root, RouterPolicy policy)
    {
        int checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        const string project = "/Users/pouya/.openclaw/workspace/fixture";
        var png = project + "/placement overview.png"; var zip = project + "/out.zip";
        var extracted = OutboundFiles.Extract("Done.\n📎 " + png + "\n📎 " + zip + "\n📎 " + png);
        Check(extracted.Text == "Done." && extracted.Files.Select(f => f.Path).SequenceEqual([png, zip]), "Standalone markers strip from prose and deduplicate, preserving spaces");
        Check(OutboundFiles.Extract("```\n📎 " + png + "\n```\n[local](" + zip + ")").Files.Count == 0, "Code examples and arbitrary local links never upload");
        var image = OutboundFiles.Extract("Before ![PCB](" + png + ") after.\n📎 " + png);
        Check(image.Text == "Before  after." && image.Files.Count == 1 && image.Files[0].Path == png, "Native Markdown image uploads once and removes the placeholder without losing prose");
        Check(OutboundFiles.Extract("![Windows](<C:\\Workspaces\\fixture\\photo with spaces.png>)").Files.Single().Path == "C:\\Workspaces\\fixture\\photo with spaces.png", "Angle-bracket Windows image paths preserve spaces");
        Check(OutboundFiles.Extract("`![code](" + png + ")`\n```\n![fenced](" + png + ")\n```\n\\![escaped](" + png + ")\n![web](https://example.invalid/image.png)").Files.Count == 0, "Code, escaped images and remote URLs never become artifact uploads");
        const string newest = "Updated DUT-X.\n\n[Updated BOM](/Users/pouya/.openclaw/workspace/fixture/BOM.csv) · [KiCad package](/Users/pouya/.openclaw/workspace/fixture/package.zip)\n\n![Updated DUT-X PCB placement](/Users/pouya/.openclaw/workspace/fixture/dist/dut-x-reuse-pcb-3d.png)";
        var nativeImage = new FinalAnswerState(); nativeImage.Consider(newest); nativeImage.Complete(); nativeImage.Validate();
        Check(nativeImage.Files.Single().Path.EndsWith("dut-x-reuse-pcb-3d.png") && !nativeImage.Parts.Any(p => p.Part.Text.Contains("![")), "Regression for the actual missed DUT X answer includes a photo delivery");
        foreach (var path in new[] { "relative.zip", "https://example.invalid/a.png", project + "/../secret", project + "//x", "C:\\Workspaces\\x:ads", project + "/.git/config" })
            Check(!OutboundFiles.LiteralPath(path), "Unsafe path refused");
        Check(OutboundFiles.LiteralPath("C:\\Workspaces\\fixture\\photo.png"), "Literal native Windows artifact supported");
        var state = new FinalAnswerState(); state.Consider("📎 " + png); state.Complete(); state.Validate();
        Check(state.Parts.Count == 0 && state.Files.Count == 1 && !state.Delivered, "File-only final requires actual upload acknowledgement");
        state.Files[0].SendUnknown = true;
        var saved = JsonSerializer.Deserialize<FinalAnswerState>(JsonSerializer.Serialize(state))!; saved.Validate();
        Check(saved.Unknown && !saved.Delivered, "Ambiguous file survives restart as uncertain, not delivered");
        var legacy = JsonSerializer.Deserialize<FinalAnswerState>("{\"Candidate\":\"📎 " + zip + "\",\"Completed\":true,\"Parts\":[]}")!;
        legacy.Validate(); Check(legacy.Files.Count == 0, "Upgrade does not retrospectively resend old final files");
        var flags = BindingFlags.NonPublic | BindingFlags.Instance;
        var type = typeof(Router).GetNestedType("Session", BindingFlags.NonPublic)!;
        var binding = new Binding(policy.ChatId, 42, "fixture", project, "file-fixture", "codex", "linux");
        using var ledger = new Ledger(Path.Combine(root, "outbound-files.db"));
        var bot = new Bot(ledger, binding.ThreadId); var native = new Native(); var files = new Files();
        var router = new Router(policy, ledger, bot, native, outboundFiles: files);
        var session = type.GetConstructors(flags | BindingFlags.Public).Single().Invoke(new object[] { binding, native });
        var sessions = typeof(Router).GetField("sessions", flags)!.GetValue(router)!;
        sessions.GetType().GetProperty("Item")!.SetValue(sessions, session, new object[] { binding.Address });
        var flush = typeof(Router).GetMethod("FlushBubble", flags)!;
        var response = (ResponseMessage)type.GetField("Response", flags | BindingFlags.Public)!.GetValue(session)!;
        Task Flush() => (Task)flush.Invoke(router, new[] { session, CancellationToken.None })!;
        response.Answer.Consider("Done.\n📎 " + png + "\n📎 " + zip); response.Answer.Complete();
        await Flush(); await Flush();
        Check(bot.Answers == 1 && bot.Uploads.SequenceEqual([true, false]), "Separate clean final, inline photo and ZIP document each delivered once");
        Check(response.Answer.Delivered && response.Answer.Files.All(f => f.Message != null && f.Sha256?.Length == 64 && f.Size > 0), "Per-file receipts pin content and Telegram IDs");
        var restored = JsonSerializer.Deserialize<FinalAnswerState>(JsonSerializer.Serialize(response.Answer))!; restored.Validate();
        response.Answer = restored; await Flush();
        Check(bot.Uploads.Count == 2, "Confirmed file IDs prevent restart duplicate");
        response.Answer = new(); response.Answer.Consider("Updated.\n![PCB](" + png + ")"); response.Answer.Complete();
        await Flush(); var imageUploads = bot.Uploads.Count; await Flush();
        Check(response.Answer.Delivered && bot.Uploads.Count == imageUploads && bot.Uploads[^1] && bot.LastAnswer == "Updated.", "Markdown image final goes through real durable flush and is not resent");
        response.Answer = new(); response.Answer.Consider("📎 " + png); response.Answer.Complete(); bot.Errors.Enqueue(400);
        await Flush();
        Check(response.Answer.Delivered && bot.Uploads.TakeLast(2).SequenceEqual([true, false]), "Explicit photo rejection falls back to document");
        response.Answer = new(); response.Answer.Consider("📎 " + png); response.Answer.Complete(); bot.Errors.Enqueue(0);
        await Flush(); var uploads = bot.Uploads.Count; await Flush();
        Check(response.Answer.Unknown && !response.Answer.Delivered && bot.Uploads.Count == uploads, "Ambiguous timeout never retries or falls back");
        response.Answer = new(); response.Answer.Consider("📎 " + zip); response.Answer.Complete(); files.Failure = true;
        await Flush(); await Flush();
        Check(response.Answer.Delivered && response.Answer.Files[0].Failure != null && bot.LastAnswer.StartsWith("Attachment not sent:"), "Read failure visibly reported, never advertised as delivered file");
        response.Answer = new(); response.Answer.Consider("📎 " + zip); response.Answer.Complete(); files.Failure = false; bot.Errors.Enqueue(429);
        await Flush(); Check(!response.Answer.Unknown && !response.Answer.Delivered, "Explicit rate limit remains retryable"); await Flush();
        Check(response.Answer.Delivered, "Rate-limit retry uploads original hash-bound bytes");
        response.Answer = new(); response.Answer.Consider("📎 " + zip); response.Answer.Complete(); bot.Errors.Enqueue(403);
        await Flush(); await Flush();
        Check(!response.Answer.Unknown && response.Answer.Files[0].Failure != null && bot.LastAnswer.Contains("403"), "Known upload rejection is visible and not replayed");
        // Goal finals use the same durable file outbox even while native work continues.
        var goalAnswer = new FinalAnswerState(); goalAnswer.Consider("📎 " + zip); goalAnswer.Complete();
        var pending = (Queue<FinalAnswerState>)type.GetField("PendingAnswers", flags | BindingFlags.Public)!.GetValue(session)!;
        pending.Enqueue(goalAnswer); await Flush();
        Check(goalAnswer.Delivered && pending.Count == 0, "Goal final file is delivered and dequeued independently of live bubble");
        return checks;
    }
    private sealed class Files : IOutboundFiles
    {
        public bool Failure;
        public Task<byte[]> Read(Binding binding, string path, string? expectedSha256, CancellationToken stop) =>
            Failure ? throw new InvalidDataException("refused") : Task.FromResult(path.EndsWith(".png") ? new byte[] {137,80,78,71,13,10,26,10,1} : new byte[] {80,75,3,4,1});
    }
    private sealed class Bot(Ledger ledger, string thread) : IBot
    {
        public int Answers; public string LastAnswer = ""; public List<bool> Uploads = []; public Queue<int> Errors = [];
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false) => throw new NotSupportedException();
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop) => Task.FromResult(JsonSerializer.SerializeToElement(new { message_id = 1 }));
        public Task Edit(long chat, int message, string text, CancellationToken stop) => Task.CompletedTask;
        public Task<JsonElement> SendAnswer(long chat, int topic, AnswerPart part, CancellationToken stop)
        { Answers++; LastAnswer = part.Text; return Task.FromResult(JsonSerializer.SerializeToElement(new {message_id = 100 + Answers})); }
        public Task<JsonElement> Upload(long chat, int topic, string filename, byte[] bytes, bool photo, CancellationToken stop)
        {
            var bubble = ledger.Get("bubble/" + thread)!.Value;
            var states = bubble.GetProperty("pendingAnswers").EnumerateArray().Select(a => a.Deserialize<FinalAnswerState>()!)
                .Append(bubble.GetProperty("finalAnswer").Deserialize<FinalAnswerState>()!);
            if (!states.Any(state => state.Files.Any(f => f.SendUnknown && f.Sha256?.Length == 64 && f.Size == bytes.Length)))
                throw new Exception("Missing durable file intent before upload");
            Uploads.Add(photo);
            if (Errors.TryDequeue(out var code)) throw new TelegramFailure(code, 1);
            return Task.FromResult(JsonSerializer.SerializeToElement(new { message_id = 200 + Uploads.Count }));
        }
    }
    private sealed class Native : INative
    {
        public uint Pid => 1; public event Action<JsonElement>? Notification { add {} remove {} }
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true) => throw new NotSupportedException();
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new NotSupportedException();
    }
}
