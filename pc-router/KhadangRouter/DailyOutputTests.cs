using System.Reflection;
using System.Text;
using System.Security.Cryptography;
using System.Text.Json;

namespace KhadangRouter;

public static class DailyOutputTests
{
    public static async Task<int> Run(string root, RouterPolicy policy)
    {
        int checks = 0;
        void Check(bool ok, string label) { if (!ok) throw new Exception(label); checks++; }
        void Limited(Action action)
        { try { action(); throw new Exception("Daily budget exceeded"); } catch (DailyOutputLimit) { checks++; } }
        var clock = new Clock { Now = DateTimeOffset.Parse("2026-10-15T06:55:00Z") }; // Oct14,23:55 Pacific.
        var path = Path.Combine(root, "daily-output.db");
        using (var ledger = new Ledger(path))
        {
            var budget = new DailyOutputBudget(ledger, clock);
            var reservations = Enumerable.Range(0, 100).Select(_ => budget.Reserve(-100123, 42)).ToArray();
            Check(reservations.Select(r => r.Token).Distinct().Count() == 100, "One hundred distinct durable reservations");
            Limited(() => budget.Reserve(-100123, 42));
            budget.Reserve(-100123, 43); budget.Reserve(-100456, 42);
            Check(true, "Daily quotas are isolated by both forum and topic");
            budget.Release(reservations[0]); budget.Release(reservations[0]);
            budget.Reserve(-100123, 42); Limited(() => budget.Reserve(-100123, 42));
        }
        using (var ledger = new Ledger(path))
        {
            var budget = new DailyOutputBudget(ledger, clock);
            Limited(() => budget.Reserve(-100123, 42));
            clock.Now = DateTimeOffset.Parse("2026-10-15T07:01:00Z");
            budget.Reserve(-100123, 42); Check(true, "Automatic reset is Pacific midnight, not UTC midnight");
            clock.Now = DateTimeOffset.Parse("2026-10-15T06:56:00Z");
            Limited(() => budget.Reserve(-100123, 42));
        }
        foreach (var failure in new[] { 0, 429 })
        {
            using var ledger = new Ledger(Path.Combine(root, "daily-failure-" + failure + ".db"));
            var budget = new DailyOutputBudget(ledger, clock); var bot = new Bot { Failure = failure };
            var limited = new DailyLimitedBot(bot, budget);
            try { await limited.SendAnswer(-100123, 42, new("fixture", []), CancellationToken.None); throw new Exception("Fixture failure missing"); }
            catch (TelegramFailure) { checks++; }
            for (var i = 0; i < (failure == 0 ? 99 : 100); i++) budget.Reserve(-100123, 42);
            Limited(() => budget.Reserve(-100123, 42));
            Check(bot.Answers == 1, "Unknown consumes quota; only explicit rejection refunds it");
            await limited.EditBubble(-100123, 77, "still working", CancellationToken.None);
            await limited.Typing(-100123, 42, CancellationToken.None);
            await limited.Send(-100123, 42, "owner status", CancellationToken.None);
            Check(bot.Edits == 1 && bot.Controls == 1 && bot.Pulses == 1, "Edits, typing and owner controls work at the daily limit");
        }
        using (var ledger = new Ledger(Path.Combine(root, "daily-seed.db")))
        {
            for (var i = 0; i < 100; i++)
            {
                var id = ledger.Attempt("telegram/sendMessage", new { chat_id=-100123, message_thread_id=42, entities=Array.Empty<object>() });
                ledger.Confirm(id, Json(new { message_id=i+1, date=clock.Now.ToUnixTimeSeconds() }));
            }
            Limited(() => new DailyOutputBudget(ledger, clock).Reserve(-100123,42));
        }
        // Actual Display shape: >256 saved answers is valid; all records remain
        // intact, but only a day's budget may cross the transport boundary.
        using (var ledger = new Ledger(Path.Combine(root, "large-outbox.db")))
        {
            var flags = BindingFlags.NonPublic | BindingFlags.Instance;
            var type = typeof(Router).GetNestedType("Session", BindingFlags.NonPublic)!;
            var binding = new Binding(policy.ChatId,42,"Large fixture",policy.WorkspaceRoot+"\\lg-magic","saved-backlog");
            var native = new Native(); var bot = new Bot();
            var router = new Router(policy, ledger, bot, native, deliveryClock: clock);
            var session = type.GetConstructors(flags|BindingFlags.Public).Single().Invoke(new object[] { binding,native });
            var answers = Enumerable.Range(0, 300).Select(i => {var answer=new FinalAnswerState();answer.Consider("Answer "+i);answer.Complete();return answer;}).ToArray();
            typeof(Router).GetMethod("RestorePendingBubbles",BindingFlags.NonPublic|BindingFlags.Static)!.Invoke(null,new[] {session,(object)Json(new {pendingAnswers=answers})});
            type.GetProperty("Message")!.SetValue(session,77);
            var flush = typeof(Router).GetMethod("FlushBubble",flags)!;
            async Task Flush() => await (Task)flush.Invoke(router,new[] {session,CancellationToken.None})!;
            for (var i=0;i<101;i++) await Flush();
            Check(bot.Answers==100 && !(bool)type.GetField("Held")!.GetValue(session)!, "Large restored backlog is rate-deferred, not a native-recovery hold");
            var saved=ledger.Get("bubble/"+binding.ThreadId)!.Value;
            Check(saved.GetProperty("pendingAnswers").GetArrayLength()==200 && saved.GetProperty("pendingAnswers")[0].GetProperty("Parts")[0].GetProperty("SendUnknown").GetBoolean()==false,
                "Deferred answers remain durably queued without false unknown-send intents");
            await Flush();Check(bot.Answers==100 && bot.Edits>0,"Rate exhaustion still allows the existing live bubble to update");
            clock.Now=clock.Now.AddDays(1);for(var i=0;i<101;i++)await Flush();
            Check(bot.Answers==200 && ledger.Get("bubble/"+binding.ThreadId)!.Value.GetProperty("pendingAnswers").GetArrayLength()==100,
                "Next calendar day drains the next hundred without an owner prompt or replay");
        }
        using (var ledger = new Ledger(Path.Combine(root, "output-quarantine.db")))
        {
            var binding=new Binding(-100123,42,"Fixture","C:\\Fixture","exact-native");
            var id=ledger.Attempt("telegram/sendDocument",new {chat_id=binding.Chat,message_thread_id=binding.Topic,filename="fixture.zip"});
            ledger.Outcome(id,"unknown");var payload=ledger.Query("SELECT payload FROM operations WHERE id=?",id)[0][0]!;
            ledger.Put("owner-output-quarantine/"+id,new {schema="ccrelay.owner_output_quarantine.v1",operation=id,chat=binding.Chat,topic=binding.Topic,
                workspace=binding.Workspace,action="retain-no-resend",payloadSha256=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(payload))).ToLowerInvariant()});
            Check(ledger.InputUnknown(binding)==0 && ledger.Unknown==1 && ledger.Query("SELECT status FROM operations WHERE id=?",id)[0][0]=="unknown",
                "Owner-quarantined output no longer blocks new input, but remains unknown and never becomes confirmed");
            Check(ledger.InputUnknown(binding with {Workspace="C:\\Other"})==1,"Quarantine cannot authorize a different project");
            ledger.Exec("UPDATE operations SET payload='{}' WHERE id=?",id);
            Check(ledger.InputUnknown(binding)==1,"Changed/unscoped receipts fail closed despite a saved quarantine");
            var native=ledger.Attempt("native/turn/steer",new {threadId=binding.ThreadId});ledger.Outcome(native,"unknown");
            Check(ledger.InputUnknown(binding)==2,"Native uncertainty is never covered by output quarantine");
        }
        return checks;
    }
    private static JsonElement Json(object value)=>JsonSerializer.SerializeToElement(value);
    private sealed class Clock : TimeProvider { public DateTimeOffset Now;public override DateTimeOffset GetUtcNow()=>Now; }
    private sealed class Native : INative
    {
        public uint Pid=>1;public event Action<JsonElement>? Notification {add{} remove{}}
        public Task<JsonElement> Call(string method,object parameters,CancellationToken stop,bool effect=true)=>throw new Exception("No native effects");
        public Task Reply(JsonElement id,object result,CancellationToken stop)=>throw new Exception("No native replies");
    }
    private sealed class Bot : IBot
    {
        public int Answers,Edits,Controls,Pulses;public int Failure=-1;
        public Task<JsonElement> SendAnswer(long chat,int topic,AnswerPart part,CancellationToken stop)
        {Answers++;if(Failure>=0)throw new TelegramFailure(Failure);return Task.FromResult(Json(new {message_id=Answers}));}
        public Task<JsonElement> Send(long chat,int topic,string text,CancellationToken stop){Controls++;return Task.FromResult(Json(new {message_id=1000+Controls}));}
        public Task Edit(long chat,int message,string text,CancellationToken stop){Edits++;return Task.CompletedTask;}
        public Task<bool> Typing(long chat,int topic,CancellationToken stop){Pulses++;return Task.FromResult(true);}
        public Task<JsonElement> Call(string method,object parameters,CancellationToken stop,bool effect=false)=>throw new Exception("No live transport");
    }
}
