using System.Text.Json;

namespace KhadangRouter;

// Credential-free fixtures only. These do not attest Windows/WSL production.
public static class LinuxCodexRuntimeTests
{
    public static async Task<int> Run(RouterPolicy basePolicy)
    {
        int checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        void Denied(Action action, string name)
        { try { action(); throw new Exception(name); } catch (InvalidDataException) { checks++; } }
        var root = LinuxCodexRuntime.ProtectedRoot + "\\codex-connector-" + new string('a', 32);
        var files = LinuxCodexRuntime.PackageFiles.ToDictionary(name => name, _ => new string('b', 64), StringComparer.Ordinal);
        var runtime = new LinuxCodexRuntime(root, new string('c', 64), files);
        var policy = basePolicy with { LinuxWorkspaceRoot = LinuxCodexRuntime.WorkspaceRoot, LinuxCodex = runtime };
        policy.Validate(); Check(true, "Explicit Linux runtime is compatible with the existing PC-only policy");
        basePolicy.Validate(); Check(basePolicy.LinuxCodex == null, "Legacy policy does not activate a Linux runtime");
        foreach (var bad in new[] { @"C:\Users\pou\helper", root + "\\..", root.Replace("codex-connector", "migration-linux-transport"), root.ToUpperInvariant(), root + "\n" })
            Denied(() => (runtime with { PackageRoot = bad }).Validate(), "Unsafe connector code root accepted");
        foreach (var digest in new[] { "", new string('g', 64), new string('a', 63), new string('a', 65) })
            Denied(() => (runtime with { WslSha256 = digest }).Validate(), "Unpinned WSL image accepted");
        var missing = new Dictionary<string, string>(files); missing.Remove("relay_core/identity.py");
        Denied(() => (runtime with { FileSha256 = missing }).Validate(), "Unpinned transitive import accepted");
        var extra = new Dictionary<string, string>(files) { ["relay_core/broker.py"] = new string('d', 64) };
        Denied(() => (runtime with { FileSha256 = extra }).Validate(), "Deferred broker code smuggled into connector package");
        Denied(() => (policy with { LinuxWorkspaceRoot = "/Users/pouya/other" }).Validate(), "Unpreserved Linux workspace root accepted");
        var workspaces = new[] { LinuxCodexRuntime.WorkspaceRoot + "/web" };
        var arguments = runtime.Arguments(workspaces);
        Check(arguments.StartsWith("-d Ubuntu-24.04 -u pou --exec /usr/bin/python3 -I -B ") && arguments.Contains("/mnt/c/ProgramData/OracovaNativeRemote/codex-connector-") &&
            arguments.Contains(" --attest --workspace \"") && !arguments.Contains("--socket"), "Fixed ordinary-owner isolated connector argv; no daemon or endpoint override");
        Check(LinuxCodexRuntime.Quote("a\"b\\") == "\"a\\\"b\\\\\"", "Windows argv quoting preserves quotes and terminal backslashes");
        Denied(() => LinuxCodexRuntime.Quote("bad\nargument"), "Launch control character accepted");
        foreach (var paths in new[] { Array.Empty<string>(), new[] { workspaces[0], workspaces[0] }, new[] { "/tmp/repo" },
            new[] { workspaces[0] + "/.." }, new[] { workspaces[0] + "/" }, Enumerable.Range(0,257).Select(n => workspaces[0]+n).ToArray() })
            Denied(() => runtime.Arguments(paths), "Unattestable workspace set accepted");
        foreach (var key in new[] { "WSLENV", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CCRELAY_BOT_TOKEN", "CODEX_HOME", "CLAUDE_CONFIG_DIR" })
            Check(!WindowsOwnerProcess.AllowedDiagnosticVariable(key), "Provider/relay environment must not enter the Linux connector");

        var owner = new OwnerProcessObservation(321, basePolicy.OwnerSid, 1, false, 456);
        Dictionary<string, object> Metadata() => new() { ["uid"] = 1000, ["peerUid"] = 1000, ["peerPid"] = 789,
            ["peerGeneration"] = "12345", ["socket"] = LinuxCodexRuntime.Socket, ["socketEndpoint"] = LinuxCodexRuntime.Socket,
            ["binarySha256"] = LinuxCodexRuntime.BinarySha256, ["credentialDenied"] = true, ["workspaces"] = workspaces };
        string Ready(Dictionary<string, object>? data = null) => JsonSerializer.Serialize(new { method = "ccrelay/transport/ready", @params = data ?? Metadata() });
        var observed = LinuxCodexChannel.ParseReady(Ready(), owner, workspaces);
        Check(observed.NativePid == 789 && observed.WindowsOwner.Pid == 321 && observed.NativeGeneration == "12345", "Linux native PID remains distinct from the owned Windows connector PID");
        foreach (var (key, value) in new (string, object)[] { ("uid",0), ("peerUid",0), ("peerPid",0), ("peerPid",-1),
            ("peerGeneration","0"), ("peerGeneration","12x"), ("peerGeneration",new string('1',33)), ("socket","/tmp/native.sock"),
            ("socketEndpoint","/tmp/other.sock"), ("binarySha256",new string('a',64)), ("credentialDenied",false),
            ("workspaces",new[] { workspaces[0]+"-other" }), ("workspaces",new[] { workspaces[0],workspaces[0] }) })
        {
            var data = Metadata(); data[key] = value;
            Denied(() => LinuxCodexChannel.ParseReady(Ready(data), owner, workspaces), "Mismatched native observation accepted");
        }
        var missingMetadata = Metadata(); missingMetadata.Remove("credentialDenied");
        Denied(() => LinuxCodexChannel.ParseReady(Ready(missingMetadata), owner, workspaces), "Missing actual denial evidence accepted");
        var extraMetadata = Metadata(); extraMetadata["role"] = "reviewer";
        Denied(() => LinuxCodexChannel.ParseReady(Ready(extraMetadata), owner, workspaces), "Role claim accepted in personal connector metadata");
        Denied(() => LinuxCodexChannel.ParseReady(Ready().Replace("\"uid\":1000", "\"uid\":1000,\"uid\":1000"), owner, workspaces), "Duplicate attestation keys accepted");
        Denied(() => LinuxCodexChannel.ParseReady("null", owner, workspaces), "Malformed attestation accepted");
        Denied(() => LinuxCodexChannel.ParseReady(new string('x',65537), owner, workspaces), "Unbounded attestation accepted");

        using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        foreach (var badOwner in new[] { owner with { Elevated = true }, owner with { Session = 0 }, owner with { Sid = "S-1-5-18" },
            owner with { Pid = 0 }, owner with { CreationTime = 0 } })
        {
            var fake = new FakeChannel(Ready());
            try { await LinuxCodexChannel.Accept(fake, () => badOwner, basePolicy.OwnerSid, workspaces, stop.Token); throw new Exception("Bad owner accepted"); }
            catch (InvalidDataException) { Check(fake.Disposed && fake.Writes.Count == 0 && fake.Reads == 0, "Wrong Windows owner fails before native I/O and closes owned connector"); }
        }
        var invalid = new FakeChannel("{}");
        try { await LinuxCodexChannel.Accept(invalid, () => owner, basePolicy.OwnerSid, workspaces, stop.Token); throw new Exception("Missing readiness accepted"); }
        catch (InvalidDataException) { Check(invalid.Disposed && invalid.Writes.Count == 0, "Failed readiness closes the connector before initialization"); }
        var valid = new FakeChannel(Ready(), "{\"id\":1,\"result\":{}}", Ready());
        var current = owner;
        await using (var wire = await LinuxCodexChannel.Accept(valid, () => current, basePolicy.OwnerSid, workspaces, stop.Token))
        {
            Check(wire.Pid == 789 && valid.Writes.Count == 0 && await wire.Read(stop.Token) == "{\"id\":1,\"result\":{}}", "Consume only connector readiness before forwarding unchanged native frames");
            await wire.Write("{}", stop.Token); Check(valid.Writes.SequenceEqual(new[] { "{}" }), "Native input is forwarded once without initialization/replay synthesis");
            try { await wire.Read(stop.Token); throw new Exception("Readiness became native event"); }
            catch (InvalidDataException) { checks++; }
            current = owner with { CreationTime = 457 };
            try { await wire.Write("{}", stop.Token); throw new Exception("Reused PID accepted"); }
            catch (InvalidDataException) { Check(valid.Writes.Count == 1, "Windows process generation changes stop input before another write"); }
        }
        Check(valid.Disposed, "Operational connector ownership is transferred and closed");
        var race = new FakeChannel(Ready()); int observations = 0;
        try { await LinuxCodexChannel.Accept(race, () => ++observations == 1 ? owner : owner with { CreationTime = 457 }, basePolicy.OwnerSid, workspaces, stop.Token); throw new Exception("Readiness owner race accepted"); }
        catch (InvalidDataException) { Check(race.Disposed && race.Writes.Count == 0, "Parent generation is bracketed around readiness"); }

        var reader = new NativeJsonlReader(new StringReader("{\"a\":1}\r\n{\"b\":2}\n"));
        Check(await reader.Read(stop.Token) == "{\"a\":1}" && await reader.Read(stop.Token) == "{\"b\":2}" && await reader.Read(stop.Token) == null,
            "Buffered JSONL preserves distinct complete frames and CRLF");
        foreach (var (text, bound) in new[] { ("partial",100), (new string('x',9000),8192), ("🙂🙂\n",7), ("bad\rframe\n",100) })
        {
            try { await new NativeJsonlReader(new StringReader(text),bound).Read(stop.Token); throw new Exception("Invalid JSONL accepted"); }
            catch (InvalidDataException) { checks++; }
        }
        foreach (var text in new[] { "{}\n{}", "{}\r{}", "\ud800", new string('x',2_097_153) })
            Denied(() => NativeJsonlReader.ValidateWrite(text), "Invalid native write accepted");
        foreach (var mode in new[] { "valid", "apiKey", "missing", "root", "failed", "wrong" })
        {
            var native = new VerificationNative(mode);
            try
            {
                await LinuxCodexChannel.VerifyNative(native, workspaces[0], stop.Token);
                Check(mode == "valid" && native.Calls.Count == 2, "Read-only ChatGPT account and real executor checks precede routing");
            }
            catch (InvalidDataException)
            {
                Check(mode != "valid" && native.Calls.Count == (mode is "apiKey" or "missing" ? 1 : 2), "Missing account or wrong executor identity fails without any model/resume call");
            }
            Check(native.Calls.All(c => !c.Effect) && native.Calls[0].Parameters.GetProperty("refreshToken").ValueKind == JsonValueKind.False,
                "Verification does not refresh authentication or journal an owner task action");
        }
        return checks;
    }
    private sealed class VerificationNative(string mode) : INative
    {
        public uint Pid => 789;
        public event Action<JsonElement>? Notification { add { } remove { } }
        public List<(string Method, JsonElement Parameters, bool Effect)> Calls = [];
        public Task<JsonElement> Call(string method, object parameters, CancellationToken stop, bool effect = true)
        {
            var input = JsonSerializer.SerializeToElement(parameters); Calls.Add((method,input,effect));
            if (method == "account/read")
                return Task.FromResult(mode == "missing" ? JsonSerializer.SerializeToElement(new { account = (object?)null }) :
                    JsonSerializer.SerializeToElement(new { account = new { type = mode == "apiKey" ? "apiKey" : "chatgpt" } }));
            if (method != "command/exec" || !input.GetProperty("command").EnumerateArray().Select(item => item.GetString()).SequenceEqual(new[] { "/usr/bin/id", "-u" }) ||
                input.GetProperty("sandboxPolicy").GetProperty("type").GetString() != "dangerFullAccess") throw new Exception("Unexpected native/model action in launch verification");
            return Task.FromResult(JsonSerializer.SerializeToElement(new { exitCode = mode == "failed" ? 1 : 0,
                stdout = mode == "root" ? "0\n" : mode == "wrong" ? "1000 is wrong" : "1000\n" }));
        }
        public Task Reply(JsonElement id, object result, CancellationToken stop) => throw new Exception("Verification must not answer native approvals");
    }
    private sealed class FakeChannel(params string[] initialFrames) : INativeChannel
    {
        private readonly Queue<string> frames = new(initialFrames);
        public uint Pid => 321;
        public bool Disposed; public int Reads;
        public List<string> Writes = [];
        public Task<string?> Read(CancellationToken stop) { Reads++; return Task.FromResult(frames.Count == 0 ? null : frames.Dequeue()); }
        public Task Write(string value, CancellationToken stop) { Writes.Add(value); return Task.CompletedTask; }
        public ValueTask DisposeAsync() { Disposed = true; return ValueTask.CompletedTask; }
    }
}
