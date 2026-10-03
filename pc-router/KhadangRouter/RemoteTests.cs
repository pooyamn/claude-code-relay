using System.Text.Json;

namespace KhadangRouter;

public static class RemoteTests
{
    private static JsonElement Json(object value) => JsonSerializer.SerializeToElement(value);
    private static JsonElement Status(string state = "connected") => Json(new { status = state,
        installationId = "PRIVATE-INSTALLATION", environmentId = state == "connected" ? "PRIVATE-ENVIRONMENT" : null,
        serverName = "PRIVATE-HOST", pairingToken = "PRIVATE-TOKEN" });
    public static async Task<int> Run()
    {
        int checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        foreach (var state in new[] { "disabled", "connecting", "connected", "errored" })
        {
            var parsed = NativeRemote.Parse(Status(state), 123, DateTimeOffset.UtcNow);
            Check(parsed.State == state && parsed.NativePid == 123 && parsed.InstallationFingerprint!.Length == 64,
                "Native remote status preserves process provenance");
            Check(!JsonSerializer.Serialize(parsed).Contains("PRIVATE-"), "Native remote identities/tokens/host are not mirrored");
        }
        foreach (var raw in new[] { "null", "{}", "{\"status\":\"connected\",\"installationId\":\"x\",\"serverName\":\"host\"}",
            "{\"status\":false}", "{\"status\":\"connected\",\"status\":\"disabled\"}",
            "{\"status\":\"idle\",\"installationId\":\"x\",\"serverName\":\"host\"}",
            "{\"status\":\"disabled\",\"installationId\":\"\",\"serverName\":\"host\"}" })
        {
            try { NativeRemote.Parse(JsonDocument.Parse(raw).RootElement, 123, DateTimeOffset.UtcNow); throw new Exception("Bad remote status accepted"); }
            catch (Exception error) when (error is InvalidDataException or InvalidOperationException or KeyNotFoundException) { checks++; }
        }
        foreach (var mode in new[] { "normal", "race", "failure", "malformed", "cancel" })
        {
            var remote = new NativeRemote(); var rpc = new Fake(mode);
            try { await remote.Read(rpc, CancellationToken.None); Check(mode != "cancel", "Cancellation not suppressed"); }
            catch (OperationCanceledException) { Check(mode == "cancel", "Remote read propagates cancellation"); }
            Check(remote.Snapshot.State == (mode == "normal" ? "connected" : mode == "race" ? "disabled" : "unavailable"),
                "Read cannot override newer status or infer connection after failure");
            Check(rpc.Calls.Count == 1 && rpc.Calls[0].Method == "remoteControl/status/read" && !rpc.Calls[0].Effect,
                "Remote status is one read; no enable/pair/model retry");
            remote.Observe(Json(new { id = 4, method = "remoteControl/status/changed", @params = Status() }), 123);
            remote.Observe(Json(new { method = "account/updated", @params = new { } }), 123);
            Check(remote.Snapshot.State == "unavailable" && !remote.Render().Contains("PRIVATE-"), "Account update clears prior remote identity");
        }
        var binding = new Binding(-100123, 42, "LG", "C:\\Workspace\\lg-magic", "exact-thread");
        foreach (var mode in new[] { "normal", "second-page", "truncated", "wrong-thread", "wrong-cwd", "bad-cursor" })
        {
            var rpc = new Fake(mode); var seen = await NativeVisibility.Read(rpc, binding, CancellationToken.None);
            Check(rpc.Calls.All(c => !c.Effect && c.Method is "thread/read" or "thread/list"), "Visibility never resumes, repairs metadata or starts a turn");
            if (mode is "wrong-thread" or "wrong-cwd" or "bad-cursor") Check(seen.State == "unavailable", "Unverified visibility fails closed");
            else
            {
                Check(seen.Source == "appServer" && seen.DefaultSources == new ThreadListObservation(false, mode != "truncated", mode == "truncated" ? 2 : 1),
                    "Default source absence distinguishes exhausted/truncated listing");
                Check(seen.AppServerSource!.Found && seen.AppServerSource.Pages == (mode == "second-page" ? 2 : 1), "Explicit appServer source finds exact stored thread");
                Check(rpc.Calls.Where(c => c.Method == "thread/list").All(c => c.Params.GetProperty("useStateDbOnly").GetBoolean()), "Visibility lists state DB without rollout repair");
            }
        }
        return checks;
    }
    private sealed class Fake(string mode) : INative
    {
        public uint Pid => 123;
        public event Action<JsonElement>? Notification;
        public List<(string Method, bool Effect, JsonElement Params)> Calls = [];
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new Exception("Unexpected remote reply");
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            var p = Json(parameters); Calls.Add((method, effect, p));
            if (method == "remoteControl/status/read")
            {
                if (mode == "failure") throw new IOException("Private transport failed");
                if (mode == "cancel") throw new OperationCanceledException();
                if (mode == "race") Notification?.Invoke(Json(new { method = "remoteControl/status/changed", @params = Status("disabled") }));
                return Task.FromResult(mode == "malformed" ? Json(new { status = true }) : Status());
            }
            if (method == "thread/read") return Task.FromResult(Json(new { thread = new { id = mode == "wrong-thread" ? "foreign" : "exact-thread",
                cwd = mode == "wrong-cwd" ? "C:\\Foreign" : "C:\\Workspace\\lg-magic", source = "appServer", preview = "PRIVATE-HISTORY" } }));
            if (method != "thread/list") throw new Exception("Unexpected remote mutation");
            bool app = p.TryGetProperty("sourceKinds", out var kinds);
            if (app && (kinds.GetArrayLength() != 1 || kinds[0].GetString() != "appServer")) throw new Exception("Unexpected source filter");
            bool next = mode is "truncated" or "bad-cursor" && !app || mode == "second-page" && app && !p.TryGetProperty("cursor", out _);
            return Task.FromResult(Json(new { data = app && !next ? new[] { new { id = "exact-thread", preview = "PRIVATE-HISTORY" } } : [],
                nextCursor = next ? mode == "bad-cursor" ? "repeated" : Calls.Count.ToString() : null }));
        }
    }
}
