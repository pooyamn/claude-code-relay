using System.Text.Json;
using KhadangRouter;

try
{
    if (args.SequenceEqual(new[] { "--self-test" })) { SelfTests.Run(); return; }
    if (args.Length != 3 || args[0] is not ("--service" or "--probe-service" or "--canary-service" or "--typing-probe-service") || args[1] != "--config")
        throw new InvalidOperationException("KhadangRouter --service|--probe-service|--canary-service|--typing-probe-service --config PATH; or --self-test");
    var policy = RouterPolicy.Load(args[2]);
    var probe = args[0] == "--probe-service";
    WindowsService.Run(async stop =>
    {
        Directory.CreateDirectory(policy.StateDirectory);
        try
        {
            // Lock BEFORE opening SQLite: a second process must not mark live
            // attempts uncertain or begin a competing Telegram poller.
            using var exclusive = new FileStream(Path.Combine(policy.StateDirectory, "exclusive.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
            using var ledger = new Ledger(Path.Combine(policy.StateDirectory, "router.db"));
            var bindings = ledger.Bindings();
            policy.ValidateBindings(bindings);
            var needsLinuxCodex = bindings.Any(b => b.Runtime == "linux");
            if (needsLinuxCodex && policy.LinuxCodex == null)
                throw new InvalidDataException("Linux native bindings require the protected ordinary-owner connector");
            LinuxClaudeTopics.ValidateRegistry(policy, bindings, ledger); // Fail the whole registry before any native launch.
            var needsClaude = policy.LinuxClaude != null;
            using var telegram = new Telegram(WindowsService.Credential(policy.CredentialFile), ledger);
            var me = await telegram.Call("getMe", new { }, stop);
            if (me.GetProperty("username").GetString() != policy.BotUsername || me.GetProperty("id").GetInt64() != policy.BotId)
                throw new InvalidOperationException("Wrong Telegram bot");
            var webhook = await telegram.Call("getWebhookInfo", new { }, stop);
            if (!string.IsNullOrEmpty(webhook.GetProperty("url").GetString())) throw new InvalidOperationException("Webhook present; refuse to change or compete");
            if (args[0] == "--typing-probe-service")
            {
                // Explicit deployment test: ephemeral UI only, no forged input,
                // Telegram poller, native process, model turn or chat message.
                var targets = bindings.Where(b => b.Chat == -1004395661179 && b.Topic == 53 ||
                    b.Chat == -1003550185469 && b.Topic == 816).ToArray();
                if (targets.Length != 2) throw new InvalidOperationException("Exact DUT and controller typing probe routes required");
                foreach (var target in targets)
                {
                    using var deadline = CancellationTokenSource.CreateLinkedTokenSource(stop);
                    deadline.CancelAfter(TimeSpan.FromSeconds(2));
                    if (!await telegram.Typing(target.Chat, target.Topic, deadline.Token))
                        throw new InvalidOperationException("Telegram typing was not confirmed; no automatic retry");
                }
                File.WriteAllText(Path.Combine(policy.StateDirectory, "typing-proof.json"), JsonSerializer.Serialize(new {
                    testedAt = DateTimeOffset.UtcNow, bot = policy.BotUsername, confirmed = true,
                    targets = targets.Select(b => new { chat = b.Chat, topic = b.Topic }),
                    telegramPolling = false, nativeProcessesStarted = false, modelInference = false, chatMessagesSent = false,
                    routerSha256 = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(typeof(Router).Assembly.Location))),
                    policySha256 = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(args[2]))) }));
                return;
            }
            if (probe)
            {
                await using var rpc = new NativeRpc(WindowsOwnerProcess.Start(policy, policy.WorkspaceRoot + "\\lg-magic"), ledger);
                await rpc.Initialize(stop);
                var account = await rpc.Call("account/read", new { refreshToken = false }, stop, effect: false);
                var loggedIn = account.TryGetProperty("account", out var a) && a.ValueKind != JsonValueKind.Null;
                if (!loggedIn) throw new InvalidOperationException("Native PC Codex is not authenticated");
                var result = await rpc.Call("command/exec", new { command = new[] { Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "whoami.exe"), "/user", "/fo", "csv", "/nh" },
                    cwd = policy.WorkspaceRoot + "\\lg-magic", sandboxPolicy = new { type = "dangerFullAccess" }, timeoutMs = 10000 }, stop);
                if (result.GetProperty("exitCode").GetInt32() != 0 || !result.GetProperty("stdout").GetString()!.Contains(policy.OwnerSid))
                    throw new InvalidOperationException("Native tool owner identity mismatch");
                var aclCheck = "try { $f=[IO.File]::Open('" + policy.CredentialFile + "',[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite); $f.Dispose(); exit 12 } " +
                    "catch [UnauthorizedAccessException] { }; " +
                    "try { $p = '" + Path.GetDirectoryName(policy.CredentialFile) + "\\bin\\acl-denial-canary.tmp'; " +
                    "$f = [IO.File]::Open($p,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write); $f.Dispose(); exit 13 } " +
                    "catch [UnauthorizedAccessException] { }; Write-Output 'ROUTER-ACL-DENIED'; exit 0";
                var denied = await rpc.Call("command/exec", new { command = new[] { Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell\\v1.0\\powershell.exe"), "-NoProfile", "-NonInteractive", "-Command", aclCheck },
                    // Fixed non-model probe, deliberately WITHOUT a provider
                    // sandbox: prove Windows ACLs deny the ordinary owner token.
                    cwd = policy.WorkspaceRoot + "\\lg-magic", sandboxPolicy = new { type = "dangerFullAccess" }, timeoutMs = 10000 }, stop);
                if (denied.GetProperty("exitCode").GetInt32() != 0 || !denied.GetProperty("stdout").GetString()!.Contains("ROUTER-ACL-DENIED"))
                    throw new InvalidOperationException("Native agent could cross the router credential/code boundary");
                var sandbox = await rpc.Call("command/exec", new { command = new[] {
                    Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "whoami.exe"), "/user" },
                    cwd = policy.WorkspaceRoot + "\\lg-magic", sandboxPolicy = new { type = "workspaceWrite",
                        writableRoots = new[] { policy.WorkspaceRoot + "\\lg-magic" }, networkAccess = false }, timeoutMs = 10000 }, stop);
                if (sandbox.GetProperty("exitCode").GetInt32() != 0 || !sandbox.GetProperty("stdout").GetString()!.Contains("CodexSandboxOffline", StringComparison.OrdinalIgnoreCase))
                    throw new InvalidOperationException("Native elevated Windows workspace sandbox did not execute as its dedicated offline identity");
                var goalReads = new List<object>();
                var asset = Attachments.ProbeAsset(policy);
                var assetPath = asset.Path.Replace("'", "''");
                var assetCheck = "$b=[IO.File]::ReadAllBytes('" + assetPath + "'); " +
                    "$h=[Security.Cryptography.SHA256]::Create(); $d=[BitConverter]::ToString($h.ComputeHash($b)).Replace('-',''); $h.Dispose(); " +
                    "if($d -ne '" + asset.Sha256 + "'){exit 14}; " +
                    "try { $f=[IO.File]::Open('" + assetPath + "',[IO.FileMode]::Open,[IO.FileAccess]::Write); $f.Dispose(); exit 15 } " +
                    "catch [UnauthorizedAccessException] { }; " +
                    "try { $f=[IO.File]::Open('" + Path.GetDirectoryName(assetPath) + "\\worker-write-canary.tmp',[IO.FileMode]::CreateNew,[IO.FileAccess]::Write); $f.Dispose(); exit 16 } " +
                    "catch [UnauthorizedAccessException] { }; Write-Output 'ATTACHMENT-READ-ONLY-OK'; exit 0";
                var assetResult = await rpc.Call("command/exec", new { command = new[] { Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell\\v1.0\\powershell.exe"), "-NoProfile", "-NonInteractive", "-Command", assetCheck },
                    cwd = policy.WorkspaceRoot + "\\lg-magic", sandboxPolicy = new { type = "dangerFullAccess" }, timeoutMs = 10000 }, stop);
                if (assetResult.GetProperty("exitCode").GetInt32() != 0 || !assetResult.GetProperty("stdout").GetString()!.Contains("ATTACHMENT-READ-ONLY-OK"))
                    throw new InvalidOperationException("Native owner attachment read-only ACL proof failed");
                var quota = new NativeQuota();
                await quota.Read(rpc, stop);
                var remote = new NativeRemote();
                await remote.Read(rpc, stop);
                var visibility = new List<object>();
                foreach (var binding in ledger.Bindings())
                {
                    if (binding.Backend != "codex" || binding.Runtime != "windows") continue;
                    // Read stored state only: do not resume, start a turn or
                    // mutate the owner's goal as a deployment fixture.
                    var read = await rpc.Call("thread/goal/get", new { threadId = binding.ThreadId }, stop, effect: false);
                    var view = new NativeGoal(binding.ThreadId); view.Apply(read.GetProperty("goal"));
                    goalReads.Add(new { threadId = binding.ThreadId, known = view.Known, goal = view.Value });
                    visibility.Add(await NativeVisibility.Read(rpc, binding, stop));
                }
                var linux = needsLinuxCodex ? await LinuxCodexChannel.ConnectVerified(policy, bindings, ledger, stop) : null;
                await using var linuxRpc = linux?.Rpc;
                File.WriteAllText(Path.Combine(policy.StateDirectory, "probe.json"), JsonSerializer.Serialize(new {
                    verified = true, pcOnly = true, bot = policy.BotUsername, nativeOwnerSid = policy.OwnerSid,
                    nativePid = rpc.Pid, nativeAccountAuthenticated = loggedIn, commandOwnerVerified = true, credentialAndCodeDenied = true,
                    aclProbeWithoutProviderSandbox = true,
                    nativeWindowsSandboxVerified = true,
                    nativeGoalReadSchemaVerified = true, nativeGoalReads = goalReads,
                    nativeQuota = quota.Snapshot,
                    nativeRemote = remote.Snapshot, nativeThreadVisibility = visibility,
                    nativeAttachmentReadOnlyAclVerified = true, nativeAttachmentFixture = asset,
                    nativeLinuxCodexVerified = linux != null,
                    nativeLinuxCodexObservation = linux?.Observation,
                    nativeLinuxAccountPresent = linux != null,
                    nativeLinuxCommandOwnerVerified = linux != null,
                    // This generic probe MUST NOT resume a real Claude handoff
                    // and consume/change its initial checkpoint. Dedicated
                    // candidate-bound native acceptance remains required.
                    nativeLinuxClaudeLaunchVerified = false,
                    nativeLinuxClaudeToolOwnerVerified = false,
                    nativeLinuxClaudeContinuityVerified = false,
                    policySha256 = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(args[2]))),
                    routerSha256 = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(typeof(Router).Assembly.Location))),
                    modelInference = false, telegramPolling = false, testedAt = DateTimeOffset.UtcNow }));
                await Task.Delay(Timeout.Infinite, stop);
            }
            else
            {
                var proof = JsonDocument.Parse(File.ReadAllText(Path.Combine(policy.StateDirectory, "probe.json"))).RootElement;
                if (!proof.GetProperty("verified").GetBoolean() || !proof.GetProperty("credentialAndCodeDenied").GetBoolean() ||
                    !proof.GetProperty("aclProbeWithoutProviderSandbox").GetBoolean() ||
                    !proof.GetProperty("nativeWindowsSandboxVerified").GetBoolean() ||
                    proof.GetProperty("policySha256").GetString() != Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(args[2]))) ||
                    proof.GetProperty("routerSha256").GetString() != Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(typeof(Router).Assembly.Location))) ||
                    proof.GetProperty("nativeOwnerSid").GetString() != policy.OwnerSid) throw new InvalidOperationException("Matching native identity/OS-ACL/code proof required before polling");
                if (needsLinuxCodex && (!proof.TryGetProperty("nativeLinuxCodexVerified", out var linuxProof) || linuxProof.ValueKind != JsonValueKind.True ||
                    !proof.TryGetProperty("nativeLinuxCommandOwnerVerified", out var commandProof) || commandProof.ValueKind != JsonValueKind.True))
                    throw new InvalidOperationException("Matching Linux native launch/credential/tool-owner proof required before polling");
                if (needsClaude) LinuxClaudeTopics.RequireAcceptance(proof);
                await using var rpc = new NativeRpc(WindowsOwnerProcess.Start(policy, policy.WorkspaceRoot + "\\lg-magic"), ledger);
                await rpc.Initialize(stop);
                var remote = new NativeRemote();
                await remote.Read(rpc, stop);
                var linux = needsLinuxCodex ? await LinuxCodexChannel.ConnectVerified(policy, bindings, ledger, stop) : null;
                await using var linuxRpc = linux?.Rpc;
                var claudeTopics = needsClaude ? new LinuxClaudeTopics(policy, ledger, bindings) : null;
                await new Router(policy, ledger, telegram, rpc, nativeRemote: remote, linuxRpc: linuxRpc, claudeTopics: claudeTopics)
                    .Run(stop, canary: args[0] == "--canary-service");
            }
        }
        catch (Exception error) when (error is not OperationCanceledException)
        {
            File.WriteAllText(Path.Combine(policy.StateDirectory, "failure.json"), JsonSerializer.Serialize(new {
                errorType = error.GetType().Name, nativeError = error is System.ComponentModel.Win32Exception native ? native.NativeErrorCode : 0,
                message = error is System.ComponentModel.Win32Exception ? "Windows launch failed" :
                    error is HttpRequestException ? "Network failure" : error.Message, at = DateTimeOffset.UtcNow }));
            throw;
        }
    });
}
catch (Exception error)
{
    Console.Error.WriteLine(args.SequenceEqual(new[] { "--self-test" }) ? error.ToString() : "Khadang PC router stopped: " + error.GetType().Name);
    Environment.ExitCode = 1;
}
