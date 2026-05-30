"""Email builder and SMTP sender"""
import smtplib
import logging
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import CONFIG

log = logging.getLogger("EmailSender")


def _badge(text: str, color: str, bg: str) -> str:
    return f'<span style="background:{bg};color:{color};font-size:11px;padding:3px 10px;border-radius:12px;font-weight:600;display:inline-block">{text}</span>'


def _dir_color(d: str) -> str:
    return {"BUY": "#10b981", "SELL": "#ef4444"}.get(d.split()[0], "#3b82f6")


def _conf_style(c: str) -> tuple:
    return {
        "VERY_HIGH": ("#10b981", "#052e16"),
        "HIGH":      ("#22c55e", "#0a1f12"),
        "MEDIUM":    ("#f59e0b", "#2d1b00"),
        "LOW":       ("#64748b", "#1e293b"),
    }.get(c, ("#64748b", "#1e293b"))


def build_signal_card(sig: dict) -> str:
    dc        = _dir_color(sig["direction"])
    cc, cbg   = _conf_style(sig["confidence"])
    reasons_li= "".join(f'<li style="margin:5px 0;color:#94a3b8;font-size:12px">{r}</li>' for r in sig["reasons"])
    ps        = sig.get("position_size", {})
    rr1 = sig.get("rr1", 0)
    rr2 = sig.get("rr2", 0)

    instrument_line = f"""
    <tr>
      <td style="padding:6px 0;color:#64748b;font-size:12px;width:38%">Instrument</td>
      <td style="color:#f8fafc;font-weight:600;font-size:12px">{sig.get("instrument","Nifty F&O")}</td>
    </tr>"""

    return f"""
    <div style="background:#111827;border-radius:14px;padding:22px;margin-bottom:22px;
                border-left:5px solid {dc};border:1px solid #1e2940">

      <!-- Header -->
      <div style="display:flex;align-items:flex-start;justify-content:space-between;
                  margin-bottom:16px;flex-wrap:wrap;gap:10px">
        <div>
          <div style="font-size:10px;color:#475569;text-transform:uppercase;
                      letter-spacing:.06em;margin-bottom:5px">{sig["strategy"]}</div>
          <div style="font-size:26px;font-weight:800;color:{dc};letter-spacing:.01em">{sig["direction"]}</div>
        </div>
        <div style="text-align:right">
          <span style="background:{cbg};color:{cc};font-size:11px;padding:4px 12px;
                       border-radius:20px;font-weight:700;border:1px solid {cc}44">
            {sig["confidence"]} CONFIDENCE
          </span>
          <div style="font-size:11px;color:#475569;margin-top:6px">
            {sig.get("timestamp","")[:16]}
          </div>
        </div>
      </div>

      <!-- Trade Details -->
      <div style="background:#0d1526;border-radius:10px;padding:16px;margin-bottom:14px">
        <div style="font-size:10px;font-weight:700;color:#475569;text-transform:uppercase;
                    letter-spacing:.06em;margin-bottom:12px">📊 Trade Details</div>
        <table style="width:100%;border-collapse:collapse">
          {instrument_line}
          <tr><td style="padding:6px 0;color:#64748b;font-size:12px">Entry Price</td>
              <td style="color:{dc};font-weight:800;font-size:18px">₹{sig["entry"]:,.0f}</td></tr>
          <tr><td style="padding:6px 0;color:#64748b;font-size:12px">Stop Loss</td>
              <td style="color:#ef4444;font-weight:700;font-size:14px">
                ₹{sig["stoploss"]:,.0f}
                <span style="font-size:11px;color:#475569;margin-left:6px">
                  ({abs(sig["entry"]-sig["stoploss"]):.0f} pts away)
                </span>
              </td></tr>
          <tr><td style="padding:6px 0;color:#64748b;font-size:12px">Target 1 (50% exit)</td>
              <td style="color:#10b981;font-weight:700;font-size:14px">
                ₹{sig["target1"]:,.0f}
                <span style="font-size:11px;background:#052e16;color:#10b981;
                             padding:2px 7px;border-radius:8px;margin-left:6px">R:R 1:{rr1}</span>
              </td></tr>
          <tr><td style="padding:6px 0;color:#64748b;font-size:12px">Target 2 (trail 50%)</td>
              <td style="color:#10b981;font-weight:700;font-size:14px">
                ₹{sig["target2"]:,.0f}
                <span style="font-size:11px;background:#052e16;color:#10b981;
                             padding:2px 7px;border-radius:8px;margin-left:6px">R:R 1:{rr2}</span>
              </td></tr>
        </table>
      </div>

      <!-- Position Size -->
      <div style="background:#0d1526;border-radius:10px;padding:16px;margin-bottom:14px">
        <div style="font-size:10px;font-weight:700;color:#475569;text-transform:uppercase;
                    letter-spacing:.06em;margin-bottom:12px">💰 Position Sizing (₹10,00,000 Capital)</div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:10px">
          <div style="text-align:center;background:#111827;border-radius:8px;padding:10px">
            <div style="font-size:10px;color:#475569;margin-bottom:4px">LOTS</div>
            <div style="font-size:22px;font-weight:800;color:#f8fafc">{ps.get("lots","—")}</div>
          </div>
          <div style="text-align:center;background:#111827;border-radius:8px;padding:10px">
            <div style="font-size:10px;color:#475569;margin-bottom:4px">QTY</div>
            <div style="font-size:22px;font-weight:800;color:#f8fafc">{ps.get("qty","—")}</div>
          </div>
          <div style="text-align:center;background:#111827;border-radius:8px;padding:10px">
            <div style="font-size:10px;color:#475569;margin-bottom:4px">MAX RISK</div>
            <div style="font-size:16px;font-weight:800;color:#ef4444">₹{ps.get("risk_amount",0):,.0f}</div>
          </div>
          <div style="text-align:center;background:#111827;border-radius:8px;padding:10px">
            <div style="font-size:10px;color:#475569;margin-bottom:4px">RISK %</div>
            <div style="font-size:22px;font-weight:800;color:#f59e0b">{ps.get("risk_pct",0):.1f}%</div>
          </div>
        </div>
      </div>

      <!-- Reasons -->
      <div style="background:#0d1526;border-radius:10px;padding:16px">
        <div style="font-size:10px;font-weight:700;color:#475569;text-transform:uppercase;
                    letter-spacing:.06em;margin-bottom:10px">🧠 Why This Trade</div>
        <ul style="margin:0;padding-left:18px;line-height:1.8">{reasons_li}</ul>
      </div>
    </div>"""


def build_email_html(signals: list, spot: float, vix: float) -> str:
    now       = datetime.now()
    now_str   = now.strftime("%d %b %Y, %I:%M %p IST")
    tradeable = [s for s in signals if s.get("is_tradeable")]
    standby   = [s for s in signals if not s.get("is_tradeable")]

    vix_color = "#10b981" if vix < 15 else "#f59e0b" if vix < 20 else "#ef4444"
    vix_label = "✅ Low" if vix < 15 else "⚠️ Moderate" if vix < 20 else "🔴 High"

    signal_cards = "".join(build_signal_card(s) for s in tradeable) if tradeable else """
    <div style="background:#111827;border-radius:14px;padding:30px;text-align:center;
                margin-bottom:22px;border:1px solid #1e293b">
      <div style="font-size:32px;margin-bottom:10px">⏸</div>
      <div style="font-size:16px;font-weight:600;color:#475569;margin-bottom:6px">No Tradeable Signals</div>
      <div style="font-size:13px;color:#334155">
        All 5 strategies scanned. Market conditions do not meet high-confidence thresholds.<br>
        Staying out of the market is also a valid position.
      </div>
    </div>"""

    standby_rows = "".join(f"""
    <div style="display:flex;align-items:center;justify-content:space-between;
                padding:11px 14px;background:#111827;border-radius:8px;
                margin-bottom:7px;border:1px solid #1e293b">
      <div>
        <div style="font-size:12px;font-weight:600;color:#475569">{s["strategy"]}</div>
        <div style="font-size:11px;color:#334155;margin-top:2px">{s["reasons"][0] if s.get("reasons") else "No signal"}</div>
      </div>
      <span style="background:#1e293b;color:#475569;font-size:10px;padding:3px 9px;
                   border-radius:10px;font-weight:600;white-space:nowrap;margin-left:10px">NO TRADE</span>
    </div>""" for s in standby)

    rules = [
        "Max risk per trade: 1.5% of capital = ₹15,000",
        "Daily loss limit: 3% = ₹30,000 — stop all trading if hit",
        "Exit 50% at Target 1, trail remaining position to Target 2",
        "If Nifty reverses 50% of expected move after entry → exit full position",
        "Never average a losing F&O position — time decay works against you",
        "Close all positions by 3:15 PM to avoid last-minute expiry volatility",
        "VERY HIGH & HIGH confidence signals only — skip MEDIUM and LOW",
    ]
    rules_html = "".join(f'<li style="padding:4px 0;color:#64748b;font-size:12px">{r}</li>' for r in rules)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Nifty Signal — {now_str}</title>
</head>
<body style="margin:0;padding:0;background:#0a0e1a;font-family:system-ui,-apple-system,'Segoe UI',sans-serif">
<div style="max-width:700px;margin:0 auto;padding:20px">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#041a0e 0%,#091428 60%,#041a0e 100%);
              border-radius:16px;padding:28px 24px;margin-bottom:24px;text-align:center;
              border:1px solid #10b98133">
    <div style="font-size:36px;margin-bottom:8px">🚀</div>
    <div style="font-size:22px;font-weight:800;color:#10b981;letter-spacing:.01em">
      Nifty 50 · Live Trading Signals
    </div>
    <div style="font-size:13px;color:#475569;margin-top:4px">
      Ultra Optimised v4 · {now_str}
    </div>
    <div style="margin-top:14px">
      <span style="background:{'#10b981' if tradeable else '#334155'};
                   color:#fff;font-size:13px;padding:6px 18px;border-radius:20px;font-weight:700">
        {'⚡ ' + str(len(tradeable)) + ' ACTIONABLE SIGNAL' + ('S' if len(tradeable)!=1 else '') if tradeable else '⏸ NO SIGNALS THIS SCAN'}
      </span>
    </div>
  </div>

  <!-- Market Snapshot -->
  <div style="background:#111827;border-radius:14px;padding:18px;margin-bottom:24px;
              border:1px solid #10b98133">
    <div style="font-size:11px;font-weight:700;color:#10b981;text-transform:uppercase;
                letter-spacing:.06em;margin-bottom:14px">📈 Market Snapshot</div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:14px">
      <div style="background:#0d1526;border-radius:10px;padding:12px;text-align:center">
        <div style="font-size:10px;color:#475569;text-transform:uppercase;margin-bottom:5px">Nifty 50</div>
        <div style="font-size:20px;font-weight:800;color:#f8fafc">₹{spot:,.0f}</div>
      </div>
      <div style="background:#0d1526;border-radius:10px;padding:12px;text-align:center">
        <div style="font-size:10px;color:#475569;text-transform:uppercase;margin-bottom:5px">India VIX</div>
        <div style="font-size:20px;font-weight:800;color:{vix_color}">{vix:.2f}</div>
        <div style="font-size:10px;color:{vix_color}">{vix_label}</div>
      </div>
      <div style="background:#0d1526;border-radius:10px;padding:12px;text-align:center">
        <div style="font-size:10px;color:#475569;text-transform:uppercase;margin-bottom:5px">Signals</div>
        <div style="font-size:20px;font-weight:800;color:{'#10b981' if tradeable else '#475569'}">{len(tradeable)}/{len(signals)}</div>
        <div style="font-size:10px;color:#475569">tradeable</div>
      </div>
    </div>
    <div style="font-size:11px;color:#334155;text-align:center">
      Strategies scanned: Wyckoff Swing · ORB Ultra · Triple Squeeze · 0DTE Condor · Macro Trend
    </div>
  </div>

  <!-- Signal Cards -->
  <div style="font-size:14px;font-weight:700;color:#f8fafc;margin-bottom:14px">
    {'⚡ Tradeable Signals' if tradeable else '⏸ No Signals This Scan'}
  </div>
  {signal_cards}

  <!-- Standby Strategies -->
  {f'<div style="font-size:13px;font-weight:600;color:#475569;margin-bottom:10px;margin-top:8px">📋 Strategies on Standby</div>{standby_rows}' if standby_rows else ''}

  <!-- Trade Rules -->
  <div style="background:#111827;border-radius:14px;padding:18px;margin-top:22px;
              border:1px solid #1e293b">
    <div style="font-size:11px;font-weight:700;color:#475569;text-transform:uppercase;
                letter-spacing:.06em;margin-bottom:10px">⚡ Iron Trading Rules</div>
    <ul style="margin:0;padding-left:18px">{rules_html}</ul>
  </div>

  <!-- Disclaimer -->
  <div style="background:#1c0a08;border-radius:10px;padding:14px;margin-top:16px;
              border-left:3px solid #ef4444">
    <div style="font-size:11px;color:#64748b;line-height:1.7">
      <strong style="color:#f87171">⚠️ DISCLAIMER:</strong>
      Algorithmically generated signals for educational purposes only. NOT SEBI-registered investment advice.
      F&O trading involves significant risk. Never trade with money you cannot afford to lose.
      Verify all signals with your own analysis before placing trades.
    </div>
  </div>

  <!-- Footer -->
  <div style="text-align:center;padding:18px;font-size:11px;color:#334155;margin-top:8px">
    Nifty v4 Signal Engine · <a href="mailto:rishankaggarwal1994@gmail.com" style="color:#475569">rishankaggarwal1994@gmail.com</a><br>
    Next auto-scan in ~15 min during market hours (9:15 AM – 3:30 PM IST)
  </div>

</div>
</body>
</html>"""


def send_email(html: str, subject: str) -> bool:
    cfg = CONFIG["email"]
    if cfg["sender_email"] == "your_gmail@gmail.com":
        print("\n" + "="*60)
        print("EMAIL NOT CONFIGURED — printing to console")
        print(f"Subject: {subject}")
        print("="*60 + "\n")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"Nifty Signal Engine <{cfg['sender_email']}>"
        msg["To"]      = cfg["recipient_email"]
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as s:
            s.ehlo(); s.starttls()
            s.login(cfg["sender_email"], cfg["sender_password"])
            s.sendmail(cfg["sender_email"], cfg["recipient_email"], msg.as_string())
        log.info(f"✅ Email sent → {cfg['recipient_email']}")
        return True
    except Exception as e:
        log.error(f"❌ Email send failed: {e}")
        return False
