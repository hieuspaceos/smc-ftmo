"""Env-based config for the cTrader signal bot."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    val = os.environ.get(name)
    return val if val not in (None, "") else default


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    return val.lower() in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class SignalBotConfig:
    """Runtime settings for the Mac mini cTrader signal bot."""

    ctrader_client_id: str = ""
    ctrader_client_secret: str = ""
    ctrader_access_token: str = ""
    ctrader_refresh_token: str = ""
    ctrader_account_id: int = 0
    ctrader_host: str = "demo.ctraderapi.com"
    ctrader_port: int = 5035

    symbols: tuple[str, ...] = ("EURUSD",)
    timeframe: str = "M15"
    history_bars: int = 500
    feed_mode: str = "auto"  # auto | csv | memory | ctrader
    csv_path: str = ""

    poll_interval_seconds: int = 60
    dry_run: bool = False

    # M15 swings (left/right). swing_length=10 → 5/5 matches config.yaml.
    swing_left: int = 5
    swing_right: int = 5
    htf_swing_length: int = 10

    # Rule-book / config.yaml aligned
    displacement_atr_mult: float = 1.2
    min_confluence_score: int = 3
    require_displacement: bool = True
    require_bias_aligned: bool = True
    bias_mode: str = "h4_only"  # strict | h4_only | any
    sl_atr_buffer: float = 0.2
    min_sl_atr: float = 0.3
    max_sl_atr: float = 5.0
    # EURUSD live floor 17 pips (manual lag + spread) — do not lower lightly
    min_sl_pips: float = 17.0
    entry_proximity_atr: float = 2.0
    tp1_r: float = 2.0
    tp2_r: float = 3.0
    tp3_r: float = 4.0

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    state_db_path: Path = Path("output/signal_state.db")
    dedup_window_minutes: int = 360

    @classmethod
    def from_env(cls, *, require_ctrader: bool = False) -> "SignalBotConfig":
        symbols_raw = _env("SMC_SIGNAL_SYMBOLS", "EURUSD")
        symbols = tuple(
            s.strip().upper() for s in symbols_raw.split(",") if s.strip()
        ) or ("EURUSD",)

        account_raw = _env("CTRADER_ACCOUNT_ID", "0")
        try:
            account_id = int(account_raw)
        except ValueError:
            account_id = 0

        cfg = cls(
            ctrader_client_id=_env("CTRADER_CLIENT_ID"),
            ctrader_client_secret=_env("CTRADER_CLIENT_SECRET"),
            ctrader_access_token=_env("CTRADER_ACCESS_TOKEN"),
            ctrader_refresh_token=_env("CTRADER_REFRESH_TOKEN"),
            ctrader_account_id=account_id,
            ctrader_host=_env("CTRADER_HOST", "demo.ctraderapi.com"),
            ctrader_port=_env_int("CTRADER_PORT", 5035),
            symbols=symbols,
            timeframe=_env("SMC_SIGNAL_TF", "M15").upper(),
            history_bars=_env_int("SMC_SIGNAL_HISTORY_BARS", 500),
            feed_mode=_env("SMC_SIGNAL_FEED_MODE", "auto").lower(),
            csv_path=_env("SMC_SIGNAL_CSV_PATH"),
            poll_interval_seconds=_env_int("SMC_SIGNAL_POLL_SECONDS", 60),
            dry_run=_env_bool("SMC_SIGNAL_DRY_RUN", False),
            swing_left=_env_int("SMC_SIGNAL_SWING_LEFT", 5),
            swing_right=_env_int("SMC_SIGNAL_SWING_RIGHT", 5),
            htf_swing_length=_env_int("SMC_SIGNAL_HTF_SWING_LENGTH", 10),
            displacement_atr_mult=_env_float("SMC_SIGNAL_DISP_ATR_MULT", 1.2),
            min_confluence_score=_env_int("SMC_SIGNAL_MIN_SCORE", 3),
            require_displacement=_env_bool("SMC_SIGNAL_REQUIRE_DISP", True),
            require_bias_aligned=_env_bool("SMC_SIGNAL_REQUIRE_BIAS", True),
            bias_mode=_env("SMC_SIGNAL_BIAS_MODE", "h4_only").lower(),
            sl_atr_buffer=_env_float("SMC_SIGNAL_SL_ATR_BUFFER", 0.2),
            min_sl_atr=_env_float("SMC_SIGNAL_MIN_SL_ATR", 0.3),
            max_sl_atr=_env_float("SMC_SIGNAL_MAX_SL_ATR", 5.0),
            min_sl_pips=_env_float("SMC_SIGNAL_MIN_SL_PIPS", 17.0),
            entry_proximity_atr=_env_float("SMC_SIGNAL_ENTRY_PROX_ATR", 2.0),
            tp1_r=_env_float("SMC_SIGNAL_TP1_R", 2.0),
            tp2_r=_env_float("SMC_SIGNAL_TP2_R", 3.0),
            tp3_r=_env_float("SMC_SIGNAL_TP3_R", 4.0),
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
            state_db_path=Path(
                _env("SMC_SIGNAL_DB_PATH", "output/signal_state.db")
            ),
            dedup_window_minutes=_env_int("SMC_SIGNAL_DEDUP_MINUTES", 360),
        )
        if require_ctrader:
            missing = [
                name
                for name, val in (
                    ("CTRADER_CLIENT_ID", cfg.ctrader_client_id),
                    ("CTRADER_CLIENT_SECRET", cfg.ctrader_client_secret),
                    ("CTRADER_ACCESS_TOKEN", cfg.ctrader_access_token),
                    ("CTRADER_ACCOUNT_ID", str(cfg.ctrader_account_id or "")),
                )
                if not val or val == "0"
            ]
            if missing:
                raise RuntimeError(
                    "Missing required cTrader env vars: " + ", ".join(missing)
                )
        return cfg
