namespace KhadangRouter;

// Cosmetic receipt/activity signals: no retries, native admission or payload.
internal sealed class ReceiptTyping(IBot bot, TimeProvider? time = null)
{
    private readonly TimeProvider clock = time ?? TimeProvider.System;
    private readonly object gate = new();
    private readonly Dictionary<TopicAddress, DateTimeOffset> next = new();
    private readonly HashSet<Task> pending = new();
    private DateTimeOffset cooldown = DateTimeOffset.MinValue;
    private long attempted, confirmed, failed, suppressed;
    private DateTimeOffset? lastConfirmed;
    private TopicAddress? lastAddress;

    public void Observe(TopicAddress address, CancellationToken stop)
    {
        lock (gate)
        {
            pending.RemoveWhere(task => task.IsCompleted);
            var now = clock.GetUtcNow();
            if (stop.IsCancellationRequested || pending.Count >= 8 || now < cooldown ||
                next.TryGetValue(address, out var due) && now < due)
            { suppressed++; return; }
            // Normally only the mapped topics reach this class. Bound its
            // bookkeeping even if a future router admits many more topics.
            if (!next.ContainsKey(address) && next.Count >= 256)
                next.Remove(next.MinBy(pair => pair.Value).Key);
            next[address] = now.AddSeconds(1);
            attempted++;
            pending.Add(Send(address, stop));
        }
    }
    public void Refresh(TopicAddress address, bool working, CancellationToken stop)
    {
        if (working) Observe(address, stop);
    }
    private async Task Send(TopicAddress address, CancellationToken stop)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(stop);
        deadline.CancelAfter(TimeSpan.FromSeconds(2));
        try
        {
            // The extra wait bound also handles a broken transport that ignores
            // cancellation. Ordinary dispatch never awaits this cosmetic call.
            var ok = await bot.Typing(address.Chat, address.Topic, deadline.Token).WaitAsync(deadline.Token);
            lock (gate)
            {
                if (ok) { confirmed++; lastConfirmed = clock.GetUtcNow(); lastAddress = address; }
                else failed++;
            }
        }
        catch (TelegramFailure error) when (error.Code == 429)
        {
            lock (gate) { failed++; cooldown = clock.GetUtcNow().AddSeconds(Math.Max(1, error.RetryAfter)); }
        }
        catch { lock (gate) failed++; } // Never log credential-bearing exceptions.
    }
    public Task Drain()
    {
        lock (gate) return Task.WhenAll(pending.ToArray());
    }
    public object Snapshot
    {
        get { lock (gate) return new { attempted, confirmed, failed, suppressed,
            inFlight = pending.Count(task => !task.IsCompleted), lastConfirmedAt = lastConfirmed,
            lastChat = lastAddress?.Chat, lastTopic = lastAddress?.Topic,
            meaning = "bridge receipt or active native work; not model acceptance or proof of progress" }; }
    }
}
