import sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parent.parent
for _pkg in ("smc_engine", "smc_bot_core", "smc_bot_webhook", "smc_bot_backtest", "smc_bot_dashboard"):
    _src = _ROOT / "packages" / _pkg / "src"
    if _src.exists() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

