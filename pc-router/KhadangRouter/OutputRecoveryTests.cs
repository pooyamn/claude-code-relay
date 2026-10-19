using System.Reflection;
using System.Text;
using System.Security.Cryptography;
using System.Text.Json;

namespace KhadangRouter;

public static class OutputRecoveryTests
{
    public static async Task<int> Run(string root, RouterPolicy policy)
    {
        int checks=0;
        void Check(bool ok,string label){if(!ok)throw new Exception(label);checks++;}
        var flags=BindingFlags.NonPublic|BindingFlags.Instance;
        var type=typeof(Router).GetNestedType("Session",BindingFlags.NonPublic)!;
        var restore=typeof(Router).GetMethod("RestorePendingBubbles",BindingFlags.NonPublic|BindingFlags.Static)!;
        var flush=typeof(Router).GetMethod("FlushBubble",flags)!;
        var queueBinding=new Binding(policy.ChatId,42,"Backlog fixture",policy.WorkspaceRoot+"\\\\lg-magic","saved-backlog");
        object Session(INative native)=>type.GetConstructors(flags|BindingFlags.Public).Single().Invoke(new object[]{queueBinding,native});
        using(var ledger=new Ledger(Path.Combine(root,"unlimited-outbox.db")))
        {
            var legacyKey="telegram/daily-output/"+queueBinding.Chat+"/"+queueBinding.Topic+"/2026-10-18";
            ledger.Put(legacyKey,new{Seeded=100,Reserved=Array.Empty<string>()});
            var originalBudget=ledger.Get(legacyKey)!.Value.GetRawText();
            var native=new Native();var bot=new Bot();var router=new Router(policy,ledger,bot,native);var session=Session(native);
            var answers=Enumerable.Range(0,300).Select(i=>{var a=new FinalAnswerState();a.Consider("Answer "+i);a.Complete();return a;}).ToArray();
            restore.Invoke(null,new[]{session,(object)Json(new{pendingAnswers=answers,outputRateLimited=true})});
            type.GetProperty("Message")!.SetValue(session,77);
            for(int i=0;i<301;i++)await (Task)flush.Invoke(router,new[]{session,CancellationToken.None})!;
            var saved=ledger.Get("bubble/"+queueBinding.ThreadId)!.Value;
            Check(bot.Answers==300,"More than one hundred answers deliver in the same day without a clock advance");
            Check(saved.GetProperty("pendingAnswers").GetArrayLength()==0 && !saved.GetProperty("held").GetBoolean(),"Large restored queue drains completely without recovery hold");
            Check(!saved.GetProperty("outputRateLimited").GetBoolean() && !saved.GetProperty("status").GetString()!.Contains("100/day"),"Stale rate-limited state and warning are removed");
            Check(ledger.Get(legacyKey)!.Value.GetRawText()==originalBudget,"Historical budget record is preserved as audit, not reset or consulted");
            var restarted=Session(native);
            restore.Invoke(null,new[]{restarted,(object)saved});
            var newAnswer=new FinalAnswerState();newAnswer.Consider("New reply after restart");newAnswer.Complete();
            restore.Invoke(null,new[]{restarted,(object)Json(new{pendingAnswers=new[]{newAnswer}})});
            var reopened=new Router(policy,ledger,bot,native);
            await (Task)flush.Invoke(reopened,new[]{restarted,CancellationToken.None})!;
            Check(bot.Answers==301,"New replies still deliver after restarting with an exhausted legacy budget");
        }
        foreach(var failure in new[]{0,429})
        {
            using var ledger=new Ledger(Path.Combine(root,"unlimited-uncertainty-"+failure+".db"));
            var native=new Native();var bot=new Bot{Failure=failure};var router=new Router(policy,ledger,bot,native);var session=Session(native);
            var a=new FinalAnswerState();a.Consider("One exact reply");a.Complete();
            restore.Invoke(null,new[]{session,(object)Json(new{pendingAnswers=new[]{a}})});
            type.GetProperty("Message")!.SetValue(session,77);
            await (Task)flush.Invoke(router,new[]{session,CancellationToken.None})!;
            var saved=ledger.Get("bubble/"+queueBinding.ThreadId)!.Value;
            var unknown=saved.GetProperty("pendingAnswers")[0].GetProperty("Parts")[0].GetProperty("SendUnknown").GetBoolean();
            Check(unknown==(failure==0),"Only an ambiguous send retains unknown delivery intent; 429 is a known rejection");
            bot.Failure=-1;await (Task)flush.Invoke(router,new[]{session,CancellationToken.None})!;
            Check(bot.Answers==(failure==0?1:2),"Unknown sends never replay; known provider rate rejection can recover");
            var restarted=Session(native);restore.Invoke(null,new[]{restarted,(object)ledger.Get("bubble/"+queueBinding.ThreadId)!.Value});
            var before=bot.Answers;await (Task)flush.Invoke(router,new[]{restarted,CancellationToken.None})!;
            Check(bot.Answers==before,"Restart does not duplicate a confirmed or uncertain answer");
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
