using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.Json;
using System.Text.RegularExpressions;
using KhadangRouter;

// Two explicit UI-check messages in the already-bound DUT topic. No native
// calls, polling, topic creation, commands, config writes or operation replay.
try
{
    if (!OperatingSystem.IsWindows() || Environment.MachineName != "DESKTOP-8SO9HDK" || args.Length != 1 ||
        !Regex.IsMatch(args[0], "\\A[0-9a-f]{32}\\z")) throw new InvalidDataException("Exact PC/proof generation required");
    using var identity = WindowsIdentity.GetCurrent();
    if (!new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator)) throw new InvalidDataException("Protected deterministic deployment lane required");
    var release = @"C:\ProgramData\KhadangRouter\release-" + args[0];
    var root = @"C:\ProgramData\OracovaNativeRemote\telegram-ui-proof-" + args[0];
    if (!Directory.Exists(root) || (File.GetAttributes(root) & FileAttributes.ReparsePoint) != 0 || File.Exists(Path.Combine(root, "intent.json")))
        throw new InvalidDataException("Fresh administrator-sealed proof root required; no replay");
    using var stage = JsonDocument.Parse(File.ReadAllText(Path.Combine(release, "stage.json")));
    var code = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(Telegram).Assembly.Location)));
    if (code != stage.RootElement.GetProperty("code").GetString()) throw new InvalidDataException("Proof uses a different renderer than installed candidate");
    using var status = JsonDocument.Parse(File.ReadAllText(@"C:\ProgramData\KhadangRouter\state\status.json"));
    const long chat = -1004395661179; const int topic = 53;
    if (!status.RootElement.GetProperty("bindings").EnumerateArray().Any(b => b.GetProperty("Chat").GetInt64() == chat && b.GetProperty("Topic").GetInt32() == topic &&
        b.GetProperty("ThreadId").GetString() == "7dc840b0-402f-451e-bc79-dadfb706d363")) throw new InvalidDataException("Exact existing DUT route required");
    var policy = RouterPolicy.Load(@"C:\ProgramData\KhadangRouter\config.json");
    using var ledger = new Ledger(Path.Combine(root, "receipts.db"));
    using var telegram = new Telegram(WindowsService.Credential(policy.CredentialFile), ledger);
    using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(60));
    var me = await telegram.Call("getMe", new { }, stop.Token);
    if (me.GetProperty("id").GetInt64() != policy.BotId || me.GetProperty("username").GetString() != "TheKhadangBot") throw new InvalidDataException("Wrong bot");
    File.WriteAllText(Path.Combine(root, "intent.json"), JsonSerializer.Serialize(new { chat, topic, code, at = DateTimeOffset.UtcNow }));
    var progress = await telegram.SendBubble(chat, topic, "UI check — not a model task\n\n⏳ Checking Telegram presentation\n\nWorking (1s)", stop.Token);
    var id = progress.GetProperty("message_id").GetInt32();
    await telegram.EditBubble(chat, id, "UI check — not a model task\n\n✓ Telegram presentation checked\n\nDone (2s)", stop.Token);
    var answer = FinalAnswerView.Split("**Telegram presentation updated.**\n\nLive progress stays in a rolling code-block bubble. Final answers now arrive separately as normal formatted messages. Commands are unchanged.\n\n[Source](https://github.com/pooyamn/claude-code-relay)\n\nThis was a UI check; no model task was started.").Single();
    var final = await telegram.SendAnswer(chat, topic, answer, stop.Token);
    var spans = final.GetProperty("entities").EnumerateArray().Select(e => e.GetProperty("type").GetString()).ToArray();
    if (!spans.Contains("bold") || !spans.Contains("text_link") || spans.Contains("pre") ||
        !progress.GetProperty("entities").EnumerateArray().Any(e => e.GetProperty("type").GetString() == "pre")) throw new InvalidDataException("Bot formatting receipt differs");
    var receipt = new { verified = true, chat, topic, code, progressMessage = id, finalMessage = final.GetProperty("message_id").GetInt32(),
        progressCodeBlock = true, finalNormalProse = true, finalLinksAndBold = true, modelInference = false, commandsChanged = false, at = DateTimeOffset.UtcNow };
    File.WriteAllText(Path.Combine(root, "result.json"), JsonSerializer.Serialize(receipt));
    Console.WriteLine(JsonSerializer.Serialize(receipt));
}
catch (Exception error)
{
    Console.Error.WriteLine("UI proof held: " + error.GetType().Name + ". Inspect saved receipts; no automatic replay.");
    Environment.ExitCode = 1;
}
