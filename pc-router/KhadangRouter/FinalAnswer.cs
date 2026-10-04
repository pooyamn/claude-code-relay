using System.Text;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace KhadangRouter;

public sealed record AnswerEntity(string type, int offset, int length,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] string? url = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] string? language = null);
public sealed record AnswerPart(string Text, AnswerEntity[] Entities,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] string? RichHtml = null);

internal sealed class FinalDelivery
{
    public AnswerPart Part { get; set; } = new("", []);
    public int? Message { get; set; }
    public bool SendUnknown { get; set; }
}

internal sealed class FinalAnswerState
{
    public string Candidate { get; set; } = "";
    public bool Explicit { get; set; }
    public bool Completed { get; set; }
    public List<FinalDelivery> Parts { get; set; } = [];
    [JsonIgnore] public bool Delivered => !Completed || Parts.All(p => p.Message != null && !p.SendUnknown);
    public void Consider(string text, bool authoritative = false)
    {
        if (Completed || string.IsNullOrWhiteSpace(text) || Explicit && !authoritative) return;
        if (text.Length > FinalAnswerView.MaximumCharacters) throw new InvalidDataException("Final answer exceeds delivery bound; native history retained");
        Candidate = text; Explicit = authoritative;
    }
    public void Complete()
    {
        if (Completed) return;
        Parts = FinalAnswerView.Split(Candidate).Select(part => new FinalDelivery { Part = part }).ToList();
        Completed = true;
    }
    public void Validate()
    {
        if (Candidate.Length > FinalAnswerView.MaximumCharacters || Parts.Count > 256 || !Completed && Parts.Count != 0 ||
            Parts.Any(p => p.Part.Text.Length is < 1 or > 3900 || p.Message is <= 0 ||
                p.Part.Entities.Any(e => e.offset < 0 || e.length <= 0 || e.offset + (long)e.length > p.Part.Text.Length ||
                    e.type is not ("pre" or "code" or "bold" or "italic" or "strikethrough" or "text_link")) ||
                p.Part.RichHtml != null && (p.Part.Entities.Length != 0 ||
                    !RichTables.TryRender(p.Part.Text, out var html) || html != p.Part.RichHtml)))
            throw new InvalidDataException("Invalid saved final-answer receipt");
    }
}

// Display-only Markdown conversion. Native text never becomes a bot command.
// Explicit UTF-16 entities avoid HTML escaping/nesting errors and preserve links.
public static class FinalAnswerView
{
    public const int MaximumCharacters = 262144;
    public static AnswerPart[] Split(string markdown)
    {
        if (markdown.Length > MaximumCharacters) throw new InvalidDataException("Final answer too large");
        return RichTables.Split(NativeGoal.Redact(markdown).Replace("\r\n", "\n"));
    }
    internal static AnswerPart[] SplitClassic(string markdown)
    {
        if (markdown.Length > MaximumCharacters) throw new InvalidDataException("Final answer too large");
        if (string.IsNullOrWhiteSpace(markdown)) return [];
        var body = new StringBuilder(); var entities = new List<AnswerEntity>();
        var lines = NativeGoal.Redact(markdown).Replace("\r\n", "\n").Split('\n');
        bool fenced = false; int codeStart = 0; string? language = null;
        for (int i = 0; i < lines.Length; i++)
        {
            var line = lines[i];
            var fence = Regex.Match(line, @"^\s{0,3}```([^`]*)$");
            if (fence.Success)
            {
                if (fenced) AddCode();
                else { fenced = true; codeStart = body.Length; language = fence.Groups[1].Value.Trim(); }
                continue;
            }
            if (fenced) { body.Append(line).Append('\n'); continue; }
            // Tables remain horizontally scrollable code blocks, not a block
            // around the entire answer. Prose before/after is normal text.
            if (line.TrimStart().StartsWith('|') && i + 1 < lines.Length && Regex.IsMatch(lines[i + 1], @"^\s*\|?[\s:|-]+\|?\s*$"))
            {
                var start = body.Length;
                do { body.Append(lines[i++]).Append('\n'); } while (i < lines.Length && lines[i].TrimStart().StartsWith('|'));
                i--; entities.Add(new("pre", start, body.Length - start)); continue;
            }
            var heading = Regex.Match(line, @"^\s{0,3}#{1,6}\s+(.+)$");
            var before = body.Length;
            Inline(heading.Success ? heading.Groups[1].Value : Regex.Replace(line, @"^(\s*)[-*+]\s+", "$1• "));
            if (heading.Success && body.Length > before) entities.Add(new("bold", before, body.Length - before));
            if (i < lines.Length - 1) body.Append('\n');
        }
        if (fenced) AddCode();
        var text = body.ToString().TrimEnd('\n');
        var result = new List<AnswerPart>();
        for (int start = 0; start < text.Length;)
        {
            int end = Math.Min(text.Length, start + 3900);
            if (end < text.Length)
            {
                if (char.IsLowSurrogate(text[end])) end--;
                var newline = text.LastIndexOf('\n', end - 1, end - start);
                if (newline >= start + 1950) end = newline + 1;
            }
            var spans = entities.Select(e => {
                var a = Math.Max(start, e.offset); var b = Math.Min(end, e.offset + e.length);
                return e with { offset = a - start, length = b - a };
            }).Where(e => e.length > 0).ToArray();
            result.Add(new(text[start..end], spans)); start = end;
        }
        return result.ToArray();

        void AddCode()
        {
            var length = body.Length - codeStart;
            if (length > 0) entities.Add(new("pre", codeStart, length, language: string.IsNullOrEmpty(language) ? null : language));
            fenced = false;
        }
        void Inline(string input)
        {
            var pattern = @"`([^`\n]+)`|\[([^\]\n]+)\]\((https?://[^)\s]+|tg://[^)\s]+)\)|\*\*(.+?)\*\*|__(.+?)__|~~(.+?)~~|(?<![\w*])\*([^*\n]+)\*(?![\w*])";
            int last = 0;
            foreach (Match match in Regex.Matches(input, pattern))
            {
                body.Append(input[last..match.Index]); var start = body.Length;
                int group = match.Groups[1].Success ? 1 : match.Groups[2].Success ? 2 : match.Groups[4].Success ? 4 : match.Groups[5].Success ? 5 : match.Groups[6].Success ? 6 : 7;
                var value = match.Groups[group].Value; body.Append(value);
                entities.Add(new(group switch { 1 => "code", 2 => "text_link", 4 or 5 => "bold", 6 => "strikethrough", _ => "italic" },
                    start, value.Length, group == 2 ? match.Groups[3].Value : null));
                last = match.Index + match.Length;
            }
            body.Append(input[last..]);
        }
    }
}
