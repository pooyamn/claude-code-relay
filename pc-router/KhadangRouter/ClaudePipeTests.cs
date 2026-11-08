using System.IO.Pipes;
using System.Text.Json;

namespace KhadangRouter;

// Real OS pipes, not an in-memory broker mock. In particular Windows EOF
// changes IsConnected without resetting the reusable server instance.
internal static class ClaudePipeTests
{
    internal static async Task<int> Run()
    {
        int checks = 0;
        void Check(bool value, string label) { if (!value) throw new Exception(label); checks++; }
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var stop = timeout.Token;
        var name = "khadang-restart-fixture-" + Guid.NewGuid().ToString("N");
        using var server = new NamedPipeServerStream(name, PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous);
        ClaudeWorkerHost.ResetPipe(server); checks++; // No connection yet.
        for (int cycle = 0; cycle < 12; cycle++)
        {
            using var client = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous);
            var accept = server.WaitForConnectionAsync(stop);
            try { await client.ConnectAsync(stop); await accept; }
            catch (OperationCanceledException error) { throw new IOException("Real pipe reconnect timed out at cycle " + cycle + "; accept=" + accept.Status + "; client=" + client.IsConnected + "; server=" + server.IsConnected, error); }
            try
            {
                if (cycle % 3 == 0)
                {
                    // Identical to the live host's successful reply -> EOF path.
                    using var writes = new SemaphoreSlim(1, 1);
                    // Zero-buffer Windows pipes require the independent client
                    // reader to run while the server writes (as in production).
                    var writing = BrokerWireFrames.Write(server, new { status = "ready" }, writes, stop);
                    var reply = await BrokerWireFrames.Read(client, stop);
                    await writing;
                    Check(reply?.GetProperty("status").GetString() == "ready", "Complete reply before client EOF");
                    client.Dispose();
                    Check(await BrokerWireFrames.Read(server, stop) == null, "Disconnected observer reaches EOF");
                    if (OperatingSystem.IsWindows()) Check(!server.IsConnected, "Windows EOF is broken despite IsConnected=false");
                }
                else if (cycle % 3 == 1) throw new UnauthorizedAccessException("Rejected fixture peer");
                else throw new JsonException("Malformed fixture frame");
            }
            catch (Exception error) when (cycle % 3 != 0 && ClaudeWorkerHost.ClientFault(error)) { checks++; }
            finally { ClaudeWorkerHost.ResetPipe(server); }
            Check(!server.IsConnected, "Same server instance resets after EOF/rejected/malformed client: " + cycle);
        }
        using (var cancelled = new CancellationTokenSource())
        {
            var accept = server.WaitForConnectionAsync(cancelled.Token); cancelled.Cancel();
            try { await accept; throw new Exception("Cancelled accept completed"); }
            catch (OperationCanceledException) { checks++; }
            ClaudeWorkerHost.ResetPipe(server);
        }
        using (var client = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous))
        {
            var accept = server.WaitForConnectionAsync(stop); await client.ConnectAsync(stop); await accept;
            Check(server.IsConnected, "Cancelled accept does not poison the next connection");
            ClaudeWorkerHost.ResetPipe(server);
        }
        server.Dispose(); ClaudeWorkerHost.ResetPipe(server); checks++;
        Check(!ClaudeWorkerHost.ClientFault(new NullReferenceException()) &&
            !ClaudeWorkerHost.ClientFault(new OutOfMemoryException()), "Programming/resource faults are not hidden as client disconnects");
        return checks;
    }
}
