using System.Security.Cryptography;
using System.Text.Json;

namespace KhadangRouter;

// Fixed owner-authorized deployment canary. No model prompt, native launch,
// arbitrary destination or poller. Once attempted, never automatically replay.
internal static class NativeTableProbe
{
    internal static async Task Run(RouterPolicy policy, Ledger ledger, IBot bot, List<Binding> bindings, string config, CancellationToken stop)
    {
        var target = bindings.Single(b => b.Chat == -1003550185469 && b.Topic == 816 && b.ThreadId == "01a0facd-1bc0-7d23-95d6-c32fde0c62db");
        var code = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(Router).Assembly.Location)));
        var policyHash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(config)));
        var key = "table-probe/" + code;
        if (ledger.Get(key) != null) throw new InvalidOperationException("Table canary already attempted; inspect receipt, never replay");
        var part = FinalAnswerView.Split("Native Telegram table test — no model request.\n\n| Output | Status |\n| --- | --- |\n| Native rich table | Ready |\n| Live bubble | Unchanged |").Single();
        if (part.RichHtml == null) throw new InvalidOperationException("Canary did not render a native table");
        ledger.Put(key, new { status = "attempting", chat = target.Chat, topic = target.Topic, at = DateTimeOffset.UtcNow });
        var sent = await bot.SendAnswer(target.Chat, target.Topic, part, stop);
        ledger.Put(key, new { status = "confirmed", message = sent.GetProperty("message_id").GetInt32(), at = DateTimeOffset.UtcNow });
        if (sent.GetProperty("chat").GetProperty("id").GetInt64() != target.Chat || sent.GetProperty("message_thread_id").GetInt32() != target.Topic ||
            !sent.GetProperty("rich_message").GetProperty("blocks").EnumerateArray().Any(b => b.GetProperty("type").GetString() == "table" && b.GetProperty("cells").GetArrayLength() == 3))
            throw new InvalidOperationException("Telegram did not return a native table in the exact controller topic");
        File.WriteAllText(Path.Combine(policy.StateDirectory, "table-proof.json"), JsonSerializer.Serialize(new {
            testedAt = DateTimeOffset.UtcNow, bot = policy.BotUsername, confirmed = true,
            chat = target.Chat, topic = target.Topic, message = sent.GetProperty("message_id").GetInt32(), nativeTableReturned = true,
            telegramPolling = false, nativeProcessesStarted = false, modelInference = false, chatMessagesSent = 1,
            routerSha256 = code, policySha256 = policyHash }));
    }
}
