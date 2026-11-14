"""Bridges to hummingbot, freqtrade, vnpy and Lean. Paper/shadow/backtest only."""
import importlib.util
import json
import os
import shutil
import sys

# role -> what APEX takes from the framework (see CAPABILITIES for the long form)
CAPABILITIES = {
    'hummingbot': {'module': 'hummingbot', 'role': 'live market data, fees and trading rules for ~30 venues; paper-trade connectors; arbitrage/XEMM executors as design reference'},
    'freqtrade': {'module': 'freqtrade', 'role': 'candle backtesting, hyperopt, FreqAI walk-forward ML; dry-run strategy consuming APEX verdicts'},
    'vnpy': {'module': 'vnpy', 'role': 'event engine, gateway ticks (5-level depth), alpha research lab'},
    'lean': {'module': None, 'needs': 'dotnet', 'role': 'independent event-driven backtest of APEX signals with its own fill/portfolio models'},
}


def status():
    out = {}
    for name, c in CAPABILITIES.items():
        if c['module']:
            ok = importlib.util.find_spec(c['module']) is not None
        else:
            ok = shutil.which(c['needs']) is not None
        out[name] = {'available': ok, 'role': c['role']}
    return out


if __name__ == '__main__':
    json.dump(status(), sys.stdout, indent=2)
    print()
