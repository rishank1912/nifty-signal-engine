#!/usr/bin/env python3
"""
=============================================================
EXTERNAL KEEPALIVE — Run this separately on any always-on
machine (your laptop, Raspberry Pi, or a second free server)
to ping the main API every 4 minutes so it never sleeps.
=============================================================
Usage:
  pip install requests schedule
  python keepalive.py

Or set up UptimeRobot (free):
  1. Go to https://uptimerobot.com (free account)
  2. Add New Monitor → HTTP(s)
  3. URL: https://your-app.railway.app/health
  4. Monitoring interval: 5 minutes
  5. Alert contact: rishankaggarwal1994@gmail.com
  → UptimeRobot will email you if API goes down AND keep it awake!
=============================================================
"""

import requests
import schedule
import time
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(message)s")
log = logging.getLogger("Keepalive")

# ── CONFIGURE THIS ──────────────────────────────────────────
API_URL = "https://your-app.railway.app"   # ← replace with your deployed URL
API_KEY = "nifty-secret-2024"              # ← match your API_KEY env var
# ────────────────────────────────────────────────────────────

def ping():
    try:
        r = requests.get(f"{API_URL}/health",
                         headers={"X-API-Key": API_KEY},
                         timeout=15)
        data = r.json()
        log.info(f"✅ Ping OK | Nifty ₹{data.get('spot',0):,.0f} | "
                 f"Scans: {data.get('scan_count',0)} | "
                 f"Emails: {data.get('email_sent',0)} | "
                 f"Market: {'OPEN' if data.get('market_open') else 'CLOSED'}")
    except Exception as e:
        log.error(f"❌ Ping FAILED: {e}")

def trigger_scan():
    """Optional: force a scan at market open."""
    now = datetime.now()
    if now.weekday() < 5 and now.hour == 9 and now.minute == 16:
        try:
            requests.get(f"{API_URL}/scan",
                         headers={"X-API-Key": API_KEY},
                         timeout=30)
            log.info("📊 Market open scan triggered")
        except:
            pass

# Ping every 4 minutes (keeps free-tier servers awake)
schedule.every(4).minutes.do(ping)
schedule.every(1).minutes.do(trigger_scan)

if __name__ == "__main__":
    log.info(f"🔔 Keepalive started → {API_URL}")
    log.info("Press Ctrl+C to stop")
    ping()  # immediate first ping
    while True:
        schedule.run_pending()
        time.sleep(30)
