"""
=============================================================
NIFTY 50 — REAL-TIME SIGNAL API  (Event-Driven Build)
=============================================================
Signal firing logic:
  - Scans every 3 minutes during market hours (continuous)
  - Sends email ONLY when a strategy crosses HIGH or VERY HIGH
  - Per-strategy cooldown (15 min) prevents duplicate alerts
  - Confidence MUST rise or direction MUST change to re-fire
  - No fixed time slots — pure event-driven alerting

Endpoints
  GET  /              → Live dashboard
  GET  /health        → Health check (UptimeRobot)
  GET  /scan          → Force immediate scan
  GET  /signals       → Last scan JSON
  GET  /trigger-email → Force email now
  GET  /status        → Engine stats
  GET  /docs          → Swagger UI
=============================================================
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import asyncio, logging, threading, time, json
from datetime import datetime, timedelta
from collections import defaultdict

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse

from config import CONFIG
from utils.data import DataFetcher
from utils.email_sender import build_email_html, send_email
from strategies.engine import StrategyEngine

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("NiftyAPI")

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────
SCAN_INTERVAL_SEC   = 180          # scan every 3 minutes
COOLDOWN_MIN        = 15           # same strategy+direction won't re-alert within 15 min
HIGH_CONF           = {"HIGH", "VERY_HIGH"}
CONF_RANK           = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "VERY_HIGH": 3}

# ─────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────
app = FastAPI(
    title=CONFIG["api"]["title"],
    version=CONFIG["api"]["version"],
    description="""
## Nifty 50 Ultra-Optimised v4 — Event-Driven Signal Engine

Continuously scans **5 strategies every 3 minutes** during NSE market hours.
Fires an email alert the **instant** any strategy reaches HIGH or VERY HIGH confidence —
no fixed time slots, pure real-time event-driven alerting.

### Signal firing rules
- Confidence must be **HIGH** or **VERY HIGH**
- 15-minute per-strategy cooldown (no duplicate spam)
- Re-fires immediately if **confidence rises** or **direction flips**
- Separate alert if **multiple strategies agree** (consensus signal)
    """,
)
app.add_middleware(CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────
STATE = {
    "last_scan":          None,
    "last_signals":       [],
    "last_spot":          0.0,
    "last_vix":           0.0,
    "scan_count":         0,
    "email_sent":         0,
    "alert_count":        0,
    "errors":             0,
    "started_at":         datetime.now().isoformat(),
    "uptime_pings":       0,

    # Per-strategy last-alert tracking
    # key = strategy_name → {direction, confidence, fired_at, count}
    "strategy_state":     {},

    # Alert history (last 50)
    "alert_history":      [],

    # Consensus tracking (multiple strategies same direction)
    "last_consensus":     None,
}


# ─────────────────────────────────────────────
# SIGNAL FIRING DECISION ENGINE
# ─────────────────────────────────────────────
def should_fire(sig: dict) -> tuple[bool, str]:
    """
    Returns (should_fire: bool, reason: str).

    Rules:
    1. Must be HIGH or VERY_HIGH confidence
    2. Must be a directional trade (not NO_TRADE or Iron Condor only)
    3. Cooldown: same strategy+direction cannot re-fire within COOLDOWN_MIN
    4. Exception: cooldown bypassed if confidence IMPROVED (MEDIUM→HIGH, HIGH→VERY_HIGH)
    5. Exception: cooldown bypassed if DIRECTION FLIPPED (BUY→SELL or vice versa)
    """
    if not sig.get("is_tradeable"):
        return False, "Not tradeable"

    conf      = sig.get("confidence", "LOW")
    direction = sig.get("direction", "NO_TRADE")
    strategy  = sig.get("strategy", "")

    if conf not in HIGH_CONF:
        return False, f"Confidence {conf} below threshold"

    prev = STATE["strategy_state"].get(strategy)

    if prev is None:
        return True, "First signal from this strategy"

    # Direction flipped → always fire
    prev_dir = prev.get("direction", "")
    if prev_dir and prev_dir != direction and direction != "NO_TRADE":
        return True, f"Direction flipped {prev_dir} → {direction}"

    # Confidence improved → always fire
    prev_rank = CONF_RANK.get(prev.get("confidence", "LOW"), 0)
    curr_rank = CONF_RANK.get(conf, 0)
    if curr_rank > prev_rank:
        return True, f"Confidence upgraded {prev.get('confidence')} → {conf}"

    # Within cooldown window?
    fired_at = prev.get("fired_at")
    if fired_at:
        elapsed = (datetime.now() - fired_at).total_seconds() / 60
        if elapsed < COOLDOWN_MIN:
            remaining = round(COOLDOWN_MIN - elapsed, 1)
            return False, f"Cooldown active ({remaining} min remaining)"

    return True, "Cooldown expired — re-firing signal"


def record_fired(sig: dict):
    STATE["strategy_state"][sig["strategy"]] = {
        "direction":  sig["direction"],
        "confidence": sig["confidence"],
        "entry":      sig["entry"],
        "fired_at":   datetime.now(),
        "count":      STATE["strategy_state"].get(sig["strategy"], {}).get("count", 0) + 1,
    }


def check_consensus(signals: list) -> dict | None:
    """
    If 3+ tradeable strategies agree on direction → fire a consensus alert.
    Cooldown: 30 min between consensus alerts.
    """
    tradeable = [s for s in signals if s.get("is_tradeable") and
                 s.get("confidence") in HIGH_CONF and
                 "NO_TRADE" not in s.get("direction", "")]

    buys  = [s for s in tradeable if "BUY"  in s["direction"]]
    sells = [s for s in tradeable if "SELL" in s["direction"] and "Condor" not in s["direction"]]

    consensus_dir   = None
    consensus_sigs  = []
    if len(buys)  >= 3: consensus_dir, consensus_sigs = "BUY",  buys
    elif len(sells) >= 3: consensus_dir, consensus_sigs = "SELL", sells

    if not consensus_dir:
        return None

    # Cooldown check for consensus
    last = STATE.get("last_consensus")
    if last:
        elapsed = (datetime.now() - last).total_seconds() / 60
        if elapsed < 30:
            return None

    STATE["last_consensus"] = datetime.now()
    return {
        "type":      "CONSENSUS",
        "direction": consensus_dir,
        "strategies": [s["strategy"] for s in consensus_sigs],
        "count":     len(consensus_sigs),
        "signals":   consensus_sigs,
    }


# ─────────────────────────────────────────────
# CORE SCAN + FIRE LOGIC
# ─────────────────────────────────────────────
def run_scan(force_email: bool = False) -> dict:
    STATE["scan_count"] += 1
    now = datetime.now()
    log.info(f"🔍 Scan #{STATE['scan_count']} — {now.strftime('%d %b %H:%M:%S IST')}")

    try:
        market  = DataFetcher.all_data()
        spot    = market["spot"]
        vix     = market["vix"]

        if spot == 0:
            log.warning("Spot price = 0, skipping scan")
            STATE["errors"] += 1
            return {"error": "No spot price"}

        STATE["last_spot"] = spot
        STATE["last_vix"]  = vix

        engine  = StrategyEngine(market["data"], spot, vix)
        signals = engine.run_all()
        STATE["last_signals"] = signals
        STATE["last_scan"]    = now.isoformat()

        # ── Per-strategy fire decision ──────────────────────
        fired_signals   = []
        skipped_reasons = []

        for sig in signals:
            fire, reason = should_fire(sig)
            strat = sig["strategy"]
            if fire:
                fired_signals.append(sig)
                record_fired(sig)
                log.info(f"  🚨 FIRE  | {strat} | {sig['direction']} | {sig['confidence']} | {reason}")
            else:
                log.info(f"  ⏸ SKIP  | {strat} | {sig.get('direction','—')} | {sig.get('confidence','—')} | {reason}")
                skipped_reasons.append(f"{strat}: {reason}")

        # ── Consensus check ─────────────────────────────────
        consensus = check_consensus(signals)
        if consensus:
            log.info(f"  🎯 CONSENSUS | {consensus['direction']} | {consensus['count']} strategies agree")

        # ── Send emails ─────────────────────────────────────
        # Individual strategy alerts
        if fired_signals or force_email:
            _send_alert_email(fired_signals or signals, spot, vix,
                              force=force_email, consensus=None)

        # Separate consensus alert
        if consensus:
            _send_consensus_email(consensus, spot, vix)

        tradeable_count = sum(1 for s in signals if s.get("is_tradeable"))
        log.info(f"  ✅ Done | {len(fired_signals)} fired | {tradeable_count} tradeable total | "
                 f"Spot ₹{spot:,.0f} | VIX {vix:.1f}")

        return {
            "timestamp":  now.isoformat(),
            "spot":       spot,
            "vix":        vix,
            "signals":    signals,
            "fired":      len(fired_signals),
            "tradeable":  tradeable_count,
        }

    except Exception as e:
        log.error(f"Scan error: {e}", exc_info=True)
        STATE["errors"] += 1
        return {"error": str(e)}


def _send_alert_email(signals: list, spot: float, vix: float,
                      force: bool = False, consensus=None):
    """Build and send the signal alert email."""
    now   = datetime.now()
    fired = [s for s in signals if s.get("is_tradeable") and s.get("confidence") in HIGH_CONF]

    if not fired and not force:
        return

    n    = len(fired)
    dirs = list({s["direction"] for s in fired})
    dir_str = " + ".join(dirs) if dirs else "Signal"

    subject = (
        f"🚨 Nifty {dir_str} Signal | "
        f"{n} Strategy {'Match' if n==1 else 'Matches'} | "
        f"₹{spot:,.0f} | {now.strftime('%d %b %I:%M %p')}"
    )
    if force:
        subject = f"📧 Manual Report | Nifty ₹{spot:,.0f} | {now.strftime('%d %b %I:%M %p')}"

    html = build_email_html(signals, spot, vix)
    ok   = send_email(html, subject)
    if ok:
        STATE["email_sent"] += 1
        STATE["alert_count"] += 1
        # Store in history
        STATE["alert_history"].append({
            "time":      now.strftime("%d %b %I:%M %p"),
            "subject":   subject,
            "direction": dir_str,
            "count":     n,
        })
        if len(STATE["alert_history"]) > 50:
            STATE["alert_history"] = STATE["alert_history"][-50:]


def _send_consensus_email(consensus: dict, spot: float, vix: float):
    """Send a separate high-priority consensus alert."""
    now     = datetime.now()
    strats  = ", ".join(consensus["strategies"])
    subject = (
        f"🎯 CONSENSUS {consensus['direction']} | "
        f"{consensus['count']} Strategies Agree | "
        f"₹{spot:,.0f} | {now.strftime('%d %b %I:%M %p')}"
    )

    dir_color = "#10b981" if consensus["direction"] == "BUY" else "#ef4444"
    strat_pills = "".join(
        f'<span style="background:#1e293b;color:#94a3b8;font-size:11px;'
        f'padding:3px 10px;border-radius:10px;margin:3px;display:inline-block">'
        f'{s}</span>'
        for s in consensus["strategies"]
    )

    html = f"""<!DOCTYPE html><html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0a0e1a;font-family:system-ui,sans-serif">
<div style="max-width:680px;margin:0 auto;padding:20px">

  <div style="background:linear-gradient(135deg,{dir_color}22,{dir_color}11);
              border:2px solid {dir_color};border-radius:16px;padding:28px;
              text-align:center;margin-bottom:24px">
    <div style="font-size:40px;margin-bottom:10px">{'🚀' if consensus['direction']=='BUY' else '🔻'}</div>
    <div style="font-size:14px;color:#94a3b8;text-transform:uppercase;
                letter-spacing:.08em;margin-bottom:8px">CONSENSUS SIGNAL</div>
    <div style="font-size:42px;font-weight:900;color:{dir_color};
                letter-spacing:.02em">{consensus['direction']}</div>
    <div style="font-size:16px;color:#94a3b8;margin-top:8px">
      {consensus['count']} independent strategies agree right now
    </div>
    <div style="margin-top:16px;font-size:20px;font-weight:700;color:#f8fafc">
      Nifty ₹{spot:,.0f} &nbsp;·&nbsp; VIX {vix:.1f} &nbsp;·&nbsp;
      {now.strftime('%d %b %I:%M %p IST')}
    </div>
  </div>

  <div style="background:#111827;border-radius:12px;padding:18px;margin-bottom:20px;
              border:1px solid #1e293b">
    <div style="font-size:12px;font-weight:600;color:#475569;text-transform:uppercase;
                letter-spacing:.05em;margin-bottom:12px">Agreeing Strategies</div>
    <div>{strat_pills}</div>
  </div>

  <div style="background:#111827;border-radius:12px;padding:18px;margin-bottom:20px;
              border:1px solid {dir_color}44">
    <div style="font-size:13px;color:#94a3b8;line-height:1.8">
      <strong style="color:#f8fafc">Why this matters:</strong>
      When {consensus['count']} strategies independently fire the same direction
      simultaneously, the probability of a sustained move is significantly higher
      than a single-strategy signal. Consider this a <strong style="color:{dir_color}">
      high-conviction entry opportunity</strong>. Check individual strategy signals
      below for entry, targets and stop-loss levels.
    </div>
  </div>

  {build_email_html(consensus['signals'], spot, vix)}

  <div style="background:#1c0a08;border-radius:8px;padding:14px;margin-top:16px;
              border-left:3px solid #ef4444">
    <div style="font-size:11px;color:#64748b;line-height:1.7">
      <strong style="color:#f87171">⚠️ DISCLAIMER:</strong>
      Algorithmically generated signal for educational purposes only.
      NOT SEBI-registered investment advice. Always apply your own judgment.
    </div>
  </div>
</div></body></html>"""

    ok = send_email(html, subject)
    if ok:
        STATE["email_sent"] += 1
        STATE["alert_count"] += 1
        STATE["alert_history"].append({
            "time":      now.strftime("%d %b %I:%M %p"),
            "subject":   subject,
            "direction": f"CONSENSUS {consensus['direction']}",
            "count":     consensus["count"],
        })


# ─────────────────────────────────────────────
# CONTINUOUS SCAN LOOP (replaces fixed schedule)
# ─────────────────────────────────────────────
def is_market_hours() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    o = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    c = now.replace(hour=15, second=0,  microsecond=0, minute=30)
    return o <= now <= c


def continuous_scan_loop():
    """Runs every SCAN_INTERVAL_SEC during market hours. Event-driven firing."""
    log.info(f"⚡ Continuous scanner started — interval: {SCAN_INTERVAL_SEC}s")
    while True:
        if is_market_hours():
            run_scan()
        else:
            now = datetime.now()
            log.debug(f"Market closed ({now.strftime('%a %H:%M')})")
        time.sleep(SCAN_INTERVAL_SEC)


# ─────────────────────────────────────────────
# KEEPALIVE (prevents cloud free-tier sleep)
# ─────────────────────────────────────────────
def keepalive_loop():
    import requests
    port = CONFIG["api"]["port"]
    time.sleep(90)
    while True:
        try:
            requests.get(f"http://localhost:{port}/health", timeout=5)
            STATE["uptime_pings"] += 1
        except:
            pass
        time.sleep(240)  # every 4 minutes


# ─────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    log.info("=" * 58)
    log.info("🚀 NIFTY SIGNAL API — EVENT-DRIVEN BUILD — STARTUP")
    log.info(f"   Capital     : ₹{CONFIG['trading']['capital']:,}")
    log.info(f"   Risk/trade  : {CONFIG['trading']['risk_per_trade']*100:.1f}%")
    log.info(f"   Recipient   : {CONFIG['email']['recipient_email']}")
    log.info(f"   Scan every  : {SCAN_INTERVAL_SEC}s ({SCAN_INTERVAL_SEC//60} min)")
    log.info(f"   Cooldown    : {COOLDOWN_MIN} min per strategy")
    log.info(f"   Fire on     : HIGH / VERY HIGH confidence only")
    log.info(f"   Email ready : {'✅' if CONFIG['email']['sender_email'] else '⚠️  SENDER_EMAIL not set'}")
    log.info("=" * 58)

    threading.Thread(target=continuous_scan_loop, daemon=True).start()
    threading.Thread(target=keepalive_loop,        daemon=True).start()

    # Initial scan after 8 seconds (let server fully start first)
    def first_scan():
        time.sleep(8)
        run_scan()
    threading.Thread(target=first_scan, daemon=True).start()


# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────
def auth(key):
    cfg_key = CONFIG["api"]["api_key"]
    if cfg_key and key != cfg_key:
        raise HTTPException(401, "Invalid API key. Pass X-API-Key header.")


# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────
@app.get("/health", tags=["Health"])
async def health():
    return {
        "status":       "ok",
        "uptime_since": STATE["started_at"],
        "scan_count":   STATE["scan_count"],
        "email_sent":   STATE["email_sent"],
        "alert_count":  STATE["alert_count"],
        "market_open":  is_market_hours(),
        "spot":         STATE["last_spot"],
        "vix":          STATE["last_vix"],
        "timestamp":    datetime.now().isoformat(),
    }


@app.get("/", response_class=HTMLResponse, tags=["Dashboard"])
async def dashboard():
    now     = datetime.now()
    spot    = STATE["last_spot"]
    vix     = STATE["last_vix"]
    mopen   = is_market_hours()
    signals = STATE["last_signals"]
    fired   = [s for s in signals if s.get("is_tradeable") and s.get("confidence") in HIGH_CONF]
    email_ok= bool(CONFIG["email"]["sender_email"])

    uptime_sec = (now - datetime.fromisoformat(STATE["started_at"])).total_seconds()
    h_up = int(uptime_sec // 3600)
    m_up = int((uptime_sec % 3600) // 60)

    next_scan = SCAN_INTERVAL_SEC - int(uptime_sec % SCAN_INTERVAL_SEC)

    # Strategy state rows
    strat_rows = ""
    for sig in signals:
        st   = sig["strategy"]
        prev = STATE["strategy_state"].get(st, {})
        conf = sig.get("confidence","—")
        dirr = sig.get("direction","—")
        fired_at = prev.get("fired_at")
        cooldown_str = "—"
        if fired_at:
            elapsed = (now - fired_at).total_seconds() / 60
            if elapsed < COOLDOWN_MIN:
                remaining = round(COOLDOWN_MIN - elapsed, 1)
                cooldown_str = f"🔒 {remaining}m left"
            else:
                cooldown_str = "✅ Ready"

        dc  = "#10b981" if "BUY" in dirr else "#ef4444" if "SELL" in dirr else "#475569"
        cc  = "#10b981" if conf == "VERY_HIGH" else "#22c55e" if conf == "HIGH" else \
              "#f59e0b" if conf == "MEDIUM" else "#475569"
        fire, reason = should_fire(sig)
        fire_icon = "🚨" if fire else "⏸"

        strat_rows += f"""
        <tr>
          <td style="padding:10px 12px;font-size:12px;color:#94a3b8">{st.split()[0]}<br>
              <span style="font-size:10px;color:#334155">{st}</span></td>
          <td style="padding:10px 12px"><span style="color:{dc};font-weight:700">{dirr}</span></td>
          <td style="padding:10px 12px"><span style="color:{cc};font-weight:600">{conf}</span></td>
          <td style="padding:10px 12px;font-size:11px;color:#475569">{cooldown_str}</td>
          <td style="padding:10px 12px;font-size:11px;color:#475569">{prev.get('count',0)}</td>
          <td style="padding:10px 12px;font-size:13px">{fire_icon}</td>
        </tr>"""

    # Alert history rows
    hist_rows = ""
    for a in reversed(STATE["alert_history"][-10:]):
        dc = "#10b981" if "BUY" in a.get("direction","") else \
             "#ef4444" if "SELL" in a.get("direction","") else "#3b82f6"
        hist_rows += f"""
        <tr>
          <td style="padding:8px 12px;font-size:11px;color:#64748b">{a['time']}</td>
          <td style="padding:8px 12px;color:{dc};font-weight:600;font-size:12px">{a['direction']}</td>
          <td style="padding:8px 12px;font-size:11px;color:#475569">{a['count']} signal(s)</td>
        </tr>"""

    if not hist_rows:
        hist_rows = '<tr><td colspan="3" style="padding:16px;text-align:center;color:#334155;font-size:12px">No alerts fired yet this session</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="refresh" content="30">
  <title>Nifty Signal API — Event-Driven</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{background:#070b14;color:#e2e8f0;font-family:system-ui,sans-serif;padding:0}}
    .w{{max-width:1100px;margin:0 auto;padding:20px 16px}}
    h1{{font-size:21px;font-weight:800;color:#f8fafc}}
    .sub{{font-size:12px;color:#475569;margin-top:3px;margin-bottom:20px}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:10px;margin-bottom:18px}}
    .kpi{{background:#111827;border-radius:12px;padding:13px 15px;border:1px solid #1e293b;position:relative;overflow:hidden}}
    .kpi::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;border-radius:12px 12px 0 0}}
    .g::before{{background:linear-gradient(90deg,#10b981,#34d399)}}
    .b::before{{background:linear-gradient(90deg,#3b82f6,#60a5fa)}}
    .a::before{{background:linear-gradient(90deg,#f59e0b,#fbbf24)}}
    .r::before{{background:linear-gradient(90deg,#ef4444,#f87171)}}
    .p::before{{background:linear-gradient(90deg,#8b5cf6,#a78bfa)}}
    .kpi-l{{font-size:10px;color:#475569;text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px}}
    .kpi-v{{font-size:22px;font-weight:800}}
    .kpi-s{{font-size:11px;color:#475569;margin-top:2px}}
    .card{{background:#111827;border-radius:12px;padding:18px;border:1px solid #1e293b;margin-bottom:14px}}
    .ct{{font-size:11px;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:.05em;margin-bottom:13px}}
    table{{width:100%;border-collapse:collapse}}
    th{{background:#0d1526;padding:8px 12px;text-align:left;font-size:10px;color:#475569;text-transform:uppercase;letter-spacing:.04em}}
    td{{border-bottom:1px solid #0d1526}}
    .btn{{display:inline-flex;align-items:center;padding:8px 15px;border-radius:8px;text-decoration:none;font-size:12px;font-weight:600;margin:0 6px 6px 0;transition:.15s}}
    .btn:hover{{opacity:.85;transform:translateY(-1px)}}
    .pulse{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}}
    .pulse-g{{background:#10b981;box-shadow:0 0 0 3px #10b98133;animation:pulse 2s infinite}}
    @keyframes pulse{{0%,100%{{box-shadow:0 0 0 3px #10b98133}}50%{{box-shadow:0 0 0 6px #10b98111}}}}
    .badge{{display:inline-block;padding:3px 10px;border-radius:20px;font-size:10px;font-weight:600}}
    .sbar{{display:flex;align-items:center;gap:10px;padding:10px 14px;background:#0d1526;border-radius:8px;font-size:12px;color:#475569;margin-bottom:14px;flex-wrap:wrap}}
    @media(max-width:600px){{.grid{{grid-template-columns:1fr 1fr}}}}
  </style>
</head>
<body>
<div class="w">

  <div style="display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:5px">
    <div>
      <h1>⚡ Nifty 50 Signal API <span style="font-size:14px;color:#10b981;background:#052e16;padding:3px 10px;border-radius:20px;margin-left:8px">Event-Driven</span></h1>
      <div class="sub">Ultra Optimised v4 &nbsp;·&nbsp; {now.strftime('%d %b %Y %I:%M:%S %p IST')} &nbsp;·&nbsp; Auto-refreshes every 30s</div>
    </div>
    <span class="badge" style="background:{'#052e16' if mopen else '#1e293b'};color:{'#10b981' if mopen else '#475569'};font-size:12px;padding:7px 14px">
      {'🟢 MARKET OPEN' if mopen else '🔴 MARKET CLOSED'}
    </span>
  </div>

  <!-- Status Bar -->
  <div class="sbar">
    <span class="pulse pulse-g"></span>
    <span style="color:#10b981;font-weight:600">Engine running</span>
    <span>·</span>
    <span>Uptime: <strong style="color:#f8fafc">{h_up}h {m_up}m</strong></span>
    <span>·</span>
    <span>Scans: <strong style="color:#f8fafc">{STATE['scan_count']}</strong></span>
    <span>·</span>
    <span>Alerts fired: <strong style="color:#f8fafc">{STATE['alert_count']}</strong></span>
    <span>·</span>
    <span>Emails sent: <strong style="color:#f8fafc">{STATE['email_sent']}</strong></span>
    <span>·</span>
    <span>Next scan: <strong style="color:#10b981">~{next_scan}s</strong></span>
    <span>·</span>
    <span>Interval: <strong style="color:#f8fafc">{SCAN_INTERVAL_SEC//60} min</strong></span>
    <span>·</span>
    <span>Cooldown: <strong style="color:#f8fafc">{COOLDOWN_MIN} min</strong></span>
  </div>

  <!-- KPIs -->
  <div class="grid">
    <div class="kpi g"><div class="kpi-l">Nifty Spot</div>
      <div class="kpi-v" style="color:#f8fafc;font-size:20px">₹{spot:,.0f}</div></div>
    <div class="kpi {'g' if vix<15 else 'a' if vix<20 else 'r'}">
      <div class="kpi-l">India VIX</div>
      <div class="kpi-v" style="color:{'#10b981' if vix<15 else '#f59e0b' if vix<20 else '#ef4444'}">{vix:.1f}</div>
      <div class="kpi-s">{'Low ✅' if vix<15 else 'Moderate ⚠️' if vix<20 else 'High 🔴'}</div></div>
    <div class="kpi b"><div class="kpi-l">HIGH+ Signals</div>
      <div class="kpi-v" style="color:{'#10b981' if fired else '#475569'}">{len(fired)}</div>
      <div class="kpi-s">ready to fire</div></div>
    <div class="kpi a"><div class="kpi-l">Alerts Fired</div>
      <div class="kpi-v" style="color:#f59e0b">{STATE['alert_count']}</div>
      <div class="kpi-s">this session</div></div>
    <div class="kpi g"><div class="kpi-l">Emails Sent</div>
      <div class="kpi-v" style="color:#10b981">{STATE['email_sent']}</div>
      <div class="kpi-s">to rishankaggarwal1994</div></div>
    <div class="kpi {'g' if email_ok else 'r'}"><div class="kpi-l">Email Config</div>
      <div class="kpi-v" style="font-size:14px;margin-top:3px;color:{'#10b981' if email_ok else '#ef4444'}">{'✅ Ready' if email_ok else '⚠️ Not Set'}</div></div>
  </div>

  <!-- Actions -->
  <div class="card">
    <div class="ct">Quick Actions</div>
    <a href="/scan"          class="btn" style="background:#10b981;color:#fff">🔍 Force Scan Now</a>
    <a href="/trigger-email" class="btn" style="background:#ef4444;color:#fff">📧 Force Email</a>
    <a href="/signals"       class="btn" style="background:#3b82f6;color:#fff">📊 Signals JSON</a>
    <a href="/status"        class="btn" style="background:#1e293b;color:#94a3b8">⚙️ Status</a>
    <a href="/docs"          class="btn" style="background:#8b5cf6;color:#fff">📖 API Docs</a>
  </div>

  <!-- Strategy State Table -->
  <div class="card">
    <div class="ct">Strategy Monitor — Real-Time State</div>
    <div style="overflow-x:auto">
      <table>
        <thead><tr>
          <th>Strategy</th><th>Direction</th><th>Confidence</th>
          <th>Cooldown</th><th>Times Fired</th><th>Will Fire?</th>
        </tr></thead>
        <tbody>{strat_rows or '<tr><td colspan="6" style="padding:20px;text-align:center;color:#334155">Waiting for first scan...</td></tr>'}</tbody>
      </table>
    </div>
  </div>

  <!-- Alert History -->
  <div class="card">
    <div class="ct">Recent Alerts Sent (Last 10)</div>
    <table>
      <thead><tr><th>Time</th><th>Direction</th><th>Signals</th></tr></thead>
      <tbody>{hist_rows}</tbody>
    </table>
  </div>

  <!-- How firing works -->
  <div class="card" style="border-color:#10b98133">
    <div class="ct" style="color:#10b981">⚡ Event-Driven Firing Logic</div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px">
      {"".join(
    f'<div style="background:#0d1526;border-radius:8px;padding:12px">'
    f'<div style="font-size:10px;color:#10b981;font-weight:600;margin-bottom:5px">{title}</div>'
    f'<div style="font-size:12px;color:#64748b;line-height:1.6">{body}</div>'
    f'</div>'
    for title, body in [
        ("Scan Interval", f"Every {SCAN_INTERVAL_SEC//60} minutes during market hours (9:15–3:30 IST)"),
        ("Fire Condition", "Confidence = HIGH or VERY HIGH only. LOW and MEDIUM are logged but never emailed."),
        ("Cooldown", f"{COOLDOWN_MIN}-min per-strategy cooldown prevents duplicate spam alerts."),
        ("Override Rules", "Cooldown bypassed if direction FLIPS or confidence IMPROVES to next level."),
        ("Consensus Alert", "Separate email if 3+ strategies agree on same direction simultaneously."),
        ("Email Format", "Entry · Stop Loss · Target 1 & 2 · Position size (lots) · R:R · All reasons"),
    ]
)}
    </div>
  </div>

  <div style="text-align:center;font-size:11px;color:#1e293b;padding:12px">
    Nifty 50 Signal Engine v4 · Event-Driven Build · Not SEBI-registered investment advice
  </div>
</div>
</body></html>"""


@app.get("/scan", tags=["Signals"])
async def scan_now(x_api_key: str = Header(None)):
    """Force an immediate scan of all 5 strategies."""
    auth(x_api_key)
    result = await asyncio.get_event_loop().run_in_executor(None, run_scan, False)
    return JSONResponse(content=result)


@app.get("/signals", tags=["Signals"])
async def get_signals(x_api_key: str = Header(None)):
    """Return cached results from the last scan."""
    auth(x_api_key)
    return {
        "last_scan":  STATE["last_scan"],
        "spot":       STATE["last_spot"],
        "vix":        STATE["last_vix"],
        "count":      len(STATE["last_signals"]),
        "fired_this_session": STATE["alert_count"],
        "signals":    STATE["last_signals"],
    }


@app.get("/trigger-email", tags=["Email"])
async def force_email(x_api_key: str = Header(None)):
    """Force-send an email with the latest results right now, bypassing cooldowns."""
    auth(x_api_key)
    if not STATE["last_signals"]:
        result = await asyncio.get_event_loop().run_in_executor(None, run_scan, True)
        return {"status": "scanned_and_sent", "fired": result.get("fired", 0)}
    _send_alert_email(STATE["last_signals"], STATE["last_spot"], STATE["last_vix"], force=True)
    return {
        "status":    "sent",
        "recipient": CONFIG["email"]["recipient_email"],
        "signals":   sum(1 for s in STATE["last_signals"] if s.get("is_tradeable")),
    }


@app.get("/status", tags=["Health"])
async def status():
    now = datetime.now()
    uptime = str(timedelta(seconds=int((now - datetime.fromisoformat(STATE["started_at"])).total_seconds())))
    return {
        "status":          "running",
        "uptime":          uptime,
        "started_at":      STATE["started_at"],
        "last_scan":       STATE["last_scan"],
        "scan_count":      STATE["scan_count"],
        "alert_count":     STATE["alert_count"],
        "email_sent":      STATE["email_sent"],
        "errors":          STATE["errors"],
        "market_open":     is_market_hours(),
        "spot":            STATE["last_spot"],
        "vix":             STATE["last_vix"],
        "scan_interval_s": SCAN_INTERVAL_SEC,
        "cooldown_min":    COOLDOWN_MIN,
        "fire_on":         list(HIGH_CONF),
        "recipient":       CONFIG["email"]["recipient_email"],
        "email_ready":     bool(CONFIG["email"]["sender_email"]),
        "strategy_state":  {
            k: {**v, "fired_at": v["fired_at"].isoformat() if v.get("fired_at") else None}
            for k, v in STATE["strategy_state"].items()
        },
        "alert_history":   STATE["alert_history"][-10:],
    }


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=CONFIG["api"]["host"],
        port=CONFIG["api"]["port"],
        reload=False,
        log_level="info",
        access_log=False,
    )
