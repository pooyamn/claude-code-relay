using System.Reflection;
using System.Text.Json;

namespace KhadangRouter;

public static class ClaudeQuestionTests
{
    public static async Task<int> Run(string root, RouterPolicy policy)
    {
        int checks=0;
        void Check(bool yes,string label){if(!yes)throw new Exception(label);checks++;}
        var flags=BindingFlags.Instance|BindingFlags.NonPublic;
        var type=typeof(Router).GetNestedType("Session",BindingFlags.NonPublic)!;
        var on=typeof(Router).GetMethod("OnClaude",flags)!;
        var flush=typeof(Router).GetMethod("FlushClaudeQuestions",flags)!;
        var binding=new Binding(policy.ChatId,42,"Claude questions",policy.WorkspaceRoot+"\\fixture","5a5e6b71-a837-4a30-a021-929a32bff048",Backend:"claude");
        object Request(string id="native-question",string text="Which route?")=>new{type="control_request",request_id=id,
            request=new{subtype="can_use_tool",tool_name="AskUserQuestion",input=new{questions=new[]{new{question=text,
                options=new[]{new{label="Route A",description="First choice"},new{label="Route B",description="Second choice"}}}}}}};
        foreach(var failure in new[]{-1,0,429})
        {
            using var ledger=new Ledger(Path.Combine(root,"claude-question-"+failure+".db"));
            var bot=new Bot{Failure=failure};var clock=new Clock();
            (Router Router,object Session) Setup()
            {
                var router=new Router(policy,ledger,bot,new Native(),deliveryClock:clock);
                var session=type.GetConstructors(flags|BindingFlags.Public).Single().Invoke(new object[]{binding,new Native()});
                type.GetField("Claude")!.SetValue(session,new Claude(binding.ThreadId));
                return(router,session);
            }
            void Event((Router Router,object Session) item,object value)=>on.Invoke(item.Router,new[]{item.Session,(object)JsonSerializer.SerializeToElement(value)});
            Task Flush((Router Router,object Session) item)=>(Task)flush.Invoke(item.Router,new[]{item.Session,CancellationToken.None})!;
            var current=Setup();Event(current,Request());
            // Owner questions must not disappear behind the automatic daily cap.
            var budget=new DailyOutputBudget(ledger,clock);for(int i=0;i<100;i++)budget.Reserve(binding.Chat,binding.Topic);
            await Flush(current);await Flush(current);
            Check(bot.Calls==1,"Pending question sends once even with an exhausted answer budget");
            Check(bot.Last.GetProperty("disable_notification").ValueKind==JsonValueKind.False && !bot.Last.TryGetProperty("entities",out _) &&
                bot.Last.GetProperty("text").GetString()!.Contains("Which route?\n") && bot.Last.GetProperty("text").GetString()!.Contains("Route B") &&
                bot.Last.GetProperty("chat_id").GetInt64()==binding.Chat && bot.Last.GetProperty("message_thread_id").GetInt32()==binding.Topic,
                "Question and options are clean notified text in the exact forum/topic");
            var original=bot.Last.GetProperty("text").GetString();
            var restarted=Setup();Event(restarted,Request());await Flush(restarted);
            Check(bot.Calls==1,"Restart does not duplicate confirmed, uncertain or rate-deferred question notifications");
            if(failure==429)
            {
                clock.Now=clock.Now.AddSeconds(3);bot.Failure=-1;await Flush(restarted);
                Check(bot.Calls==2 && bot.Last.GetProperty("text").GetString()==original,"Known rate rejection retries the same nonce after retry_after");
            }
            Event(restarted,new{type="control_cancel_request",request_id="native-question"});
            var bubble=(RollingBubble)type.GetField("Bubble")!.GetValue(restarted.Session)!;
            Check(!bubble.Tail.Contains("Claude question:"),"Native cancellation removes stale question and commands from bubble");
            var count=bot.Calls;Event(restarted,Request("cancel-before-delivery"));
            Event(restarted,new{type="control_cancel_request",request_id="cancel-before-delivery"});await Flush(restarted);
            Check(bot.Calls==count,"Cancelled unsent questions never generate a notification");
        }
        using(var ledger=new Ledger(Path.Combine(root,"claude-question-sensitive.db")))
        {
            var bot=new Bot();var router=new Router(policy,ledger,bot,new Native());
            var session=type.GetConstructors(flags|BindingFlags.Public).Single().Invoke(new object[]{binding,new Native()});
            type.GetField("Claude")!.SetValue(session,new Claude(binding.ThreadId));
            on.Invoke(router,new[]{session,(object)JsonSerializer.SerializeToElement(new{type="control_request",request_id="sensitive",
                request=new{subtype="can_use_tool",tool_name="Bash",input=new{password="PRIVATE-CANARY"}}})});
            await (Task)flush.Invoke(router,new[]{session,CancellationToken.None})!;
            var text=bot.Last.GetProperty("text").GetString()!;
            Check(!text.Contains("PRIVATE-CANARY") && !text.Contains("/approve") && text.Contains("/deny"),"Sensitive approval stays deny-only without leaking its input");
        }
        var legacy="Retained assistant text\n\nClaude question: AskUserQuestion\n1. OLD QUESTION\n/answer abcdef123456 1 example\n/deny abcdef123456\n\nNew assistant text";
        var clean=Router.RemoveSavedClaudeQuestions(legacy);
        Check(clean.Contains("Retained assistant text") && clean.Contains("New assistant text") && !clean.Contains("OLD QUESTION") && !clean.Contains("/answer"),
            "Restart removes flattened legacy prompts before restoring only live native requests");
        Check((bool)Telegram.SendParameters(binding.Chat,binding.Topic,"bubble")["disable_notification"],"Ordinary silent output policy remains unchanged");
        return checks;
    }
    private sealed class Clock:TimeProvider
    {public DateTimeOffset Now=DateTimeOffset.Parse("2026-10-18T06:00:00Z");public override DateTimeOffset GetUtcNow()=>Now;}
    private sealed class Bot:IBot
    {
        public int Calls;public int Failure=-1;public JsonElement Last;
        public Task<JsonElement> Call(string method,object parameters,CancellationToken stop,bool effect=false)
        {if(method!="sendMessage"||!effect)throw new Exception("Unexpected effect");Calls++;Last=JsonSerializer.SerializeToElement(parameters);
            if(Failure>=0)throw new TelegramFailure(Failure,2);return Task.FromResult(JsonSerializer.SerializeToElement(new{message_id=700+Calls}));}
        public Task<JsonElement> Send(long c,int t,string s,CancellationToken stop)=>throw new Exception("Questions must not use silent Send");
        public Task Edit(long c,int m,string s,CancellationToken stop)=>throw new Exception("No edit");
    }
    private sealed class Native:INative
    {public uint Pid=>1;public event Action<JsonElement>? Notification{add{}remove{}}
        public Task<JsonElement> Call(string m,object p,CancellationToken s,bool effect=true)=>throw new Exception("No native calls");
        public Task Reply(JsonElement i,object r,CancellationToken s)=>throw new Exception("No native reply");}
    private sealed class Claude(string pin):IClaudeNative
    {public uint Pid=>1;public string SessionId=>pin;public bool Connected=>true;public event Action<JsonElement>? Notification{add{}remove{}}
        public Task<JsonElement> Initialize(CancellationToken s)=>throw new Exception("No native initialize");
        public Task<JsonElement> Control(string t,object p,CancellationToken s,bool effect=true)=>throw new Exception("No native controls");
        public Task<JsonElement> SendNow(string i,JsonElement c,CancellationToken s)=>throw new Exception("No native prompt");
        public Task Answer(string i,object a,CancellationToken s)=>throw new Exception("No auto answer");
        public ValueTask DisposeAsync()=>ValueTask.CompletedTask;}
}
