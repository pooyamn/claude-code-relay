namespace KhadangRouter;

public sealed partial class Router
{
    private async Task MenuLoop(CancellationToken stop)
    {
        while (!stop.IsCancellationRequested)
        {
            try
            {
                await Menus(stop);
                ledger.Put("telegram/menu-health", new { state = "ready", at = DateTimeOffset.UtcNow });
                return;
            }
            catch (OperationCanceledException) when (stop.IsCancellationRequested) { throw; }
            catch (Exception error) when (error is TelegramFailure or IOException or InvalidOperationException or System.Text.Json.JsonException)
            {
                // Configuration is idempotent and confirmed by exact readback.
                // A menu outage is NOT an outage of message polling or input.
                ledger.Put("telegram/menu-health", new { state = "degraded", errorType = error.GetType().Name, at = DateTimeOffset.UtcNow });
            }
            await Task.Delay(TimeSpan.FromSeconds(30), stop);
        }
    }
}
