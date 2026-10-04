using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace KhadangRouter;

public sealed record GoalCommand(string Action, string? Objective = null)
{
    public static GoalCommand Parse(string argument)
    {
        argument = argument.Trim();
        var action = argument.ToLowerInvariant();
        if (action is "" or "status") return new("status");
        if (action is "pause" or "resume" or "clear") return new(action);
        var parts = argument.Split((char[]?)null, 2, StringSplitOptions.RemoveEmptyEntries);
        if (parts[0].Equals("set", StringComparison.OrdinalIgnoreCase))
        {
            if (parts.Length != 2) throw new InvalidDataException("Use /goal set <objective>.");
            argument = parts[1].Trim();
        }
        if (argument.Length == 0 || argument.EnumerateRunes().Count() > 4000)
            throw new InvalidDataException("Goal objective must contain 1–4000 characters.");
        return new("set", argument);
    }
}

// Native evidence only. A late RPC reply must not overwrite a newer native
// notification. A persisted observation is not asserted current after restart.
public sealed class NativeGoal(string threadId)
{
    private readonly object gate = new();
    private JsonElement? value;
    private bool known;
    private string? error;
    private long revision;
    private DateTimeOffset? observedAt;
    public (JsonElement? Goal, bool Known, DateTimeOffset? ObservedAt) Snapshot { get { lock (gate) return (value, known && error == null, observedAt); } }
    public long Revision { get { lock (gate) return revision; } }
    public JsonElement? Value { get { lock (gate) return value; } }
    public bool Known { get { lock (gate) return known && error == null; } }
    private static readonly string[] Statuses = ["active", "paused", "blocked", "usageLimited", "budgetLimited", "complete"];

    public bool Apply(JsonElement goal, long? expectedRevision = null)
    {
        if (goal.ValueKind != JsonValueKind.Null)
        {
            if (goal.ValueKind != JsonValueKind.Object || !goal.TryGetProperty("threadId", out var id) ||
                id.ValueKind != JsonValueKind.String || id.GetString() != threadId ||
                !goal.TryGetProperty("objective", out var objective) || objective.ValueKind != JsonValueKind.String ||
                string.IsNullOrWhiteSpace(objective.GetString()) || objective.GetString()!.EnumerateRunes().Count() > 4000 ||
                !goal.TryGetProperty("status", out var status) || status.ValueKind != JsonValueKind.String || !Statuses.Contains(status.GetString()))
                throw new InvalidDataException("Native goal identity/schema mismatch");
            foreach (var field in new[] { "tokensUsed", "timeUsedSeconds", "createdAt", "updatedAt" })
                if (!goal.TryGetProperty(field, out var number) || number.ValueKind != JsonValueKind.Number || !number.TryGetInt64(out var total) || total < 0)
                    throw new InvalidDataException("Invalid native goal accounting");
            if (goal.TryGetProperty("tokenBudget", out var budget) && budget.ValueKind != JsonValueKind.Null &&
                (budget.ValueKind != JsonValueKind.Number || !budget.TryGetInt64(out var maximum) || maximum <= 0)) throw new InvalidDataException("Invalid native goal budget");
        }
        lock (gate)
        {
            if (expectedRevision != null && expectedRevision != revision) return false;
            value = goal.ValueKind == JsonValueKind.Null ? null : goal.Clone(); known = true; error = null; observedAt = DateTimeOffset.UtcNow; revision++; return true;
        }
    }
    public void Unavailable(long expectedRevision)
    {
        lock (gate) { if (revision == expectedRevision) { error = "status unavailable (last observation not current)"; revision++; } }
    }
    public string? Footer
    {
        get
        {
            lock (gate)
            {
                if (error != null) return error;
                if (!known) return "status not yet verified";
                if (value == null) return null;
                var status = value.Value.GetProperty("status").GetString()!;
                var objective = Literal(value.Value.GetProperty("objective").GetString()!);
                var prefix = status + " — "; var limit = Math.Max(1, 160 - prefix.Length);
                if (objective.Length > limit)
                {
                    var end = limit - 1;
                    if (end > 0 && char.IsHighSurrogate(objective[end - 1])) end--;
                    objective = objective[..end] + "…";
                }
                return prefix + objective;
            }
        }
    }
    public static string Literal(string text)
    {
        var clean = new StringBuilder();
        foreach (var rune in text.EnumerateRunes())
            clean.Append(Rune.GetUnicodeCategory(rune) is UnicodeCategory.Control or UnicodeCategory.Format ? " " : rune.ToString());
        text = Regex.Replace(clean.ToString(), @"\s+", " ").Trim();
        return Redact(text);
    }
    public static string Redact(string text)
    {
        text = Regex.Replace(text, @"\b(?:bot\d+:[A-Za-z0-9_-]+|sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]+)\b", "[REDACTED]");
        text = Regex.Replace(text, @"(?i)(Bearer\s+)\S+", "$1[REDACTED]");
        return Regex.Replace(text, "(?i)([\\w-]*(?:token|password|secret|api[_-]?key)[\\w-]*\\s*[=:]\\s*)(?:\"[^\"]*\"|'[^']*'|[^\\s,;]+)", "$1[REDACTED]");
    }
}
