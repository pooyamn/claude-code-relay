using System.Net.Http.Headers;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.Json;
using KhadangRouter;
using MediaProbe;

if (args.SequenceEqual(new[] { "--self-test" }))
{
    var fixture = Fixture.Create();
    if (Attachments.ImageExtension(fixture.Bytes) != ".png" || fixture.Colors.Distinct().Count() != 3 || fixture.Bytes.Length > 4096)
        throw new InvalidDataException("Generated fixture failed");
    Console.WriteLine("Generated PNG fixture passed; no credentials/network/models."); return;
}
string? state = null;
try
{
    bool observeOnly = args.Length == 5 && args[4] == "--observe-only";
    if (!OperatingSystem.IsWindows() || (args.Length != 4 && !observeOnly) || args[0] != "--config" || args[2] != "--run" ||
        !Guid.TryParseExact(args[3], "N", out var run)) throw new InvalidOperationException("Protected one-shot media probe requires --config PATH --run GUID");
    using var identity = WindowsIdentity.GetCurrent();
    if (!identity.IsSystem || System.Diagnostics.Process.GetCurrentProcess().SessionId != 0)
        throw new InvalidOperationException("Diagnostic launcher requires SYSTEM Session 0; native inference uses the medium owner token");
    var policy = RouterPolicy.Load(args[1]);
    if (policy.BotId != 8735489806 || policy.OwnerId != 110123423 || policy.ChatId != -1004320138859)
        throw new InvalidOperationException("Diagnostic is pinned to the authorized PC Khadang installation");
    const int topic = 159;
    state = Path.Combine(policy.StateDirectory, "diagnostics", "media-" + run.ToString("N"));
    PrivateDirectory(state);
    // A task restart cannot repeat a send or model turn, even after a crash.
    using var claim = new FileStream(Path.Combine(state, "one-shot.claim"), FileMode.CreateNew, FileAccess.Write, FileShare.None);
    using var ledger = new Ledger(Path.Combine(state, "diagnostic.db")); // Never open the live router database.
    using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(180));
    using var bot = new Telegram(WindowsService.Credential(policy.CredentialFile), ledger);
    var me = await bot.Call("getMe", new { }, deadline.Token);
    if (me.GetProperty("id").GetInt64() != policy.BotId || me.GetProperty("username").GetString() != policy.BotUsername)
        throw new InvalidOperationException("Diagnostic bot identity mismatch");
    var chat = await bot.Call("getChat", new { chat_id = policy.ChatId }, deadline.Token);
    if (chat.GetProperty("id").GetInt64() != policy.ChatId || !chat.GetProperty("is_forum").GetBoolean())
        throw new InvalidOperationException("Diagnostic forum identity mismatch");
    await using var rpc = new NativeRpc(WindowsOwnerProcess.Start(policy, policy.WorkspaceRoot + "\\lg-magic"), ledger);
    await rpc.Initialize(deadline.Token);
    var quota = new NativeQuota(); await quota.Read(rpc, deadline.Token); var before = quota.Snapshot;
    File.WriteAllText(Path.Combine(state, "quota-observation.json"), JsonSerializer.Serialize(before));
    if (observeOnly)
    {
        // Diagnose a failed guard with explicit read-only protocol evidence.
        // Never upload a fixture, start a thread or infer availability here.
        var accountBefore = await rpc.Call("account/read", new { refreshToken = false }, deadline.Token, effect: false);
        var usage = await rpc.Call("account/rateLimits/read", new { }, deadline.Token, effect: false);
        var accountAfter = await rpc.Call("account/read", new { refreshToken = false }, deadline.Token, effect: false);
        string? problem = null; QuotaObservation? parsed = null;
        try
        {
            var fingerprint = NativeQuota.Account(accountBefore);
            if (fingerprint != NativeQuota.Account(accountAfter)) throw new InvalidDataException("Account changed during diagnostic read");
            parsed = NativeQuota.Parse(usage, fingerprint, DateTimeOffset.UtcNow);
        }
        catch (Exception error) when (error is InvalidDataException or KeyNotFoundException or InvalidOperationException or JsonException)
        { problem = error.GetType().Name + ": " + error.Message; }
        File.WriteAllText(Path.Combine(state, "observation-diagnostic.json"), JsonSerializer.Serialize(new { at = DateTimeOffset.UtcNow,
            initial = before, parsed, problem, accountFields = accountBefore.EnumerateObject().Select(p => p.Name).ToArray(),
            usageFields = usage.EnumerateObject().Select(p => p.Name).ToArray(), modelTurns = 0, telegramUploads = 0 }));
        return;
    }
    // Read-only coarse guard, NOT global admission or a proof of reserved cost.
    if (before.State != "observed" || !before.AccountVerified || before.OrdinaryUsageAllowed != true || before.Buckets.Count == 0 ||
        before.Buckets.Any(b => b.SpendControlReached == true || b.ReachedType != null || b.Primary == null ||
            b.Primary.UsedPercent >= 90 || b.Secondary?.UsedPercent >= 90)) throw new InvalidOperationException("Fresh native included-usage observation required for this single diagnostic turn");
    var fixture = Fixture.Create();
    File.WriteAllBytes(Path.Combine(state, "source.png"), fixture.Bytes);
    File.WriteAllText(Path.Combine(state, "truth.json"), JsonSerializer.Serialize(fixture.Colors));
    var sent = await UploadFixture(WindowsService.Credential(policy.CredentialFile), policy, fixture.Bytes, ledger, deadline.Token);
    if (sent.GetProperty("chat").GetProperty("id").GetInt64() != policy.ChatId || sent.GetProperty("message_thread_id").GetInt32() != topic ||
        sent.GetProperty("from").GetProperty("id").GetInt64() != policy.BotId) throw new InvalidOperationException("Fixture send receipt target mismatch; no cleanup or model turn");
    var message = sent.GetProperty("message_id").GetInt32();
    ledger.Put("generated-message", new { chat = policy.ChatId, topic, message, bot = policy.BotId });
    var reference = Attachments.References(sent).Single();
    var assetFolder = Path.Combine(policy.StateDirectory, "attachments", "media-probe-" + run.ToString("N"));
    ReadableDirectory(assetFolder, policy.OwnerSid);
    var asset = Path.Combine(assetFolder, "fixture.png");
    await using (var target = new FileStream(asset, FileMode.CreateNew, FileAccess.Write, FileShare.None))
    {
        await bot.Download(reference, target, deadline.Token); await target.FlushAsync(deadline.Token); target.Flush(true);
    }
    ReadableFile(asset, policy.OwnerSid);
    var downloaded = File.ReadAllBytes(asset);
    if (!downloaded.SequenceEqual(fixture.Bytes)) throw new InvalidDataException("Actual Telegram download differs from generated fixture");
    ledger.Put("download", new { verified = true, asset, bytes = downloaded.Length, sha256 = Convert.ToHexString(SHA256.HashData(downloaded)) });
    // Delete ONLY the confirmed generated bot message. Both effect receipts stay
    // in this protected diagnostic ledger; ambiguous delivery is never replayed.
    await DeleteFixture(WindowsService.Credential(policy.CredentialFile), policy.ChatId, message, ledger, deadline.Token);
    var started = await rpc.Call("thread/start", new { cwd = policy.WorkspaceRoot + "\\lg-magic", sandbox = "read-only", approvalPolicy = "never",
        serviceName = "khadang-generated-media-diagnostic", environments = Array.Empty<object>(),
        baseInstructions = "Only inspect the supplied image and return the requested JSON. Never use tools, delegate, read project files, edit files or perform external actions.",
        developerInstructions = "This is a one-turn generated image acceptance test, not a project task. Do not use any tools." }, deadline.Token);
    var thread = started.GetProperty("thread").GetProperty("id").GetString()!;
    ledger.Put("diagnostic-thread", new { thread, asset });
    var done = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
    var tool = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
    var answers = new List<string>(); var gate = new object();
    void Notify(JsonElement notification)
    {
        if (!notification.TryGetProperty("params", out var p) || !p.TryGetProperty("threadId", out var id) || id.GetString() != thread) return;
        var method = notification.GetProperty("method").GetString();
        if (notification.TryGetProperty("id", out _)) { tool.TrySetResult(true); return; }
        if (method == "item/started")
        {
            var type = p.GetProperty("item").GetProperty("type").GetString();
            if (type is not ("userMessage" or "agentMessage" or "reasoning")) tool.TrySetResult(true);
        }
        if (method == "item/completed" && p.GetProperty("item").GetProperty("type").GetString() == "agentMessage")
        {
            var text = p.GetProperty("item").GetProperty("text").GetString()!;
            if (text.Length > 4096) { tool.TrySetResult(true); return; }
            lock (gate) { if (answers.Count < 8) answers.Add(text); else tool.TrySetResult(true); }
        }
        if (method == "turn/completed") done.TrySetResult(p.GetProperty("turn").Clone());
    }
    rpc.Notification += Notify;
    try
    {
        var turn = await rpc.Call("turn/start", new { threadId = thread, effort = "low", approvalPolicy = "never",
            sandboxPolicy = new { type = "readOnly", networkAccess = false }, environments = Array.Empty<object>(),
            input = new object[] { new { type = "text", text = "Identify the three solid-colored vertical panels in this image, from left to right. Return only JSON with a colors array of exactly three lowercase color names. Allowed names: red, green, blue, yellow, magenta, cyan. Do not use tools." }, new { type = "localImage", path = asset } },
            outputSchema = new { type = "object", properties = new { colors = new { type = "array", minItems = 3, maxItems = 3,
                items = new { type = "string", @enum = new[] { "red", "green", "blue", "yellow", "magenta", "cyan" } } } }, required = new[] { "colors" }, additionalProperties = false } }, deadline.Token);
        var winner = await Task.WhenAny(done.Task, tool.Task, Task.Delay(TimeSpan.FromSeconds(90), deadline.Token));
        if (winner != done.Task || tool.Task.IsCompleted) throw new InvalidOperationException("Diagnostic tool activity or deadline; no retry, owned native process will stop");
        var completed = await done.Task;
        if (completed.GetProperty("id").GetString() != turn.GetProperty("turn").GetProperty("id").GetString() || completed.GetProperty("status").GetString() != "completed")
            throw new InvalidOperationException("Native diagnostic turn did not complete successfully");
        string answer; lock (gate) answer = answers.LastOrDefault() ?? throw new InvalidOperationException("Native diagnostic produced no final message");
        using var parsed = JsonDocument.Parse(answer);
        var colors = parsed.RootElement.GetProperty("colors").EnumerateArray().Select(c => c.GetString()).ToArray();
        if (!colors.SequenceEqual(fixture.Colors)) throw new InvalidDataException("Model answer did not match private randomized image truth");
        await quota.Read(rpc, deadline.Token);
        File.WriteAllText(Path.Combine(state, "result.json"), JsonSerializer.Serialize(new { verified = true, at = DateTimeOffset.UtcNow,
            generatedPixelsOnly = true, actualTelegramUpload = true, actualTelegramDownload = true, generatedMessageRemoved = true,
            diagnosticThread = thread, nativePid = rpc.Pid, ownerSid = policy.OwnerSid, actualModelImageInterpretation = true, colors,
            nativeToolActivityObserved = false, modelTurns = 1, liveRouterDatabaseOpened = false, telegramPolling = false,
            globalAdmissionVerified = false, quotaBefore = before, quotaAfter = quota.Snapshot, unknown = ledger.Unknown,
            asset, sha256 = Convert.ToHexString(SHA256.HashData(downloaded)) }));
    }
    finally { rpc.Notification -= Notify; }
}
catch (Exception error)
{
    if (state != null) File.WriteAllText(Path.Combine(state, "failure.json"), JsonSerializer.Serialize(new { errorType = error.GetType().Name,
        at = DateTimeOffset.UtcNow, retry = false, message = error is HttpRequestException or TaskCanceledException ? "Bounded network/deadline failure" : error.Message }));
    Console.Error.WriteLine("Media diagnostic failed: " + error.GetType().Name); Environment.ExitCode = 1;
}

static void PrivateDirectory(string path)
{
    Directory.CreateDirectory(path);
    for (var dir = new DirectoryInfo(path); dir != null; dir = dir.Parent)
        if ((dir.Attributes & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Diagnostic reparse path refused");
    var acl = new DirectorySecurity(); acl.SetAccessRuleProtection(true, false); acl.SetOwner(new SecurityIdentifier("S-1-5-32-544"));
    foreach (var sid in new[] { "S-1-5-18", "S-1-5-32-544" }) acl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(sid), FileSystemRights.FullControl,
        InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
    new DirectoryInfo(path).SetAccessControl(acl);
}
static void ReadableDirectory(string path, string owner)
{
    PrivateDirectory(path); var directory = new DirectoryInfo(path); var acl = directory.GetAccessControl();
    acl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(owner), FileSystemRights.ReadAndExecute,
        InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow)); directory.SetAccessControl(acl);
}
static void ReadableFile(string path, string owner)
{
    var acl = new FileSecurity(); acl.SetAccessRuleProtection(true, false); acl.SetOwner(new SecurityIdentifier("S-1-5-32-544"));
    foreach (var sid in new[] { "S-1-5-18", "S-1-5-32-544" }) acl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(sid), FileSystemRights.FullControl, AccessControlType.Allow));
    acl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(owner), FileSystemRights.Read, AccessControlType.Allow)); new FileInfo(path).SetAccessControl(acl);
}
static async Task<JsonElement> UploadFixture(string token, RouterPolicy policy, byte[] bytes, Ledger ledger, CancellationToken stop)
{
    using var content = new MultipartFormDataContent();
    content.Add(new StringContent(policy.ChatId.ToString(System.Globalization.CultureInfo.InvariantCulture)), "chat_id");
    content.Add(new StringContent("159"), "message_thread_id"); content.Add(new StringContent("true"), "disable_notification");
    var image = new ByteArrayContent(bytes); image.Headers.ContentType = new MediaTypeHeaderValue("image/png");
    content.Add(image, "document", "generated-diagnostic.png");
    return await Effect(token, "sendDocument", content, new { chat = policy.ChatId, topic = 159, generated = true, sha256 = Convert.ToHexString(SHA256.HashData(bytes)) }, ledger, stop);
}
static async Task DeleteFixture(string token, long chat, int message, Ledger ledger, CancellationToken stop)
{
    using var content = System.Net.Http.Json.JsonContent.Create(new { chat_id = chat, message_id = message });
    var result = await Effect(token, "deleteMessage", content, new { chat, message, confirmedGeneratedBotMessageOnly = true }, ledger, stop);
    if (result.ValueKind != JsonValueKind.True) throw new InvalidDataException("Generated message removal not confirmed");
}
static async Task<JsonElement> Effect(string token, string method, HttpContent content, object evidence, Ledger ledger, CancellationToken stop)
{
    var attempt = ledger.Attempt("telegram/" + method, evidence);
    using var http = new HttpClient(new HttpClientHandler { AllowAutoRedirect = false }) { Timeout = TimeSpan.FromSeconds(45) };
    try
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, "https://api.telegram.org/bot" + token + "/" + method) { Content = content };
        using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, stop);
        if (response.Content.Headers.ContentLength > 65536) throw new InvalidDataException("Diagnostic response too large");
        await response.Content.LoadIntoBufferAsync(65536);
        using var parsed = JsonDocument.Parse(await response.Content.ReadAsByteArrayAsync(stop)); var root = parsed.RootElement;
        if (!root.GetProperty("ok").GetBoolean()) { ledger.Outcome(attempt, "rejected"); throw new TelegramFailure(root.GetProperty("error_code").GetInt32()); }
        if (!response.IsSuccessStatusCode) throw new TelegramFailure((int)response.StatusCode);
        var result = root.GetProperty("result").Clone(); ledger.Confirm(attempt, result); return result;
    }
    catch (Exception error) when (error is HttpRequestException or TaskCanceledException)
    {
        ledger.Outcome(attempt, "unknown"); throw new TelegramFailure(0); // Redact token-bearing URLs.
    }
    catch { ledger.Outcome(attempt, "unknown"); throw; }
}
