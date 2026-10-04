using System.Text.Json;

namespace KhadangRouter;

public static class BubbleFormatTests
{
    public static int Run()
    {
        int checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        const string literal = "🙂 Tool: `<tag>&` ```\nWorking (1m 3s)\nGoal: active";
        var send = Telegram.BubbleSendParameters(-100123, 53, literal);
        var entity = Telegram.BubbleEntities(literal).Single();
        Check((string)send["text"] == literal && !send.ContainsKey("parse_mode"), "Code-block formatting never changes or escapes bubble text");
        Check(entity.type == "pre" && entity.offset == 0 && entity.length == literal.Length, "Whole bubble including tools/timer/goal is preformatted in UTF-16");
        Check((int)send["message_thread_id"] == 53 && (long)send["chat_id"] == -100123, "Formatted bubble retains exact destination");
        var edit = Telegram.BubbleEditParameters(-100123, 901, literal);
        Check((int)edit["message_id"] == 901 && (string)edit["text"] == literal, "Amendment preserves existing bubble message ID and text");
        Check(!Telegram.SendParameters(-100123, 53, literal).ContainsKey("entities"), "Ordinary control messages keep their existing plain formatting");
        Check(!Telegram.BubbleSendParameters(-5238984877, 0, literal).ContainsKey("message_thread_id"), "Whole-group bubble does not invent a topic");
        const string link = "Claude app: https://claude.ai/code/session-fixture";
        var text = "🙂 Tool output\n" + link + "\n\nWorking (0m 8s)";
        var entities = Telegram.BubbleEntities(text);
        Check(entities.Length == 3 && entities[0].type == "pre" && entities[1].type == "url" && entities[2].type == "pre", "App link stays tappable between two code-block segments of one message");
        Check(text.Substring(entities[1].offset, entities[1].length) == "https://claude.ai/code/session-fixture", "App URL span is correct after a non-BMP emoji");
        Check(entities[0].length == text.IndexOf(link, StringComparison.Ordinal) && text[entities[2].offset] == '\n', "Pre spans exclude the whole app-link line");
        var multiple = Telegram.BubbleEntities(link + "\n" + link);
        Check(multiple.Length == 2 && multiple.All(e => e.type == "url"), "Repeated app-link lines do not overlap pre entities");
        Check(Telegram.BubbleEntities("").Length == 0, "Empty text has no invalid zero-length entity");
        var bubble = new RollingBubble(); bubble.Append(new string('x', 9000) + "🙂\n" + link);
        var bounded = bubble.Render(TimeSpan.FromSeconds(8), "active");
        Check(bounded.Length <= 3900 && (string)Telegram.BubbleSendParameters(-100123, 53, bounded)["text"] == bounded,
            "Code-block entities add no characters to the existing rolling limit");
        var json = JsonSerializer.SerializeToElement(send);
        Check(json.GetProperty("entities")[0].GetProperty("type").GetString() == "pre" &&
            json.GetProperty("entities")[0].GetProperty("length").GetInt32() == literal.Length, "Wire entity names and UTF-16 lengths match Telegram API");
        return checks;
    }
}
