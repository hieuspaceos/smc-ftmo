"""Workspace pytest configuration.

Adds each package's src/ directory to sys.path so `pytest` discovers
modules without requiring `pip install -e` of every package.

Also maps old `bot.*` imports to their new package locations for the
back-compat shim (bot/__init__.py re-exports).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGES = ROOT / "packages"

# Add each package's src/ to sys.path (in dependency order so imports
# resolve in the right sequence).
for pkg in [
    "smc_engine",
    "smc_bot_core",
    "smc_bot_webhook",
    "smc_bot_backtest",
    "smc_bot_dashboard",
]:
    src = PACKAGES / pkg / "src"
    if src.exists() and str(src) not in sys.path:
        sys.path.insert(0, str(src))

# Make `bot.*` shim work (bot/__init__.py re-exports new packages).
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
