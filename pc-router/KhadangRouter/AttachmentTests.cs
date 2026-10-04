using System.Text.Json;

namespace KhadangRouter;

public static class AttachmentTests
{
    private static JsonElement Json(object? value) => JsonSerializer.SerializeToElement(value);
    private static JsonElement Raw(string value) => JsonDocument.Parse(value).RootElement.Clone();
    private static object File(string id = "fixture-id", string name = "..\\untrusted.ps1", long size = 3) => new { file_id = id, file_unique_id = "unique-" + id, file_size = size, file_name = name, mime_type = "untrusted/mime" };
    private static object Photos => new[] { new { file_id = "small", file_unique_id = "unique-small", file_size = 3, width = 20, height = 20 }, new { file_id = "large", file_unique_id = "unique-large", file_size = 3, width = 200, height = 200 } };
    public static async Task<int> Run(string root, RouterPolicy template)
    {
        int checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        void Denied(Action action, string name)
        {
            try { action(); throw new Exception(name); }
            catch (Exception error) when (error is AttachmentFailure or InvalidOperationException or KeyNotFoundException) { checks++; }
        }
        Check(Attachments.References(Json(new { photo = Photos })).Single().FileId == "large", "Highest-resolution photo selected, not arbitrary thumbnail");
        foreach (var kind in new[] { "document", "video", "audio", "voice", "video_note", "animation", "sticker" })
            Check(Attachments.References(Json(new Dictionary<string, object> { [kind] = File() })).Single().Kind == kind, "All common file references retained: " + kind);
        Check(Attachments.References(Json(new { live_photo = new { file_id = "motion", photo = Photos } })).Count == 2, "Live photo retains both still and motion");
        Check(Attachments.References(Json(new { live_photo = new { file_id = "motion" } })).Single().Kind == "live_photo.video", "Optional live-photo still not invented");
        foreach (var payload in new[] { "{\"document\":{}}", "{\"photo\":[]}", "{\"photo\":{}}", "{\"document\":{\"file_id\":\"x\",\"file_size\":true}}", "{\"document\":{\"file_id\":\"x\",\"file_size\":-1}}", "{\"document\":{\"file_id\":\"x\",\"file_size\":20000001}}", "{\"document\":{\"file_id\":\"x\",\"file_name\":true}}", "{\"document\":{\"file_id\":\"x\\n\"}}" })
            Denied(() => Attachments.References(Raw(payload)), "Malformed/unbounded attachment accepted");
        var reference = Attachments.References(Json(new { document = File() })).Single();
        Check(Telegram.DownloadPath(Json(new { file_unique_id = reference.UniqueId, file_size = 3, file_path = "documents/file_1.dat" }), reference) == "documents/file_1.dat", "Provider file metadata remains bounded and identity-scoped");
        foreach (var path in new[] { "../token", "documents/../token", "documents//file", "https://foreign/file", "/documents/file", "documents/file?x=y", "documents/%2e%2e", "documents/file#x", "documents\\file", "documents/file\n" })
            Denied(() => Telegram.DownloadPath(Json(new { file_unique_id = reference.UniqueId, file_size = 3, file_path = path }), reference), "Download origin/path escape accepted");
        Denied(() => Telegram.DownloadPath(Json(new { file_unique_id = "foreign", file_size = 3, file_path = "documents/file" }), reference), "Changed file identity accepted");
        Denied(() => Telegram.DownloadPath(Json(new { file_unique_id = reference.UniqueId, file_size = 4, file_path = "documents/file" }), reference), "Changed file size accepted");
        using (var source = new MemoryStream(new byte[] { 1, 2, 3 }))
        using (var target = new MemoryStream()) { await Telegram.CopyAttachment(source, target, 3, CancellationToken.None); Check(target.ToArray().SequenceEqual(new byte[] { 1, 2, 3 }), "Streaming preserves exact bytes"); }
        foreach (var (actual, expected) in new[] { (2, 3L), (4, 3L), (0, 1L) })
        {
            using var source = new MemoryStream(new byte[actual]); using var target = new MemoryStream();
            try { await Telegram.CopyAttachment(source, target, expected, CancellationToken.None); throw new Exception("Incorrect stream length accepted"); } catch (AttachmentFailure) { checks++; }
        }
        using (var source = new MemoryStream(new byte[Attachments.MaximumBytes + 1]))
        using (var target = Stream.Null)
        { try { await Telegram.CopyAttachment(source, target, null, CancellationToken.None); throw new Exception("Unbounded unknown-size stream accepted"); } catch (AttachmentFailure) { checks++; } }
        foreach (var (bytes, extension) in new[] { (new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 }, ".png"), (new byte[] { 255, 216, 255 }, ".jpg"), ("GIF89a"u8.ToArray(), ".gif"), ("RIFFxxxxWEBP"u8.ToArray(), ".webp") })
            Check(Attachments.ImageExtension(bytes) == extension, "Image input selected by byte signature, not filename/MIME");
        Check(Attachments.ImageExtension("fake.png"u8) == null, "A filename is not image evidence");
        var staged = new[] { new StagedAttachment("photo", "C:\\Protected\\generated.jpg", 3, new string('a', 64), "../untrusted.ps1", "image/jpeg", true), new StagedAttachment("voice", "C:\\Protected\\generated.bin", 3, new string('b', 64), null, "audio/ogg", false) };
        var inputs = Json(Attachments.Input(123, 456, "Owner Caption", staged));
        Check(inputs.GetArrayLength() == 2 && inputs[1].GetProperty("type").GetString() == "localImage" && inputs[1].GetProperty("path").GetString() == staged[0].Path, "Images use native localImage while other files remain paths");
        Check(inputs[0].GetProperty("text").GetString()!.Contains("Owner Caption") && !inputs.GetRawText().Contains("file_id") && !inputs.GetRawText().Contains("api.telegram.org"), "Caption/provenance retained without credential URL or bot file ID");
        if (OperatingSystem.IsWindows())
        {
            var directory = Path.Combine(root, "real-windows-stage"); Directory.CreateDirectory(directory);
            var workspace = Path.Combine(directory, "workspaces"); Directory.CreateDirectory(Path.Combine(workspace, "lg-magic"));
            var policy = template with { StateDirectory = directory, WorkspaceRoot = workspace };
            using var ledger = new Ledger(Path.Combine(directory, "router.db"));
            var bot = new AttachmentBot(policy, new AttachmentNative(), "fixture");
            var message = Message(policy, 1, document: File(size: 3));
            var store = new Attachments(policy, ledger, bot); var binding = new Binding(policy.ChatId, 42, "LG", workspace + "\\lg-magic", "attachment-thread");
            var files = await store.Stage(message, binding, 1, CancellationToken.None);
            Check(FileBytes(files.Single().Path).SequenceEqual(new byte[] { 1, 2, 3 }) && !files.Single().Path.Contains("untrusted.ps1"), "Actual Windows materialization uses generated paths and exact bytes");
            Check(ledger.Get("attachments/1")!.Value.GetProperty("state").GetString() == "staged", "Actual cache manifest links source/binding/bytes before native input");
            try { await store.Stage(message, binding, 1, CancellationToken.None); throw new Exception("Staging receipt replayed"); } catch (AttachmentFailure) { checks++; }
        }
        foreach (var scenario in new[] { "image", "document", "caption-slash", "failed", "failed-json", "slow", "ended", "album", "unsupported" })
        {
            var directory = Path.Combine(root, "attachment-" + scenario); Directory.CreateDirectory(directory);
            var workspace = OperatingSystem.IsWindows() ? Path.Combine(directory, "workspaces") : "C:\\AttachmentWorkspaces";
            if (OperatingSystem.IsWindows()) Directory.CreateDirectory(Path.Combine(workspace, "lg-magic"));
            var policy = template with { StateDirectory = directory, WorkspaceRoot = workspace, OwnerFullAccess = true };
            using var ledger = new Ledger(Path.Combine(directory, "router.db"));
            ledger.Bind(new Binding(policy.ChatId, 42, "LG", workspace + "\\lg-magic", "attachment-thread"));
            ledger.Put("bubble/attachment-thread", new { tail = "Initial history\n", message = 900, sendUnknown = false, held = false, busy = false, status = "Done", elapsedMs = 11000 });
            var native = new AttachmentNative(); var store = new FixtureStore(native, scenario); var bot = new AttachmentBot(policy, native, scenario);
            using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            var running = new Router(policy, ledger, bot, native, store).Run(stop.Token);
            try { await bot.Completed.Task.WaitAsync(TimeSpan.FromSeconds(5)); }
            finally { stop.Cancel(); try { await running; } catch (OperationCanceledException) { } }
            Check(bot.Sends == 1 && bot.Last!.Length <= 3900, "New native turn gets one bubble; attachment controls/errors amend it: " + scenario);
            Check(!ledger.Get("bubble/attachment-thread")!.Value.GetProperty("held").GetBoolean() && ledger.Unknown == 0, "Known pre-native media failures do not hold session or create uncertain effects: " + scenario);
            Check(native.Starts == 0 && native.Calls.All(c => c.Method != "thread/start"), "Attachments never create new sessions or convert stale media into new turns");
            if (scenario is "failed" or "failed-json" or "ended" or "album" or "unsupported") Check(native.Steers == 0 && bot.Last!.Contains("held:"), "No partial/failed/stale/unsupported attachment input sent");
            else
            {
                Check(native.Steers == 1 && native.LastInput!.Value[0].GetProperty("text").GetString()!.Contains(scenario == "caption-slash" ? "/goal clear" : "Owner Caption"), "Caption stays with exactly one native steering input");
                Check(native.LastExpected == "arrival-turn" && !native.Calls.Any(c => c.Method == "thread/goal/clear"), "Exact arrival turn retained; caption never becomes a command");
            }
            if (scenario == "slow") Check(native.Interrupts == 1, "Interrupt RPC can acknowledge while file staging waits");
            Check(store.Calls <= 1, "Foreign owner input cannot download an attachment");
        }
        return checks;
    }
    private static byte[] FileBytes(string path) => System.IO.File.ReadAllBytes(path);
    private static JsonElement Message(RouterPolicy policy, int id, object? document = null, object? photo = null, string caption = "Owner Caption", long? owner = null, string? album = null) => JsonSerializer.SerializeToElement(new {
        from = new { id = owner ?? policy.OwnerId, is_bot = false }, chat = new { id = policy.ChatId, is_forum = true }, message_thread_id = 42, message_id = id, caption,
        document, photo, media_group_id = album }, new JsonSerializerOptions { DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull });
    private sealed class AttachmentNative : INative
    {
        public uint Pid => 1;
        public event Action<JsonElement>? Notification;
        public List<(string Method, bool Effect)> Calls = [];
        public int Starts, Steers, Interrupts;
        public string? LastExpected;
        public JsonElement? LastInput;
        public TaskCompletionSource Interrupted = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public void Event(string method, object value) => Notification?.Invoke(Json(new { method, @params = value }));
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            Calls.Add((method, effect)); var args = Json(parameters);
            if (method == "thread/resume") return Task.FromResult(Json(new { cwd = args.GetProperty("cwd").GetString(), approvalPolicy = "never", approvalsReviewer = "user", sandbox = new { type = "dangerFullAccess" }, thread = new { id = "attachment-thread" } }));
            if (method == "thread/goal/get") return Task.FromResult(Json(new { goal = (object?)null }));
            if (method == "turn/steer") { Steers++; LastExpected = args.GetProperty("expectedTurnId").GetString(); LastInput = args.GetProperty("input").Clone(); return Task.FromResult(Json(new { turnId = LastExpected })); }
            if (method == "turn/start") { Starts++; throw new Exception("No fresh-turn fallback in media fixture"); }
            if (method == "turn/interrupt") { Interrupts++; Interrupted.TrySetResult(); return Task.FromResult(Json(new { })); }
            throw new Exception("Unexpected attachment native method " + method);
        }
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new Exception("No model request in attachment fixture");
    }
    private sealed class FixtureStore(AttachmentNative native, string scenario) : IAttachments
    {
        public int Calls;
        public async Task<IReadOnlyList<StagedAttachment>> Stage(JsonElement message, Binding binding, long updateId, CancellationToken stop)
        {
            Calls++;
            if (scenario == "failed") throw new IOException("Credential URL must never be mirrored");
            if (scenario == "failed-json") throw new JsonException("Credential URL must never be mirrored");
            if (scenario == "slow") await native.Interrupted.Task.WaitAsync(stop);
            if (scenario == "ended") native.Event("turn/completed", new { threadId = binding.ThreadId, turn = new { id = "arrival-turn", status = "completed" } });
            return new[] { new StagedAttachment(scenario == "document" ? "document" : "photo", "C:\\Protected\\generated.bin", 3, new string('a', 64), "../untrusted.ps1", "application/octet-stream", scenario != "document") };
        }
    }
    private sealed class AttachmentBot(RouterPolicy policy, AttachmentNative native, string scenario) : IBot
    {
        private JsonElement menus;
        private int polls;
        public int Sends;
        public string? Last;
        public TaskCompletionSource Completed = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public async Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = false)
        {
            if (method == "setMyCommands") { menus = Json(parameters).GetProperty("commands").Clone(); return Json(true); }
            if (method == "getMyCommands") return menus;
            if (method != "getUpdates") throw new Exception("Unexpected attachment bot API");
            if (++polls == 1)
            {
                native.Event("turn/started", new { threadId = "attachment-thread", turn = new { id = "arrival-turn" } });
                native.Event("item/agentMessage/delta", new { threadId = "attachment-thread", turnId = "arrival-turn", itemId = "history", delta = "Current tool history\n" });
                var media = Message(policy, 100, document: scenario == "document" ? File() : null, photo: scenario is "document" or "unsupported" ? null : Photos, caption: scenario == "caption-slash" ? "/goal clear" : "Owner Caption", album: scenario == "album" ? "fixture-album" : null);
                object Update(int id, JsonElement message) => new { update_id = id, message };
                var control = Json(new { from = new { id = policy.OwnerId, is_bot = false }, chat = new { id = policy.ChatId, is_forum = true }, message_thread_id = 42, message_id = 102, text = scenario == "slow" ? "/cancel" : "/status" });
                return Json(new[] { Update(100, media), Update(101, Message(policy, 101, photo: Photos, owner: policy.OwnerId + 1)), Update(102, control) });
            }
            await Task.Delay(Timeout.Infinite, stop); return Json(Array.Empty<object>());
        }
        public Task<JsonElement> Send(long chat, int topic, string text, CancellationToken stop)
        { Sends++; Observe(text); return Task.FromResult(Json(new { message_id = 901 })); }
        public Task Edit(long chat, int message, string text, CancellationToken stop)
        {
            if (message is not (900 or 901)) throw new Exception("Unknown media bubble receipt"); Observe(text);
            return Task.CompletedTask;
        }
        private void Observe(string text)
        {
            Last = text;
            if ((text.Contains("steered") || text.Contains("held:")) && (text.Contains("PC session:") || text.Contains("Interrupt requested"))) Completed.TrySetResult();
        }
        public Task Download(AttachmentReference file, Stream target, CancellationToken stop) => target.WriteAsync(new byte[] { 1, 2, 3 }, stop).AsTask();
    }
}
