using System.ComponentModel;
using System.Text.Json;

namespace KhadangRouter;

// Pure connector/registry fixtures; never Windows/WSL/native acceptance.
public static class LinuxClaudeRuntimeTests
{
    public static async Task<int> Run(RouterPolicy basePolicy, string testRoot)
    {
        int checks = 0;
        void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
        void Denied(Action action, string name)
        { try { action(); throw new Exception(name); } catch (InvalidDataException) { checks++; } }
        const string pin = "98b493a3-a1a4-4ef2-b7da-b9bf48ece0fe";
        var binding = new Binding(basePolicy.ChatId, 53, "DUT", LinuxCodexRuntime.WorkspaceRoot + "/duts", pin, "claude", "linux");
        var root = LinuxCodexRuntime.ProtectedRoot + "\\claude-connector-" + new string('a',32);
        var files = LinuxClaudeRuntime.PackageFiles.ToDictionary(name => name, _ => new string('b',64), StringComparer.Ordinal);
        var checkpoint = new ClaudeCheckpoint(binding.Chat,binding.Topic,binding.Workspace,new string('c',64));
        var runtime = new LinuxClaudeRuntime(root,new string('d',64),files,new() { [pin] = checkpoint });
        var policy = basePolicy with { LinuxWorkspaceRoot = LinuxCodexRuntime.WorkspaceRoot, LinuxClaude = runtime };
        policy.Validate(); LinuxClaudeTopics.ValidateRegistry(policy,[binding]);
        Check(basePolicy.LinuxClaude == null, "Legacy configuration does not activate Claude");
        foreach (var bad in new[] { @"C:\Users\pou\helper", root + "\\..", root.ToUpperInvariant(), root.Replace("claude-connector","codex-connector"), root + "\n" })
            Denied(() => (runtime with { PackageRoot = bad }).Validate(), "Unprotected Claude package accepted");
        var missing = new Dictionary<string,string>(files); missing.Remove("pc_claude_stdio.py");
        Denied(() => (runtime with { FileSha256 = missing }).Validate(), "Unpinned Claude helper accepted");
        var extra = new Dictionary<string,string>(files) { ["broker.py"] = new string('b',64) };
        Denied(() => (runtime with { FileSha256 = extra }).Validate(), "New broker smuggled into personal connector");
        foreach (var bad in new[] { "", new string('g',64), new string('a',63) })
        {
            Denied(() => (runtime with { WslSha256 = bad }).Validate(), "Unpinned WSL image accepted");
            Denied(() => (runtime with { Checkpoints = new() { [pin] = checkpoint with { Sha256 = bad } } }).Validate(), "Unreviewed checkpoint digest accepted");
        }
        foreach (var session in new[] { pin.ToUpperInvariant(), "new", LinuxClaudeRuntime.HeldSession })
            Denied(() => (runtime with { Checkpoints = new() { [session] = checkpoint } }).Validate(), "Substitute/held Claude session accepted");
        Denied(() => (runtime with { Checkpoints = [] }).Validate(), "Empty Claude checkpoint policy accepted");
        Denied(() => (policy with { LinuxWorkspaceRoot = "/Users/pouya/other" }).Validate(), "Unpreserved Claude workspace root accepted");
        foreach (var bad in new[] { binding with { Chat = binding.Chat-1 }, binding with { Topic = 54 }, binding with { Workspace = binding.Workspace+"-other" },
            binding with { ThreadId = Guid.NewGuid().ToString("D") }, binding with { Backend = "codex" }, binding with { Runtime = "windows" } })
            Denied(() => runtime.Arguments(bad,true), "Checkpoint scope drift accepted");
        Denied(() => LinuxClaudeTopics.ValidateRegistry(basePolicy,[binding]), "Missing runtime fallback accepted");
        var two = new[] { binding, binding with { Topic = 54,ThreadId = Guid.NewGuid().ToString("D") } };
        Denied(() => LinuxClaudeTopics.ValidateRegistry(policy,two), "Partially admitted registry accepted");
        var unrelated = binding with { Topic = 54, ThreadId = Guid.NewGuid().ToString("D"), Backend = "codex" };
        LinuxClaudeTopics.ValidateRegistry(policy,[binding,unrelated]); Check(true, "Mixed registry keeps native backends distinct");
        var arguments = runtime.Arguments(binding,false);
        Check(arguments.StartsWith("-d Ubuntu-24.04 -u pou --exec /usr/bin/python3 -I -B ") && arguments.Contains("/pc_claude_stdio.py\"") &&
            arguments.Contains(" --session \""+pin+"\"") && arguments.Contains("/handoff-"+pin+".json\"") &&
            arguments.EndsWith(" --checkpoint-sha256 "+checkpoint.Sha256), "Fixed WSL owner/python argv carries only exact selected handoff");
        Check(!arguments.Contains("--owner-full-access") && runtime.Arguments(binding,true) == arguments + " --owner-full-access",
            "Only explicit owner policy grants full access");
        Check(runtime.CheckpointPath(binding) == root+"\\handoff-"+pin+".json", "Handoff Windows path is derived, never caller-selected");

        var owner = new OwnerProcessObservation(123,basePolicy.OwnerSid,1,false,456);
        Dictionary<string,object> Metadata() => new() { ["type"] = "ccrelay_claude_ready", ["session_id"] = pin, ["workspace"] = binding.Workspace,
            ["uid"] = 1000, ["native_uid"] = 1000, ["native_pid"] = 789, ["native_generation"] = "10",
            ["binary_sha256"] = LinuxClaudeRuntime.BinarySha256, ["credential_denied"] = true, ["checkpoint_sha256"] = checkpoint.Sha256, ["inherited_lease"] = true };
        string Ready(Dictionary<string,object>? fields = null) => JsonSerializer.Serialize(fields ?? Metadata());
        var observation = LinuxClaudeChannel.ParseReady(Ready(),owner,binding,checkpoint.Sha256);
        Check(observation.NativePid == 789 && observation.WindowsOwner.Pid == 123 && observation.SessionId == pin,
            "Native Linux PID and owned Windows launcher observation remain distinct");
        foreach (var (key,value) in new (string,object)[] { ("type","result"), ("session_id",Guid.NewGuid().ToString("D")), ("workspace",binding.Workspace+"-other"),
            ("uid",0), ("native_uid",0), ("native_pid",0), ("native_pid",-1), ("native_generation","0"), ("native_generation","10x"),
            ("native_generation",new string('1',33)), ("binary_sha256",new string('e',64)), ("credential_denied",false),
            ("credential_denied","true"), ("checkpoint_sha256",new string('e',64)), ("inherited_lease",false) })
        {
            var fields = Metadata(); fields[key] = value;
            Denied(() => LinuxClaudeChannel.ParseReady(Ready(fields),owner,binding,checkpoint.Sha256), "Mismatched native Claude launch evidence accepted");
        }
        var incomplete = Metadata(); incomplete.Remove("inherited_lease");
        Denied(() => LinuxClaudeChannel.ParseReady(Ready(incomplete),owner,binding,checkpoint.Sha256), "Missing actual lease observation accepted");
        var surplus = Metadata(); surplus["role"] = "reviewer";
        Denied(() => LinuxClaudeChannel.ParseReady(Ready(surplus),owner,binding,checkpoint.Sha256), "Folder-based role claim accepted");
        foreach (var text in new[] { "null", "{}", Ready().Replace("\"uid\":1000","\"uid\":1000,\"uid\":1000"), new string('x',65537) })
            Denied(() => LinuxClaudeChannel.ParseReady(text,owner,binding,checkpoint.Sha256), "Malformed/duplicate/unbounded native readiness accepted");

        using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        foreach (var bad in new[] { owner with { Elevated = true }, owner with { Session = 0 }, owner with { Sid = "S-1-5-18" },
            owner with { Pid = 0 }, owner with { CreationTime = 0 } })
        {
            var channel = new FakeChannel(Ready());
            try { await LinuxClaudeChannel.Accept(channel,()=>bad,()=>false,basePolicy.OwnerSid,binding,checkpoint.Sha256,stop.Token); throw new Exception("Bad owner accepted"); }
            catch (InvalidDataException) { Check(channel.Disposed && channel.Reads == 0 && channel.Writes.Count == 0,"Bad Windows owner fails before stream I/O"); }
        }
        var broken = new FakeChannel("{}");
        try { await LinuxClaudeChannel.Accept(broken,()=>owner,()=>false,basePolicy.OwnerSid,binding,checkpoint.Sha256,stop.Token); throw new Exception("Bad readiness accepted"); }
        catch (InvalidDataException) { Check(broken.Disposed && broken.Writes.Count == 0,"Failed attestation closes only the owned connector"); }
        int seen = 0; var race = new FakeChannel(Ready());
        try { await LinuxClaudeChannel.Accept(race,()=>++seen==1?owner:owner with { CreationTime = 457 },()=>false,basePolicy.OwnerSid,binding,checkpoint.Sha256,stop.Token); throw new Exception("Owner race accepted"); }
        catch (InvalidDataException) { Check(race.Disposed,"Actual Windows process generation brackets readiness"); }
        var valid = new FakeChannel(Ready(),"{\"type\":\"result\",\"result\":\"final\"}",Ready());
        var current = owner;
        await using (var channel = await LinuxClaudeChannel.Accept(valid,()=>current,()=>false,basePolicy.OwnerSid,binding,checkpoint.Sha256,stop.Token))
        {
            Check(channel.Pid == 789 && await channel.Read(stop.Token) == "{\"type\":\"result\",\"result\":\"final\"}","Only readiness is consumed; native frames stay unchanged");
            await channel.Write("{}",stop.Token); Check(valid.Writes.SequenceEqual(new[] { "{}" }),"Forward input once without protocol synthesis");
            try { await channel.Read(stop.Token); throw new Exception("Readiness repeated"); } catch (InvalidDataException) { checks++; }
            current = owner with { CreationTime = 457 };
            try { await channel.Write("{}",stop.Token); throw new Exception("PID reuse accepted"); }
            catch (InvalidDataException) { Check(valid.Writes.Count == 1,"Changed generation rejects input before write"); }
        }
        Check(valid.Disposed,"Disposal transfers only the owned stream lifetime");
        bool terminal = false; var final = new FakeChannel(Ready(),"{\"type\":\"result\"}");
        await using (var channel = await LinuxClaudeChannel.Accept(final,()=>terminal?throw new Win32Exception(6):owner,()=>terminal,basePolicy.OwnerSid,binding,checkpoint.Sha256,stop.Token))
        {
            terminal = true;
            Check(await channel.Read(stop.Token) == "{\"type\":\"result\"}" && await channel.Read(stop.Token) == null,"Confirmed owned-handle exit still drains its same private final pipe");
            try { await channel.Write("{}",stop.Token); throw new Exception("Input sent after exit"); }
            catch (IOException) { Check(final.Writes.Count == 0,"Terminal output allowance can never permit input"); }
        }
        terminal = false; var unknown = new FakeChannel(Ready(),"{\"type\":\"result\"}");
        await using (var channel = await LinuxClaudeChannel.Accept(unknown,()=>terminal?throw new Win32Exception(6):owner,()=>false,basePolicy.OwnerSid,binding,checkpoint.Sha256,stop.Token))
        {
            terminal = true;
            try { await channel.Read(stop.Token); throw new Exception("Unverified terminal accepted"); }
            catch (IOException) { Check(unknown.Reads == 1,"An observation error alone is not terminal evidence"); }
        }

        var names = new[] { "nativeLinuxClaudeLaunchVerified", "nativeLinuxClaudeToolOwnerVerified", "nativeLinuxClaudeContinuityVerified" };
        var proof = names.ToDictionary(name => name,_ => true);
        LinuxClaudeTopics.RequireAcceptance(JsonSerializer.SerializeToElement(proof)); Check(true,"Dedicated matching acceptance permits admission, not fixture evidence");
        foreach (var name in names)
        {
            var falseProof = new Dictionary<string,bool>(proof) { [name] = false };
            try { LinuxClaudeTopics.RequireAcceptance(JsonSerializer.SerializeToElement(falseProof)); throw new Exception("Unverified acceptance permitted"); }
            catch (InvalidOperationException) { checks++; }
            var absent = new Dictionary<string,bool>(proof); absent.Remove(name);
            try { LinuxClaudeTopics.RequireAcceptance(JsonSerializer.SerializeToElement(absent)); throw new Exception("Missing acceptance permitted"); }
            catch (InvalidOperationException) { checks++; }
        }
        var ledgerPath = Path.Combine(testRoot,"linux-claude-factory.db");
        using var ledger = new Ledger(ledgerPath); int launches = 0;
        Task<INativeChannel> Open(Binding selected,CancellationToken token) { launches++; return Task.FromResult<INativeChannel>(new FakeChannel()); }
        var topics = new LinuxClaudeTopics(policy,ledger,[binding],Open);
        try { await topics.Open(binding with { Topic = 54 },stop.Token); throw new Exception("Factory rebound topic"); }
        catch (InvalidDataException) { Check(launches == 0,"Factory refuses substitute binding before launch"); }
        await using (var native = await topics.Open(binding,stop.Token))
            Check(native.SessionId == pin,"Factory keeps the original selected Claude pin");
        try { await topics.Open(binding,stop.Token); throw new Exception("Duplicate launch accepted"); }
        catch (InvalidOperationException) { Check(launches == 1,"No second native launch in the same factory"); }
        using var reopened = new Ledger(ledgerPath); // Independent actual SQLite connection, not an in-memory cache.
        var restarted = new LinuxClaudeTopics(policy,reopened,[binding],Open);
        try { await restarted.Open(binding,stop.Token); throw new Exception("Handoff replay accepted after restart"); }
        catch (InvalidOperationException) { Check(launches == 1,"Durable handoff receipt holds the same checkpoint after restart"); }
        var nextRuntime = runtime with { Checkpoints = new() { [pin] = checkpoint with { Sha256 = new string('e',64) } } };
        var next = new LinuxClaudeTopics(policy with { LinuxClaude = nextRuntime },ledger,[binding],Open);
        await using (var native = await next.Open(binding,stop.Token))
            Check(launches == 2,"An explicitly reviewed new checkpoint can authorize a new generation of the same session");
        var failedRuntime = runtime with { Checkpoints = new() { [pin] = checkpoint with { Sha256 = new string('f',64) } } };
        var failedPolicy = policy with { LinuxClaude = failedRuntime };
        var failed = new LinuxClaudeTopics(failedPolicy,ledger,[binding],(_,_) => { launches++; throw new IOException("Synthetic failed observation"); });
        try { await failed.Open(binding,stop.Token); throw new Exception("Failed launch accepted"); } catch (IOException) { checks++; }
        var afterFailure = new LinuxClaudeTopics(failedPolicy,reopened,[binding],Open);
        try { await afterFailure.Open(binding,stop.Token); throw new Exception("Uncertain launch repeated"); }
        catch (InvalidOperationException) { Check(launches == 3,"Failed launch still consumes the durable handoff before any retry"); }
        var recoveryPolicy = policy with { LinuxClaude = runtime with { GuardedRecovery = true,
            Checkpoints = new() { [pin] = checkpoint with { Model = "opus" } } } };
        using var recoveryLedger = new Ledger(Path.Combine(testRoot,"claude-recovery.db"));
        recoveryLedger.Put("claude/launch-handoff/" + pin, new { checkpointSha256 = checkpoint.Sha256 });
        int renewals = 0, recoveredLaunches = 0;
        Task<string> Renew(Binding selected, string digest, string? model, CancellationToken token)
        {
            Check(selected == binding && LinuxClaudeRuntime.Digest(digest) && model == "opus", "Recovery preserves exact scope and model");
            renewals++; return Task.FromResult(new string('f',64));
        }
        Task<INativeChannel> Reopen(Binding selected, string digest, string? model, CancellationToken token)
        {
            Check(recoveryLedger.Get(LinuxClaudeTopics.RecoveryKey(binding))!.Value.GetProperty("state").GetString() == "launch-attempted",
                "Recovery commits intent before any native launch");
            Check(selected == binding && digest == new string('f',64) && model == "opus", "Launch uses renewed evidence without replacement");
            recoveredLaunches++; return Task.FromResult<INativeChannel>(new FakeChannel());
        }
        LinuxClaudeTopics Recovery() => new(recoveryPolicy,recoveryLedger,[binding],Open,Renew,Reopen);
        var recoveryTopics = Recovery();
        await using (var native = await recoveryTopics.Open(binding,stop.Token))
            Check(native.SessionId == pin && recoveredLaunches == 1, "Consumed checkpoint can renew only the original idle session");
        try { await recoveryTopics.Open(binding,stop.Token); throw new Exception("Duplicate recovery"); }
        catch (InvalidOperationException) { Check(renewals == 1,"Recovery stays one-shot within a generation"); }
        await using (var native = await Recovery().Open(binding,stop.Token))
            Check(recoveredLaunches == 2,"Subsequent clean startup rechecks history instead of replaying a handoff");
        var uncertain = recoveryLedger.Attempt("claude/user/send-now",new { SessionId = pin });
        recoveryLedger.Outcome(uncertain,"unknown");
        try { await Recovery().Open(binding,stop.Token); throw new Exception("Unknown replay"); }
        catch (InvalidOperationException) { Check(renewals == 2,"Unknown action blocks even read-only checkpoint renewal"); }
        recoveryLedger.Exec("UPDATE operations SET status='rejected' WHERE id=?",uncertain); // Test-only explicit reconciliation.
        recoveryLedger.Put("claude/request/" + pin + "/pending",new { status = "pending" });
        try { await Recovery().Open(binding,stop.Token); throw new Exception("Pending approval"); }
        catch (InvalidOperationException) { Check(renewals == 2,"Pending native approval is never auto-answered"); }
        recoveryLedger.Put("claude/request/" + pin + "/pending",new { status = "cancelled" });
        object Bubble(bool busy = false, bool held = true, string status = "Held — Claude stream disconnected", bool unknownSend = false) =>
            new { chat = binding.Chat, topic = binding.Topic, backend = "claude", runtime = "linux", busy, held, status,
                claudeState = "idle", sendUnknown = unknownSend, pendingResponses = Array.Empty<string>(), pendingAnswers = Array.Empty<string>() };
        foreach (var unsafeBubble in new[] { Bubble(busy:true), Bubble(status:"Held — native conversation reset"), Bubble(unknownSend:true) })
        {
            recoveryLedger.Put("bubble/" + pin,unsafeBubble);
            try { await Recovery().Open(binding,stop.Token); throw new Exception("Unsafe recovery bubble"); }
            catch (InvalidOperationException) { Check(renewals == 2,"Only a disconnected idle stream may recover"); }
        }
        recoveryLedger.Put("bubble/" + pin,Bubble());
        await using (var native = await Recovery().Open(binding,stop.Token))
            Check(recoveredLaunches == 3,"Confirmed idle disconnected bubble allows guarded renewal");
        var failingRecovery = new LinuxClaudeTopics(recoveryPolicy,recoveryLedger,[binding],Open,Renew,(_,_,_,_) => throw new IOException("Synthetic recovery launch failure"));
        try { await failingRecovery.Open(binding,stop.Token); throw new Exception("Failed recovery launch accepted"); } catch (IOException) { checks++; }
        try { await Recovery().Open(binding,stop.Token); throw new Exception("Failed recovery replay"); }
        catch (InvalidOperationException) { Check(renewals == 4 && recoveredLaunches == 3,"Failed launch remains durably stopped across startup generations"); }
        var snapshot = new Dictionary<string,object> { ["type"] = "ccrelay_claude_snapshot", ["uid"] = 1000, ["session_id"] = pin,
            ["workspace"] = binding.Workspace, ["source_writer"] = "quiesced", ["model_inference"] = false, ["history_quiescent"] = true,
            ["history"] = new { path = "/Users/pouya/.claude/projects/-Users-pouya--openclaw-workspace-duts/" + pin + ".jsonl", bytes = 123, sha256 = new string('a',64) } };
        Check(LinuxClaudeTopics.RecoveryHistory(JsonSerializer.Serialize(snapshot),binding).GetProperty("bytes").GetInt64() == 123,"Exact idle transcript snapshot accepted");
        foreach (var (key,value) in new (string,object)[] { ("uid",0), ("session_id",Guid.NewGuid().ToString("D")), ("workspace",binding.Workspace+"-other"),
            ("source_writer","running"), ("model_inference",true), ("history_quiescent",false), ("history",new { path = "/tmp/history", bytes = 123, sha256 = new string('a',64) }) })
            Denied(() => LinuxClaudeTopics.RecoveryHistory(JsonSerializer.Serialize(new Dictionary<string,object>(snapshot) { [key] = value }),binding),"Unsafe recovery snapshot accepted");
        return checks;
    }
    private sealed class FakeChannel(params string[] frames) : INativeChannel
    {
        private readonly Queue<string> pending = new(frames);
        public uint Pid => 123;
        public bool Disposed; public int Reads;
        public List<string> Writes = [];
        public Task<string?> Read(CancellationToken stop) { Reads++; return Task.FromResult(pending.Count == 0 ? null : pending.Dequeue()); }
        public Task Write(string message,CancellationToken stop) { Writes.Add(message); return Task.CompletedTask; }
        public ValueTask DisposeAsync() { Disposed = true; return ValueTask.CompletedTask; }
    }
}
