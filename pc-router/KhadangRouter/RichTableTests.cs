using System.Text;
using System.Text.Json;

namespace KhadangRouter;

internal static class RichTableTests
{
    internal static int Run()
    {
        int checks = 0;
        void Check(bool condition, string name) { if (!condition) throw new Exception(name); checks++; }
        const string table = "| Route | State |\n| --- | --- |\n| DUT | **Ready** |";
        var parts = FinalAnswerView.Split("Before.\n\n" + table + "\n\n```python\nprint('ok')\n```\nAfter.");
        Check(parts.Length == 3 && parts[0].RichHtml!.StartsWith("<p>Before.</p><table bordered striped>") &&
            parts[0].RichHtml!.Contains("<th>Route</th>") && parts[0].RichHtml!.Contains("<td><b>Ready</b></td>"), "Prose and table use native rich output, with header cells and emphasis");
        Check(parts.Select(Telegram.AnswerMethod).SequenceEqual(new[] { "sendRichMessage", "sendMessage", "sendMessage" }), "Old relay transport ordering restored; real code stays classic");
        Check(parts[1].RichHtml == null && parts[1].Entities.Single().type == "pre" && parts[1].Entities.Single().language == "python" && parts[2].Text == "After.", "Code remains visible and final prose follows it");
        var wire = Telegram.AnswerParameters(-100123, 53, parts[0]);
        Check(wire.Count == 3 && (int)wire["message_thread_id"] == 53 && !wire.ContainsKey("text") && !wire.ContainsKey("entities") &&
            !wire.ContainsKey("parse_mode") && !wire.ContainsKey("disable_notification"), "Native rich wire uses exact topic and notifies, without conflicting classic parameters");
        Check(JsonSerializer.SerializeToElement(wire["rich_message"]).GetProperty("html").GetString() == parts[0].RichHtml, "Rich wire exactly matches saved durable part");
        Check(FinalAnswerView.Split("```\n" + table + "\n```").Single().RichHtml != null, "Models' table-only fences become actual tables");
        Check(FinalAnswerView.Split("~~~\n" + table + "\n~~~").Single().RichHtml != null, "Alternate table-only fences supported");
        Check(FinalAnswerView.Split("| A | B |\n| -- | -- |\n| `a|b` | x\\|y |").Single().RichHtml!.Contains("<td><code>a|b</code></td><td>x|y</td>"), "Escaped pipes and inline code pipes do not create fake columns");
        Check(FinalAnswerView.Split("A | B\n--- | :---:\nx | y").Single().RichHtml!.Contains("<td>x</td><td>y</td>"), "Markdown tables without outer pipes supported");
        var safe = FinalAnswerView.Split("| Literal | Link |\n| --- | --- |\n| <img src=x> & token=PRIVATE-CANARY | [source](https://example.invalid/?x=1&y=2) |").Single().RichHtml!;
        Check(safe.Contains("&lt;img src=x&gt; &amp;") && !safe.Contains("PRIVATE-CANARY") && !safe.Contains("<img") && safe.Contains("href=\"https://example.invalid/?x=1&amp;y=2\""), "Literal HTML and link attributes escaped, credentials redacted before rich conversion");
        Check(FinalAnswerView.Split("| A | B |\n| nope | --- |\n| x | y |").All(p => p.RichHtml == null), "Malformed separators are ordinary text, not fabricated tables");
        Check(FinalAnswerView.Split("```text\nnot just a table\n" + table + "\n```").All(p => p.RichHtml == null), "Mixed code block contents stay literal code");
        var rows = Enumerable.Range(0, 600).Select(i => "| row-" + i + " | 🙂 " + new string('x', 30) + " |").ToArray();
        var longParts = FinalAnswerView.Split("| Key | Value |\n| --- | --- |\n" + string.Join('\n', rows));
        Check(longParts.Length > 1 && longParts.All(p => p.RichHtml != null && p.Text.StartsWith("| Key | Value |\n| --- | --- |") && p.Text.Length <= 3900 && Encoding.UTF8.GetByteCount(p.RichHtml!) <= 30000), "Long native tables split by rows with repeated headers and bounded UTF-16/UTF-8 payloads");
        Check(longParts.SelectMany(p => p.Text.Split('\n').Skip(2)).SequenceEqual(rows), "Every long table row delivered once, untruncated and in order");
        var wide = "| " + string.Join(" | ", Enumerable.Range(1, 21)) + " |\n| " + string.Join(" | ", Enumerable.Repeat("---", 21)) + " |";
        Check(FinalAnswerView.Split(wide).All(p => p.RichHtml == null && p.Entities.Any(e => e.type == "pre")), "Over-limit column count preserved in bounded classic code, no invalid rich request");
        var huge = "| A | B |\n| --- | --- |\n| " + new string('x', 8000) + " | y |";
        Check(FinalAnswerView.Split(huge).All(p => p.RichHtml == null) && string.Concat(FinalAnswerView.Split(huge).Select(p => p.Text)) == huge, "Oversized single row is preserved without truncation");
        var answer = new FinalAnswerState(); answer.Consider(table); answer.Complete(); answer.Parts[0].Message = 123;
        var restored = JsonSerializer.Deserialize<FinalAnswerState>(JsonSerializer.Serialize(answer))!; restored.Validate();
        Check(restored.Delivered && restored.Parts[0].Message == 123 && restored.Parts[0].Part.RichHtml == answer.Parts[0].Part.RichHtml, "Restart preserves confirmed native table ID and exact HTML without resend");
        var legacy = JsonSerializer.Deserialize<AnswerPart>("{\"Text\":\"old final\",\"Entities\":[]}")!;
        Check(legacy.RichHtml == null && Telegram.AnswerMethod(legacy) == "sendMessage", "Existing saved classic receipts remain backward-compatible");
        restored.Parts[0].Part = restored.Parts[0].Part with { RichHtml = "<p>tampered</p>" };
        bool refused = false; try { restored.Validate(); } catch (InvalidDataException) { refused = true; }
        Check(refused, "Saved rich HTML must match deterministic renderer, not arbitrary markup");
        return checks;
    }
}
