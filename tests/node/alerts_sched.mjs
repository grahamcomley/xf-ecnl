import {schedAlerts, schedMsg, zonedMs} from "./alerts.js";
let R=[]; const ok=(n,c,d="")=>{R.push(c);console.log((c?"PASS ":"FAIL ")+n,c?"":JSON.stringify(d))};
const mk=(tz,q,teams,sc)=>({uid:"u",sub:{endpoint:"https://x/"},tz,q,badge:true,teams:teams.map(k=>({k,...(sc===undefined?{}:{sc})}))});
const devs={"d:uat:sea":mk("America/Los_Angeles",{on:false,s:"22:00",e:"07:00"},["u16b-1"]),
 "d:uat:seaq":mk("America/Los_Angeles",{on:true,s:"22:00",e:"07:00"},["u16b-1"]),
 "d:uat:off":mk("America/Los_Angeles",{on:false,s:"22:00",e:"07:00"},["u16b-1"],false),
 "d:uat:two":mk("America/Phoenix",{on:false,s:"22:00",e:"07:00"},["u16b-1","u13g-9"]),
 "d:uat:none":mk("America/Los_Angeles",{on:false,s:"22:00",e:"07:00"},["u17b-5"])};
for (const [k,v] of Object.entries(devs)) v.name=k;
const env={SITE:"uat",USERS:{list:async()=>({keys:Object.keys(devs).map(n=>({name:n,metadata:{t:devs[n].teams.map(t=>t.k).join(",")}})),list_complete:true}),get:async k=>devs[k],delete:async()=>{},put:async()=>{}}};
const A={g:"101",cf:"u16b-1-1",cn:"ECNL",h:"u16b-1",a:"u16b-2",hn:"XF 1 U16",an:"Barca",f:["t"],d:"2026-12-06",t:"09:30",v:"Field 4",tz:"America/Phoenix",od:"2026-12-06",ot:"08:00",ov:"Field 4",otz:"America/Phoenix"};
const F={...A,g:"106",f:["v"],t:"11:00",ot:"11:00",v:"Reach 11 Field 2",ov:"Field 6",d:"2026-12-09",od:"2026-12-09"};
const Gg={g:"201",cf:"u13g-1-1",cn:"ECNL",h:"u13g-8",a:"u13g-9",hn:"Eastside",an:"XF G13",f:["d"],d:"2026-12-14",t:"10:00",v:"Starfire 3",tz:"America/Los_Angeles",od:"2026-12-13",ot:"10:00",ov:"Starfire 3",otz:"America/Los_Angeles"};
// 1) daytime Seattle: one change
const day=zonedMs("2026-12-01","14:00","America/Los_Angeles");
let st={}; globalThis.SENT=[];
await schedAlerts(env,st,[{s:[A]}],day);
const by=d=>SENT.filter(m=>m.dev===d);
const s1=by("d:uat:sea")[0];
ok("single time change sent", s1 && s1.t==="Time changed: XF 1 U16 vs Barca", s1);
ok("time shown in phone zone, labelled, old time in brackets", s1 && s1.b==="Sun Dec 6, 8:30 AM PST · Field 4 (was 7:00 AM)", s1&&s1.b);
ok("quiet hours off at 2 PM: quiet device also sent", by("d:uat:seaq").length===1);
ok("team switched off: nothing", by("d:uat:off").length===0);
ok("not following: nothing", by("d:uat:none").length===0);
const az=by("d:uat:two")[0];
ok("Arizona phone sees field-zone time", az && az.b.startsWith("Sun Dec 6, 9:30 AM MST"), az&&az.b);
// 2) several games at once
globalThis.SENT=[]; st={};
await schedAlerts(env,st,[{s:[A,Gg]}],day);
const two=by("d:uat:two")[0];
ok("two games -> one grouped alert", by("d:uat:two").length===1 && two.t==="Schedule changes: 2 of your games", two);
ok("grouped lines", two && two.b.includes("XF 1 U16: time now Sun Dec 6, 9:30 AM MST") && two.b.includes("XF G13: date now Mon Dec 14, 11:00 AM MST"), two&&two.b);
// 3) quiet hours: held, then sent when they end; started games dropped
const night=zonedMs("2026-12-01","23:30","America/Los_Angeles");
globalThis.SENT=[]; st={};
await schedAlerts(env,st,[{s:[A,F]}],night);
ok("during quiet hours: quiet device held", by("d:uat:seaq").length===0 && st.sh && st.sh.seaq && st.sh.seaq.length===2, st.sh);
globalThis.SENT=[];
await schedAlerts(env,st,[],zonedMs("2026-12-02","07:05","America/Los_Angeles"));
const mor=by("d:uat:seaq")[0];
ok("released after quiet hours as one alert", by("d:uat:seaq").length===1 && mor.t==="Schedule changes: 2 of your games" && !(st.sh||{}).seaq, mor);
// 4) held until after kickoff -> dropped
const late={...A,d:"2026-12-02",od:"2026-12-02",t:"06:00",ot:"05:00",tz:"America/Los_Angeles",otz:"America/Los_Angeles"};
globalThis.SENT=[]; st={};
await schedAlerts(env,st,[{s:[late]}],zonedMs("2026-12-01","23:00","America/Los_Angeles"));
globalThis.SENT=[];
await schedAlerts(env,st,[],zonedMs("2026-12-02","07:05","America/Los_Angeles"));
ok("game started before quiet hours ended: dropped", by("d:uat:seaq").length===0);
// 5) field + date formats
const m=schedMsg({tz:"America/Los_Angeles"},[{c:F,t:"u16b-1"}]);
ok("field change format", m.t==="Field changed: XF 1 U16 vs Barca" && m.b==="Wed Dec 9, 10:00 AM PST · Reach 11 Field 2 (was Field 6)", m);
const md=schedMsg({tz:"America/Los_Angeles"},[{c:Gg,t:"u13g-9"}]);
ok("date change format, away game", md.t==="Date changed: XF G13 @ Eastside" && md.b==="Mon Dec 14, 10:00 AM PST · Starfire 3 (was Sun Dec 13)", md);
console.log(`${R.filter(Boolean).length}/${R.length} passed`);

// 6) per team: one team on, the other off
devs["d:uat:mix"]={uid:"u",sub:{endpoint:"https://x/"},tz:"America/Phoenix",q:{on:false,s:"22:00",e:"07:00"},badge:true,teams:[{k:"u16b-1"},{k:"u13g-9",sc:false}],name:"d:uat:mix"};
globalThis.SENT=[]; await schedAlerts(env,{},[{s:[A,Gg]}],day);
const mx=SENT.filter(m=>m.dev==="d:uat:mix");
ok("per team: only the team with it on", mx.length===1 && mx[0].t==="Time changed: XF 1 U16 vs Barca", mx);
console.log(`${R.filter(Boolean).length}/${R.length} passed (incl. per-team)`);
