using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace KhadangRouter;

public sealed record QuotaWindowView(int UsedPercent, long? DurationMinutes, long? ResetsAt);
public sealed record QuotaBucketView(string Id, QuotaWindowView? Primary, QuotaWindowView? Secondary,
    bool? SpendControlReached, string? ReachedType);
public sealed record QuotaObservation(string Schema, string State, DateTimeOffset? ObservedAt,
    string? AccountFingerprint, bool AccountVerified, bool? OrdinaryUsageAllowed,
    IReadOnlyList<QuotaBucketView> Buckets, bool ReserveEnforced = false);

// Observation only. Percentages are not bounded turn costs, a complete
// account/model pool mapping, stop evidence or an all-source pre-turn fence.
// Never turn this view into a ModelAdmission grant or silently buy/reset quota.
public sealed class NativeQuota
{
    private readonly object gate = new();
    private readonly SemaphoreSlim reads = new(1, 1);
    private long revision;
    private QuotaObservation value = Empty("unavailable");
    private static QuotaObservation Empty(string state) => new("ccrelay.native_quota_observation.v1", state, null, null, false, null, []);
    public QuotaObservation Snapshot { get { lock (gate) return value; } }
    public void Invalidate()
    {
        lock (gate) { revision++; value = value with { State = "stale", AccountVerified = false }; }
    }
    public async Task Read(INative rpc, CancellationToken stop)
    {
        await reads.WaitAsync(stop);
        long started; lock (gate) started = revision;
        void Updated(JsonElement message)
        {
            if (!message.TryGetProperty("id", out _) && message.TryGetProperty("method", out var method) &&
                method.ValueKind == JsonValueKind.String && method.GetString() is "account/updated" or "account/rateLimits/updated") Invalidate();
        }
        rpc.Notification += Updated;
        try
        {
            // Bracket usage with the active managed account; don't extract an
            // ID from auth.json, an email, a token or somebody else's process.
            var before = Account(await rpc.Call("account/read", new { refreshToken = false }, stop, effect: false));
            var usage = await rpc.Call("account/rateLimits/read", new { }, stop, effect: false);
            var after = Account(await rpc.Call("account/read", new { refreshToken = false }, stop, effect: false));
            if (before != after) throw new InvalidDataException("Native account changed during quota read");
            var parsed = Parse(usage, before, DateTimeOffset.UtcNow);
            lock (gate) { if (revision == started) { revision++; value = parsed; } }
        }
        catch (Exception error) when (error is NativeRejected or IOException or TimeoutException or InvalidDataException or
            InvalidOperationException or KeyNotFoundException or JsonException)
        {
            // A failed read is not an uncertain external action. Keep owner
            // controls/steering usable, discard availability, never retry here.
            lock (gate) { if (revision == started) { revision++; value = Empty("unavailable"); } }
        }
        catch (OperationCanceledException)
        {
            lock (gate) { if (revision == started) { revision++; value = Empty("unavailable"); } }
            throw;
        }
        finally { rpc.Notification -= Updated; reads.Release(); }
    }
    public static string? Account(JsonElement result)
    {
        var account = result.GetProperty("account");
        if (account.ValueKind != JsonValueKind.Object || account.GetProperty("type").GetString() != "chatgpt")
            throw new InvalidDataException("Managed ChatGPT account required");
        if (!result.TryGetProperty("workspaceRouting", out var routing) || routing.ValueKind == JsonValueKind.Null) return null;
        if (routing.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Invalid native account routing");
        return Fingerprint(routing.GetProperty("chatgptAccountId"));
    }
    private static string Fingerprint(JsonElement id)
    {
        if (id.ValueKind != JsonValueKind.String || string.IsNullOrWhiteSpace(id.GetString()) || id.GetString()!.Length > 256)
            throw new InvalidDataException("Invalid native account identity");
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(id.GetString()!)));
    }
    public static QuotaObservation Parse(JsonElement result, string? account, DateTimeOffset observedAt)
    {
        if (result.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Invalid quota reply");
        var backendAccount = result.TryGetProperty("accountId", out var id) && id.ValueKind != JsonValueKind.Null ? Fingerprint(id) : null;
        if (backendAccount != null && account != null && backendAccount != account)
            throw new InvalidDataException("Quota belongs to another account");
        var legacy = result.GetProperty("rateLimits");
        var buckets = new List<QuotaBucketView>();
        if (result.TryGetProperty("rateLimitsByLimitId", out var map) && map.ValueKind != JsonValueKind.Null)
        {
            if (map.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Invalid quota bucket map");
            var keys = new HashSet<string>(StringComparer.Ordinal);
            foreach (var item in map.EnumerateObject())
            {
                if (!keys.Add(item.Name) || keys.Count > 16) throw new InvalidDataException("Duplicate or excessive quota buckets");
                buckets.Add(Bucket(item.Value, item.Name));
            }
        }
        // The single bucket is an alias, not another independent allowance.
        // A disagreeing alias is not evidence of extra available capacity.
        var single = Bucket(legacy, null);
        var alias = buckets.FirstOrDefault(b => b.Id == single.Id);
        if (alias != null && alias != single) throw new InvalidDataException("Quota alias disagrees with bucket map");
        if (alias == null) buckets.Add(single);
        return new("ccrelay.native_quota_observation.v1", "observed", observedAt, account,
            account != null && backendAccount == account, OptionalBool(result, "ordinaryUsageAllowed"), buckets.AsReadOnly());
    }
    private static QuotaBucketView Bucket(JsonElement value, string? key)
    {
        if (value.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Invalid quota bucket");
        var supplied = value.TryGetProperty("limitId", out var id) && id.ValueKind != JsonValueKind.Null ? id.GetString() : null;
        if (supplied != null && key != null && supplied != key) throw new InvalidDataException("Quota key/identity mismatch");
        var name = key ?? supplied ?? "legacy";
        if (!Regex.IsMatch(name, "\\A[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\\z")) throw new InvalidDataException("Unsafe quota label");
        string? reached = null;
        if (value.TryGetProperty("rateLimitReachedType", out var reachedValue) && reachedValue.ValueKind != JsonValueKind.Null)
        {
            reached = reachedValue.GetString();
            if (reached is not ("rate_limit_reached" or "workspace_owner_credits_depleted" or "workspace_member_credits_depleted" or
                "workspace_owner_usage_limit_reached" or "workspace_member_usage_limit_reached"))
                throw new InvalidDataException("Unrecognized native reached type");
        }
        return new(name, Window(value, "primary"), Window(value, "secondary"), OptionalBool(value, "spendControlReached"), reached);
    }
    private static bool? OptionalBool(JsonElement value, string name)
    {
        if (!value.TryGetProperty(name, out var field) || field.ValueKind == JsonValueKind.Null) return null;
        if (field.ValueKind is not (JsonValueKind.True or JsonValueKind.False)) throw new InvalidDataException("Invalid quota permission");
        return field.GetBoolean();
    }
    private static QuotaWindowView? Window(JsonElement bucket, string name)
    {
        if (!bucket.TryGetProperty(name, out var window) || window.ValueKind == JsonValueKind.Null) return null;
        if (window.ValueKind != JsonValueKind.Object) throw new InvalidDataException("Invalid quota window");
        var used = window.GetProperty("usedPercent");
        if (used.ValueKind != JsonValueKind.Number || !used.TryGetInt32(out var percent) || percent < 0 || percent > 100)
            throw new InvalidDataException("Invalid quota percentage");
        long? Integer(string field, long max)
        {
            if (!window.TryGetProperty(field, out var item) || item.ValueKind == JsonValueKind.Null) return null;
            if (item.ValueKind != JsonValueKind.Number || !item.TryGetInt64(out var number) || number <= 0 || number > max)
                throw new InvalidDataException("Invalid quota window metadata");
            return number;
        }
        return new(percent, Integer("windowDurationMins", int.MaxValue), Integer("resetsAt", 253402300799));
    }
    public string Render()
    {
        var snapshot = Snapshot;
        const string reserve = "Automation target: keep 10% for Pouya; not yet enforced.";
        if (snapshot.State != "observed") return "Native subscription limits " + snapshot.State + ". No availability inferred.\n" + reserve;
        var lines = new List<string> { "Native subscription limits (read-only, " + snapshot.ObservedAt!.Value.ToString("MM-dd HH:mm 'UTC'") + "):" };
        foreach (var bucket in snapshot.Buckets)
        {
            void Add(string slot, QuotaWindowView? window)
            {
                if (window == null) { lines.Add(bucket.Id + " " + slot + ": unavailable"); return; }
                lines.Add(bucket.Id + " " + slot + ": " + window.UsedPercent + "% used" +
                    (window.DurationMinutes is { } duration ? " / " + duration + "m window" : " / unknown window") +
                    (window.ResetsAt is { } reset ? "; reset " + DateTimeOffset.FromUnixTimeSeconds(reset).ToString("MM-dd HH:mm 'UTC'") : "; reset unknown"));
            }
            Add("primary", bucket.Primary); Add("secondary", bucket.Secondary);
            if (bucket.SpendControlReached == true || bucket.ReachedType != null) lines.Add(bucket.Id + ": backend reports a limit reached.");
        }
        lines.Add("Included-usage permission: " + (snapshot.OrdinaryUsageAllowed is { } allowed ? allowed ? "allowed" : "not allowed" : "unavailable"));
        if (!snapshot.AccountVerified) lines.Add("Account binding unverified; not admission evidence.");
        lines.Add(reserve);
        return string.Join('\n', lines);
    }
}
