"""Market data fetcher — yfinance wrapper"""
import yfinance as yf
import pandas as pd
import numpy as np
import logging
from config import CONFIG

log = logging.getLogger("DataFetcher")


class DataFetcher:

    TIMEFRAMES = {
        "5m":  "2d",
        "15m": "5d",
        "1h":  "30d",
        "4h":  "60d",
        "1d":  "730d",
    }

    @staticmethod
    def ohlcv(symbol: str, interval: str = "15m", period: str = "5d") -> pd.DataFrame:
        try:
            df = yf.download(
    symbol,
    period=period,
    interval=interval,
    auto_adjust=True,
    progress=False,
    threads=False,
)
            if df.empty:
                return pd.DataFrame()
            df.columns = [c.lower() for c in df.columns]
            return df[["open","high","low","close","volume"]].dropna()
        except Exception as e:
            log.error(f"Fetch error {symbol}@{interval}: {e}")
            return pd.DataFrame()

    @classmethod
    def multi_tf(cls, symbol: str) -> dict:
        return {
            tf: cls.ohlcv(symbol, tf, period)
            for tf, period in cls.TIMEFRAMES.items()
            if not (df := cls.ohlcv(symbol, tf, period)).empty
            or True
        }

    @staticmethod
    def spot(symbol: str) -> float:
        try:
            df = yf.download(
                symbol,
                period="5d",
                auto_adjust=True,
                progress=False,
                threads=False,
            )

            if df.empty:
                return 0.0

            return round(float(df["Close"].iloc[-1]), 2)

        except Exception as e:
            log.error(f"Spot fetch error {symbol}: {e}")
            return 0.0

    @staticmethod
    def all_data() -> dict:
        sym    = CONFIG["trading"]["nifty_symbol"]
        vix_s  = CONFIG["trading"]["vix_symbol"]
        spot   = DataFetcher.spot(sym)
        vix    = DataFetcher.spot(vix_s)
        tfs    = {}
        for tf, period in DataFetcher.TIMEFRAMES.items():
            df = DataFetcher.ohlcv(sym, tf, period)
            if not df.empty:
                tfs[tf] = df
        return {"spot": spot, "vix": vix, "data": tfs, "symbol": sym}
