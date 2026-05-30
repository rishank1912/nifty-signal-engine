# 🚀 Nifty 50 Signal Engine — Cloud Deployment Guide

Signals sent to: **rishankaggarwal1994@gmail.com** · 24/7 · 14 scans/day

---

## ⚡ Option 1: Railway.app — RECOMMENDED (Free, 5 min setup)

Railway gives **$5 free credit/month** (enough for ~500 hours). No credit card needed.

### Step 1 — Push to GitHub
```bash
cd nifty_cloud
git init
git add .
git commit -m "Nifty Signal Engine v4"
# Create a NEW private repo on github.com, then:
git remote add origin https://github.com/YOUR_USERNAME/nifty-signal-engine.git
git push -u origin main
```

### Step 2 — Deploy on Railway
1. Go to **[railway.app](https://railway.app)** → Sign up with GitHub
2. Click **"New Project"** → **"Deploy from GitHub repo"**
3. Select your `nifty-signal-engine` repo
4. Railway auto-detects the `Dockerfile` and starts building

### Step 3 — Set Environment Variables
In Railway dashboard → your project → **Variables** tab, add:

| Variable | Value |
|----------|-------|
| `SENDER_EMAIL` | your Gmail address |
| `SENDER_PASSWORD` | your 16-char Gmail App Password |
| `API_KEY` | `nifty-signal-2024` (change this) |
| `RECIPIENT_EMAIL` | `rishankaggarwal1994@gmail.com` |
| `TZ` | `Asia/Kolkata` |

### Step 4 — Get your URL
Railway gives you a URL like `https://nifty-signal-engine-production.up.railway.app`

Open it → you'll see the live dashboard! ✅

---

## ⚡ Option 2: Render.com (Free, always-on with paid plan)

### Free tier note
Render free tier **sleeps after 15 min of inactivity**. Use the `keepalive.py` script
or UptimeRobot to prevent this. Or upgrade to Starter ($7/mo) for always-on.

### Steps
1. Go to **[render.com](https://render.com)** → New → Web Service
2. Connect GitHub → select your repo
3. Render detects `render.yaml` automatically
4. Add environment variables in the dashboard (same as Railway above)
5. Click **Deploy** → get your `https://nifty-signal-engine.onrender.com` URL

---

## ⚡ Option 3: Fly.io (Best free tier, truly always-on)

Fly.io gives **3 shared VMs free forever** with no sleep.

```bash
# Install flyctl
curl -L https://fly.io/install.sh | sh

# Login
fly auth login

# Deploy (first time)
cd nifty_cloud
fly launch --name nifty-signal-engine --region sin

# Set secrets
fly secrets set SENDER_EMAIL="your@gmail.com"
fly secrets set SENDER_PASSWORD="xxxx xxxx xxxx xxxx"
fly secrets set API_KEY="nifty-signal-2024"

# Deploy updates
fly deploy
```

Your app runs at: `https://nifty-signal-engine.fly.dev`

---

## ⚡ Option 4: Docker on Any VPS (₹200-500/month)

Use **DigitalOcean** (₹360/mo), **Hetzner** (€3.79/mo = cheapest), or **AWS EC2 t3.micro**.

```bash
# On your VPS — install Docker
curl -fsSL https://get.docker.com | sh

# Clone your repo
git clone https://github.com/YOUR_USERNAME/nifty-signal-engine.git
cd nifty-signal-engine

# Create .env file with your secrets
cp .env.example .env
nano .env    # fill in SENDER_EMAIL, SENDER_PASSWORD, API_KEY

# Start
docker compose up -d

# Check logs
docker compose logs -f

# Your API is running on http://YOUR_VPS_IP:8000
```

### Auto-restart on reboot (VPS)
```bash
# Docker compose already has restart: unless-stopped
# But also add to crontab:
crontab -e
# Add this line:
@reboot cd /root/nifty-signal-engine && docker compose up -d
```

---

## 🔒 Step: Get Gmail App Password

This is the only setup that needs care:

1. Go to [myaccount.google.com](https://myaccount.google.com)
2. Click **Security** → **2-Step Verification** → turn it ON
3. Back on Security page → **App Passwords** (appears after 2FA is enabled)
4. Select app: **Mail** · Select device: **Other** → type "Nifty API"
5. Google generates: `abcd efgh ijkl mnop` (16 chars)
6. Copy this → paste as `SENDER_PASSWORD` env var

> ⚠️ Use this App Password, NOT your Gmail login password

---

## 📡 Set Up UptimeRobot (Free — keeps server awake + alerts if down)

1. Go to [uptimerobot.com](https://uptimerobot.com) → free account
2. **Add New Monitor**:
   - Monitor Type: `HTTP(s)`
   - Friendly Name: `Nifty Signal Engine`
   - URL: `https://your-app-url.railway.app/health`
   - Monitoring Interval: `5 minutes`
3. **Alert Contacts**: add `rishankaggarwal1994@gmail.com`
4. Save → UptimeRobot now:
   - Pings `/health` every 5 min → **keeps Render/Railway awake**
   - Emails you if the API goes down

---

## 🔧 API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Live dashboard (open in browser) |
| `GET /health` | Health check (for UptimeRobot) |
| `GET /scan` | Force a scan right now |
| `GET /signals` | Last scan results (JSON) |
| `GET /trigger-email` | Force send email immediately |
| `GET /status` | Full engine status |
| `GET /docs` | Swagger UI (all endpoints) |

### Auth header
```bash
curl -H "X-API-Key: nifty-signal-2024" https://your-app.railway.app/scan
```

---

## 📅 Auto-Scan Schedule (IST)

```
09:20  09:35  10:00  10:30  11:00  11:30
12:00  12:30  13:00  13:30  14:00  14:30
15:00  15:15
```
**14 scans per trading day · Mon–Fri only**

---

## 📧 Email Alert Format

Each email to `rishankaggarwal1994@gmail.com` contains:

```
🚀 DIRECTION: BUY / SELL
Strategy: Wyckoff Swing Master

Entry Price:  ₹23,724
Stop Loss:    ₹23,584  (140 pts)
Target 1:     ₹23,980  R:R 1:1.8  ← exit 50% here
Target 2:     ₹24,200  R:R 1:3.4  ← trail 50%

Position Size:
  Lots:       2
  Qty:        100 units
  Max Risk:   ₹14,000 (1.4% of capital)

Reasons:
  ✓ 3/4 timeframes bullish EMA aligned
  ✓ ADX 26.3 > 20 — trend confirmed
  ✓ RSI 58.4 rising — momentum building
  ✓ MACD histogram expanding
  ✓ Supertrend bullish on 1H
  ✓ VIX 14.2 in optimal range

Confidence: VERY HIGH
```

---

## 💡 Quick Troubleshooting

| Problem | Fix |
|---------|-----|
| No email received | Check spam folder; verify App Password (not login password) |
| `spot = 0` in logs | NSE data has 15-min delay on yfinance; check during market hours |
| App sleeping (Render) | Set up UptimeRobot or upgrade to paid plan |
| Wrong timezone | Ensure `TZ=Asia/Kolkata` env var is set |
| `401 Unauthorized` | Pass `X-API-Key` header matching your `API_KEY` env var |

---

*Nifty 50 Signal Engine v4 · Not SEBI-registered investment advice*
