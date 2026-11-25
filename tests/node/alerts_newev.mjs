import {newEvAlerts, newEvMsg, testNewEvOwner, zonedMs} from "./alerts.js";
import fs from "fs";
let R=[]; const ok=(n,c,d="")=>{R.push(c);console.log((c?"PASS ":"FAIL ")+n,c?"":JSON.stringify(d))};
const it={k:"u17b-62277",tn:"XF 1",ev:4467,fl:42675,en:"ECNL West Coast Super Cup",first:"2026-11-27",n:1,g:[{id:"1153206",d:"2026-11-27",t:"14:30",tz:"America/Los_Angeles",o:"Boise Timbers",h:true,v:"Surf Sports Park · Field #12"}],later:["2026-11-28","2026-11-29"]};
const it2={...it,k:"u13g-9",tn:"XF G13",ev:4325,en:"Legends FC Holiday Classic",first:"2026-12-05",g:[{id:"9",d:"2026-12-05",t:"09:00",tz:"America/Los_Angeles",o:"Eastside",h:false,v:"Field 3"}],later:[],n:3};
const m1=newEvMsg({tz:"America/Los_Angeles"},[it]);
ok("single: title", m1.t==="Schedule posted: ECNL West Coast Super Cup", m1.t);
ok("single: body", m1.b==="XF 1 · first game Fri Nov 27, 2:30 PM PST vs Boise Timbers · Surf Sports Park · Field #12. Then bracket games Sat–Sun.", m1.b);
ok("single: opens the event", m1.u==="/#t=u17b-62277&g=1153206&v=events", m1.u);
const m2=newEvMsg({tz:"America/Denver"},[it2]);
ok("3 games, away, other zone", m2.b==="XF G13 · first game Sat Dec 5, 10:00 AM MST @ Eastside · Field 3. 3 games.", m2.b);
const mk=(tz,q,teams)=>({uid:"u",sub:{endpoint:"https://x/"},tz,q,badge:true,teams});
const devs={"d:uat:a":mk("America/Los_Angeles",{on:false,s:"22:00",e:"07:00"},[{k:"u17b-62277"},{k:"u13g-9"}]),
 "d:uat:q":mk("America/Los_Angeles",{on:true,s:"22:00",e:"07:00"},[{k:"u17b-62277"}]),
 "d:uat:off":mk("America/Los_Angeles",{on:false,s:"22:00",e:"07:00"},[{k:"u17b-62277",ne:false}]),
 "d:uat:none":mk("America/Los_Angeles",{on:false,s:"22:00",e:"07:00"},[{k:"u15b-1"}])};
for (const [k,v] of Object.entries(devs)) v.name=k;
const env={SITE:"uat",USERS:{list:async()=>({keys:Object.keys(devs).map(n=>({name:n,metadata:{t:devs[n].teams.map(t=>t.k).join(",")}})),list_complete:true}),get:async k=>devs[k],delete:async()=>{},put:async()=>{}}};
const day=zonedMs("2026-11-24","14:00","America/Los_Angeles");
globalThis.SENT=[]; let st={};
await newEvAlerts(env,st,[{e:[it,it2]}],day);
const by=d=>SENT.filter(m=>m.dev===d);
ok("two teams -> one grouped alert", by("d:uat:a").length===1 && by("d:uat:a")[0].t==="Schedules posted: 2 of your teams", by("d:uat:a"));
ok("grouped lines", by("d:uat:a")[0].b==="XF 1: ECNL West Coast Super Cup, first game Fri Nov 27\nXF G13: Legends FC Holiday Classic, first game Sat Dec 5", by("d:uat:a")[0].b);
ok("team switched off: nothing", by("d:uat:off").length===0);
ok("not following: nothing", by("d:uat:none").length===0);
globalThis.SENT=[]; st={};
await newEvAlerts(env,st,[{e:[it]}],zonedMs("2026-11-24","23:30","America/Los_Angeles"));
ok("quiet hours: held", by("d:uat:q").length===0 && st.eh.q && st.eh.q.length===1, st.eh);
globalThis.SENT=[];
await newEvAlerts(env,st,[],zonedMs("2026-11-25","07:05","America/Los_Angeles"));
ok("sent when quiet hours end", by("d:uat:q").length===1 && !(st.eh||{}).q);
globalThis.SENT=[]; st={};
await newEvAlerts(env,st,[{e:[it]}],zonedMs("2026-11-27","15:00","America/Los_Angeles"));
ok("first game already started: dropped", SENT.length===0, SENT);
// owner test with real conf data
const conf=JSON.parse(fs.readFileSync("/tmp/xfo/site/data/conf/u17b-4284-40525.json","utf8"));
const odev={uid:"own",sub:{endpoint:"https://x/"},tz:"America/Los_Angeles",q:{on:false},badge:true,teams:[{k:"u17b-131393",f:"u17b-4284-40525",n:"Snohomish United"}],name:"d:uat:own"};
const env2={SITE:"uat",ASSETS:{fetch:async r=>({ok:true,json:async()=>conf})},USERS:{list:async()=>({keys:[{name:"d:uat:own",metadata:{t:"u17b-131393"}}],list_complete:true}),get:async()=>odev}};
globalThis.SENT=[];
const RealDate=Date; globalThis.Date=class extends RealDate{constructor(...a){super(...(a.length?a:[RealDate.parse("2026-11-10T18:00:00Z")]))} static now(){return RealDate.parse("2026-11-10T18:00:00Z")}};
const r=await testNewEvOwner(env2,"own");
globalThis.Date=RealDate;
ok("owner test sends to owner's device with 'Test:'", r.sent===1 && SENT[0].t.startsWith("Test: Schedule posted:"), {r,s:SENT[0]});
console.log("owner test:", SENT[0]&&SENT[0].t, "|", SENT[0]&&SENT[0].b);
console.log(`${R.filter(Boolean).length}/${R.length} passed`);
