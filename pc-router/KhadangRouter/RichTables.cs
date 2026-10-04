using System.Net;
using System.Text;
using System.Text.RegularExpressions;

namespace KhadangRouter;

// Display only. Literal model HTML is escaped; only locally generated text/table
// tags go to sendRichMessage. Real code stays on sendMessage for client parity.
internal static class RichTables
{
    private sealed record Segment(string Kind, string Text);
    private const int HtmlBudget = 30000; // below Telegram's 32768 rich-message limit
    private static readonly Regex Fence = new(@"^\s{0,3}(`{3,}|~{3,})(.*)$");
    private static readonly Regex Separator = new(@"^:?-{2,}:?$");
    private static readonly Regex InlinePattern = new(@"`([^`\n]+)`|\[([^\]\n]+)\]\((https?://[^)\s]+|tg://[^)\s]+)\)|\*\*(.+?)\*\*|__(.+?)__|~~(.+?)~~|(?<![\w*])\*([^*\n]+)\*(?![\w*])");

    internal static AnswerPart[] Split(string markdown)
    {
        var segments = Segments(markdown);
        if (!segments.Any(s => s.Kind == "table")) return FinalAnswerView.SplitClassic(markdown);
        var result = new List<AnswerPart>(); var group = "";
        foreach (var segment in segments)
        {
            if (segment.Kind == "code") { Flush(); result.AddRange(FinalAnswerView.SplitClassic(segment.Text)); continue; }
            if (segment.Kind == "table")
            {
                var chunks = TableChunks(segment.Text);
                if (chunks == null)
                {
                    // A single over-limit row or >20 columns cannot be expressed
                    // safely. Preserve ALL content as classic pre, never truncate.
                    Flush(); result.AddRange(FinalAnswerView.SplitClassic("```\n" + segment.Text + "\n```")); continue;
                }
                foreach (var chunk in chunks) Add(chunk);
            }
            else foreach (var chunk in TextChunks(segment.Text)) Add(chunk);
        }
        Flush();
        if (result.Count > 256) throw new InvalidDataException("Final answer exceeds bounded delivery count; native history retained");
        return result.ToArray();

        void Add(string value)
        {
            var next = group.Length == 0 ? value : group + "\n\n" + value;
            if (group.Length != 0 && !Fits(next)) { Flush(); next = value; }
            group = next;
        }
        void Flush()
        {
            if (string.IsNullOrWhiteSpace(group)) { group = ""; return; }
            if (TryRender(group, out var html)) result.Add(new(group, [], html));
            else result.AddRange(FinalAnswerView.SplitClassic(group));
            group = "";
        }
    }

    internal static bool TryRender(string markdown, out string html)
    {
        var segments = Segments(markdown);
        return Render(segments, out html) && segments.Any(s => s.Kind == "table") && markdown.Length is > 0 and <= 3900;
    }
    private static bool Fits(string markdown) => markdown.Length <= 3900 && Render(Segments(markdown), out _);
    private static bool Render(List<Segment> segments, out string html)
    {
        var output = new StringBuilder(); int blocks = 0; html = "";
        foreach (var segment in segments)
        {
            if (segment.Kind == "code") return false;
            if (segment.Kind == "table")
            {
                var lines = segment.Text.Split('\n'); var header = Cells(lines[0]);
                if (header.Length > 20) return false;
                output.Append("<table bordered striped><thead><tr>");
                foreach (var cell in header) output.Append("<th>").Append(Inline(cell)).Append("</th>");
                output.Append("</tr></thead><tbody>"); blocks += header.Length + 3;
                foreach (var line in lines.Skip(2))
                {
                    var cells = Cells(line); output.Append("<tr>");
                    foreach (var cell in cells) output.Append("<td>").Append(Inline(cell)).Append("</td>");
                    output.Append("</tr>"); blocks += cells.Length + 1;
                }
                output.Append("</tbody></table>");
            }
            else
            {
                foreach (var paragraph in Regex.Split(segment.Text.Trim('\n'), @"\n\s*\n").Where(p => p.Length != 0))
                {
                    output.Append("<p>");
                    var lines = paragraph.Split('\n');
                    for (int i = 0; i < lines.Length; i++)
                    {
                        if (i != 0) output.Append("<br>");
                        var heading = Regex.Match(lines[i], @"^\s{0,3}#{1,6}\s+(.+)$");
                        if (heading.Success) output.Append("<b>").Append(Inline(heading.Groups[1].Value)).Append("</b>");
                        else output.Append(Inline(Regex.Replace(lines[i], @"^(\s*)[-*+]\s+", "$1• ")));
                    }
                    output.Append("</p>"); blocks++;
                }
            }
            if (blocks > 450 || Encoding.UTF8.GetByteCount(output.ToString()) > HtmlBudget) return false;
        }
        html = output.ToString(); return html.Length != 0;
    }

    private static string Inline(string input)
    {
        var result = new StringBuilder(); int last = 0;
        foreach (Match match in InlinePattern.Matches(input))
        {
            result.Append(WebUtility.HtmlEncode(input[last..match.Index]));
            int group = match.Groups[1].Success ? 1 : match.Groups[2].Success ? 2 : match.Groups[4].Success ? 4 : match.Groups[5].Success ? 5 : match.Groups[6].Success ? 6 : 7;
            var tag = group switch { 1 => "code", 2 => "a", 4 or 5 => "b", 6 => "s", _ => "i" };
            result.Append('<').Append(tag);
            if (group == 2) result.Append(" href=\"").Append(WebUtility.HtmlEncode(match.Groups[3].Value)).Append('"');
            result.Append('>').Append(WebUtility.HtmlEncode(match.Groups[group].Value)).Append("</").Append(tag).Append('>');
            last = match.Index + match.Length;
        }
        return result.Append(WebUtility.HtmlEncode(input[last..])).ToString();
    }

    private static List<Segment> Segments(string markdown)
    {
        var lines = markdown.Split('\n'); var result = new List<Segment>(); var text = new List<string>();
        for (int i = 0; i < lines.Length;)
        {
            var fence = Fence.Match(lines[i]);
            if (fence.Success)
            {
                Flush(); int start = i++; var delimiter = fence.Groups[1].Value;
                while (i < lines.Length && !Regex.IsMatch(lines[i], @"^\s{0,3}" + Regex.Escape(delimiter[0].ToString()) + "{" + delimiter.Length + @",}\s*$")) i++;
                bool closed = i < lines.Length;
                var content = lines[(start + 1)..i];
                if (closed && ReadTable(content, 0, out var end) && end == content.Length)
                    result.Add(new("table", string.Join('\n', content)));
                else
                {
                    // Normalize alternate fences for the existing classic parser.
                    result.Add(new("code", "```" + fence.Groups[2].Value.Trim() + "\n" + string.Join('\n', content) + "\n```"));
                }
                if (closed) i++;
            }
            else if (ReadTable(lines, i, out var end))
            {
                Flush(); result.Add(new("table", string.Join('\n', lines[i..end]))); i = end;
            }
            else text.Add(lines[i++]);
        }
        Flush(); return result;
        void Flush()
        {
            var value = string.Join('\n', text).Trim('\n');
            if (!string.IsNullOrWhiteSpace(value)) result.Add(new("text", value));
            text.Clear();
        }
    }
    private static bool ReadTable(string[] lines, int start, out int end)
    {
        end = start;
        if (start + 1 >= lines.Length || !lines[start].Contains('|')) return false;
        var header = Cells(lines[start]); var separator = Cells(lines[start + 1]);
        if (header.Length == 0 || header.Length != separator.Length || !separator.All(c => Separator.IsMatch(c))) return false;
        end = start + 2;
        while (end < lines.Length && lines[end].Contains('|') && Cells(lines[end]).Length == header.Length) end++;
        return true;
    }
    private static string[] Cells(string line)
    {
        line = line.Trim(); var cells = new List<string>(); var value = new StringBuilder(); int backticks = 0;
        for (int i = 0; i < line.Length; i++)
        {
            if (line[i] == '\\' && i + 1 < line.Length && line[i + 1] == '|') { value.Append('|'); i++; continue; }
            if (line[i] == '`')
            {
                int count = 1; while (i + count < line.Length && line[i + count] == '`') count++;
                backticks = backticks == count ? 0 : backticks == 0 ? count : backticks;
                value.Append('`', count); i += count - 1; continue;
            }
            if (line[i] == '|' && backticks == 0) { cells.Add(value.ToString().Trim()); value.Clear(); }
            else value.Append(line[i]);
        }
        cells.Add(value.ToString().Trim());
        if (line.StartsWith('|')) cells.RemoveAt(0);
        if (line.EndsWith('|') && cells.Count != 0 && cells[^1].Length == 0) cells.RemoveAt(cells.Count - 1);
        return cells.ToArray();
    }
    private static List<string>? TableChunks(string table)
    {
        var lines = table.Split('\n'); var header = string.Join('\n', lines[..2]);
        if (!Fits(header)) return null;
        var result = new List<string>(); var current = header;
        foreach (var row in lines.Skip(2))
        {
            if (!Fits(header + "\n" + row)) return null;
            if (!Fits(current + "\n" + row)) { result.Add(current); current = header; }
            current += "\n" + row;
        }
        result.Add(current); return result;
    }
    private static IEnumerable<string> TextChunks(string text)
    {
        for (int start = 0; start < text.Length;)
        {
            int end = Math.Min(text.Length, start + 3900);
            if (end < text.Length)
            {
                if (char.IsLowSurrogate(text[end])) end--;
                int newline = text.LastIndexOf('\n', end - 1, end - start);
                if (newline > start + 1950) end = newline + 1;
            }
            yield return text[start..end]; start = end;
        }
    }
}
