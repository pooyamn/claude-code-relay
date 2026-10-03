using System.Text.Json;
using KhadangRouter;

try
{
    if (args.SequenceEqual(new[] { "--self-test" })) { SelfTests.Run(); return; }
    if (args.Length != 3 || args[0] is not ("--service" or "--probe-service" or "--canary-service") || args[1] != "--config")
        throw new InvalidOperationException("KhadangRouter --service|--probe-service|--canary-service --config PATH; or --self-test");
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
            using var telegram = new Telegram(WindowsService.Credential(policy.CredentialFile), ledger);
            var me = await telegram.Call("getMe", new { }, stop);
            if (me.GetProperty("username").GetString() != policy.BotUsername || me.GetProperty("id").GetInt64() != policy.BotId)
                throw new InvalidOperationException("Wrong Telegram bot");
            var webhook = await telegram.Call("getWebhookInfo", new { }, stop);
            if (!string.IsNullOrEmpty(webhook.GetProperty("url").GetString())) throw new InvalidOperationException("Webhook present; refuse to change or compete");
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
                var aclCheck = "try { [IO.File]::ReadAllBytes('" + policy.CredentialFile + "') | Out-Null; exit 12 } " +
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
                File.WriteAllText(Path.Combine(policy.StateDirectory, "probe.json"), JsonSerializer.Serialize(new {
                    verified = true, pcOnly = true, bot = policy.BotUsername, nativeOwnerSid = policy.OwnerSid,
                    nativePid = rpc.Pid, nativeAccountAuthenticated = loggedIn, commandOwnerVerified = true, credentialAndCodeDenied = true,
                    aclProbeWithoutProviderSandbox = true,
                    nativeWindowsSandboxVerified = true,
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
                await using var rpc = new NativeRpc(WindowsOwnerProcess.Start(policy, policy.WorkspaceRoot + "\\lg-magic"), ledger);
                await rpc.Initialize(stop);
                await new Router(policy, ledger, telegram, rpc).Run(stop, canary: args[0] == "--canary-service");
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
    Console.Error.WriteLine("Khadang PC router stopped: " + error.GetType().Name);
    Environment.ExitCode = 1;
}
