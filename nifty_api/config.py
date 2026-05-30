"""
=============================================================
NIFTY 50 SIGNAL ENGINE — CLOUD CONFIG
All secrets from ENV VARIABLES. Set in Railway/Render dashboard.
Required: SENDER_EMAIL, SENDER_PASSWORD, API_KEY
Optional: RECIPIENT_EMAIL, CAPITAL, RISK_PCT, PORT
=============================================================
"""
import os

def env(key, default=""):      return os.environ.get(key, default)
def env_float(key, d):
    try: return float(os.environ.get(key, d))
    except: return float(d)
def env_int(key, d):
    try: return int(os.environ.get(key, d))
    except: return int(d)

CONFIG = {
    "email": {
        "sender_email":    env("rishankaggarwal1994@gmail.com",    ""),
        "sender_password": env("cvrn jbhd xlrv xjwx", ""),
        "recipient_email": env("rishankaggarwal1994@gmail.com"),
        "smtp_host":       "smtp.gmail.com",
        "smtp_port":       587,
    },
    "trading": {
        "capital":          env_int("CAPITAL", 1_000_000),
        "risk_per_trade":   env_float("RISK_PCT", 0.015),
        "max_daily_loss":   0.03,
        "max_positions":    3,
        "nifty_lot_size":   50,
        "nifty_symbol":     "^NSEI",
        "banknifty_symbol": "^NSEBANK",
        "vix_symbol":       "^INDIAVIX",
    },
    "filters": {
        "min_adx": 20, "min_vix": 10, "max_vix": 22, "condor_max_vix": 18,
        "min_volume_mult": 1.8, "orb_gap_skip_pct": 0.8,
        "squeeze_min_tfs": 2, "macro_min_score": 8, "swing_min_score": 7,
    },
    "schedule": {
        "times": ["09:20","09:35","10:00","10:30","11:00","11:30",
                  "12:00","12:30","13:00","13:30","14:00","14:30","15:00","15:15"],
        "market_open": "09:15", "market_close": "15:30", "weekend_days": [5, 6],
    },
    "api": {
        "host": "0.0.0.0", "port": env_int("PORT", 8000),
        "title": "Nifty 50 Signal Engine v4", "version": "4.0.0",
        "api_key": env("API_KEY", "nifty-secret-2024"),
    },
}
