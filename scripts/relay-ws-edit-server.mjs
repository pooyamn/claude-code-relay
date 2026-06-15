// Persistent WS "edit transport" with response logging + retry-after pause.
import { o as signDevicePayload, a as pubRaw } from "file:///opt/homebrew/lib/node_modules/openclaw/dist/device-identity-D3vNL0Bn.js";
import { createRequire } from "node:module";
import fs from "node:fs"; import os from "node:os"; import path from "node:path"; import readline from "node:readline";
const require = createRequire(import.meta.url);
const WebSocket = require("/opt/homebrew/lib/node_modules/openclaw/node_modules/ws/index.js");
const dev = JSON.parse(fs.readFileSync(path.join(os.homedir(),".openclaw/identity/device.json")));
const auth = JSON.parse(fs.readFileSync(path.join(os.homedir(),".openclaw/identity/device-auth.json")));
const op = auth.tokens.operator;
const TARGET=process.argv[2], THREAD=String(process.argv[3]);
const LOG=path.join(path.dirname(new URL(import.meta.url).pathname),"relay-work","edit-server.log");
const elog=(s)=>{try{fs.appendFileSync(LOG,new Date().toISOString().slice(11,23)+" "+s+"\n")}catch(e){}};
const out=(o)=>{ try{ process.stdout.write(JSON.stringify(o)+"\n"); }catch(e){} };
const ws=new WebSocket("ws://localhost:18789"); let id=1, ready=false, pend=new Map();
let pausedUntil=0, edits=0, dropped=0;
const key=()=>'es-'+Date.now()+'-'+Math.floor(Math.random()*1e6);
const req=(method,params,tag)=>{ const i='r'+(id++); pend.set(i,tag); ws.send(JSON.stringify({type:'req',id:i,method,params})); return i; };
ws.on('message',(b)=>{let m;try{m=JSON.parse(b)}catch(e){return}
 if(m.event==='connect.challenge'){const nonce=m.payload.nonce,t=Date.now(),plat=process.platform;
   const pl=["v3",dev.deviceId,"gateway-client","backend",op.role,(op.scopes||[]).join(","),String(t),op.token,nonce,plat,""].join("|");
   ws.send(JSON.stringify({type:'req',id:'c1',method:'connect',params:{minProtocol:4,maxProtocol:4,client:{id:'gateway-client',version:'2026.6.5',platform:plat,mode:'backend'},caps:[],auth:{deviceToken:op.token},role:op.role,scopes:op.scopes,device:{id:dev.deviceId,publicKey:pubRaw(dev.publicKeyPem),signature:signDevicePayload(dev.privateKeyPem,pl),signedAt:t,nonce}}}));return;}
 if(m.type==='res'&&m.id==='c1'){ ready=m.ok; elog("CONNECT ok="+m.ok); out({ready:m.ok}); return; }
 if(m.type==='res'&&pend.has(m.id)){ const tag=pend.get(m.id); pend.delete(m.id);
   const pay=m.payload||{}; const ok = (pay.ok!==false) && m.ok;
   const warn = pay.warning||pay.error||(m.error&&JSON.stringify(m.error))||"";
   // detect a Telegram retry-after / flood and pause
   const ra = String(warn).match(/retry[_ ]after[:\s]*([0-9]+)|too many requests/i);
   if(!ok || ra){
     let secs = ra && ra[1] ? parseInt(ra[1]) : 5;
     pausedUntil = Date.now() + secs*1000;
     elog(tag+" FAIL ok="+ok+" pause="+secs+"s warn="+String(warn).slice(0,160));
   } else if(tag.startsWith("edit") && (edits%5===0)) {
     elog(tag+" ok (edits="+edits+" dropped="+dropped+")");
   }
   if(tag.startsWith("send")){ out({reqid:tag.split(":")[1], messageId:String(pay.messageId??''), ok}); }
 }});
ws.on('error',(e)=>{ elog("WSERR "+e.message); out({error:e.message}); process.exit(1); });
const rl=readline.createInterface({input:process.stdin});
rl.on('line',(line)=>{ let o; try{o=JSON.parse(line)}catch(e){return}
 if(!ready) return;
 if(o.op==='send'){ const p={channel:'telegram',to:TARGET,threadId:THREAD,message:o.text,idempotencyKey:key()}; if(o.silent)p.silent=true; req('send',p,"send:"+(o.reqid||"")); elog("SEND len="+(o.text||'').length); }
 else if(o.op==='edit'){
   if(Date.now()<pausedUntil){ dropped++; return; }   // respect flood pause
   edits++; req('message.action',{channel:'telegram',action:'edit',idempotencyKey:key(),params:{to:TARGET,threadId:THREAD,messageId:String(o.mid),message:o.text}},"edit#"+edits); }
 else if(o.op==='delete'){ req('message.action',{channel:'telegram',action:'delete',idempotencyKey:key(),params:{to:TARGET,threadId:THREAD,messageId:String(o.mid)}},"delete"); }
 else if(o.op==='quit'){ elog("QUIT edits="+edits+" dropped="+dropped); process.exit(0); }
});
