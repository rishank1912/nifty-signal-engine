"""Technical indicators — pure pandas/numpy, no ta-lib dependency"""
import pandas as pd
import numpy as np


class Indicators:

    @staticmethod
    def compute(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or len(df) < 30:
            return df
        c, h, l, v = df["close"], df["high"], df["low"], df.get("volume", pd.Series(1, index=df.index))

        # EMAs
        for span in [9, 21, 55, 200]:
            df[f"ema{span}"] = c.ewm(span=span, adjust=False).mean()
        df["sma20"] = c.rolling(20).mean()

        # RSI-14
        delta = c.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        df["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))

        # MACD
        e12 = c.ewm(span=12, adjust=False).mean()
        e26 = c.ewm(span=26, adjust=False).mean()
        df["macd"]   = e12 - e26
        df["macdsig"]= df["macd"].ewm(span=9, adjust=False).mean()
        df["macdhist"]= df["macd"] - df["macdsig"]

        # Bollinger Bands
        std = c.rolling(20).std()
        df["bb_upper"] = df["sma20"] + 2*std
        df["bb_lower"] = df["sma20"] - 2*std
        df["bb_width"] = df["bb_upper"] - df["bb_lower"]

        # ATR-14
        hl  = h - l
        hc  = (h - c.shift()).abs()
        lc  = (l - c.shift()).abs()
        tr  = pd.concat([hl,hc,lc], axis=1).max(axis=1)
        df["atr"] = tr.rolling(14).mean()

        # ADX / +DI / -DI
        pdm = h.diff().clip(lower=0)
        ndm = (-l.diff()).clip(lower=0)
        atr14 = tr.rolling(14).mean()
        df["pdi"] = 100 * pdm.rolling(14).mean() / atr14.replace(0, np.nan)
        df["mdi"] = 100 * ndm.rolling(14).mean() / atr14.replace(0, np.nan)
        dx = 100 * (df["pdi"] - df["mdi"]).abs() / (df["pdi"] + df["mdi"]).replace(0, np.nan)
        df["adx"] = dx.rolling(14).mean()

        # Supertrend (multiplier=3)
        mid = (h + l) / 2
        df["st_upper"] = mid + 3 * df["atr"]
        df["st_lower"] = mid - 3 * df["atr"]
        df["st_bull"]  = c > df["st_lower"]

        # Stochastic
        lo14 = l.rolling(14).min()
        hi14 = h.rolling(14).max()
        df["stoch_k"] = 100 * (c - lo14) / (hi14 - lo14).replace(0, np.nan)
        df["stoch_d"] = df["stoch_k"].rolling(3).mean()

        # Keltner Channel (for squeeze)
        kc_upper = df["sma20"] + 1.5 * df["atr"]
        kc_lower = df["sma20"] - 1.5 * df["atr"]
        df["in_squeeze"] = (df["bb_upper"] < kc_upper) & (df["bb_lower"] > kc_lower)

        # Squeeze momentum histogram
        df["sq_hist"] = c - c.rolling(20).mean()

        # VWAP
        df["vwap"] = (c * v).cumsum() / v.replace(0, np.nan).cumsum()

        return df

    @staticmethod
    def latest(df: pd.DataFrame) -> dict:
        if df.empty or len(df) < 2:
            return {}
        return {
            k: (round(float(v), 4) if isinstance(v, (float, np.floating)) else bool(v))
            for k, v in df.iloc[-1].items()
            if not (isinstance(v, float) and np.isnan(v))
        }

    @staticmethod
    def prev(df: pd.DataFrame, n: int = 1) -> dict:
        if df.empty or len(df) < n + 1:
            return {}
        return {
            k: (round(float(v), 4) if isinstance(v, (float, np.floating)) else bool(v))
            for k, v in df.iloc[-(n+1)].items()
            if not (isinstance(v, float) and np.isnan(v))
        }
