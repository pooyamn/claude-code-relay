using KhadangRouter;

// Actual Windows routing fixtures under the limited owner. --self-test in the
// service executable also tests administrator-owned attachment materialization;
// that privileged test must wait for exact-version deployment authorization.
if (!args.SequenceEqual(new[] { "--self-test" })) throw new InvalidOperationException("MigrationRoutingTests --self-test");
var root = Path.Combine(Path.GetTempPath(), "khadang-migration-routing-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
var policy = new RouterPolicy("TheKhadangBot", 123, 456, -100123, "S-1-5-21-1-2-3-1001",
    "C:\\Native\\codex.exe", new string('a', 64), "C:\\Protected\\token.dpapi", "C:\\Protected\\state", "C:\\Workspaces");
try
{
    var checks = await RoutingTests.Run(root, policy);
    Directory.Delete(root, recursive: true); // Only this fresh fixture directory.
    Console.WriteLine("All " + checks + " PC-routing checks passed (no live credentials/models/Telegram).");
}
catch (Exception error)
{
    Console.Error.WriteLine(error);
    Environment.ExitCode = 1; // Keep failed fixture bytes for diagnosis.
}
