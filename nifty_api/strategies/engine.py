"""
=============================================================
ALL 5 ULTRA-OPTIMISED STRATEGIES — SIGNAL GENERATORS
=============================================================
1. Wyckoff Swing Master    — multi-TF trend + SMC confluence
2. Precision ORB Ultra     — opening range breakout + volume
3. Triple Squeeze + AI     — TTM Squeeze multi-TF momentum
4. 0DTE Condor Machine     — theta decay iron condor
5. Macro Trend Alpha       — daily macro + trend confluence
=============================================================
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime
from utils.indicators import Indicators
from config import CONFIG

log = logging.getLogger("StrategyEngine")


# ─────────────────────────────────────────────
# POSITION SIZER
# ─────────────────────────────────────────────
def size_position(entry: float, sl: float) -> dict:
    cap      = CONFIG["trading"]["capital"]
    risk_pct = CONFIG["trading"]["risk_per_trade"]
    lot_size = CONFIG["trading"]["nifty_lot_size"]
    risk_amt = cap * risk_pct
    pts      = abs(entry - sl)
    if pts == 0:
        return {"lots": 1, "qty": lot_size, "risk_amount": 0, "risk_pct": 0}
    qty      = int(risk_amt / pts)
    lots     = max(1, round(qty / lot_size))
    act_qty  = lots * lot_size
    act_risk = act_qty * pts
    return {
        "lots":        lots,
        "qty":         act_qty,
        "risk_amount": round(act_risk, 0),
        "risk_pct":    round(act_risk / cap * 100, 2),
    }


# ─────────────────────────────────────────────
# SIGNAL BUILDER
# ─────────────────────────────────────────────
def make_signal(strategy, direction, entry, t1, t2, sl,
                confidence, reasons, ps, instrument):
    rr1 = round(abs(t1-entry)/abs(entry-sl), 2) if sl != entry else 0
    rr2 = round(abs(t2-entry)/abs(entry-sl), 2) if sl != entry else 0
    return {
        "strategy":      strategy,
        "direction":     direction,
        "instrument":    instrument,
        "entry":         entry,
        "target1":       t1,
        "target2":       t2,
        "stoploss":      sl,
        "rr1":           rr1,
        "rr2":           rr2,
        "confidence":    confidence,
        "reasons":       reasons,
        "position_size": ps,
        "is_tradeable":  direction not in ("NO_TRADE",) and confidence in ("HIGH","VERY_HIGH"),
        "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def no_trade(strategy, reason):
    return make_signal(strategy, "NO_TRADE", 0, 0, 0, 0, "LOW",
                       [reason], {}, "N/A")


# ─────────────────────────────────────────────
# STRATEGY ENGINE CLASS
# ─────────────────────────────────────────────
class StrategyEngine:

    def __init__(self, multi_tf_data: dict, spot: float, vix: float):
        self.raw  = multi_tf_data
        self.spot = spot
        self.vix  = vix
        self.data = {}
        for tf, df in multi_tf_data.items():
            self.data[tf] = Indicators.compute(df.copy())

    def _l(self, tf):
        """Latest indicator row for timeframe."""
        return Indicators.latest(self.data.get(tf, pd.DataFrame()))

    def _p(self, tf, n=1):
        """Previous indicator row."""
        return Indicators.prev(self.data.get(tf, pd.DataFrame()), n)

    # ── STRATEGY 1: WYCKOFF SWING MASTER ─────────────────
    def wyckoff_swing(self) -> dict:
        name = "Wyckoff Swing Master"
        spot = self.spot
        d15  = self._l("15m"); d1h = self._l("1h")
        d4h  = self._l("4h"); d1d = self._l("1d")
        atr  = d1h.get("atr", spot * 0.006)
        score, reasons = 0, []

        # Multi-TF EMA alignment
        bull = sum([
            d15.get("ema9",0) > d15.get("ema21",0),
            d1h.get("ema9",0) > d1h.get("ema21",0),
            d4h.get("ema9",0) > d4h.get("ema21",0),
            d1d.get("ema9",0) > d1d.get("ema21",0),
        ])
        bear = 4 - bull

        if bull >= 3:
            score += 2; reasons.append(f"{bull}/4 timeframes show bullish EMA alignment (9 > 21)")
        elif bear >= 3:
            score += 2; reasons.append(f"{bear}/4 timeframes show bearish EMA alignment (9 < 21)")

        # ADX — trend strength
        adx = d1h.get("adx", 0)
        if adx > CONFIG["filters"]["min_adx"]:
            score += 2; reasons.append(f"1H ADX {adx:.1f} > {CONFIG['filters']['min_adx']} — strong trend in progress")
        elif adx > 15:
            score += 1; reasons.append(f"1H ADX {adx:.1f} — moderate trend developing")

        # RSI
        rsi = d1h.get("rsi", 50)
        prev_rsi = self._p("1h").get("rsi", 50)
        if bull >= 3 and rsi > 52 and rsi > prev_rsi:
            score += 2; reasons.append(f"1H RSI {rsi:.1f} > 52 and rising — bullish momentum accelerating")
        elif bear >= 3 and rsi < 48 and rsi < prev_rsi:
            score += 2; reasons.append(f"1H RSI {rsi:.1f} < 48 and falling — bearish momentum accelerating")

        # MACD histogram expanding
        hist  = d1h.get("macdhist", 0)
        phist = self._p("1h").get("macdhist", 0)
        if abs(hist) > abs(phist):
            score += 2; reasons.append(f"MACD histogram expanding ({hist:+.0f} vs {phist:+.0f}) — momentum building")

        # Supertrend
        st_bull = d1h.get("st_bull", False)
        if st_bull and bull >= 3:
            score += 2; reasons.append("Supertrend bullish on 1H — price above dynamic trailing stop")
        elif not st_bull and bear >= 3:
            score += 2; reasons.append("Supertrend bearish on 1H — price below dynamic trailing stop")

        # Squeeze released (volatility expanding)
        df1h = self.data.get("1h", pd.DataFrame())
        if len(df1h) >= 2:
            was_squeeze = bool(df1h["in_squeeze"].iloc[-2]) if "in_squeeze" in df1h.columns else False
            in_squeeze  = d1h.get("in_squeeze", False)
            if was_squeeze and not in_squeeze:
                score += 2; reasons.append("Bollinger Band squeeze just released on 1H — high-probability directional breakout")

        # VIX filter
        if self.vix and CONFIG["filters"]["min_vix"] < self.vix < CONFIG["filters"]["max_vix"]:
            score += 1; reasons.append(f"VIX {self.vix:.1f} in optimal range — strategy active")
        elif self.vix >= CONFIG["filters"]["max_vix"]:
            score -= 2; reasons.append(f"VIX {self.vix:.1f} elevated — reduce position size by 50%")

        # Build signal
        if score >= CONFIG["filters"]["swing_min_score"] and bull >= 3:
            entry = round(spot + 5, 0); sl = round(spot - 1.5*atr, 0)
            t1    = round(spot + 2.0*atr, 0); t2 = round(spot + 3.5*atr, 0)
            direction = "BUY"; instr = "Nifty CE (ATM) or Futures Long"
        elif score >= CONFIG["filters"]["swing_min_score"] and bear >= 3:
            entry = round(spot - 5, 0); sl = round(spot + 1.5*atr, 0)
            t1    = round(spot - 2.0*atr, 0); t2 = round(spot - 3.5*atr, 0)
            direction = "SELL"; instr = "Nifty PE (ATM) or Futures Short"
        else:
            return no_trade(name, f"Confluence score {score}/13 too low (need ≥{CONFIG['filters']['swing_min_score']}). Waiting for better setup.")

        conf = "VERY_HIGH" if score >= 11 else "HIGH" if score >= 7 else "MEDIUM"
        reasons.append(f"Conviction score: {score}/13 | ATR: {atr:.0f} pts | SL width: {abs(entry-sl):.0f} pts")
        ps = size_position(entry, sl)
        return make_signal(name, direction, entry, t1, t2, sl, conf, reasons, ps, instr)

    # ── STRATEGY 2: PRECISION ORB ULTRA ──────────────────
    def orb_ultra(self) -> dict:
        name = "Precision ORB Ultra"
        spot = self.spot
        now  = datetime.now()
        df5  = self.data.get("5m", pd.DataFrame())
        d15  = self._l("15m")
        score, reasons = 0, []

        if df5.empty or len(df5) < 5:
            return no_trade(name, "Insufficient 5M candle data — ORB cannot be computed yet")

        # Get today's candles
        today_df = df5[df5.index.normalize() == pd.Timestamp(now.date())] if hasattr(df5.index, 'normalize') else df5.tail(20)
        if today_df.empty or len(today_df) < 3:
            return no_trade(name, "Market just opened — waiting for ORB to form (9:15–9:30 AM)")

        orb        = today_df.iloc[:3]
        orb_high   = round(orb["high"].max(), 0)
        orb_low    = round(orb["low"].min(),  0)
        orb_range  = orb_high - orb_low
        atr        = d15.get("atr", orb_range * 1.2)
        vwap       = d15.get("vwap", spot)

        # Best entry windows
        h, m = now.hour, now.minute
        in_window = (9 <= h < 10 and m >= 30) or (13 <= h < 14 and m >= 30)
        if in_window:
            score += 2; reasons.append(f"In high-probability ORB entry window ({'09:30–10:00' if h == 9 else '13:30–14:00'})")

        # Volume filter
        avg_vol  = df5["volume"].mean()
        last_vol = df5.iloc[-1]["volume"]
        vol_mult = last_vol / avg_vol if avg_vol > 0 else 1
        if vol_mult >= CONFIG["filters"]["min_volume_mult"]:
            score += 2; reasons.append(f"Breakout volume {vol_mult:.1f}× average — institutional participation confirmed")
        elif vol_mult >= 1.3:
            score += 1; reasons.append(f"Above-average volume {vol_mult:.1f}× — moderate participation")
        else:
            reasons.append(f"Volume {vol_mult:.1f}× avg — below breakout threshold ({CONFIG['filters']['min_volume_mult']}×)")

        # VWAP alignment
        if spot > vwap:
            score += 1; reasons.append(f"Price ₹{spot:,.0f} above VWAP ₹{vwap:,.0f} — bull bias confirmed")
        else:
            score += 1; reasons.append(f"Price ₹{spot:,.0f} below VWAP ₹{vwap:,.0f} — bear bias confirmed")

        # Breakout detection
        if spot > orb_high * 1.001:
            direction = "BUY"
            entry = round(orb_high + 2, 0); sl = round(orb_low - 5, 0)
            t1    = round(orb_high + orb_range * 1.5, 0)
            t2    = round(orb_high + orb_range * 2.2, 0)
            instr = "Nifty CE (ATM+1) or Futures Long"
            score += 3; reasons.insert(0, f"✅ ORB breakout confirmed: {spot} > ORB High {orb_high} (range: {orb_range:.0f} pts)")
        elif spot < orb_low * 0.999:
            direction = "SELL"
            entry = round(orb_low - 2, 0); sl = round(orb_high + 5, 0)
            t1    = round(orb_low - orb_range * 1.5, 0)
            t2    = round(orb_low - orb_range * 2.2, 0)
            instr = "Nifty PE (ATM+1) or Futures Short"
            score += 3; reasons.insert(0, f"✅ ORB breakdown confirmed: {spot} < ORB Low {orb_low} (range: {orb_range:.0f} pts)")
        else:
            return no_trade(name, f"Price {spot} inside ORB range {orb_low}–{orb_high}. Waiting for breakout/breakdown.")

        # Candle quality filter (rejection candle check)
        last_c = df5.iloc[-1]
        cr = last_c["high"] - last_c["low"]
        close_pos = (last_c["close"] - last_c["low"]) / cr if cr > 0 else 0.5
        if direction == "BUY" and close_pos < 0.25:
            return no_trade(name, f"Rejection filter triggered: breakout candle closed in bottom {close_pos:.0%} — false breakout risk")
        if direction == "SELL" and close_pos > 0.75:
            return no_trade(name, f"Rejection filter triggered: breakdown candle closed in top {1-close_pos:.0%} — false breakdown risk")

        score += 1; reasons.append(f"Candle close quality {close_pos:.0%} — valid breakout structure (rejection filter passed)")
        reasons.append(f"Profit plan: Book 40% at T1 (₹{t1:,.0f}), 40% at T2 (₹{t2:,.0f}), trail 20% with ATR stop")

        conf = "VERY_HIGH" if score >= 7 else "HIGH" if score >= 5 else "MEDIUM"
        ps = size_position(entry, sl)
        return make_signal(name, direction, entry, t1, t2, sl, conf, reasons, ps, instr)

    # ── STRATEGY 3: TRIPLE SQUEEZE + AI MOMENTUM ─────────
    def triple_squeeze(self) -> dict:
        name = "Triple Squeeze + AI Momentum"
        spot = self.spot
        score, reasons = 0, []

        # Count timeframes in squeeze
        sq_tfs = [tf for tf in ["15m","1h","4h"] if self._l(tf).get("in_squeeze", False)]
        if len(sq_tfs) < CONFIG["filters"]["squeeze_min_tfs"]:
            return no_trade(name, f"Only {len(sq_tfs)}/3 TFs in squeeze (need ≥{CONFIG['filters']['squeeze_min_tfs']}). No squeeze setup active.")

        score += len(sq_tfs) * 2
        reasons.append(f"🎯 TTM Squeeze active on {len(sq_tfs)}/3 timeframes: {', '.join(sq_tfs)}")

        d1h  = self._l("1h"); p1h = self._p("1h")
        atr  = d1h.get("atr", spot * 0.006)
        hist  = d1h.get("sq_hist", 0)
        phist = p1h.get("sq_hist", 0)
        rsi   = d1h.get("rsi", 50)

        # Histogram expanding
        df1h = self.data.get("1h", pd.DataFrame())
        if len(df1h) >= 3 and "sq_hist" in df1h.columns:
            h_series = df1h["sq_hist"].dropna()
            if len(h_series) >= 3 and abs(h_series.iloc[-1]) > abs(h_series.iloc[-2]) > abs(h_series.iloc[-3]):
                score += 3; reasons.append("Squeeze histogram expanding 3 consecutive bars — momentum igniting 🔥")

        # MACD confirmation
        macd = d1h.get("macdhist", 0)
        if (hist > 0 and macd > 0) or (hist < 0 and macd < 0):
            score += 2; reasons.append(f"MACD confirms squeeze direction ({macd:+.0f}) — dual momentum alignment")

        # RSI direction
        if hist > 0 and rsi > 52:
            score += 2; reasons.append(f"RSI {rsi:.1f} > 52 + positive histogram — bullish squeeze release signal")
            direction = "BUY"
            entry = round(spot + 3, 0); sl = round(spot - 1.2*atr, 0)
            t1    = round(spot + 1.5*atr, 0); t2 = round(spot + 2.8*atr, 0)
            instr = "Nifty CE (ATM) or Bull Call Spread"
        elif hist < 0 and rsi < 48:
            score += 2; reasons.append(f"RSI {rsi:.1f} < 48 + negative histogram — bearish squeeze release signal")
            direction = "SELL"
            entry = round(spot - 3, 0); sl = round(spot + 1.2*atr, 0)
            t1    = round(spot - 1.5*atr, 0); t2 = round(spot - 2.8*atr, 0)
            instr = "Nifty PE (ATM) or Bear Put Spread"
        else:
            return no_trade(name, f"Squeeze present but direction unclear. RSI: {rsi:.1f}, Histogram: {hist:+.0f}. Wait for clear momentum.")

        # VIX filter
        if self.vix and self.vix < 20:
            score += 1; reasons.append(f"VIX {self.vix:.1f} < 20 — squeeze strategy operates best in moderate vol")

        reasons.append(f"Position plan: Exit 70% at T1 (ATR×1.5), trail 30% with Chandelier Exit to T2 (ATR×2.8)")
        reasons.append(f"Total conviction score: {score}/14")

        conf = "VERY_HIGH" if score >= 11 else "HIGH" if score >= 8 else "MEDIUM"
        ps = size_position(entry, sl)
        return make_signal(name, direction, entry, t1, t2, sl, conf, reasons, ps, instr)

    # ── STRATEGY 4: 0DTE CONDOR MACHINE ──────────────────
    def condor_0dte(self) -> dict:
        name = "0DTE Condor Machine"
        spot = self.spot
        now  = datetime.now()
        score, reasons = 0, []
        atr_d = self._l("1d").get("atr", spot * 0.01)

        # Best days: Wednesday or Thursday
        wday = now.weekday()
        if wday == 3:
            score += 3; reasons.append("Thursday: 0DTE condor day — maximum theta decay to weekly expiry")
        elif wday == 2:
            score += 2; reasons.append("Wednesday: Initiating condor 1 day early — extra premium + roll flexibility")
        else:
            return no_trade(name, f"Condor strategy reserved for Wednesday/Thursday only. Today: {now.strftime('%A')}. Waiting.")

        # VIX must be 10–18 for condor selling
        if not self.vix or not (CONFIG["filters"]["min_vix"] < self.vix < CONFIG["filters"]["condor_max_vix"]):
            return no_trade(name, f"VIX {self.vix:.1f} outside condor sweet-spot (10–18). Premiums {'too cheap' if self.vix < 10 else 'too expensive — use buying strategy instead'}.")

        score += 2; reasons.append(f"VIX {self.vix:.1f} in optimal 10–18 range — condor premiums fairly priced")

        # Calculate strikes using Expected Move
        atm  = round(spot / 50) * 50
        wing = max(150, round(atr_d * 0.5 / 50) * 50)
        sell_ce = atm + wing;  buy_ce  = sell_ce + 200
        sell_pe = atm - wing;  buy_pe  = sell_pe - 200

        # Estimate premium (realistic for Nifty weekly)
        credit_est = round(wing * 0.08, 0)
        max_profit = credit_est * 50
        max_loss   = (200 - credit_est) * 50

        reasons.append(f"ATM: ₹{atm:,} | Wing width: {wing} pts (0.5× weekly ATR)")
        reasons.append(f"SELL {sell_ce} CE + BUY {buy_ce} CE → Call spread")
        reasons.append(f"SELL {sell_pe} PE + BUY {buy_pe} PE → Put spread")
        reasons.append(f"Estimated net credit: ₹{credit_est:.0f}/lot (~₹{max_profit:.0f} max profit)")
        reasons.append(f"Max loss: ₹{max_loss:.0f}/lot | Breakevens: {sell_pe-credit_est:.0f}–{sell_ce+credit_est:.0f}")
        reasons.append(f"Exit rule: Close at 65% profit (₹{max_profit*0.65:.0f}) OR 2:30 PM Thursday — whichever first")
        reasons.append(f"Adjustment: If spot hits {sell_pe} or {sell_ce} → delta-hedge with 0.25 lot Nifty futures")

        score += 2
        conf = "VERY_HIGH" if score >= 7 else "HIGH"

        entry = spot; sl = sell_ce + credit_est * 2
        t1 = spot; t2 = spot  # time-based exit, not price-based
        ps = {"lots": 1, "qty": 50, "risk_amount": round(max_loss, 0),
              "risk_pct": round(max_loss / CONFIG["trading"]["capital"] * 100, 2)}

        return make_signal(name, "SELL (Iron Condor)", entry, t1, t2, sl, conf, reasons, ps,
                           f"Iron Condor: Sell {sell_pe}PE+{sell_ce}CE · Buy {buy_pe}PE+{buy_ce}CE")

    # ── STRATEGY 5: MACRO TREND ALPHA ────────────────────
    def macro_trend(self) -> dict:
        name = "Macro Trend Alpha"
        spot = self.spot
        score, reasons = 0, []
        d1d = self._l("1d"); d4h = self._l("4h")
        atr = d1d.get("atr", spot * 0.01)

        # Daily RSI
        rsi = d1d.get("rsi", 50)
        if rsi > 58:
            score += 2; reasons.append(f"Daily RSI {rsi:.1f} > 58 — strong bullish momentum on weekly chart")
        elif rsi > 52:
            score += 1; reasons.append(f"Daily RSI {rsi:.1f} > 52 — mild bullish bias")
        elif rsi < 42:
            score += 2; reasons.append(f"Daily RSI {rsi:.1f} < 42 — strong bearish momentum on weekly chart")
        elif rsi < 48:
            score += 1; reasons.append(f"Daily RSI {rsi:.1f} < 48 — mild bearish bias")
        else:
            reasons.append(f"Daily RSI {rsi:.1f} — neutral zone, no macro edge")

        # ADX
        adx = d1d.get("adx", 0)
        if adx > 28:
            score += 3; reasons.append(f"Daily ADX {adx:.1f} > 28 — powerful macro trend in force")
        elif adx > 20:
            score += 2; reasons.append(f"Daily ADX {adx:.1f} > 20 — solid macro trend")
        elif adx > 15:
            score += 1; reasons.append(f"Daily ADX {adx:.1f} — trend developing")

        # MACD
        hist = d1d.get("macdhist", 0)
        phist = self._p("1d").get("macdhist", 0)
        if hist > 0 and hist > phist:
            score += 2; reasons.append(f"Daily MACD histogram positive & expanding — bulls in structural control")
        elif hist < 0 and hist < phist:
            score += 2; reasons.append(f"Daily MACD histogram negative & expanding — bears in structural control")
        elif hist > 0:
            score += 1; reasons.append(f"Daily MACD histogram positive — bullish bias")
        elif hist < 0:
            score += 1; reasons.append(f"Daily MACD histogram negative — bearish bias")

        # Triple EMA stack (daily)
        e9 = d1d.get("ema9",0); e21 = d1d.get("ema21",0); e55 = d1d.get("ema55",0)
        if e9 > e21 > e55 and spot > e9:
            score += 2; reasons.append(f"Daily triple EMA bullish stack (EMA9>{e21:.0f}>EMA55) + price above all — bull regime")
        elif e9 < e21 < e55 and spot < e9:
            score += 2; reasons.append(f"Daily triple EMA bearish stack (EMA9<{e21:.0f}<EMA55) + price below all — bear regime")

        # 4H DI confirmation
        pdi4 = d4h.get("pdi", 25); mdi4 = d4h.get("mdi", 25)
        if pdi4 > mdi4 + 5:
            score += 1; reasons.append(f"4H +DI ({pdi4:.1f}) > -DI ({mdi4:.1f}) by {pdi4-mdi4:.1f} pts — bullish momentum confirmed")
        elif mdi4 > pdi4 + 5:
            score += 1; reasons.append(f"4H -DI ({mdi4:.1f}) > +DI ({pdi4:.1f}) by {mdi4-pdi4:.1f} pts — bearish momentum confirmed")

        # VIX
        if self.vix:
            if self.vix < 15:
                score += 1; reasons.append(f"VIX {self.vix:.1f} — calm macro environment, trend trades reliable")
            elif self.vix > 22:
                score -= 1; reasons.append(f"VIX {self.vix:.1f} elevated — reduce position size by 40%")

        # Fire signal
        if score >= CONFIG["filters"]["macro_min_score"] and rsi > 50 and hist > 0:
            direction = "BUY"; entry = round(spot + 5, 0); sl = round(spot - 1.8*atr, 0)
            t1 = round(spot + 2.5*atr, 0); t2 = round(spot + 4.0*atr, 0)
            instr = "Nifty CE (ATM) or Bull Call Spread"
        elif score >= CONFIG["filters"]["macro_min_score"] and rsi < 50 and hist < 0:
            direction = "SELL"; entry = round(spot - 5, 0); sl = round(spot + 1.8*atr, 0)
            t1 = round(spot - 2.5*atr, 0); t2 = round(spot - 4.0*atr, 0)
            instr = "Nifty PE (ATM) or Bear Put Spread"
        else:
            return no_trade(name, f"Macro score {score}/14 (need ≥{CONFIG['filters']['macro_min_score']}). RSI {rsi:.1f}, MACD {hist:+.0f}. No edge today.")

        conf = "VERY_HIGH" if score >= 12 else "HIGH" if score >= 8 else "MEDIUM"
        reasons.append(f"Macro conviction score: {score}/14 | ATR: {atr:.0f} pts")
        reasons.append(f"Execution: 40% at market, 30% on first pullback, 30% on confirmation")
        ps = size_position(entry, sl)
        return make_signal(name, direction, entry, t1, t2, sl, conf, reasons, ps, instr)

    def run_all(self) -> list:
        strategies = [
            ("wyckoff_swing",  self.wyckoff_swing),
            ("orb_ultra",      self.orb_ultra),
            ("triple_squeeze", self.triple_squeeze),
            ("condor_0dte",    self.condor_0dte),
            ("macro_trend",    self.macro_trend),
        ]
        results = []
        for key, fn in strategies:
            try:
                sig = fn()
                sig["strategy_key"] = key
                results.append(sig)
                icon = "✅" if sig["is_tradeable"] else "⏸"
                log.info(f"  {icon} {sig['strategy']}: {sig['direction']} | {sig['confidence']}")
            except Exception as e:
                log.error(f"  ❌ {key} error: {e}")
        return results
