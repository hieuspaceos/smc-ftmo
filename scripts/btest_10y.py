"""Standalone 10y backtest — no Streamlit deps."""
import os, sys, time
from pathlib import Path
os.chdir('/Users/hieuspace/Desktop/CODE/smc-ftmo')
sys.path.insert(0, '/Users/hieuspace/Desktop/CODE/smc-ftmo/src')

import pandas as pd
from collections import Counter
from src.backtester import run_backtest

CFG_PATH = Path('/Users/hieuspace/Desktop/CODE/smc-ftmo/config.yaml')

def run(label, cfg):
    t0 = time.perf_counter()
    trades, _ = run_backtest('EURUSD', cfg)
    print(f'{label:36s}  t={time.perf_counter()-t0:>3.0f}s  n={len(trades)}')
    if trades:
        m = {}
        for t in trades:
            y = pd.Timestamp(t['timestamp_entry']).year
            m[y] = m.get(y, 0) + 1
        for y in sorted(m.keys()):
            print(f'    {y}: {m[y]}')

# Base FTMO defaults from yaml
import yaml
with CFG_PATH.open() as f:
    base = yaml.safe_load(f)
base['start_date'] = '2016-01-01'
base['end_date'] = '2026-08-21'
base['tf_m15'] = True
base['tf_h1'] = True
base['tf_h4'] = False
base['tf_d'] = False

# Default FTMO (min_conf=4, filters on)
run('FTMO defaults (min_conf=4)', dict(base))

# All filters off (min_conf=1)
loose = dict(base)
loose['min_confluence_score'] = 1
loose['use_clean_sweep_filter'] = False
loose['use_displacement_filter'] = False
loose['use_pd_zone_filter'] = False
loose['use_session_window'] = False
run('All filters off', loose)
