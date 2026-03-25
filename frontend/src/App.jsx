import { useState, useEffect, useRef, useCallback, createContext, useContext } from "react";
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, LineChart, Line } from "recharts";

/* ═══════════════════════════════════════════════════════════════════════════
   PUMPDESK v2 — SOLANA ALPHA DESK (PRODUCTION BUILD)
   Fully wired to API. No mock data. Every component interactive.
   ═══════════════════════════════════════════════════════════════════════════ */

const API = typeof window !== "undefined" && window.location.hostname === "localhost" ? "http://localhost:8765" : "";
const WS_URL = typeof window !== "undefined" && window.location.hostname === "localhost" ? "ws://localhost:8765/ws" : typeof window !== "undefined" ? `wss://${window.location.host}/ws` : "";

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
  paper:{ accent:"#f0a030", accentSoft:"rgba(240,160,48,0.1)", accentBorder:"rgba(240,160,48,0.25)", accentText:"#f5b94e", label:"PAPER", balanceLabel:"Paper Balance" },
  live: { accent:"#34d399", accentSoft:"rgba(52,211,153,0.1)", accentBorder:"rgba(52,211,153,0.25)", accentText:"#4eeaad", label:"LIVE",  balanceLabel:"SOL Balance" },
};
const ThemeCtx = createContext({ B: DARK, M: MODE.paper });
const useTheme = () => useContext(ThemeCtx);

const f = {
  sol:(v,d=4)=>v==null?"—":`${Number(v).toFixed(d)}`,
  pnl:(v,d=3)=>v==null?"—":`${v>=0?"+":""}${Number(v).toFixed(d)}`,
  pct:(v)=>v==null?"—":`${(v*100).toFixed(1)}%`,
  num:(v)=>v==null?"—":Number(v).toLocaleString(),
  addr:(a,n=4)=>a?`${a.slice(0,n)}…${a.slice(-n)}`:"—",
  time:(iso)=>{try{return new Date(iso).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",second:"2-digit"});}catch{return"—";}},
  date:(iso)=>{try{return new Date(iso).toLocaleDateString("en-US",{month:"short",day:"numeric"});}catch{return"—";}},
  age:(iso)=>{if(!iso)return"—";const ms=Date.now()-new Date(iso).getTime();return ms<6e4?`${~~(ms/1e3)}s`:ms<36e5?`${~~(ms/6e4)}m`:`${~~(ms/36e5)}h`;},
};

const BOT_DESCS = {
  graduation_sniper:"Monitors all PumpFun tokens approaching 100% bonding curve. When a token nears graduation ($69K mcap), snipes entry before the PumpSwap migration creates a price spike. Uses curve_analyzer for real-time bonding curve math.",
  wallet_copier:"Tracks profitable wallets from CRM and mirrors their trades with configurable delay and position sizing. Parses Solana transactions in real-time via Geyser gRPC.",
  multi_dex_arb:"Scans Raydium, Orca, Jupiter, PumpSwap, and Meteora every 5s for standing price discrepancies. Executes corrective arb via Jito bundles for atomic multi-hop.",
  momentum_scanner:"Detects sudden volume and price acceleration across PumpFun tokens. Filters by creator score, holder distribution, and social signals before generating buy signals.",
  token_launcher:"Creates new PumpFun tokens with atomically bundled buys via Jito. Dev wallet + N bundle wallets buy in the same block. Manages graduation monitoring and creator fee collection.",
  volume_bot:"Executes buy+sell in the same Jito bundle for net-zero volume generation. Makes tokens appear on PumpFun trending lists. Three patterns: organic, boost, stealth.",
  anti_sniper:"Creates tokens designed to trigger sniper bot auto-buys, then sells bundled positions into the snipers. Ethically gray — disabled by default.",
  jito_backrunner:"Watches Solana mempool for large swaps, calculates backrun arb opportunities, and submits atomic Jito bundles. Shares flashloan infrastructure with liquidation bot.",
  liquidation_bot:"Monitors Kamino, MarginFi, Solend, and Drift for undercollateralized positions. Executes flashloan liquidations when health factor drops below 1.0.",
  yield_optimizer:"Deploys into JLP positions with delta-neutral hedging. Also monitors lending rate spreads across protocols for rate arbitrage opportunities.",
};

// ── Shared UI ───────────────────────────────────────────────────────────────
function Badge({color,children,dot}){const c=color||DARK.muted;return<span style={{display:"inline-flex",alignItems:"center",gap:4,padding:"2px 8px",borderRadius:20,background:c+"15",color:c,fontSize:10,fontWeight:700,letterSpacing:"0.06em",textTransform:"uppercase",fontFamily:"'JetBrains Mono',monospace"}}>{dot&&<span style={{width:5,height:5,borderRadius:"50%",background:c,flexShrink:0}}/>}{children}</span>;}
function Card({children,style={},className,onClick}){const{B}=useTheme();return<div className={className} onClick={onClick} style={{background:B.surf,border:`1px solid ${B.border}`,borderRadius:14,boxShadow:"0 2px 8px rgba(0,0,0,0.25)",...style}}>{children}</div>;}
function CardHeader({title,sub,right}){const{B}=useTheme();return<div style={{padding:"18px 20px 0",marginBottom:14,display:"flex",justifyContent:"space-between",alignItems:"flex-start"}}><div><div style={{fontSize:13,fontWeight:600,color:B.text,letterSpacing:"-0.01em"}}>{title}</div>{sub&&<div style={{fontSize:11,color:B.muted,marginTop:3}}>{sub}</div>}</div>{right}</div>;}
function Sparkline({data,color,h=20,w=58}){const{B}=useTheme();if(!data?.length)return null;const max=Math.max(...data),min=Math.min(...data);const pts=data.map((v,i)=>`${(i/(data.length-1))*w},${h-2-((v-min)/(max-min||1))*(h-4)}`).join(" ");const c=color||(data[data.length-1]>=data[0]?B.green:B.red);return<svg width={w} height={h}><polyline points={pts} fill="none" stroke={c} strokeWidth={1.5} strokeLinejoin="round" opacity={.85}/></svg>;}
function StatusBadge({status}){const{B}=useTheme();const map={live:{bg:B.greenSoft,c:B.green},paused:{bg:B.amberSoft,c:B.amber},error:{bg:B.redSoft,c:B.red},planned:{bg:B.surf2,c:B.muted},open:{bg:B.tealSoft,c:B.teal},closed:{bg:B.surf2,c:B.muted},preparing:{bg:B.amberSoft,c:B.amber},launched:{bg:B.greenSoft,c:B.green},failed:{bg:B.redSoft,c:B.red},stalled:{bg:B.amberSoft,c:B.amber},graduating:{bg:B.amberSoft,c:B.yellow},graduated:{bg:B.tealSoft,c:B.teal},dead:{bg:B.surf2,c:B.dim}};const s=map[status]||{bg:B.surf2,c:B.muted};return<span style={{display:"inline-flex",alignItems:"center",gap:4,background:s.bg,color:s.c,fontSize:10,fontWeight:700,letterSpacing:"0.06em",padding:"3px 9px",borderRadius:20,textTransform:"uppercase"}}>{(status==="live"||status==="open")&&<span style={{width:5,height:5,borderRadius:"50%",background:s.c,animation:"pulse 2s infinite"}}/>}{status||"—"}</span>;}
function ChartTip({active,payload,label}){const{B}=useTheme();if(!active||!payload?.length)return null;return<div style={{background:B.surf,border:`1px solid ${B.border}`,borderRadius:8,padding:"10px 14px",fontSize:12,boxShadow:"0 8px 32px rgba(0,0,0,0.4)"}}><div style={{color:B.muted,marginBottom:4,fontSize:11,fontFamily:"'JetBrains Mono',monospace"}}>{label}</div>{payload.map((p,i)=><div key={i} style={{color:p.color||B.text,fontWeight:600,fontFamily:"'JetBrains Mono',monospace"}}>{p.name}: {typeof p.value==="number"?f.sol(p.value,3):p.value} SOL</div>)}</div>;}
function Table({cols,rows,empty,onRowClick}){const{B}=useTheme();if(!rows?.length)return<div style={{padding:20,color:B.muted,textAlign:"center",fontSize:12,fontStyle:"italic"}}>{empty||"No data"}</div>;return<div style={{overflowX:"auto"}}><table style={{width:"100%",borderCollapse:"separate",borderSpacing:0,fontSize:12}}><thead><tr>{cols.map((c,i)=><th key={i} style={{padding:"8px 10px",textAlign:c.align||"left",color:B.muted,fontSize:10,fontWeight:600,textTransform:"uppercase",letterSpacing:"0.06em",borderBottom:`1px solid ${B.border}`,whiteSpace:"nowrap",background:B.surf}}>{c.label}</th>)}</tr></thead><tbody>{rows.map((r,ri)=><tr key={ri} className="bot-row" onClick={()=>onRowClick?.(r)} style={{borderBottom:`1px solid ${B.bg}`,cursor:onRowClick?"pointer":"default"}}>{cols.map((c,ci)=><td key={ci} style={{padding:"8px 10px",color:B.text,whiteSpace:"nowrap",textAlign:c.align||"left",fontFamily:c.mono?"'JetBrains Mono',monospace":"inherit",fontSize:c.mono?11:12}}>{c.render?c.render(r):r[c.key]}</td>)}</tr>)}</tbody></table></div>;}
function PnL({value}){const{B}=useTheme();if(value==null||isNaN(value))return<span style={{color:B.muted}}>—</span>;const v=Number(value);const c=v>0?B.green:v<0?B.red:B.muted;return<span className="num" style={{color:c,fontWeight:600}}>{f.pnl(v)}</span>;}
function ModeSwitch({mode,onChange}){const{B}=useTheme();return<div style={{display:"flex",background:B.surf2,border:`1px solid ${B.border}`,borderRadius:8,overflow:"hidden"}}>{["paper","live"].map(m=><button key={m} onClick={()=>onChange(m)} style={{padding:"5px 14px",fontSize:10,fontWeight:mode===m?700:400,background:mode===m?(m==="paper"?DARK.amberSoft:DARK.greenSoft):"transparent",color:mode===m?(m==="paper"?DARK.amber:DARK.green):B.muted,border:"none",letterSpacing:"0.06em",textTransform:"uppercase",cursor:"pointer",transition:"all 0.15s"}}>{m}</button>)}</div>;}
function Inp({label,value,onChange,type,ph,mb,w}){const{B}=useTheme();return<div style={{marginBottom:mb||0,width:w||"100%"}}>{label&&<div style={{fontSize:10,color:B.muted,marginBottom:4,textTransform:"uppercase",letterSpacing:"0.08em",fontWeight:600}}>{label}</div>}<input type={type||"text"} value={value} onChange={e=>onChange(e.target.value)} placeholder={ph} style={{width:"100%",padding:"9px 12px",background:B.surf2,border:`1px solid ${B.border}`,borderRadius:8,color:B.text,fontSize:12,fontFamily:"'JetBrains Mono',monospace",boxSizing:"border-box"}}/></div>;}
function Toggle({on,onChange,label}){const{B}=useTheme();return<label style={{display:"flex",alignItems:"center",gap:10,cursor:"pointer",fontSize:12,color:B.text}}><div onClick={e=>{e.preventDefault();onChange(!on);}} style={{width:36,height:20,borderRadius:10,position:"relative",transition:"all .2s",background:on?DARK.amber+"33":B.surf2,border:`1.5px solid ${on?DARK.amber:B.border}`}}><div style={{width:14,height:14,borderRadius:7,position:"absolute",top:1.5,left:on?18:2,transition:"all .2s",background:on?DARK.amber:B.muted}}/></div>{label}</label>;}
function Toast({msg,type,onDone}){useEffect(()=>{const t=setTimeout(onDone,3000);return()=>clearTimeout(t);},[onDone]);const c=type==="error"?DARK.red:type==="success"?DARK.green:DARK.amber;return<div style={{position:"fixed",bottom:24,right:24,background:DARK.surf,border:`1px solid ${c}44`,borderRadius:10,padding:"12px 20px",color:c,fontSize:12,fontWeight:600,boxShadow:`0 8px 32px rgba(0,0,0,0.5)`,zIndex:200,animation:"in 0.3s both",fontFamily:"'JetBrains Mono',monospace"}}>{msg}</div>;}
function Skeleton({h=16,w="100%",r=6}){return<div style={{height:h,width:w,borderRadius:r,background:DARK.surf2,animation:"pulse 1.5s infinite"}}/>;}
function SignalFeed({signals}){const{B}=useTheme();const ref=useRef(null);useEffect(()=>{if(ref.current)ref.current.scrollTop=ref.current.scrollHeight;},[signals]);return<div ref={ref} style={{height:200,overflowY:"auto",background:B.bg,borderRadius:8,border:`1px solid ${B.border}`,padding:10,fontFamily:"'JetBrains Mono',monospace",fontSize:11}}>{!signals?.length&&<div style={{color:B.muted,padding:10,fontStyle:"italic"}}>Awaiting signals...</div>}{signals?.map((s,i)=><div key={i} style={{padding:"3px 0",borderBottom:`1px solid ${B.surf}`,lineHeight:1.5}}><span style={{color:B.dim}}>{f.time(s.timestamp||s.created_at)}</span>{" "}<span style={{color:DARK.amber}}>[{s.signal_summary?.bot||s.bot||s.type||"SYS"}]</span>{" "}<span style={{color:s.data?.approved?B.green:s.data?.approved===false?B.red:B.text}}>{s.signal_summary?`${s.signal_summary.token} ${s.signal_summary.action} (${(s.signal_summary.confidence*100).toFixed(0)}%) → ${s.data?.approved?"✓ APPROVED":"✗ REJECTED"}`:(s.reason||s.signal_type||s.status||JSON.stringify(s).slice(0,80))}</span></div>)}</div>;}


// ═══════════════════════════════════════════════════════════════════════════
//  BOT DRAWER — per-bot data from API, unique trades/signals/chart per bot
// ═══════════════════════════════════════════════════════════════════════════
function BotDrawer({bot,onClose,signals,allTrades}){
  const {B}=useTheme();
  const [tab,setTab]=useState("overview");
  const [botTrades,setBotTrades]=useState(null);
  const [loading,setLoading]=useState(true);

  // Fetch per-bot trades from API
  useEffect(()=>{
    setLoading(true);
    fetch(API+`/trades?bot=${bot.key}&limit=50`).then(r=>r.json()).then(d=>{setBotTrades(d.trades||[]);setLoading(false);}).catch(()=>{setBotTrades([]);setLoading(false);});
  },[bot.key]);

  // Filter WS signals for this bot
  const botSignals=(signals||[]).filter(s=>(s.signal_summary?.bot||s.bot)===bot.key).slice(-20);

  // Build per-bot P&L chart from trades
  const pnlChart=(botTrades||[]).slice().reverse().reduce((acc,t,i)=>{
    const prev=acc.length?acc[acc.length-1].c:0;
    acc.push({d:f.date(t.created_at),c:prev+(t.realized_pnl_sol||0),v:t.realized_pnl_sol||0});
    return acc;
  },[]);

  return<div style={{position:"fixed",top:0,right:0,width:520,height:"100vh",background:B.surf,borderLeft:`1px solid ${B.border}`,zIndex:100,animation:"slidein 0.3s cubic-bezier(.16,1,.3,1)",display:"flex",flexDirection:"column",boxShadow:"-8px 0 32px rgba(0,0,0,0.4)"}}>
    <div style={{padding:"16px 20px",borderBottom:`1px solid ${B.border}`,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
      <div style={{display:"flex",alignItems:"center",gap:10}}>
        <div style={{width:36,height:36,borderRadius:10,background:`${bot.color}15`,border:`1px solid ${bot.color}30`,display:"flex",alignItems:"center",justifyContent:"center",fontSize:16,fontWeight:700,color:bot.color}}>{bot.id}</div>
        <div><div style={{fontSize:14,fontWeight:600}}>{bot.name}</div><div style={{fontSize:11,color:B.muted}}>{bot.strategy}</div></div>
      </div>
      <div style={{display:"flex",alignItems:"center",gap:8}}>
        <StatusBadge status={bot.status}/>
        <button onClick={onClose} style={{background:"none",border:"none",color:B.muted,fontSize:18,padding:4,cursor:"pointer"}}>✕</button>
      </div>
    </div>
    <div style={{display:"flex",borderBottom:`1px solid ${B.border}`}}>
      {["overview","trades","signals","controls"].map(t=><button key={t} onClick={()=>setTab(t)} style={{padding:"10px 16px",fontSize:11,fontWeight:tab===t?700:400,background:"transparent",border:"none",borderBottom:`2px solid ${tab===t?bot.color:"transparent"}`,color:tab===t?B.text:B.muted,cursor:"pointer",textTransform:"capitalize"}}>{t}{t==="trades"&&botTrades?.length?` (${botTrades.length})`:""}{t==="signals"&&botSignals.length?` (${botSignals.length})`:""}</button>)}
    </div>
    <div style={{flex:1,overflowY:"auto",padding:20}}>
      {tab==="overview"&&<div>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr 1fr",gap:10,marginBottom:20}}>
          <Card style={{padding:12}}><div style={{fontSize:9,color:B.muted,marginBottom:3}}>P&L</div><div className="num" style={{fontSize:16,fontWeight:700,color:bot.pnl>0?B.green:bot.pnl<0?B.red:B.muted}}>{f.pnl(bot.pnl)}</div></Card>
          <Card style={{padding:12}}><div style={{fontSize:9,color:B.muted,marginBottom:3}}>TRADES</div><div className="num" style={{fontSize:16,fontWeight:700}}>{bot.trades}</div></Card>
          <Card style={{padding:12}}><div style={{fontSize:9,color:B.muted,marginBottom:3}}>WIN RATE</div><div className="num" style={{fontSize:16,fontWeight:700,color:bot.winRate>.6?B.green:bot.winRate>.4?B.amber:B.muted}}>{f.pct(bot.winRate)}</div></Card>
          <Card style={{padding:12}}><div style={{fontSize:9,color:B.muted,marginBottom:3}}>OPEN</div><div className="num" style={{fontSize:16,fontWeight:700,color:B.teal}}>{bot.openPositions||0}</div></Card>
        </div>
        <div style={{fontSize:12,color:B.sub,lineHeight:1.7,marginBottom:16}}>{BOT_DESCS[bot.key]||bot.strategy}</div>
        <Card style={{padding:"14px 16px",marginBottom:16}}>
          <div style={{fontSize:11,color:B.muted,marginBottom:8,textTransform:"uppercase",letterSpacing:"0.06em",fontWeight:600}}>Cumulative P&L</div>
          {loading?<Skeleton h={100}/>:pnlChart.length?<ResponsiveContainer width="100%" height={100}>
            <AreaChart data={pnlChart}><defs><linearGradient id={`dbg${bot.id}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={bot.color} stopOpacity={.2}/><stop offset="100%" stopColor={bot.color} stopOpacity={0}/></linearGradient></defs>
              <XAxis dataKey="d" tick={{fill:B.muted,fontSize:9}} axisLine={false} tickLine={false} interval="preserveStartEnd"/>
              <Tooltip content={<ChartTip/>}/>
              <Area type="monotone" dataKey="c" stroke={bot.color} strokeWidth={2} fill={`url(#dbg${bot.id})`} dot={false} name="Cumulative"/>
            </AreaChart>
          </ResponsiveContainer>:<div style={{color:B.muted,fontSize:11,padding:20,textAlign:"center"}}>No trades yet — waiting for first signal</div>}
        </Card>
        {pnlChart.length>1&&<Card style={{padding:"14px 16px"}}>
          <div style={{fontSize:11,color:B.muted,marginBottom:8,textTransform:"uppercase",letterSpacing:"0.06em",fontWeight:600}}>Per-Trade P&L</div>
          <ResponsiveContainer width="100%" height={80}>
            <BarChart data={pnlChart} barSize={6}><XAxis dataKey="d" hide/><Tooltip content={<ChartTip/>}/>
              <Bar dataKey="v" name="Trade P&L" radius={[2,2,0,0]}>{pnlChart.map((e,i)=><Cell key={i} fill={(e.v||0)>=0?B.green:B.red} fillOpacity={.7}/>)}</Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>}
      </div>}
      {tab==="trades"&&<div>
        {loading?<div style={{display:"flex",flexDirection:"column",gap:8}}>{[1,2,3].map(i=><Skeleton key={i} h={40}/>)}</div>:
        <Table cols={[
          {label:"Time",render:r=><span className="num" style={{fontSize:10}}>{f.time(r.created_at)}</span>},
          {label:"Action",render:r=><Badge color={r.action==="buy"?B.green:B.red}>{r.action}</Badge>},
          {label:"Mint",render:r=><span style={{color:B.teal,cursor:"pointer"}} title={r.mint}>{f.addr(r.mint,5)}</span>,mono:true},
          {label:"Size",render:r=>f.sol(r.size_sol,3),align:"right",mono:true},
          {label:"P&L",render:r=><PnL value={r.realized_pnl_sol}/>,align:"right"},
          {label:"Reason",render:r=><span style={{fontSize:10,color:B.muted,maxWidth:120,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap",display:"inline-block"}}>{r.reason||r.signal_type||"—"}</span>},
        ]} rows={botTrades} empty={`No trades for ${bot.name} yet`}/>}
      </div>}
      {tab==="signals"&&<div>
        {botSignals.length?botSignals.slice().reverse().map((s,i)=><Card key={i} style={{padding:"12px 16px",marginBottom:8}}>
          <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:4}}>
            <Badge color={s.data?.approved?B.green:B.red}>{s.data?.approved?"APPROVED":"REJECTED"}</Badge>
            <span className="num" style={{fontSize:10,color:B.dim}}>{f.time(s.timestamp||s.created_at)}</span>
          </div>
          <div style={{fontSize:12,color:B.text}}>{s.signal_summary?.token} — {s.signal_summary?.action}</div>
          <div style={{fontSize:10,color:B.muted,marginTop:4}}>Confidence: <span style={{color:(s.signal_summary?.confidence||0)>.7?B.green:B.amber,fontWeight:600}}>{f.pct(s.signal_summary?.confidence)}</span>
          {s.data?.reason&&<span style={{marginLeft:8}}>· {s.data.reason}</span>}</div>
          {s.correlation?.corroborating_bots?.length>0&&<div style={{fontSize:10,color:B.teal,marginTop:2}}>Corroborated by: {s.correlation.corroborating_bots.join(", ")}</div>}
        </Card>):<div style={{color:B.muted,fontSize:12,padding:20,textAlign:"center"}}>No signals from {bot.name} in this session</div>}
      </div>}
      {tab==="controls"&&<BotControls bot={bot}/>}
    </div>
  </div>;
}

function BotControls({bot}){
  const {B}=useTheme();
  const [saving,setSaving]=useState(false);
  const [toast,setToast]=useState(null);
  return<div>
    <Card style={{padding:"16px 20px",marginBottom:16}}>
      <div style={{fontSize:12,fontWeight:600,marginBottom:8}}>Status</div>
      <div style={{display:"flex",alignItems:"center",gap:12}}>
        <StatusBadge status={bot.status}/>
        <span style={{fontSize:12,color:B.sub}}>{bot.enabled?"Receiving signals from Redis":"Paused — not listening"}</span>
      </div>
      <div style={{fontSize:10,color:B.muted,marginTop:8}}>Bot key: <span className="num" style={{color:B.teal}}>{bot.key}</span></div>
      <div style={{fontSize:10,color:B.muted,marginTop:2}}>Open positions: <span className="num">{bot.openPositions||0}</span></div>
    </Card>
    <Card style={{padding:"16px 20px",marginBottom:16}}>
      <div style={{fontSize:12,fontWeight:600,marginBottom:8}}>Configuration</div>
      <div style={{fontSize:11,color:B.muted,lineHeight:1.8,fontFamily:"'JetBrains Mono',monospace",background:B.bg,padding:12,borderRadius:8,border:`1px solid ${B.border}`}}>
        <div><span style={{color:DARK.amber}}>ENABLE_{bot.key.toUpperCase()}=</span><span style={{color:bot.enabled?B.green:B.red}}>{bot.enabled?"true":"false"}</span></div>
        <div><span style={{color:DARK.amber}}>MAX_POSITION_SOL=</span><span style={{color:B.text}}>configured in Settings</span></div>
        <div><span style={{color:DARK.amber}}>MIN_CONFIDENCE=</span><span style={{color:B.text}}>per fast_path.py rules</span></div>
      </div>
    </Card>
    <Card style={{padding:"16px 20px"}}>
      <div style={{fontSize:12,fontWeight:600,marginBottom:8,color:B.red}}>Danger Zone</div>
      <button onClick={()=>{setSaving(true);fetch(API+"/blacklist/token",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({mint:"EMERGENCY_STOP_"+bot.key})}).then(()=>{setToast("Emergency stop sent");setSaving(false);}).catch(()=>{setToast("Failed — orchestrator may be down");setSaving(false);});}} disabled={saving} style={{padding:"8px 16px",background:B.redSoft,border:`1px solid ${B.red}33`,borderRadius:8,color:B.red,fontSize:11,fontWeight:600,opacity:saving?.5:1}}>
        {saving?"Stopping...":"Emergency Stop Bot"}
      </button>
      <div style={{fontSize:10,color:B.muted,marginTop:6}}>Sends kill signal via Redis to halt all processing for this bot.</div>
    </Card>
    {toast&&<Toast msg={toast} type="success" onDone={()=>setToast(null)}/>}
  </div>;
}


// ═══════════════════════════════════════════════════════════════════════════
//  PAGE: OVERVIEW — fully wired to API data
// ═══════════════════════════════════════════════════════════════════════════
function OverviewPage({bots,status,positions,hotTokens,signals,allTrades,period,setPeriod}){
  const {B,M}=useTheme();
  const totalPnl=bots.reduce((s,b)=>s+(b.pnl||0),0);
  const activeBots=bots.filter(b=>b.enabled).length;
  const totalTrades=bots.reduce((s,b)=>s+(b.trades||0),0);
  const pieData=bots.filter(b=>(b.pnl||0)!==0).map(b=>({name:b.name?.split(" ")[0]||b.key,value:b.pnl,color:b.color}));

  // Build cumulative chart from real trades
  const cumChart=(allTrades||[]).slice().reverse().reduce((acc,t)=>{
    const prev=acc.length?acc[acc.length-1].c:0;
    acc.push({d:f.date(t.created_at),c:prev+(t.realized_pnl_sol||0),v:t.realized_pnl_sol||0});
    return acc;
  },[]);

  // Build daily P&L from trades grouped by date
  const dailyPnl=Object.entries((allTrades||[]).reduce((acc,t)=>{
    const d=f.date(t.created_at);acc[d]=(acc[d]||0)+(t.realized_pnl_sol||0);return acc;
  },{})).map(([d,v])=>({d,v:Number(v.toFixed(4))}));

  // Sparkline from last 20 trades cumulative
  const sparkData=cumChart.slice(-20).map(c=>c.c);

  return <div className="in">
    <div style={{background:M.accentSoft,border:`1px solid ${M.accentBorder}`,borderRadius:10,padding:"10px 16px",marginBottom:20,display:"flex",alignItems:"center",gap:12,flexWrap:"wrap"}}>
      <span style={{width:7,height:7,borderRadius:"50%",background:M.accent,animation:"pulse 2s infinite"}}/><span style={{fontSize:12,color:M.accentText,fontWeight:600}}>{M.label} Mode — {activeBots} Bots Active</span>
      <span style={{fontSize:11,color:B.muted}}>Orchestrator: fast path &lt;100ms · slow path Claude AI · {status?.daily_trades||totalTrades} trades today</span>
      <div style={{marginLeft:"auto",display:"flex",gap:2}}>{["1D","7D","1M","ALL"].map(p=><button key={p} onClick={()=>setPeriod(p)} style={{padding:"3px 8px",fontSize:9,fontWeight:period===p?700:400,background:period===p?M.accentSoft:"transparent",color:period===p?M.accentText:B.muted,border:`1px solid ${period===p?M.accentBorder:"transparent"}`,borderRadius:4,cursor:"pointer"}}>{p}</button>)}</div>
    </div>
    <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:16,marginBottom:24}}>
      {[{label:"Total P&L",value:f.pnl(status?.daily_pnl_sol||totalPnl)+" SOL",sub:`${activeBots} bots active`,color:(status?.daily_pnl_sol||totalPnl)>=0?B.green:B.red,spark:sparkData},
        {label:"Active Bots",value:`${activeBots}/10`,sub:"Running in "+M.label.toLowerCase(),color:activeBots>0?B.green:B.muted},
        {label:"Trades Today",value:f.num(status?.daily_trades||totalTrades),sub:`Daily loss: ${f.sol(status?.daily_loss_sol||0,2)} SOL`,color:B.amber},
        {label:"Exposure",value:f.sol(status?.total_exposure_sol||0,2)+" SOL",sub:status?.open_positions?`${status.open_positions} positions`:"No positions",color:B.teal}
      ].map((k,i)=><Card key={i} style={{padding:"18px 20px"}}>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:12}}><span style={{fontSize:10,color:B.muted,letterSpacing:"0.06em",fontWeight:600,textTransform:"uppercase"}}>{k.label}</span>{k.spark?.length>2&&<Sparkline data={k.spark}/>}</div>
        <div className="num" style={{fontSize:26,fontWeight:700,color:k.color,lineHeight:1,letterSpacing:"-0.03em",marginBottom:6}}>{k.value}</div><div style={{fontSize:11,color:B.muted}}>{k.sub}</div>
      </Card>)}
    </div>
    <div style={{display:"grid",gridTemplateColumns:"1.4fr 1fr",gap:20,marginBottom:20}}>
      <Card style={{padding:"20px 20px 12px"}}><CardHeader title="Cumulative Return" sub={`${cumChart.length} trades · SOL`}/>
        {cumChart.length?<ResponsiveContainer width="100%" height={200}><AreaChart data={cumChart} margin={{top:4,right:4,bottom:0,left:-20}}><defs><linearGradient id="pg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={M.accent} stopOpacity={.22}/><stop offset="100%" stopColor={M.accent} stopOpacity={0}/></linearGradient></defs><CartesianGrid strokeDasharray="2 4" stroke={B.border} vertical={false}/><XAxis dataKey="d" tick={{fill:B.muted,fontSize:10}} axisLine={false} tickLine={false} interval="preserveStartEnd"/><YAxis tick={{fill:B.muted,fontSize:10}} axisLine={false} tickLine={false} tickFormatter={v=>v.toFixed(2)}/><Tooltip content={<ChartTip/>}/><Area type="monotone" dataKey="c" stroke={M.accent} strokeWidth={2.5} fill="url(#pg)" dot={false} name="Cumulative"/></AreaChart></ResponsiveContainer>
        :<div style={{height:200,display:"flex",alignItems:"center",justifyContent:"center",color:B.muted,fontSize:12}}>Trades will appear here when bots execute</div>}
      </Card>
      <Card style={{padding:"18px 20px"}}><CardHeader title="Alpha by Bot" sub="Where SOL comes from"/><div style={{display:"flex",flexDirection:"column",gap:10,marginTop:4}}>{pieData.length?pieData.sort((a,b)=>b.value-a.value).map((cat,i)=><div key={i}><div style={{display:"flex",justifyContent:"space-between",marginBottom:5}}><div style={{display:"flex",alignItems:"center",gap:7}}><span style={{width:8,height:8,borderRadius:2,background:cat.color}}/><span style={{fontSize:12,color:B.sub}}>{cat.name}</span></div><span className="num" style={{fontSize:12,fontWeight:600,color:cat.value>0?B.green:B.red}}>{f.pnl(cat.value)} SOL</span></div><div style={{height:5,background:B.surf2,borderRadius:3,overflow:"hidden"}}><div style={{width:`${Math.min(100,Math.abs(cat.value)/(Math.abs(totalPnl)||1)*100)}%`,height:"100%",borderRadius:3,background:cat.color,opacity:.8}}/></div></div>):<div style={{color:B.muted,fontSize:12,padding:20,textAlign:"center"}}>Waiting for first profitable trade</div>}</div></Card>
    </div>
    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:20,marginBottom:20}}>
      <Card style={{padding:"20px 20px 12px"}}><CardHeader title="Daily P&L" sub="Per-day result"/>
        {dailyPnl.length?<ResponsiveContainer width="100%" height={160}><BarChart data={dailyPnl} barSize={18} margin={{top:0,right:4,bottom:0,left:-20}}><CartesianGrid strokeDasharray="2 4" stroke={B.border} vertical={false}/><XAxis dataKey="d" tick={{fill:B.muted,fontSize:10}} axisLine={false} tickLine={false} interval="preserveStartEnd"/><YAxis tick={{fill:B.muted,fontSize:10}} axisLine={false} tickLine={false} tickFormatter={v=>v.toFixed(2)}/><Tooltip content={<ChartTip/>}/><Bar dataKey="v" name="Daily P&L" radius={[3,3,0,0]}>{dailyPnl.map((e,i)=><Cell key={i} fill={e.v>=0?B.green:B.red} fillOpacity={.75}/>)}</Bar></BarChart></ResponsiveContainer>
        :<div style={{height:160,display:"flex",alignItems:"center",justifyContent:"center",color:B.muted,fontSize:12}}>Daily results will aggregate here</div>}
      </Card>
      <Card style={{padding:"18px 20px"}}><CardHeader title="Hot Tokens" sub="Signal correlation engine"/>
        <Table cols={[{label:"Token",render:r=><span style={{color:DARK.amber,fontWeight:600}}>{r.symbol||f.addr(r.mint)}</span>},{label:"Signals",key:"signal_count",align:"right",mono:true},{label:"Score",render:r=><span style={{color:r.score>.7?B.green:B.amber}}>{f.sol(r.score,2)}</span>,align:"right",mono:true},{label:"Bots",render:r=>(r.bots||[]).join(", ")}]} rows={hotTokens} empty="Scanning for correlated signals..."/>
      </Card>
    </div>
    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:20}}>
      <Card style={{padding:"18px 20px"}}><CardHeader title="Live Signal Feed" sub="Real-time from orchestrator"/><SignalFeed signals={signals}/></Card>
      <Card style={{padding:"18px 20px"}}><CardHeader title="Open Positions" sub={`${positions?.length||0} active`}/><Table cols={[{label:"Bot",key:"bot"},{label:"Mint",render:r=><span style={{color:B.teal}}>{f.addr(r.mint,5)}</span>,mono:true},{label:"Size",render:r=>f.sol(r.size_sol,3),align:"right",mono:true},{label:"uPnL",render:r=><PnL value={r.unrealized_pnl_sol}/>,align:"right"},{label:"Age",render:r=>f.age(r.opened_at||r.created_at),mono:true},{label:"Status",render:r=><StatusBadge status={r.status}/>}]} rows={positions} empty="No open positions"/></Card>
    </div>
  </div>;
}

// ═══════════════════════════════════════════════════════════════════════════
//  PAGE: BOTS — click to open drawer
// ═══════════════════════════════════════════════════════════════════════════
function BotsPage({bots,onSelectBot,loading}){
  const {B}=useTheme();
  if(loading)return<div className="in"><div style={{display:"grid",gridTemplateColumns:"repeat(2,1fr)",gap:16}}>{[1,2,3,4,5,6,7,8,9,10].map(i=><Card key={i} style={{padding:"18px 20px",height:120}}><Skeleton h={16} w="60%"/><div style={{marginTop:12,display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:8}}><Skeleton h={30}/><Skeleton h={30}/><Skeleton h={30}/></div></Card>)}</div></div>;
  return <div className="in"><div style={{display:"grid",gridTemplateColumns:"repeat(2,1fr)",gap:16}}>
    {bots.map(bot=><Card key={bot.id||bot.key} className="bot-card" onClick={()=>onSelectBot(bot)} style={{padding:"18px 20px",borderLeft:`3px solid ${bot.color}`,cursor:"pointer"}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:12}}>
        <div style={{display:"flex",alignItems:"center",gap:10}}>
          <div style={{width:34,height:34,borderRadius:10,background:`${bot.color}15`,border:`1px solid ${bot.color}30`,display:"flex",alignItems:"center",justifyContent:"center",fontSize:15,fontWeight:700,color:bot.color}}>{bot.id}</div>
          <div><div style={{fontSize:13,fontWeight:600,color:B.text}}>{bot.name}</div><div style={{fontSize:11,color:B.muted,marginTop:2}}>{bot.strategy}</div></div>
        </div>
        <StatusBadge status={bot.status}/>
      </div>
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr 1fr",gap:10}}>
        <div><div style={{fontSize:10,color:B.muted,marginBottom:3}}>P&L</div><div className="num" style={{fontSize:14,fontWeight:700,color:(bot.pnl||0)>0?B.green:(bot.pnl||0)<0?B.red:B.muted}}>{f.pnl(bot.pnl||0)} SOL</div></div>
        <div><div style={{fontSize:10,color:B.muted,marginBottom:3}}>Trades</div><div className="num" style={{fontSize:14,fontWeight:700,color:B.text}}>{bot.trades||0}</div></div>
        <div><div style={{fontSize:10,color:B.muted,marginBottom:3}}>Win Rate</div><div className="num" style={{fontSize:14,fontWeight:700,color:(bot.winRate||0)>.6?B.green:(bot.winRate||0)>.4?B.amber:B.muted}}>{f.pct(bot.winRate||0)}</div></div>
        <div><div style={{fontSize:10,color:B.muted,marginBottom:3}}>Open</div><div className="num" style={{fontSize:14,fontWeight:700,color:B.teal}}>{bot.openPositions||0}</div></div>
      </div>
    </Card>)}
  </div></div>;
}


// ═══════════════════════════════════════════════════════════════════════════
//  PAGE: LAUNCHER — with all fields restored + launched tokens portfolio
// ═══════════════════════════════════════════════════════════════════════════
function LauncherPage({launchStatus,onLaunch}){
  const {B}=useTheme();
  const [fm,setFm]=useState({name:"",symbol:"",description:"",image_url:"",twitter:"",telegram:"",website:"",dev_buy_sol:"0.1",bundle_wallets:"5",bundle_sol_per_wallet:"0.05",enable_volume_bot:false});
  const [launched,setLaunched]=useState([]);
  const u=(k,v)=>setFm(p=>({...p,[k]:v}));
  const cost=parseFloat(fm.dev_buy_sol||0)+parseInt(fm.bundle_wallets||0)*parseFloat(fm.bundle_sol_per_wallet||0);
  useEffect(()=>{fetch(API+"/launched-tokens").then(r=>r.json()).then(d=>setLaunched(d.tokens||[])).catch(()=>{});},[]);
  return <div className="in"><div style={{display:"grid",gridTemplateColumns:"1.2fr .8fr",gap:20}}>
    <Card style={{padding:"22px 24px"}}>
      <div style={{fontSize:14,fontWeight:600,marginBottom:4}}>Create Token</div>
      <div style={{fontSize:11,color:B.muted,marginBottom:16}}>Launch on PumpFun with Jito bundle for atomic execution</div>
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,marginBottom:12}}><Inp label="Token Name" value={fm.name} onChange={v=>u("name",v)} ph="PumpDesk Alpha"/><Inp label="Symbol" value={fm.symbol} onChange={v=>u("symbol",v)} ph="PDESK"/></div>
      <Inp label="Description" value={fm.description} onChange={v=>u("description",v)} ph="AI-powered alpha generation..." mb={12}/>
      <Inp label="Image URL" value={fm.image_url} onChange={v=>u("image_url",v)} ph="https://..." mb={12}/>
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:12,marginBottom:16}}>
        <Inp label="Twitter" value={fm.twitter} onChange={v=>u("twitter",v)} ph="@handle"/>
        <Inp label="Telegram" value={fm.telegram} onChange={v=>u("telegram",v)} ph="t.me/group"/>
        <Inp label="Website" value={fm.website} onChange={v=>u("website",v)} ph="https://"/>
      </div>
      <div style={{borderTop:`1px solid ${B.border}`,paddingTop:14}}><div style={{fontSize:10,color:DARK.amber,marginBottom:10,textTransform:"uppercase",letterSpacing:"0.08em",fontWeight:700}}>Jito Bundle Config</div>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:12,marginBottom:12}}><Inp label="Dev Buy (SOL)" value={fm.dev_buy_sol} onChange={v=>u("dev_buy_sol",v)} type="number"/><Inp label="Bundle Wallets" value={fm.bundle_wallets} onChange={v=>u("bundle_wallets",v)} type="number"/><Inp label="SOL/Wallet" value={fm.bundle_sol_per_wallet} onChange={v=>u("bundle_sol_per_wallet",v)} type="number"/></div>
        <Toggle on={fm.enable_volume_bot} onChange={v=>u("enable_volume_bot",v)} label="Auto-start Volume Bot after launch"/>
      </div>
      <div style={{marginTop:18,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
        <div><div style={{fontSize:10,color:B.muted,textTransform:"uppercase",marginBottom:2}}>Total Cost</div><div className="num" style={{fontSize:22,fontWeight:700,color:DARK.amber}}>{cost.toFixed(3)} SOL</div></div>
        <button onClick={()=>onLaunch(fm)} disabled={!fm.name||!fm.symbol} style={{padding:"10px 24px",background:DARK.amber,border:"none",borderRadius:8,color:"#0f1219",fontWeight:700,fontSize:12,cursor:fm.name&&fm.symbol?"pointer":"not-allowed",opacity:fm.name&&fm.symbol?1:.45}}>Launch Token →</button>
      </div>
    </Card>
    <div>
      <Card style={{padding:"18px 20px",marginBottom:16}}>
        <div style={{fontSize:13,fontWeight:600,marginBottom:8}}>Launch Status</div>
        {launchStatus?<div><div style={{display:"flex",gap:8,alignItems:"center",marginBottom:8}}><StatusBadge status={launchStatus.status}/><span style={{fontWeight:600}}>{launchStatus.symbol}</span></div>{launchStatus.mint&&<div style={{fontSize:11,color:B.muted}}>Mint: <span className="num" style={{color:B.teal}}>{launchStatus.mint}</span></div>}</div>:<div style={{color:B.muted,fontSize:12,fontStyle:"italic"}}>Ready to launch</div>}
      </Card>
      <Card style={{padding:"18px 20px",marginBottom:16}}>
        <div style={{fontSize:13,fontWeight:600,marginBottom:8}}>Launched Tokens ({launched.length})</div>
        {launched.length?<div style={{display:"flex",flexDirection:"column",gap:6}}>{launched.slice(0,8).map((t,i)=><div key={i} style={{display:"flex",justifyContent:"space-between",alignItems:"center",padding:"6px 0",borderBottom:`1px solid ${B.border}`}}>
          <div><span style={{fontWeight:600,color:DARK.amber}}>{t.symbol||"?"}</span><span style={{fontSize:10,color:B.muted,marginLeft:6}}>{f.addr(t.mint,5)}</span></div>
          <StatusBadge status={t.status||"launched"}/>
        </div>)}</div>:<div style={{color:B.muted,fontSize:11}}>No tokens launched yet</div>}
      </Card>
      <Card style={{padding:"18px 20px"}}><div style={{fontSize:13,fontWeight:600,marginBottom:8}}>Revenue Model</div><div style={{fontSize:11,color:B.muted,lineHeight:1.8}}><div>Pre-grad: sell bundled positions on rising curve</div><div>Post-grad: creator fees <span className="num" style={{color:DARK.amber}}>0.3–0.95%</span></div><div>100 SOL/day vol = <span className="num" style={{color:B.green}}>0.3–0.95 SOL/day</span> passive</div></div></Card>
    </div>
  </div></div>;
}

// ═══════════════════════════════════════════════════════════════════════════
//  PAGE: INTELLIGENCE
// ═══════════════════════════════════════════════════════════════════════════
function IntelPage({assessment,status}){
  const {B}=useTheme();
  const models=[
    {id:"claude",name:"Claude Sonnet 4",provider:"Anthropic",color:"#f0a030",status:"live",desc:"Slow path strategic assessment every 5min"},
    {id:"fast",name:"Fast Path Engine",provider:"Custom Rules",color:"#34d399",status:"live",desc:"<100ms rule-based signal filtering"},
    {id:"oracle",name:"Graduation Oracle",provider:"Heuristic",color:"#2ec4b6",status:"live",desc:"Token graduation probability scoring"},
    {id:"judge",name:"Creator Judge",provider:"On-chain",color:"#fbbf24",status:"live",desc:"Creator wallet history analysis"},
  ];
  return <div className="in">
    <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:24}}>
      <div><div className="head" style={{fontSize:20,fontWeight:700,background:"linear-gradient(135deg,#f0a030,#2ec4b6)",WebkitBackgroundClip:"text",WebkitTextFillColor:"transparent"}}>Two-Tier Decision Engine</div><div style={{fontSize:12,color:B.muted,marginTop:4}}>Fast path rules + slow path Claude AI · orchestrator is the only decision maker</div></div>
      <div style={{textAlign:"right"}}><div style={{fontSize:10,color:B.muted}}>Creator scores cached</div><div className="num" style={{fontSize:16,fontWeight:700,color:B.teal}}>{status?.creator_scores_cached||0}</div></div>
    </div>
    <Card style={{padding:"20px 24px",marginBottom:20}}><CardHeader title="Engine Registry"/><div style={{display:"flex",flexDirection:"column",gap:10}}>{models.map(m=><div key={m.id} style={{display:"grid",gridTemplateColumns:"2fr 1fr 2fr",gap:12,alignItems:"center",padding:"14px 16px",background:B.surf2,borderRadius:10,border:`1px solid ${m.color}25`}}>
      <div style={{display:"flex",alignItems:"center",gap:10}}><div style={{width:32,height:32,borderRadius:8,background:`${m.color}15`,border:`1px solid ${m.color}30`,display:"flex",alignItems:"center",justifyContent:"center",fontSize:12,fontWeight:700,color:m.color}}>{m.id[0].toUpperCase()}</div><div><div style={{fontSize:12,fontWeight:600}}>{m.name}</div><div style={{fontSize:10,color:B.dim}}>{m.provider}</div></div></div>
      <div style={{display:"flex",alignItems:"center",gap:6}}><span style={{width:7,height:7,borderRadius:"50%",background:m.color,boxShadow:`0 0 6px ${m.color}`}}/><span style={{fontSize:11,fontWeight:600,color:m.color}}>{m.status}</span></div>
      <div style={{fontSize:11,color:B.muted}}>{m.desc}</div>
    </div>)}</div></Card>
    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:12,marginBottom:20}}>
      <Card style={{padding:14}}><div style={{fontSize:10,color:B.muted,marginBottom:3}}>BLACKLISTED CREATORS</div><div className="num" style={{fontSize:18,fontWeight:700,color:B.red}}>{status?.blacklisted_creators||0}</div></Card>
      <Card style={{padding:14}}><div style={{fontSize:10,color:B.muted,marginBottom:3}}>HYPE SCORES CACHED</div><div className="num" style={{fontSize:18,fontWeight:700,color:B.amber}}>{status?.hype_scores_cached||0}</div></Card>
      <Card style={{padding:14}}><div style={{fontSize:10,color:B.muted,marginBottom:3}}>HOT TOKENS</div><div className="num" style={{fontSize:18,fontWeight:700,color:B.teal}}>{status?.hot_tokens?.length||0}</div></Card>
    </div>
    <Card style={{padding:"20px 24px"}}><CardHeader title="Claude AI Assessment" right={assessment?.timestamp&&<span style={{fontSize:10,color:B.muted}}>{f.time(assessment.timestamp)}</span>}/>{assessment?<pre style={{color:B.text,fontSize:12,lineHeight:1.7,whiteSpace:"pre-wrap",fontFamily:"'JetBrains Mono',monospace",background:B.bg,padding:14,borderRadius:8,border:`1px solid ${B.border}`,maxHeight:300,overflowY:"auto",margin:"0 20px 20px"}}>{typeof assessment==="string"?assessment:JSON.stringify(assessment,null,2)}</pre>:<div style={{padding:20,color:B.muted,fontSize:12,fontStyle:"italic"}}>First cycle runs ~60s after startup...</div>}</Card>
  </div>;
}

// ═══════════════════════════════════════════════════════════════════════════
//  PAGE: CRM — persistent wallets + pipeline
// ═══════════════════════════════════════════════════════════════════════════
function CRMPage(){
  const {B}=useTheme();
  const [sub,setSub]=useState("wallets");
  const [wallets,setWallets]=useState(()=>{try{return JSON.parse(localStorage.getItem("pd_wallets"))||[];}catch{return[];}});
  const [newAddr,setNewAddr]=useState("");
  const [newLabel,setNewLabel]=useState("");
  useEffect(()=>{localStorage.setItem("pd_wallets",JSON.stringify(wallets));},[wallets]);
  const addWallet=()=>{if(!newAddr.trim())return;setWallets(p=>[...p,{address:newAddr,label:newLabel||"Unnamed",pnl:0,trades:0,winRate:0,confidence:"NEW",color:"#60a5fa",addedAt:new Date().toISOString()}]);setNewAddr("");setNewLabel("");};
  const removeWallet=(i)=>setWallets(p=>p.filter((_,j)=>j!==i));
  const [pipeline,setPipeline]=useState(()=>{try{return JSON.parse(localStorage.getItem("pd_pipeline"))||{scouting:[],evaluating:[],active:[],harvesting:[]};}catch{return{scouting:[],evaluating:[],active:[],harvesting:[]};}});
  useEffect(()=>{localStorage.setItem("pd_pipeline",JSON.stringify(pipeline));},[pipeline]);
  const [pipeInput,setPipeInput]=useState("");
  const [pipeStage,setPipeStage]=useState("scouting");
  const addPipe=()=>{if(!pipeInput.trim())return;setPipeline(p=>({...p,[pipeStage]:[...p[pipeStage],{name:pipeInput,addedAt:new Date().toISOString()}]}));setPipeInput("");};
  const removePipe=(stage,i)=>setPipeline(p=>({...p,[stage]:p[stage].filter((_,j)=>j!==i)}));
  const stages=[{key:"scouting",label:"Scouting",color:B.muted},{key:"evaluating",label:"Evaluating",color:DARK.amber},{key:"active",label:"Active",color:DARK.green},{key:"harvesting",label:"Harvesting",color:DARK.teal}];

  return <div className="in">
    <div style={{display:"flex",gap:2,marginBottom:20}}>{["wallets","pipeline"].map(s=><button key={s} onClick={()=>setSub(s)} style={{padding:"8px 18px",background:sub===s?DARK.amberSoft:"transparent",color:sub===s?DARK.amber:B.muted,border:`1px solid ${sub===s?DARK.amberBorder:"transparent"}`,borderRadius:8,fontSize:12,fontWeight:600,cursor:"pointer",textTransform:"capitalize"}}>{s==="wallets"?"Tracked Wallets":"Deal Pipeline"}</button>)}</div>
    {sub==="wallets"&&<div>
      <Card style={{padding:"14px 20px",marginBottom:16}}>
        <div style={{display:"flex",gap:10,alignItems:"flex-end"}}><Inp label="Wallet Address" value={newAddr} onChange={setNewAddr} ph="Paste Solana address…"/><Inp label="Label" value={newLabel} onChange={setNewLabel} ph="Name" w="160px"/><button onClick={addWallet} disabled={!newAddr.trim()} style={{padding:"9px 18px",background:DARK.amber,border:"none",borderRadius:8,color:"#0f1219",fontWeight:700,fontSize:11,whiteSpace:"nowrap",opacity:newAddr.trim()?1:.4}}>+ Add</button></div>
      </Card>
      {wallets.length?<div style={{display:"flex",flexDirection:"column",gap:10}}>{wallets.map((w,i)=><Card key={i} style={{padding:"14px 20px",borderLeft:`3px solid ${w.color||B.teal}`}}>
        <div style={{display:"grid",gridTemplateColumns:"2fr 1fr 1fr auto",gap:12,alignItems:"center"}}>
          <div><div style={{fontSize:12,fontWeight:600}}>{w.label}</div><div className="num" style={{fontSize:10,color:B.dim}}>{w.address?.length>16?f.addr(w.address,8):w.address}</div></div>
          <Badge color={w.confidence==="HIGH"?B.green:w.confidence==="OWN"?DARK.amber:B.teal} dot>{w.confidence||"NEW"}</Badge>
          <div style={{fontSize:10,color:B.muted}}>Added {f.age(w.addedAt)}</div>
          <button onClick={()=>removeWallet(i)} style={{background:"none",border:"none",color:B.muted,fontSize:14,cursor:"pointer"}}>✕</button>
        </div>
      </Card>)}</div>:<div style={{color:B.muted,fontSize:12,padding:20,textAlign:"center"}}>Add wallets to track — the Wallet Copier bot will mirror their trades</div>}
    </div>}
    {sub==="pipeline"&&<div>
      <Card style={{padding:"14px 20px",marginBottom:16}}>
        <div style={{display:"flex",gap:10,alignItems:"flex-end"}}>
          <div><div style={{fontSize:10,color:B.muted,marginBottom:4,textTransform:"uppercase",fontWeight:600}}>Stage</div><select value={pipeStage} onChange={e=>setPipeStage(e.target.value)} style={{padding:"9px 12px",background:B.surf2,border:`1px solid ${B.border}`,borderRadius:8,color:B.text,fontSize:12}}>{stages.map(s=><option key={s.key} value={s.key}>{s.label}</option>)}</select></div>
          <div style={{flex:1}}><Inp label="Name" value={pipeInput} onChange={setPipeInput} ph="Token, wallet, or opportunity..."/></div>
          <button onClick={addPipe} disabled={!pipeInput.trim()} style={{padding:"9px 18px",background:DARK.amber,border:"none",borderRadius:8,color:"#0f1219",fontWeight:700,fontSize:11,opacity:pipeInput.trim()?1:.4}}>+ Add</button>
        </div>
      </Card>
      <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:12}}>
        {stages.map(col=><div key={col.key}>
          <div style={{fontSize:11,fontWeight:700,color:col.color,textTransform:"uppercase",letterSpacing:"0.08em",marginBottom:12,paddingBottom:8,borderBottom:`2px solid ${col.color}33`}}>{col.label} ({(pipeline[col.key]||[]).length})</div>
          {(pipeline[col.key]||[]).map((item,i)=><Card key={i} style={{padding:12,marginBottom:8,borderLeft:`3px solid ${col.color}44`}}>
            <div style={{display:"flex",justifyContent:"space-between",alignItems:"center"}}><div style={{fontSize:12,fontWeight:600}}>{item.name}</div><button onClick={()=>removePipe(col.key,i)} style={{background:"none",border:"none",color:B.muted,fontSize:12,cursor:"pointer"}}>✕</button></div>
            <div style={{fontSize:10,color:B.dim,marginTop:2}}>{f.age(item.addedAt)}</div>
          </Card>)}
        </div>)}
      </div>
    </div>}
  </div>;
}

// ═══════════════════════════════════════════════════════════════════════════
//  PAGE: SETTINGS — fully wired, config saves, blacklist management
// ═══════════════════════════════════════════════════════════════════════════
function SettingsPage({bots,riskSettings,setRiskSettings,status}){
  const {B}=useTheme();
  const [blInput,setBlInput]=useState("");
  const [blType,setBlType]=useState("creator");
  const [blacklist,setBlacklist]=useState([]);
  const [toast,setToast]=useState(null);
  const [saving,setSaving]=useState(false);
  const addBl=()=>{if(!blInput.trim())return;const endpoint=blType==="creator"?"/blacklist/creator":"/blacklist/token";const body=blType==="creator"?{address:blInput}:{mint:blInput};fetch(API+endpoint,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}).then(r=>r.json()).then(d=>{if(d.ok){setBlacklist(p=>[...p,{type:blType,address:blInput}]);setToast("Blacklisted via API");}else setToast("Failed: "+d.error);}).catch(()=>setToast("API unreachable"));setBlInput("");};
  const removeBl=(i)=>setBlacklist(p=>p.filter((_,j)=>j!==i));
  const updateRisk=(k,v)=>setRiskSettings(p=>({...p,[k]:v}));
  const saveConfig=()=>{setSaving(true);fetch(API+"/config",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(riskSettings)}).then(r=>r.json()).then(d=>{setToast(d.ok?"Config saved to VPS":"Save failed: "+(d.error||"unknown"));setSaving(false);}).catch(()=>{setToast("API unreachable — config not saved");setSaving(false);});};

  return <div className="in" style={{maxWidth:1000}}>
    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:20,marginBottom:20}}>
      <Card style={{padding:"22px 24px"}}>
        <div style={{fontSize:14,fontWeight:600,marginBottom:16}}>Risk Controls</div>
        <div style={{display:"flex",flexDirection:"column",gap:12}}>
          <Inp label="Max Position Size (SOL)" value={String(riskSettings.maxPos)} onChange={v=>updateRisk("maxPos",v)} type="number"/>
          <Inp label="Max Concurrent Positions" value={String(riskSettings.maxConcurrent)} onChange={v=>updateRisk("maxConcurrent",v)} type="number"/>
          <Inp label="Max Daily Loss (SOL)" value={String(riskSettings.maxDailyLoss)} onChange={v=>updateRisk("maxDailyLoss",v)} type="number"/>
          <Inp label="Emergency Exit Drop %" value={String(riskSettings.emergencyPct)} onChange={v=>updateRisk("emergencyPct",v)} type="number"/>
        </div>
        <div style={{marginTop:16,fontSize:10,color:DARK.amber,fontWeight:700,textTransform:"uppercase",letterSpacing:"0.08em",marginBottom:10}}>Progressive Exit Stages</div>
        {riskSettings.exitStages.map((s,i)=><div key={i} style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,marginBottom:6}}>
          <Inp label={`Stage ${i+1} Trigger (×)`} value={String(s.trigger)} onChange={v=>{const ns=[...riskSettings.exitStages];ns[i]={...ns[i],trigger:v};updateRisk("exitStages",ns);}} type="number"/>
          <Inp label="Sell %" value={String(s.sell)} onChange={v=>{const ns=[...riskSettings.exitStages];ns[i]={...ns[i],sell:v};updateRisk("exitStages",ns);}} type="number"/>
        </div>)}
        <button onClick={saveConfig} disabled={saving} style={{marginTop:12,padding:"8px 20px",background:DARK.amberSoft,border:`1px solid ${DARK.amberBorder}`,borderRadius:8,color:DARK.amber,fontSize:11,fontWeight:600,opacity:saving?.5:1}}>{saving?"Saving...":"Save to VPS →"}</button>
      </Card>
      <div>
        <Card style={{padding:"22px 24px",marginBottom:16}}>
          <div style={{fontSize:14,fontWeight:600,marginBottom:12}}>Bot Status (from API)</div>
          <div style={{display:"flex",flexDirection:"column",gap:10}}>
            {bots.map(b=><div key={b.id||b.key} style={{display:"flex",justifyContent:"space-between",alignItems:"center",padding:"6px 0",borderBottom:`1px solid ${B.border}`}}>
              <span style={{fontSize:12}}><span className="num" style={{color:B.dim,fontSize:10,marginRight:6}}>#{b.id}</span>{b.name}</span>
              <StatusBadge status={b.status}/>
            </div>)}
          </div>
        </Card>
        <Card style={{padding:"22px 24px"}}>
          <div style={{fontSize:14,fontWeight:600,marginBottom:8}}>Architecture</div>
          <div style={{fontSize:11,color:B.muted,lineHeight:2,fontFamily:"'JetBrains Mono',monospace",background:B.bg,padding:14,borderRadius:8,border:`1px solid ${B.border}`}}>
            <div><span style={{color:DARK.amber}}>Services:</span> 20 Docker via Redis pub/sub (24 ch)</div>
            <div><span style={{color:DARK.amber}}>Decision:</span> Fast path &lt;100ms + slow path Claude AI</div>
            <div><span style={{color:DARK.amber}}>Execution:</span> Jito bundles for atomic multi-tx</div>
            <div><span style={{color:DARK.amber}}>Exit:</span> Progressive staged sells + -{riskSettings.emergencyPct}% breaker</div>
            <div style={{marginTop:6}}><span style={{color:B.teal}}>PumpFun:</span> 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P</div>
            <div><span style={{color:B.teal}}>Curve:</span> 800M tokens → $69K mcap → PumpSwap</div>
          </div>
        </Card>
      </div>
    </div>
    <Card style={{padding:"22px 24px",marginBottom:20}}>
      <div style={{fontSize:14,fontWeight:600,marginBottom:12}}>Blacklist Management</div>
      <div style={{display:"flex",gap:10,alignItems:"flex-end",marginBottom:12}}>
        <div><div style={{fontSize:10,color:B.muted,marginBottom:4,textTransform:"uppercase",fontWeight:600}}>Type</div><select value={blType} onChange={e=>setBlType(e.target.value)} style={{padding:"9px 12px",background:B.surf2,border:`1px solid ${B.border}`,borderRadius:8,color:B.text,fontSize:12}}><option value="creator">Creator</option><option value="token">Token</option></select></div>
        <div style={{flex:1}}><Inp label="Address / Mint" value={blInput} onChange={setBlInput} ph="Paste address…"/></div>
        <button onClick={addBl} disabled={!blInput.trim()} style={{padding:"9px 16px",background:DARK.redSoft,border:`1px solid ${DARK.red}33`,borderRadius:8,color:DARK.red,fontSize:11,fontWeight:600,opacity:blInput.trim()?1:.4}}>Block</button>
      </div>
      <div style={{fontSize:11,color:B.muted,marginBottom:8}}>{status?.blacklisted_creators||0} creators blacklisted on orchestrator</div>
      {blacklist.length>0&&<div style={{display:"flex",flexDirection:"column",gap:6}}>{blacklist.map((b,i)=><div key={i} style={{display:"flex",justifyContent:"space-between",alignItems:"center",padding:"6px 10px",background:B.surf2,borderRadius:6,fontSize:11}}>
        <span><Badge color={DARK.red}>{b.type}</Badge> <span className="num" style={{marginLeft:6}}>{b.address}</span></span>
        <button onClick={()=>removeBl(i)} style={{background:"none",border:"none",color:B.muted,fontSize:12,cursor:"pointer"}}>✕</button>
      </div>)}</div>}
    </Card>
    {toast&&<Toast msg={toast} type={toast.includes("Failed")||toast.includes("unreachable")?"error":"success"} onDone={()=>setToast(null)}/>}
  </div>;
}


// ═══════════════════════════════════════════════════════════════════════════
//  MAIN APP — fully wired state management
// ═══════════════════════════════════════════════════════════════════════════
const NAV=[{id:"overview",label:"Overview",icon:"▦"},{id:"bots",label:"Bots",icon:"⚡"},{id:"launcher",label:"Launcher",icon:"△"},{id:"intel",label:"Intelligence",icon:"✦"},{id:"crm",label:"CRM",icon:"⊕"},{id:"settings",label:"Settings",icon:"⚙"}];

export default function PumpDesk(){
  const [page,setPage]=useState("overview");
  const [mode,setMode]=useState("paper");
  const [status,setStatus]=useState(null);
  const [positions,setPositions]=useState([]);
  const [allTrades,setAllTrades]=useState([]);
  const [hotTokens,setHotTokens]=useState([]);
  const [assessment,setAssessment]=useState(null);
  const [signals,setSignals]=useState([]);
  const [launchStatus,setLaunchStatus]=useState(null);
  const [wsOk,setWsOk]=useState(false);
  const [selectedBot,setSelectedBot]=useState(null);
  const [bots,setBots]=useState([]);
  const [botsLoading,setBotsLoading]=useState(true);
  const [period,setPeriod]=useState("ALL");
  const [apiOk,setApiOk]=useState(null);
  const [riskSettings,setRiskSettings]=useState({maxPos:"2.0",maxConcurrent:"5",maxDailyLoss:"5.0",emergencyPct:"30",exitStages:[{trigger:"2",sell:"50"},{trigger:"5",sell:"25"},{trigger:"10",sell:"15"}]});
  const wsRef=useRef(null);
  const B=DARK,M=MODE[mode];

  const fetchAll=useCallback(async()=>{
    try{
      const [s,p,t,h,a,bo]=await Promise.allSettled([
        fetch(API+"/status").then(r=>r.json()),
        fetch(API+"/positions").then(r=>r.json()),
        fetch(API+"/trades?limit=200").then(r=>r.json()),
        fetch(API+"/hot-tokens").then(r=>r.json()),
        fetch(API+"/assessment").then(r=>r.json()),
        fetch(API+"/bots").then(r=>r.json()),
      ]);
      setApiOk(true);
      if(s.status==="fulfilled")setStatus(s.value);
      if(p.status==="fulfilled")setPositions(p.value?.positions||[]);
      if(t.status==="fulfilled")setAllTrades(t.value?.trades||[]);
      if(h.status==="fulfilled")setHotTokens(h.value?.tokens||[]);
      if(a.status==="fulfilled")setAssessment(a.value);
      if(bo.status==="fulfilled"&&bo.value?.bots){setBots(bo.value.bots);setBotsLoading(false);}
    }catch{setApiOk(false);}
  },[]);

  useEffect(()=>{let ws,rt;const connect=()=>{try{ws=new WebSocket(WS_URL);wsRef.current=ws;ws.onopen=()=>setWsOk(true);ws.onclose=()=>{setWsOk(false);rt=setTimeout(connect,3000);};ws.onerror=()=>ws.close();ws.onmessage=e=>{try{const msg=JSON.parse(e.data);setSignals(p=>[...p.slice(-300),msg]);if(msg.type==="assessment")setAssessment(msg.data);if(msg.type==="launch_status")setLaunchStatus(msg);if(msg.type==="decision")fetchAll();}catch{}};}catch{}};connect();return()=>{ws?.close();clearTimeout(rt);};},[fetchAll]);
  useEffect(()=>{fetchAll();const iv=setInterval(fetchAll,8000);return()=>clearInterval(iv);},[fetchAll]);

  const handleLaunch=(fm)=>{if(wsRef.current?.readyState===1)wsRef.current.send(JSON.stringify({type:"launch",data:fm}));setLaunchStatus({status:"preparing",symbol:fm.symbol});};
  const activeBots=bots.filter(b=>b.enabled).length;

  // Filter trades by period
  const filteredTrades=allTrades.filter(t=>{
    if(period==="ALL")return true;
    const d=new Date(t.created_at);const now=Date.now();
    if(period==="1D")return now-d<864e5;
    if(period==="7D")return now-d<6048e5;
    if(period==="1M")return now-d<2592e6;
    return true;
  });

  return <ThemeCtx.Provider value={{B,M}}>
    <div style={{display:"flex",minHeight:"100vh",background:B.bg,color:B.text,fontFamily:"'Outfit','Plus Jakarta Sans',sans-serif"}}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
        *{box-sizing:border-box;margin:0;padding:0}
        ::-webkit-scrollbar{width:4px;height:4px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:${B.dim};border-radius:4px}
        @keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
        @keyframes in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
        @keyframes slidein{from{transform:translateX(100%)}to{transform:translateX(0)}}
        .in{animation:in 0.3s cubic-bezier(.16,1,.3,1) both}
        .bot-row:hover{background:${B.surf2}!important}
        .bot-card{transition:all 0.15s}.bot-card:hover{border-color:${B.borderHover}!important;transform:translateY(-1px)}
        .nav-btn{transition:all 0.15s}.nav-btn:hover{background:${B.surf2}!important}
        .num{font-family:'JetBrains Mono',monospace;font-variant-numeric:tabular-nums;letter-spacing:-0.02em}
        .head{font-family:'Outfit',sans-serif;letter-spacing:-0.02em}
        input:focus{outline:none;border-color:${M.accent}55!important}
        select:focus{outline:none}
        button{cursor:pointer;font-family:inherit}
        ::selection{background:${M.accent}33}
      `}</style>

      {/* Sidebar */}
      <aside style={{width:210,flexShrink:0,background:B.surf,borderRight:`1px solid ${B.border}`,display:"flex",flexDirection:"column",position:"sticky",top:0,height:"100vh"}}>
        <div style={{padding:"18px 14px 14px",borderBottom:`1px solid ${B.border}`}}>
          <div style={{display:"flex",alignItems:"center",gap:10}}>
            <div style={{width:34,height:34,borderRadius:10,background:`linear-gradient(135deg,${DARK.amber},${DARK.teal})`,display:"flex",alignItems:"center",justifyContent:"center",flexShrink:0,boxShadow:`0 4px 14px ${M.accent}22`}}>
              <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth={2.5} strokeLinecap="round"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
            </div>
            <div><div className="head" style={{fontWeight:800,fontSize:15}}>PUMP<span style={{fontWeight:300}}>DESK</span></div><div style={{fontSize:10,color:B.muted,marginTop:2,display:"flex",alignItems:"center",gap:5}}><span style={{width:5,height:5,borderRadius:"50%",background:wsOk?B.green:apiOk===false?B.red:B.muted,animation:wsOk?"pulse 2s infinite":"none"}}/><span className="num">{wsOk?"live":apiOk===false?"offline":"connecting"}</span></div></div>
          </div>
        </div>
        <nav style={{padding:"8px 6px",flex:1,overflowY:"auto"}}>
          {NAV.map(item=>{const active=page===item.id;return<button key={item.id} className="nav-btn" onClick={()=>setPage(item.id)} style={{display:"flex",alignItems:"center",gap:9,width:"100%",padding:"9px 10px",borderRadius:8,border:"none",background:active?M.accentSoft:"transparent",color:active?M.accentText:B.sub,fontSize:13,fontWeight:active?600:400,textAlign:"left",marginBottom:1}}>
            <span style={{fontSize:13,width:18,textAlign:"center",flexShrink:0,filter:active?"none":"opacity(0.55)"}}>{item.icon}</span>{item.label}
            {item.id==="bots"&&activeBots>0&&<span style={{marginLeft:"auto",fontSize:9,background:B.greenSoft,color:B.green,borderRadius:8,padding:"2px 6px",fontWeight:700}}>{activeBots}</span>}
            {item.id==="intel"&&<span style={{marginLeft:"auto",fontSize:9,background:M.accentSoft,color:M.accentText,borderRadius:8,padding:"2px 6px",fontWeight:700}}>AI</span>}
          </button>;})}
        </nav>
        <div style={{padding:"10px 14px",borderTop:`1px solid ${B.border}`,display:"flex",flexDirection:"column",gap:4}}>
          <div style={{fontSize:10,color:B.dim,fontFamily:"'JetBrains Mono',monospace"}}>{new Date().toUTCString().slice(17,25)} UTC</div>
          {apiOk===false&&<div style={{fontSize:9,color:B.red,fontWeight:600}}>API OFFLINE</div>}
        </div>
      </aside>

      {/* Main */}
      <div style={{flex:1,display:"flex",flexDirection:"column",minWidth:0}}>
        <header style={{height:54,borderBottom:`1px solid ${B.border}`,display:"flex",alignItems:"center",justifyContent:"space-between",padding:"0 22px",background:B.surf,position:"sticky",top:0,zIndex:50,flexShrink:0}}>
          <div><div className="head" style={{fontSize:14,fontWeight:600}}>{NAV.find(n=>n.id===page)?.label}</div><div style={{fontSize:10,color:B.muted,marginTop:1}}>{mode==="paper"?"Paper mode · simulated trades":"Live trading · real SOL deployed"}</div></div>
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
          {page==="overview"&&<OverviewPage bots={bots} status={status} positions={positions} hotTokens={hotTokens} signals={signals} allTrades={filteredTrades} period={period} setPeriod={setPeriod}/>}
          {page==="bots"&&<BotsPage bots={bots} onSelectBot={setSelectedBot} loading={botsLoading}/>}
          {page==="launcher"&&<LauncherPage launchStatus={launchStatus} onLaunch={handleLaunch}/>}
          {page==="intel"&&<IntelPage assessment={assessment} status={status}/>}
          {page==="crm"&&<CRMPage/>}
          {page==="settings"&&<SettingsPage bots={bots} riskSettings={riskSettings} setRiskSettings={setRiskSettings} status={status}/>}
        </main>
      </div>

      {/* Bot Drawer overlay */}
      {selectedBot&&<><div onClick={()=>setSelectedBot(null)} style={{position:"fixed",inset:0,background:"rgba(0,0,0,0.5)",zIndex:99}}/><BotDrawer bot={selectedBot} onClose={()=>setSelectedBot(null)} signals={signals} allTrades={allTrades}/></>}
    </div>
  </ThemeCtx.Provider>;
}

