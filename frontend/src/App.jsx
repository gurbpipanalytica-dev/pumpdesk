import { useState, useEffect, useRef, useCallback, createContext, useContext } from "react";
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, PieChart, Pie } from "recharts";

/* ═══════════════════════════════════════════════════════════════════════════
   PUMPDESK v2 — SOLANA ALPHA DESK
   Sidebar: Overview │ Bots │ Launcher │ Intelligence │ CRM │ Settings
   Inspired by Polydesk — sidebar nav, recharts, theme context, mode switch
   ═══════════════════════════════════════════════════════════════════════════ */

const API = typeof window !== "undefined" && window.location.hostname === "localhost" ? "http://localhost:8765" : "";
const WS_URL = typeof window !== "undefined" && window.location.hostname === "localhost" ? "ws://localhost:8765/ws" : typeof window !== "undefined" ? `wss://${window.location.host}/ws` : "";

// ── Theme System (Polydesk-inspired) ────────────────────────────────────────
const DARK = {
  bg:"#0f1219", surf:"#161b26", surf2:"#1c2233", surf3:"#232b3d",
  border:"rgba(255,255,255,0.06)", borderHover:"rgba(255,255,255,0.12)",
  text:"#e2e6ed", sub:"#8892a6", muted:"#4e5a6e", dim:"#2d3748",
  green:"#34d399", greenSoft:"rgba(52,211,153,0.1)", greenBorder:"rgba(52,211,153,0.25)",
  red:"#f87171", redSoft:"rgba(248,113,113,0.1)",
  amber:"#f0a030", amberSoft:"rgba(240,160,48,0.1)", amberBorder:"rgba(240,160,48,0.25)",
  teal:"#2ec4b6", tealSoft:"rgba(46,196,182,0.1)", tealBorder:"rgba(46,196,182,0.25)",
  yellow:"#fbbf24",
};
const MODE = {
  paper: { accent:"#f0a030", accentSoft:"rgba(240,160,48,0.1)", accentBorder:"rgba(240,160,48,0.25)", accentText:"#f5b94e", label:"PAPER", balanceLabel:"Paper Balance" },
  live:  { accent:"#34d399", accentSoft:"rgba(52,211,153,0.1)", accentBorder:"rgba(52,211,153,0.25)", accentText:"#4eeaad", label:"LIVE",  balanceLabel:"SOL Balance" },
};
const ThemeCtx = createContext({ B: DARK, M: MODE.paper });
const useTheme = () => useContext(ThemeCtx);

// ── Helpers ──────────────────────────────────────────────────────────────────
const f = {
  sol: (v, d=4) => v == null ? "—" : `${v.toFixed(d)}`,
  pnl: (v, d=3) => v == null ? "—" : `${v>=0?"+":""}${v.toFixed(d)}`,
  pct: (v) => v == null ? "—" : `${(v*100).toFixed(1)}%`,
  num: (v) => v == null ? "—" : v.toLocaleString(),
  addr: (a, n=4) => a ? `${a.slice(0,n)}…${a.slice(-n)}` : "—",
  time: (iso) => { try { return new Date(iso).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",second:"2-digit"}); } catch { return "—"; }},
  age: (iso) => { if(!iso) return "—"; const ms=Date.now()-new Date(iso).getTime(); return ms<60e3?`${~~(ms/1e3)}s`:ms<36e5?`${~~(ms/6e4)}m`:`${~~(ms/36e5)}h`; },
};

// ── Shared Components ───────────────────────────────────────────────────────

function Badge({color, children, dot}){
  const c=color||DARK.muted;
  return <span style={{display:"inline-flex",alignItems:"center",gap:4,padding:"2px 8px",borderRadius:20,background:c+"15",color:c,fontSize:10,fontWeight:700,letterSpacing:"0.06em",textTransform:"uppercase",fontFamily:"'JetBrains Mono',monospace"}}>
    {dot&&<span style={{width:5,height:5,borderRadius:"50%",background:c,flexShrink:0}}/>}{children}
  </span>;
}

function Card({children, style={}, className}){
  const {B}=useTheme();
  return <div className={className} style={{background:B.surf,border:`1px solid ${B.border}`,borderRadius:14,boxShadow:"0 2px 8px rgba(0,0,0,0.25)",...style}}>{children}</div>;
}

function CardHeader({title, sub, right}){
  const {B}=useTheme();
  return <div style={{padding:"18px 20px 0",marginBottom:14,display:"flex",justifyContent:"space-between",alignItems:"flex-start"}}>
    <div><div style={{fontSize:13,fontWeight:600,color:B.text,letterSpacing:"-0.01em"}}>{title}</div>{sub&&<div style={{fontSize:11,color:B.muted,marginTop:3}}>{sub}</div>}</div>
    {right}
  </div>;
}

function Metric({label,value,sub,color}){
  const {B}=useTheme();
  return <div>
    <div style={{fontSize:10,color:B.muted,textTransform:"uppercase",letterSpacing:"0.08em",fontWeight:600,marginBottom:5}}>{label}</div>
    <div className="num" style={{fontSize:26,fontWeight:700,color:color||B.text,lineHeight:1,letterSpacing:"-0.03em"}}>{value}</div>
    {sub&&<div style={{fontSize:11,color:B.muted,marginTop:5}}>{sub}</div>}
  </div>;
}

function Sparkline({positive=true}){
  const {B}=useTheme();
  const d=positive?[3,5,4,7,6,8,9,8,11,10,13,12,15,14,17,20]:[15,13,14,11,12,9,10,8,7,9,6,5,7,4,3,2];
  const max=Math.max(...d),min=Math.min(...d);
  const pts=d.map((v,i)=>`${(i/(d.length-1))*56},${18-((v-min)/(max-min||1))*16}`).join(" ");
  return <svg width={58} height={20}><polyline points={pts} fill="none" stroke={positive?B.green:B.red} strokeWidth={1.5} strokeLinejoin="round" opacity={.85}/></svg>;
}

function StatusBadge({status}){
  const {B}=useTheme();
  const map={live:{bg:B.greenSoft,c:B.green},paused:{bg:B.amberSoft,c:B.amber},error:{bg:B.redSoft,c:B.red},planned:{bg:B.surf2,c:B.muted},
    open:{bg:B.tealSoft,c:B.teal},closed:{bg:B.surf2,c:B.muted},preparing:{bg:B.amberSoft,c:B.amber},launched:{bg:B.greenSoft,c:B.green},
    failed:{bg:B.redSoft,c:B.red},stalled:{bg:B.amberSoft,c:B.amber},graduating:{bg:B.amberSoft,c:B.yellow},graduated:{bg:B.tealSoft,c:B.teal},dead:{bg:B.surf2,c:B.dim}};
  const s=map[status]||{bg:B.surf2,c:B.muted};
  return <span style={{display:"inline-flex",alignItems:"center",gap:4,background:s.bg,color:s.c,fontSize:10,fontWeight:700,letterSpacing:"0.06em",padding:"3px 9px",borderRadius:20,textTransform:"uppercase"}}>
    {(status==="live"||status==="open")&&<span style={{width:5,height:5,borderRadius:"50%",background:s.c,animation:"pulse 2s infinite"}}/>}{status||"—"}
  </span>;
}

function ChartTip({active,payload,label}){
  const {B}=useTheme();
  if(!active||!payload?.length) return null;
  return <div style={{background:B.surf,border:`1px solid ${B.border}`,borderRadius:8,padding:"10px 14px",fontSize:12,boxShadow:"0 8px 32px rgba(0,0,0,0.4)"}}>
    <div style={{color:B.muted,marginBottom:4,fontSize:11,fontFamily:"'JetBrains Mono',monospace"}}>{label}</div>
    {payload.map((p,i)=><div key={i} style={{color:p.color||B.text,fontWeight:600,fontFamily:"'JetBrains Mono',monospace"}}>{p.name}: {typeof p.value==="number"?f.sol(p.value,3):p.value} SOL</div>)}
  </div>;
}

function Table({cols,rows,empty}){
  const {B}=useTheme();
  if(!rows?.length) return <div style={{padding:20,color:B.muted,textAlign:"center",fontSize:12,fontStyle:"italic"}}>{empty||"No data"}</div>;
  return <div style={{overflowX:"auto"}}><table style={{width:"100%",borderCollapse:"separate",borderSpacing:0,fontSize:12}}>
    <thead><tr>{cols.map((c,i)=><th key={i} style={{padding:"8px 10px",textAlign:c.align||"left",color:B.muted,fontSize:10,fontWeight:600,textTransform:"uppercase",letterSpacing:"0.06em",borderBottom:`1px solid ${B.border}`,whiteSpace:"nowrap",background:B.surf}}>{c.label}</th>)}</tr></thead>
    <tbody>{rows.map((r,ri)=><tr key={ri} className="bot-row" style={{borderBottom:`1px solid ${B.bg}`}}>
      {cols.map((c,ci)=><td key={ci} style={{padding:"8px 10px",color:B.text,whiteSpace:"nowrap",textAlign:c.align||"left",fontFamily:c.mono?"'JetBrains Mono',monospace":"inherit",fontSize:c.mono?11:12}}>{c.render?c.render(r):r[c.key]}</td>)}
    </tr>)}</tbody>
  </table></div>;
}

function PnL({value}){
  const {B}=useTheme();
  if(typeof value!=="number") return <span style={{color:B.muted}}>—</span>;
  const c=value>0?B.green:value<0?B.red:B.muted;
  return <span className="num" style={{color:c,fontWeight:600}}>{f.pnl(value)}</span>;
}

function ModeSwitch({mode, onChange}){
  const {B}=useTheme();
  return <div style={{display:"flex",background:B.surf2,border:`1px solid ${B.border}`,borderRadius:8,overflow:"hidden"}}>
    {["paper","live"].map(m=><button key={m} onClick={()=>onChange(m)} style={{padding:"5px 14px",fontSize:10,fontWeight:mode===m?700:400,background:mode===m?(m==="paper"?DARK.amberSoft:DARK.greenSoft):"transparent",color:mode===m?(m==="paper"?DARK.amber:DARK.green):B.muted,border:"none",letterSpacing:"0.06em",textTransform:"uppercase",cursor:"pointer",transition:"all 0.15s"}}>{m}</button>)}
  </div>;
}

// ── Mock Data (will be replaced by API) ─────────────────────────────────────
const mockPnlData = Array.from({length:14},(_,i)=>{const d=new Date();d.setDate(d.getDate()-13+i);return{d:d.toLocaleDateString("en-US",{month:"short",day:"numeric"}),v:Math.random()*0.4-0.1,c:(i+1)*0.05+Math.random()*0.3};});
const BOTS = [
  {id:1,name:"Graduation Sniper",color:"#34d399",status:"live",strategy:"Bonding curve graduation detection",pnl:0.42,trades:23,winRate:.74},
  {id:2,name:"Wallet Copier",color:"#2ec4b6",status:"live",strategy:"Mirror smart money wallets",pnl:0.18,trades:12,winRate:.67},
  {id:3,name:"Multi-DEX Arb",color:"#f0a030",status:"live",strategy:"Cross-DEX price discrepancy",pnl:0.45,trades:8,winRate:1},
  {id:4,name:"Momentum Scanner",color:"#4c9eeb",status:"live",strategy:"Volume + price velocity detection",pnl:0.11,trades:31,winRate:.61},
  {id:5,name:"Token Launcher",color:"#fbbf24",status:"paused",strategy:"Create + Jito bundle launch",pnl:0,trades:0,winRate:0},
  {id:6,name:"Volume Bot",color:"#64748b",status:"paused",strategy:"Anti-MEV same-block buy+sell",pnl:0,trades:0,winRate:0},
  {id:7,name:"Anti-Sniper Trap",color:"#f87171",status:"paused",strategy:"Bait token → sell into sniper buys",pnl:0,trades:0,winRate:0},
  {id:8,name:"Jito Backrunner",color:"#a78bfa",status:"live",strategy:"Backrun arb via Jito bundles",pnl:1.23,trades:12,winRate:.92},
  {id:9,name:"Liquidation Bot",color:"#fb923c",status:"live",strategy:"Flashloan liquidations on lending",pnl:0.89,trades:3,winRate:1},
  {id:10,name:"Yield Optimizer",color:"#60a5fa",status:"live",strategy:"JLP delta-neutral + lending arb",pnl:0.03,trades:0,winRate:0},
];
const pieData = [{name:"Sniper",value:0.42,color:"#34d399"},{name:"Copier",value:0.18,color:"#2ec4b6"},{name:"Arb",value:0.45,color:"#f0a030"},{name:"Backrun",value:1.23,color:"#a78bfa"},{name:"Liquidation",value:0.89,color:"#fb923c"}];


// ═══════════════════════════════════════════════════════════════════════════
//  PAGE: OVERVIEW
// ═══════════════════════════════════════════════════════════════════════════
function OverviewPage({status,positions,trades,hotTokens,signals}){
  const {B,M}=useTheme();
  const totalPnl=BOTS.reduce((s,b)=>s+b.pnl,0);
  const activeBots=BOTS.filter(b=>b.status==="live").length;
  const totalTrades=BOTS.reduce((s,b)=>s+b.trades,0);
  return <div className="in">
    <div style={{background:M.accentSoft,border:`1px solid ${M.accentBorder}`,borderRadius:10,padding:"10px 16px",marginBottom:20,display:"flex",alignItems:"center",gap:12,flexWrap:"wrap"}}>
      <span style={{width:7,height:7,borderRadius:"50%",background:M.accent,animation:"pulse 2s infinite"}}/>
      <span style={{fontSize:12,color:M.accentText,fontWeight:600}}>{M.label} Mode — {activeBots} Bots Active</span>
      <span style={{fontSize:11,color:B.muted}}>Orchestrator: fast path &lt;100ms · slow path Claude AI · {totalTrades} trades</span>
    </div>
    <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:16,marginBottom:24}}>
      {[
        {label:"Total P&L",value:f.pnl(totalPnl)+" SOL",sub:`${activeBots} bots generating alpha`,color:totalPnl>=0?B.green:B.red,spark:true},
        {label:"Active Bots",value:`${activeBots}/10`,sub:"Running in "+M.label.toLowerCase()+" mode",color:activeBots>0?B.green:B.muted},
        {label:"Total Trades",value:f.num(totalTrades),sub:"Executed this session",color:B.amber},
        {label:"Exposure",value:f.sol(status?.total_exposure_sol||0,2)+" SOL",sub:status?.open_positions?`${status.open_positions} open positions`:"No positions",color:B.teal},
      ].map((k,i)=><Card key={i} style={{padding:"18px 20px"}}>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:12}}>
          <span style={{fontSize:10,color:B.muted,letterSpacing:"0.06em",fontWeight:600,textTransform:"uppercase"}}>{k.label}</span>
          {k.spark&&<Sparkline positive={totalPnl>=0}/>}
        </div>
        <div className="num" style={{fontSize:26,fontWeight:700,color:k.color,lineHeight:1,letterSpacing:"-0.03em",marginBottom:6}}>{k.value}</div>
        <div style={{fontSize:11,color:B.muted}}>{k.sub}</div>
      </Card>)}
    </div>
    <div style={{display:"grid",gridTemplateColumns:"1.4fr 1fr",gap:20,marginBottom:20}}>
      <Card style={{padding:"20px 20px 12px"}}>
        <CardHeader title="Cumulative Return" sub="All bots combined · SOL"/>
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={mockPnlData} margin={{top:4,right:4,bottom:0,left:-20}}>
            <defs><linearGradient id="pg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={M.accent} stopOpacity={.22}/><stop offset="100%" stopColor={M.accent} stopOpacity={0}/></linearGradient></defs>
            <CartesianGrid strokeDasharray="2 4" stroke={B.border} vertical={false}/>
            <XAxis dataKey="d" tick={{fill:B.muted,fontSize:10}} axisLine={false} tickLine={false} interval="preserveStartEnd"/>
            <YAxis tick={{fill:B.muted,fontSize:10}} axisLine={false} tickLine={false} tickFormatter={v=>v.toFixed(1)}/>
            <Tooltip content={<ChartTip/>}/>
            <Area type="monotone" dataKey="c" stroke={M.accent} strokeWidth={2.5} fill="url(#pg)" dot={false} name="Cumulative"/>
          </AreaChart>
        </ResponsiveContainer>
      </Card>
      <Card style={{padding:"18px 20px"}}>
        <CardHeader title="Alpha by Bot" sub="Where SOL comes from"/>
        <div style={{display:"flex",flexDirection:"column",gap:10,marginTop:4}}>
          {pieData.map((cat,i)=><div key={i}>
            <div style={{display:"flex",justifyContent:"space-between",marginBottom:5}}>
              <div style={{display:"flex",alignItems:"center",gap:7}}><span style={{width:8,height:8,borderRadius:2,background:cat.color}}/><span style={{fontSize:12,color:B.sub}}>{cat.name}</span></div>
              <span className="num" style={{fontSize:12,fontWeight:600,color:cat.value>0?B.green:B.red}}>{f.pnl(cat.value)} SOL</span>
            </div>
            <div style={{height:5,background:B.surf2,borderRadius:3,overflow:"hidden"}}><div style={{width:`${(cat.value/totalPnl)*100}%`,height:"100%",borderRadius:3,background:cat.color,opacity:.8}}/></div>
          </div>)}
        </div>
      </Card>
    </div>
    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:20,marginBottom:20}}>
      <Card style={{padding:"20px 20px 12px"}}>
        <CardHeader title="Daily P&L" sub="Per-session result"/>
        <ResponsiveContainer width="100%" height={160}>
          <BarChart data={mockPnlData} barSize={18} margin={{top:0,right:4,bottom:0,left:-20}}>
            <CartesianGrid strokeDasharray="2 4" stroke={B.border} vertical={false}/>
            <XAxis dataKey="d" tick={{fill:B.muted,fontSize:10}} axisLine={false} tickLine={false} interval="preserveStartEnd"/>
            <YAxis tick={{fill:B.muted,fontSize:10}} axisLine={false} tickLine={false} tickFormatter={v=>v.toFixed(1)}/>
            <Tooltip content={<ChartTip/>}/>
            <Bar dataKey="v" name="Daily P&L" radius={[3,3,0,0]}>{mockPnlData.map((e,i)=><Cell key={i} fill={e.v>=0?B.green:B.red} fillOpacity={.75}/>)}</Bar>
          </BarChart>
        </ResponsiveContainer>
      </Card>
      <Card style={{padding:"18px 20px"}}>
        <CardHeader title="Hot Tokens" sub="Signal correlation engine"/>
        <Table cols={[
          {label:"Token",render:r=><span style={{color:DARK.amber,fontWeight:600}}>{r.symbol||f.addr(r.mint)}</span>},
          {label:"Signals",key:"signal_count",align:"right",mono:true},
          {label:"Score",render:r=><span style={{color:r.score>.7?B.green:B.amber}}>{f.sol(r.score,2)}</span>,align:"right",mono:true},
          {label:"Bots",render:r=>(r.bots||[]).join(", ")},
        ]} rows={hotTokens} empty="Scanning for correlated signals..."/>
      </Card>
    </div>
    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:20}}>
      <Card style={{padding:"18px 20px"}}><CardHeader title="Live Signal Feed" sub="Real-time from all bots"/><SignalFeed signals={signals}/></Card>
      <Card style={{padding:"18px 20px"}}>
        <CardHeader title="Open Positions" sub={`${positions?.length||0} active`}/>
        <Table cols={[
          {label:"Bot",key:"bot"},{label:"Mint",render:r=><span style={{color:B.teal}}>{f.addr(r.mint,5)}</span>,mono:true},
          {label:"Size",render:r=>f.sol(r.size_sol,3),align:"right",mono:true},
          {label:"uPnL",render:r=><PnL value={r.unrealized_pnl_sol}/>,align:"right"},
          {label:"Status",render:r=><StatusBadge status={r.status}/>},
        ]} rows={positions} empty="No open positions"/>
      </Card>
    </div>
  </div>;
}

function SignalFeed({signals}){
  const {B}=useTheme();
  const ref=useRef(null);
  useEffect(()=>{if(ref.current)ref.current.scrollTop=ref.current.scrollHeight;},[signals]);
  return <div ref={ref} style={{height:200,overflowY:"auto",background:B.bg,borderRadius:8,border:`1px solid ${B.border}`,padding:10,fontFamily:"'JetBrains Mono',monospace",fontSize:11}}>
    {!signals?.length&&<div style={{color:B.muted,padding:10,fontStyle:"italic"}}>Awaiting signals...</div>}
    {signals?.map((s,i)=><div key={i} style={{padding:"3px 0",borderBottom:`1px solid ${B.surf}`,lineHeight:1.5}}>
      <span style={{color:B.dim}}>{f.time(s.timestamp||s.created_at)}</span>{" "}
      <span style={{color:DARK.amber}}>[{s.bot||s.type||"SYS"}]</span>{" "}
      <span style={{color:B.text}}>{s.reason||s.signal_type||s.status||JSON.stringify(s).slice(0,80)}</span>
    </div>)}
  </div>;
}

// ═══════════════════════════════════════════════════════════════════════════
//  PAGE: BOTS
// ═══════════════════════════════════════════════════════════════════════════
function BotsPage(){
  const {B}=useTheme();
  return <div className="in"><div style={{display:"grid",gridTemplateColumns:"repeat(2,1fr)",gap:16}}>
    {BOTS.map(bot=><Card key={bot.id} className="bot-card" style={{padding:"18px 20px",borderLeft:`3px solid ${bot.color}`,cursor:"pointer"}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:12}}>
        <div style={{display:"flex",alignItems:"center",gap:10}}>
          <div style={{width:34,height:34,borderRadius:10,background:`${bot.color}15`,border:`1px solid ${bot.color}30`,display:"flex",alignItems:"center",justifyContent:"center",fontSize:15,fontWeight:700,color:bot.color}}>{bot.id}</div>
          <div><div style={{fontSize:13,fontWeight:600,color:B.text}}>{bot.name}</div><div style={{fontSize:11,color:B.muted,marginTop:2}}>{bot.strategy}</div></div>
        </div>
        <StatusBadge status={bot.status}/>
      </div>
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:12}}>
        <div><div style={{fontSize:10,color:B.muted,marginBottom:3}}>P&L</div><div className="num" style={{fontSize:16,fontWeight:700,color:bot.pnl>0?B.green:bot.pnl<0?B.red:B.muted}}>{f.pnl(bot.pnl)} SOL</div></div>
        <div><div style={{fontSize:10,color:B.muted,marginBottom:3}}>Trades</div><div className="num" style={{fontSize:16,fontWeight:700,color:B.text}}>{bot.trades}</div></div>
        <div><div style={{fontSize:10,color:B.muted,marginBottom:3}}>Win Rate</div><div className="num" style={{fontSize:16,fontWeight:700,color:bot.winRate>.6?B.green:bot.winRate>.4?B.amber:B.red}}>{f.pct(bot.winRate)}</div></div>
      </div>
    </Card>)}
  </div></div>;
}

// ═══════════════════════════════════════════════════════════════════════════
//  PAGE: LAUNCHER
// ═══════════════════════════════════════════════════════════════════════════
function LauncherPage({launchStatus,onLaunch}){
  const {B}=useTheme();
  const [fm,setFm]=useState({name:"",symbol:"",description:"",dev_buy_sol:"0.1",bundle_wallets:"5",bundle_sol_per_wallet:"0.05",enable_volume_bot:false});
  const u=(k,v)=>setFm(p=>({...p,[k]:v}));
  const cost=parseFloat(fm.dev_buy_sol||0)+parseInt(fm.bundle_wallets||0)*parseFloat(fm.bundle_sol_per_wallet||0);
  return <div className="in"><div style={{display:"grid",gridTemplateColumns:"1.2fr .8fr",gap:20}}>
    <Card style={{padding:"22px 24px"}}>
      <div style={{fontSize:14,fontWeight:600,marginBottom:4}}>Create Token</div>
      <div style={{fontSize:11,color:B.muted,marginBottom:20}}>Launch a token on PumpFun with Jito bundle for atomic execution</div>
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,marginBottom:12}}>
        <Inp label="Token Name" value={fm.name} onChange={v=>u("name",v)} ph="PumpDesk Alpha"/>
        <Inp label="Symbol" value={fm.symbol} onChange={v=>u("symbol",v)} ph="PDESK"/>
      </div>
      <Inp label="Description" value={fm.description} onChange={v=>u("description",v)} ph="AI-powered alpha generation..." mb={12}/>
      <div style={{borderTop:`1px solid ${B.border}`,paddingTop:14,marginTop:4}}>
        <div style={{fontSize:10,color:DARK.amber,marginBottom:10,textTransform:"uppercase",letterSpacing:"0.08em",fontWeight:700}}>Jito Bundle Config</div>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:12,marginBottom:12}}>
          <Inp label="Dev Buy (SOL)" value={fm.dev_buy_sol} onChange={v=>u("dev_buy_sol",v)} type="number"/>
          <Inp label="Bundle Wallets" value={fm.bundle_wallets} onChange={v=>u("bundle_wallets",v)} type="number"/>
          <Inp label="SOL / Wallet" value={fm.bundle_sol_per_wallet} onChange={v=>u("bundle_sol_per_wallet",v)} type="number"/>
        </div>
      </div>
      <div style={{marginTop:18,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
        <div><div style={{fontSize:10,color:B.muted,textTransform:"uppercase",letterSpacing:"0.08em",marginBottom:2}}>Total Cost</div><div className="num" style={{fontSize:22,fontWeight:700,color:DARK.amber}}>{cost.toFixed(3)} <span style={{fontSize:13}}>SOL</span></div></div>
        <button onClick={()=>onLaunch(fm)} disabled={!fm.name||!fm.symbol} style={{padding:"10px 24px",background:DARK.amber,border:"none",borderRadius:8,color:"#0f1219",fontWeight:700,fontSize:12,cursor:fm.name&&fm.symbol?"pointer":"not-allowed",opacity:fm.name&&fm.symbol?1:.45}}>Launch Token →</button>
      </div>
    </Card>
    <div>
      <Card style={{padding:"18px 20px",marginBottom:16}}>
        <div style={{fontSize:13,fontWeight:600,marginBottom:8}}>Launch Status</div>
        {launchStatus?<div><div style={{display:"flex",gap:8,alignItems:"center",marginBottom:8}}><StatusBadge status={launchStatus.status}/><span style={{fontWeight:600,fontSize:14}}>{launchStatus.symbol}</span></div>
          {launchStatus.mint&&<div style={{fontSize:11,color:B.muted}}>Mint: <span className="num" style={{color:B.teal}}>{launchStatus.mint}</span></div>}
        </div>:<div style={{color:B.muted,fontSize:12,fontStyle:"italic"}}>Ready to launch</div>}
      </Card>
      <Card style={{padding:"18px 20px"}}>
        <div style={{fontSize:13,fontWeight:600,marginBottom:8}}>Revenue Model</div>
        <div style={{fontSize:11,color:B.muted,lineHeight:1.8}}>
          <div>Pre-grad: sell bundled positions on rising curve</div>
          <div>Post-grad: creator fees <span className="num" style={{color:DARK.amber}}>0.3–0.95%</span> of all trading</div>
          <div>100 SOL/day volume = <span className="num" style={{color:B.green}}>0.3–0.95 SOL/day</span> passive</div>
        </div>
      </Card>
    </div>
  </div></div>;
}

function Inp({label,value,onChange,type,ph,mb}){
  const {B}=useTheme();
  return <div style={{marginBottom:mb||0}}>
    {label&&<div style={{fontSize:10,color:B.muted,marginBottom:4,textTransform:"uppercase",letterSpacing:"0.08em",fontWeight:600}}>{label}</div>}
    <input type={type||"text"} value={value} onChange={e=>onChange(e.target.value)} placeholder={ph} style={{width:"100%",padding:"9px 12px",background:B.surf2,border:`1px solid ${B.border}`,borderRadius:8,color:B.text,fontSize:12,fontFamily:"'JetBrains Mono',monospace",boxSizing:"border-box"}}/>
  </div>;
}


// ═══════════════════════════════════════════════════════════════════════════
//  PAGE: INTELLIGENCE (AI Brain)
// ═══════════════════════════════════════════════════════════════════════════
function IntelPage({assessment,status}){
  const {B}=useTheme();
  const models=[
    {id:"claude",name:"Claude Sonnet 4",provider:"Anthropic",role:"supervisor",color:"#f0a030",status:"live",latency:1200,desc:"Slow path strategic assessment every 5min"},
    {id:"fast",name:"Fast Path Engine",provider:"Custom",role:"rules",color:"#34d399",status:"live",latency:8,desc:"<100ms rule-based signal filtering"},
    {id:"oracle",name:"Graduation Oracle",provider:"Heuristic",role:"prediction",color:"#2ec4b6",status:"live",latency:50,desc:"Token graduation probability scoring"},
    {id:"judge",name:"Creator Judge",provider:"On-chain",role:"scoring",color:"#fbbf24",status:"live",latency:200,desc:"Creator wallet history analysis"},
  ];
  return <div className="in">
    <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:24}}>
      <div>
        <div className="head" style={{fontSize:20,fontWeight:700,letterSpacing:"-0.02em",background:"linear-gradient(135deg,#f0a030,#2ec4b6)",WebkitBackgroundClip:"text",WebkitTextFillColor:"transparent"}}>Two-Tier Decision Engine</div>
        <div style={{fontSize:12,color:B.muted,marginTop:4}}>Fast path rules + slow path Claude AI · orchestrator is the only decision maker</div>
      </div>
      <div style={{display:"flex",gap:8,alignItems:"center"}}>
        <span style={{width:8,height:8,borderRadius:"50%",background:DARK.green,boxShadow:`0 0 8px ${DARK.green}`}}/>
        <span style={{fontSize:11,color:DARK.green,fontWeight:600,letterSpacing:"0.06em"}}>{models.filter(m=>m.status==="live").length} ENGINES LIVE</span>
      </div>
    </div>
    <Card style={{padding:"20px 24px",marginBottom:20}}>
      <CardHeader title="Engine Registry" sub="Each engine has a role in the decision pipeline"/>
      <div style={{display:"flex",flexDirection:"column",gap:10}}>
        {models.map(m=><div key={m.id} style={{display:"grid",gridTemplateColumns:"2fr 1fr 1fr 2fr",gap:12,alignItems:"center",padding:"14px 16px",background:B.surf2,borderRadius:10,border:`1px solid ${m.color}25`}}>
          <div style={{display:"flex",alignItems:"center",gap:10}}>
            <div style={{width:32,height:32,borderRadius:8,background:`${m.color}15`,border:`1px solid ${m.color}30`,display:"flex",alignItems:"center",justifyContent:"center",fontSize:12,fontWeight:700,color:m.color}}>{m.id[0].toUpperCase()}</div>
            <div><div style={{fontSize:12,fontWeight:600}}>{m.name}</div><div style={{fontSize:10,color:B.dim}}>{m.provider}</div></div>
          </div>
          <div style={{display:"flex",alignItems:"center",gap:6}}><span style={{width:7,height:7,borderRadius:"50%",background:m.color,boxShadow:`0 0 6px ${m.color}`}}/><span style={{fontSize:11,fontWeight:600,color:m.color,textTransform:"capitalize"}}>{m.status}</span></div>
          <div><div className="num" style={{fontSize:11,fontWeight:600,color:m.latency<100?B.green:m.latency<500?B.amber:B.sub}}>{m.latency}ms</div><div style={{fontSize:9,color:B.dim}}>latency</div></div>
          <div style={{fontSize:11,color:B.muted}}>{m.desc}</div>
        </div>)}
      </div>
    </Card>
    <Card style={{padding:"20px 24px"}}>
      <CardHeader title="Claude AI Assessment" sub="Slow path strategic analysis" right={assessment?.timestamp&&<span style={{fontSize:10,color:B.muted}}>{f.time(assessment.timestamp)}</span>}/>
      {assessment?<pre style={{color:B.text,fontSize:12,lineHeight:1.7,whiteSpace:"pre-wrap",fontFamily:"'JetBrains Mono',monospace",background:B.bg,padding:14,borderRadius:8,border:`1px solid ${B.border}`,maxHeight:260,overflowY:"auto",margin:"0 20px 20px"}}>{typeof assessment==="string"?assessment:JSON.stringify(assessment,null,2)}</pre>
      :<div style={{padding:"20px",color:B.muted,fontSize:12,fontStyle:"italic"}}>First cycle runs ~60s after startup...</div>}
    </Card>
  </div>;
}

// ═══════════════════════════════════════════════════════════════════════════
//  PAGE: CRM
// ═══════════════════════════════════════════════════════════════════════════
function CRMPage(){
  const {B}=useTheme();
  const [sub,setSub]=useState("wallets");
  const wallets=[
    {address:"5qJd…xM7r",label:"Alpha Whale #1",pnl:42.3,trades:156,winRate:.72,focus:"PumpFun memecoins",confidence:"HIGH",color:"#34d399"},
    {address:"8kPn…yT2q",label:"Sniper Bot",pnl:18.7,trades:89,winRate:.81,focus:"Graduation sniping",confidence:"HIGH",color:"#2ec4b6"},
    {address:"2mRz…wK9s",label:"Dev Wallet A",pnl:-3.2,trades:24,winRate:.42,focus:"Our bundled launches",confidence:"OWN",color:"#f0a030"},
    {address:"4tHn…cN6w",label:"DeFi Native",pnl:67.1,trades:203,winRate:.68,focus:"Cross-DEX arb + LP",confidence:"MEDIUM",color:"#60a5fa"},
    {address:"9vFa…bL4p",label:"Suspected Rugger",pnl:0,trades:12,winRate:0,focus:"Rug pull patterns",confidence:"BLACKLISTED",color:"#f87171"},
  ];
  const pipeline=[
    {stage:"Scouting",color:B.muted,items:[{name:"New creator #45f2",action:"Monitoring first token",age:"12m"},{name:"Whale wallet 9kP",action:"Analyzing trade pattern",age:"2h"}]},
    {stage:"Evaluating",color:DARK.amber,items:[{name:"MOONCAT token",action:"Creator score: 0.71",age:"45m"},{name:"Wallet cluster #8",action:"Backtest running",age:"3h"}]},
    {stage:"Active",color:DARK.green,items:[{name:"SOLGOD (graduating)",action:"91% curve, position open",age:"6h"},{name:"Alpha Whale #1",action:"Copy-trading, +42.3 SOL",age:"2d"}]},
    {stage:"Harvesting",color:DARK.teal,items:[{name:"PDESK creator fees",action:"0.3% fees accruing",age:"1d"},{name:"LP farm SOLGOD/SOL",action:"Pending graduation",age:"—"}]},
  ];
  return <div className="in">
    <div style={{display:"flex",gap:2,marginBottom:20}}>
      {["wallets","pipeline"].map(s=><button key={s} onClick={()=>setSub(s)} style={{padding:"8px 18px",background:sub===s?DARK.amberSoft:"transparent",color:sub===s?DARK.amber:B.muted,border:`1px solid ${sub===s?DARK.amberBorder:"transparent"}`,borderRadius:8,fontSize:12,fontWeight:600,cursor:"pointer",textTransform:"capitalize"}}>{s==="wallets"?"Tracked Wallets":"Deal Pipeline"}</button>)}
    </div>
    {sub==="wallets"&&<div style={{display:"flex",flexDirection:"column",gap:12}}>
      {wallets.map((w,i)=><Card key={i} style={{padding:"16px 20px",borderLeft:`3px solid ${w.color}`}}>
        <div style={{display:"grid",gridTemplateColumns:"2fr 1fr 1fr 1fr 1fr 1fr",gap:12,alignItems:"center"}}>
          <div style={{display:"flex",alignItems:"center",gap:10}}>
            <div style={{width:32,height:32,borderRadius:8,background:`${w.color}15`,border:`1px solid ${w.color}30`,display:"flex",alignItems:"center",justifyContent:"center",fontSize:12,fontWeight:700,color:w.color}}>{w.label[0]}</div>
            <div><div style={{fontSize:12,fontWeight:600}}>{w.label}</div><div className="num" style={{fontSize:10,color:B.dim}}>{w.address}</div></div>
          </div>
          <div><div style={{fontSize:10,color:B.muted,marginBottom:2}}>P&L</div><PnL value={w.pnl}/></div>
          <div><div style={{fontSize:10,color:B.muted,marginBottom:2}}>Trades</div><div className="num" style={{fontSize:13,fontWeight:600}}>{w.trades}</div></div>
          <div><div style={{fontSize:10,color:B.muted,marginBottom:2}}>Win Rate</div><div className="num" style={{fontSize:13,fontWeight:600,color:w.winRate>.6?B.green:B.amber}}>{f.pct(w.winRate)}</div></div>
          <div><div style={{fontSize:10,color:B.muted,marginBottom:2}}>Focus</div><div style={{fontSize:11,color:B.sub}}>{w.focus}</div></div>
          <div><Badge color={w.confidence==="HIGH"?B.green:w.confidence==="BLACKLISTED"?B.red:w.confidence==="OWN"?DARK.amber:B.sub} dot>{w.confidence}</Badge></div>
        </div>
      </Card>)}
    </div>}
    {sub==="pipeline"&&<div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:12}}>
      {pipeline.map(col=><div key={col.stage}>
        <div style={{fontSize:11,fontWeight:700,color:col.color,textTransform:"uppercase",letterSpacing:"0.08em",marginBottom:12,paddingBottom:8,borderBottom:`2px solid ${col.color}33`}}>{col.stage} ({col.items.length})</div>
        {col.items.map((item,i)=><Card key={i} style={{padding:12,marginBottom:8,borderLeft:`3px solid ${col.color}44`}}>
          <div style={{fontSize:12,fontWeight:600,marginBottom:3}}>{item.name}</div>
          <div style={{fontSize:10,color:B.muted}}>{item.action}</div>
          <div style={{fontSize:10,color:B.dim,marginTop:4}}>{item.age}</div>
        </Card>)}
      </div>)}
    </div>}
  </div>;
}

// ═══════════════════════════════════════════════════════════════════════════
//  PAGE: SETTINGS
// ═══════════════════════════════════════════════════════════════════════════
function SettingsPage({status}){
  const {B}=useTheme();
  return <div className="in" style={{maxWidth:960}}><div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:20}}>
    <Card style={{padding:"22px 24px"}}>
      <div style={{fontSize:14,fontWeight:600,marginBottom:16}}>Risk Controls</div>
      {[{k:"Mode",v:status?.paper_mode?"PAPER":"LIVE",c:status?.paper_mode?DARK.yellow:DARK.green},{k:"Max Position",v:"2.0 SOL",c:B.teal},{k:"Max Concurrent",v:"5 positions",c:B.teal},{k:"Max Daily Loss",v:"5.0 SOL",c:B.red},{k:"Emergency Exit",v:"-30% drawdown",c:B.red}].map(r=><div key={r.k} style={{display:"flex",justifyContent:"space-between",padding:"8px 0",borderBottom:`1px solid ${B.border}`}}>
        <span style={{fontSize:13,color:B.text}}>{r.k}</span><span className="num" style={{fontSize:13,color:r.c,fontWeight:600}}>{r.v}</span>
      </div>)}
      <div style={{marginTop:16,fontSize:10,color:DARK.amber,fontWeight:700,textTransform:"uppercase",letterSpacing:"0.08em",marginBottom:10}}>Exit Stages</div>
      {[["2×","50%"],["5×","25%"],["10×","15%"]].map(([t,s],i)=><div key={i} style={{display:"flex",justifyContent:"space-between",fontSize:12,color:B.muted,padding:"5px 0"}}>
        <span>Stage {i+1}: <span style={{color:B.text}}>{t}</span> gain</span><span className="num" style={{color:B.green}}>sell {s}</span>
      </div>)}
    </Card>
    <Card style={{padding:"22px 24px"}}>
      <div style={{fontSize:14,fontWeight:600,marginBottom:16}}>Architecture</div>
      <div style={{fontSize:11,color:B.muted,lineHeight:2,fontFamily:"'JetBrains Mono',monospace",background:B.bg,padding:14,borderRadius:8,border:`1px solid ${B.border}`}}>
        <div><span style={{color:DARK.amber}}>Services:</span> 20 Docker via Redis pub/sub (24 ch)</div>
        <div><span style={{color:DARK.amber}}>Decision:</span> Fast path &lt;100ms + slow path Claude AI</div>
        <div><span style={{color:DARK.amber}}>Execution:</span> Jito bundles for atomic multi-tx</div>
        <div><span style={{color:DARK.amber}}>Exit:</span> Progressive staged sells + -30% breaker</div>
        <div style={{marginTop:8}}><span style={{color:B.teal}}>PumpFun:</span> 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P</div>
        <div><span style={{color:B.teal}}>Curve:</span> 800M tokens → $69K mcap → PumpSwap</div>
        <div><span style={{color:B.teal}}>Creator fee:</span> 0.3% min → 0.95% max at 420 SOL</div>
      </div>
    </Card>
  </div></div>;
}


// ═══════════════════════════════════════════════════════════════════════════
//  MAIN APP (Polydesk-inspired sidebar + header)
// ═══════════════════════════════════════════════════════════════════════════

const NAV=[
  {id:"overview",label:"Overview",icon:"▦"},{id:"bots",label:"Bots",icon:"⚡"},
  {id:"launcher",label:"Launcher",icon:"△"},{id:"intel",label:"Intelligence",icon:"✦"},
  {id:"crm",label:"CRM",icon:"⊕"},{id:"settings",label:"Settings",icon:"⚙"},
];

export default function PumpDesk(){
  const [page,setPage]=useState("overview");
  const [mode,setMode]=useState("paper");
  const [status,setStatus]=useState(null);
  const [positions,setPositions]=useState([]);
  const [trades,setTrades]=useState([]);
  const [hotTokens,setHotTokens]=useState([]);
  const [assessment,setAssessment]=useState(null);
  const [signals,setSignals]=useState([]);
  const [launchStatus,setLaunchStatus]=useState(null);
  const [wsOk,setWsOk]=useState(false);
  const wsRef=useRef(null);
  const B=DARK, M=MODE[mode];

  const fetchAll=useCallback(async()=>{
    try{
      const [s,p,t,h,a]=await Promise.allSettled([
        fetch(API+"/status").then(r=>r.json()),fetch(API+"/positions").then(r=>r.json()),
        fetch(API+"/trades?limit=30").then(r=>r.json()),fetch(API+"/hot-tokens").then(r=>r.json()),
        fetch(API+"/assessment").then(r=>r.json()),
      ]);
      if(s.status==="fulfilled")setStatus(s.value);if(p.status==="fulfilled")setPositions(p.value?.positions||[]);
      if(t.status==="fulfilled")setTrades(t.value?.trades||[]);if(h.status==="fulfilled")setHotTokens(h.value?.tokens||[]);
      if(a.status==="fulfilled")setAssessment(a.value);
    }catch{}
  },[]);

  useEffect(()=>{let ws,rt;const connect=()=>{try{ws=new WebSocket(WS_URL);wsRef.current=ws;ws.onopen=()=>setWsOk(true);ws.onclose=()=>{setWsOk(false);rt=setTimeout(connect,3000);};ws.onerror=()=>ws.close();ws.onmessage=e=>{try{const msg=JSON.parse(e.data);setSignals(p=>[...p.slice(-250),msg]);if(msg.type==="assessment")setAssessment(msg.data);if(msg.type==="launch_status")setLaunchStatus(msg);if(msg.type?.includes("position"))fetchAll();}catch{}};}catch{}};connect();return()=>{ws?.close();clearTimeout(rt);};},[fetchAll]);
  useEffect(()=>{fetchAll();const iv=setInterval(fetchAll,10000);return()=>clearInterval(iv);},[fetchAll]);

  const handleLaunch=(fm)=>{if(wsRef.current?.readyState===1)wsRef.current.send(JSON.stringify({type:"launch",data:fm}));setLaunchStatus({status:"preparing",symbol:fm.symbol});};
  const activeBots=BOTS.filter(b=>b.status==="live").length;

  return <ThemeCtx.Provider value={{B,M}}>
    <div style={{display:"flex",minHeight:"100vh",background:B.bg,color:B.text,fontFamily:"'Outfit','Plus Jakarta Sans',sans-serif",transition:"background 0.3s"}}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
        *{box-sizing:border-box;margin:0;padding:0;}
        ::-webkit-scrollbar{width:4px;height:4px}::-webkit-scrollbar-track{background:transparent}
        ::-webkit-scrollbar-thumb{background:${B.dim};border-radius:4px}
        @keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
        @keyframes in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
        .in{animation:in 0.3s cubic-bezier(.16,1,.3,1) both}
        .bot-row:hover{background:${B.surf2}!important}
        .bot-card{transition:all 0.15s}.bot-card:hover{border-color:${B.borderHover}!important;transform:translateY(-1px)}
        .nav-btn{transition:all 0.15s}.nav-btn:hover{background:${B.surf2}!important}
        .num{font-family:'JetBrains Mono',monospace;font-variant-numeric:tabular-nums;letter-spacing:-0.02em}
        .head{font-family:'Outfit',sans-serif;letter-spacing:-0.02em}
        input:focus{outline:none;border-color:${M.accent}55!important}
        button{cursor:pointer;font-family:inherit}
        ::selection{background:${M.accent}33}
      `}</style>

      {/* ── SIDEBAR ── */}
      <aside style={{width:210,flexShrink:0,background:B.surf,borderRight:`1px solid ${B.border}`,display:"flex",flexDirection:"column",position:"sticky",top:0,height:"100vh"}}>
        <div style={{padding:"18px 14px 14px",borderBottom:`1px solid ${B.border}`}}>
          <div style={{display:"flex",alignItems:"center",gap:10}}>
            <div style={{width:34,height:34,borderRadius:10,background:`linear-gradient(135deg,${DARK.amber},${DARK.teal})`,display:"flex",alignItems:"center",justifyContent:"center",flexShrink:0,boxShadow:`0 4px 14px ${M.accent}22`}}>
              <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth={2.5} strokeLinecap="round"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
            </div>
            <div>
              <div className="head" style={{fontWeight:800,fontSize:15,color:B.text}}>PUMP<span style={{fontWeight:300}}>DESK</span></div>
              <div style={{fontSize:10,color:B.muted,marginTop:2,display:"flex",alignItems:"center",gap:5}}>
                <span style={{width:5,height:5,borderRadius:"50%",background:wsOk?B.green:B.muted,animation:wsOk?"pulse 2s infinite":"none"}}/>
                <span className="num">v2.0</span>
              </div>
            </div>
          </div>
        </div>
        <nav style={{padding:"8px 6px",flex:1,overflowY:"auto"}}>
          {NAV.map(item=>{
            const active=page===item.id;
            return <button key={item.id} className="nav-btn" onClick={()=>setPage(item.id)} style={{
              display:"flex",alignItems:"center",gap:9,width:"100%",padding:"9px 10px",borderRadius:8,border:"none",
              background:active?M.accentSoft:"transparent",color:active?M.accentText:B.sub,
              fontSize:13,fontWeight:active?600:400,textAlign:"left",marginBottom:1,
            }}>
              <span style={{fontSize:13,width:18,textAlign:"center",flexShrink:0,filter:active?"none":"opacity(0.55)"}}>{item.icon}</span>
              {item.label}
              {item.id==="bots"&&activeBots>0&&<span style={{marginLeft:"auto",fontSize:9,background:B.greenSoft,color:B.green,borderRadius:8,padding:"2px 6px",fontWeight:700}}>{activeBots}</span>}
              {item.id==="intel"&&<span style={{marginLeft:"auto",fontSize:9,background:M.accentSoft,color:M.accentText,borderRadius:8,padding:"2px 6px",fontWeight:700}}>AI</span>}
            </button>;
          })}
        </nav>
        <div style={{padding:"10px 14px",borderTop:`1px solid ${B.border}`}}>
          <div style={{fontSize:10,color:B.dim,fontFamily:"'JetBrains Mono',monospace"}}>{new Date().toUTCString().slice(17,25)} UTC</div>
        </div>
      </aside>

      {/* ── MAIN ── */}
      <div style={{flex:1,display:"flex",flexDirection:"column",minWidth:0}}>
        <header style={{height:54,borderBottom:`1px solid ${B.border}`,display:"flex",alignItems:"center",justifyContent:"space-between",padding:"0 22px",background:B.surf,position:"sticky",top:0,zIndex:50,flexShrink:0}}>
          <div>
            <div className="head" style={{fontSize:14,fontWeight:600}}>{NAV.find(n=>n.id===page)?.label}</div>
            <div style={{fontSize:10,color:B.muted,marginTop:1}}>{mode==="paper"?"Paper mode · simulated trades":"Live trading · real SOL deployed"}</div>
          </div>
          <div style={{display:"flex",alignItems:"center",gap:8}}>
            <div style={{display:"flex",alignItems:"center",gap:7,background:M.accentSoft,border:`1px solid ${M.accentBorder}`,borderRadius:8,padding:"5px 11px"}}>
              <span style={{fontSize:10,color:B.muted,letterSpacing:"0.06em",textTransform:"uppercase",fontWeight:500}}>{M.balanceLabel}</span>
              <span className="num" style={{fontSize:13,fontWeight:700,color:M.accentText}}>{f.sol(status?.total_exposure_sol||0,2)} SOL</span>
              {mode==="paper"&&<Badge color={DARK.amber}>PAPER</Badge>}
            </div>
            <ModeSwitch mode={mode} onChange={setMode}/>
          </div>
        </header>
        <main style={{flex:1,padding:22,overflowY:"auto"}}>
          {page==="overview"&&<OverviewPage status={status} positions={positions} trades={trades} hotTokens={hotTokens} signals={signals}/>}
          {page==="bots"&&<BotsPage/>}
          {page==="launcher"&&<LauncherPage launchStatus={launchStatus} onLaunch={handleLaunch}/>}
          {page==="intel"&&<IntelPage assessment={assessment} status={status}/>}
          {page==="crm"&&<CRMPage/>}
          {page==="settings"&&<SettingsPage status={status}/>}
        </main>
      </div>
    </div>
  </ThemeCtx.Provider>;
}

