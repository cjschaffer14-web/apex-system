"""Re-tests one lab strategy in Freqtrade. Rules match the lab: long or flat, decided at the close, filled at the next open."""
import json
import os

import numpy as np
from freqtrade.strategy import IStrategy
from pandas import DataFrame

SPEC = json.loads(os.environ.get("APEX_SPEC", '{"family":"rsi_revert","params":{"period":14,"buy_below":25,"sell_above":55}}'))


def wilder_rsi(close, n):
    """Same recursion as the lab: simple mean for the first n moves, then Wilder smoothing."""
    d = close.diff().fillna(0.0).to_numpy()
    gain, loss, out = 0.0, 0.0, np.full(len(d), np.nan)
    for i in range(1, len(d)):
        g, l = max(d[i], 0.0), max(-d[i], 0.0)
        if i <= n:
            gain += g / n
            loss += l / n
        else:
            gain = (gain * (n - 1) + g) / n
            loss = (loss * (n - 1) + l) / n
        if i >= n:
            out[i] = 100.0 if loss == 0 else 100.0 - 100.0 / (1.0 + gain / loss)
    return out


class ApexCheck(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1h"
    can_short = False
    minimal_roi = {"0": 100.0}
    stoploss = -0.99
    use_exit_signal = True
    exit_profit_only = False
    process_only_new_candles = True
    startup_candle_count = 400

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        p = SPEC["params"]
        if SPEC["family"] == "rsi_revert":
            dataframe["rsi"] = wilder_rsi(dataframe["close"], p["period"])
        elif SPEC["family"] == "boll_revert":
            dataframe["ma"] = dataframe["close"].rolling(p["period"]).mean()
            dataframe["sd"] = dataframe["close"].rolling(p["period"]).std(ddof=0)
        else:
            raise ValueError("family not ported: " + SPEC["family"])
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        p = SPEC["params"]
        if SPEC["family"] == "rsi_revert":
            dataframe.loc[dataframe["rsi"] < p["buy_below"], "enter_long"] = 1
        else:
            dataframe.loc[dataframe["close"] < dataframe["ma"] - p["k"] * dataframe["sd"], "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        p = SPEC["params"]
        if SPEC["family"] == "rsi_revert":
            dataframe.loc[dataframe["rsi"] > p["sell_above"], "exit_long"] = 1
        else:
            dataframe.loc[dataframe["close"] >= dataframe["ma"], "exit_long"] = 1
        return dataframe
