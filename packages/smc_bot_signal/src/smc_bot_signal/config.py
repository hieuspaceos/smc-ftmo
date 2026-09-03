"""Env-based config for the cTrader signal bot."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
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
    history_bars: int = 5000
    # Default 5000 M15 bars ≈ 52 days. We need ≥30 daily bars for the Daily
    # bias detector (_detect_tf_bias uses max(30, swing_length*2) warm-up),
    # so 5000 M15 bars ≈ 35 daily bars is enough. Bump further per-symbol if
    # you trade H1/H4 setups that need longer lookback.
    feed_mode: str = "auto"  # auto | csv | memory | ctrader
    csv_path: str = ""

    poll_interval_seconds: int = 60
    dry_run: bool = False

    # M15 swings (left/right). swing_length=20 → 10/10 mirrors src/smc_engine
    # baseline (swing_length=10 in scripts/btest_*.py). Smaller windows (5/5)
    # produce sub-17pip OBs on EURUSD M15 that the SL floor filters out.
    swing_left: int = 10
    swing_right: int = 10
    htf_swing_length: int = 10

    # Rule-book / config.yaml aligned.
    # L6_TIGHT defaults (2026-09-03 walk-forward OOS, 4 windows EUR + 4 XAU,
    # 8.7 years, costs applied):
    #   EUR  : mean PF 4.11, mean MaxDD -1.52%, mean WR 42.4%, 21.5 trades/window
    #   XAU  : mean PF 5.51, mean MaxDD -1.49%, mean WR 43.7%, 78.7 trades/window
    #   Stress (spread 2x, slip std 3x): PF 4.02 / 5.44 (-1-2% only, edge robust).
    # Earlier L6_LOOSE defaults (score=2, no bias required, prox=8) inflated PF
    # to 15-30 on the same OOS windows — that edge was a gate artifact, not a
    # real signal. L6_TIGHT drops the score floor and forces D+H4 alignment so
    # only displaced, bias-aligned, in-PD first-test setups reach the webhook.
    # Env vars still override per-deploy.
    #
    # Account size: FTMO Challenge $25,000 phase. risk_pct=0.0055 -> $137.50/trade.
    # With XAU SL floor 400 pip ($4/oz / $400/lot), 1 lot = $400 risk would blow
    # the per-trade budget 3x — lot sizing will auto-cap at 0.34 lot. The engine
    # itself is symbol-agnostic; sizing is handled in signal_engine._ob_to_payload.
    account_size: float = 25_000.0
    risk_pct: float = 0.0055  # 0.55% per trade -> $137.50 on $25k
    displacement_atr_mult: float = 1.5
    min_confluence_score: int = 4
    require_displacement: bool = True
    require_bias_aligned: bool = True
    bias_mode: str = "d1_with_h4_filter"  # D1 primary; H4 only blocks when counter-trend
    sl_atr_buffer: float = 0.4
    min_sl_atr: float = 0.5
    max_sl_atr: float = 6.0
    # Per-symbol absolute SL floor (pips, native convention):
    #   EURUSD: 1 pip = 0.0001 -> 17 pip floor = $170/lot risk on 1.0 ATR EURUSD M15.
    #   XAUUSD: 1 pip = 0.01   -> 400 pip floor = $4/oz = $400/lot risk on M15.
    #   BTCUSD: 1 pip = 1.0    -> 50 pip floor = $50/lot (placeholder, verify broker).
    # Engine reads min_sl_pips_map[symbol] in _ob_to_payload and falls back to
    # the first value for unknown symbols.
    min_sl_pips_map: dict[str, float] = field(default_factory=lambda: {"EURUSD": 17.0, "XAUUSD": 400.0, "BTCUSD": 50.0})
    entry_proximity_atr: float = 3.0
    # Rolling scan lookback for first-touch OBs. Default 100 M15 bars = ~25h.
    # scan() emits a signal if an OB first-touched within this window. Avoid
    # making it too wide — stale first-touches past a few sessions have lost
    # their edge. Dedup state in state.py + Telegram rate limit the burst to
    # one signal per OB.
    scan_lookback_bars: int = 100
    # Design A scale-in ONLY (no ladder). Matches ScaleInExit in src/scale_in_exit.py
    # and scripts/btest_signal_engine_full.py: scale_in_r=2.0, final_tp_r=4.0.
    scale_in_r: float = 2.0
    leg2_lot_size: float = 0.5
    final_tp_r: float = 4.0
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
            history_bars=_env_int("SMC_SIGNAL_HISTORY_BARS", 5000),
            feed_mode=_env("SMC_SIGNAL_FEED_MODE", "auto").lower(),
            csv_path=_env("SMC_SIGNAL_CSV_PATH"),
            poll_interval_seconds=_env_int("SMC_SIGNAL_POLL_SECONDS", 60),
            dry_run=_env_bool("SMC_SIGNAL_DRY_RUN", False),
            swing_left=_env_int("SMC_SIGNAL_SWING_LEFT", 10),
            swing_right=_env_int("SMC_SIGNAL_SWING_RIGHT", 10),
            htf_swing_length=_env_int("SMC_SIGNAL_HTF_SWING_LENGTH", 10),
            displacement_atr_mult=_env_float("SMC_SIGNAL_DISP_ATR_MULT", 1.0),
            min_confluence_score=_env_int("SMC_SIGNAL_MIN_SCORE", 2),
            require_displacement=_env_bool("SMC_SIGNAL_REQUIRE_DISP", True),
            require_bias_aligned=_env_bool("SMC_SIGNAL_REQUIRE_BIAS", False),
            bias_mode=_env("SMC_SIGNAL_BIAS_MODE", "any").lower(),
            sl_atr_buffer=_env_float("SMC_SIGNAL_SL_ATR_BUFFER", 0.6),
            min_sl_atr=_env_float("SMC_SIGNAL_MIN_SL_ATR", 0.3),
            max_sl_atr=_env_float("SMC_SIGNAL_MAX_SL_ATR", 12.0),
            min_sl_pips=_env_float("SMC_SIGNAL_MIN_SL_PIPS", 17.0),
            entry_proximity_atr=_env_float("SMC_SIGNAL_ENTRY_PROX_ATR", 3.0),
            scan_lookback_bars=_env_int("SMC_SIGNAL_SCAN_LOOKBACK_BARS", 100),
            scale_in_r=_env_float("SMC_SIGNAL_SCALE_IN_R", 2.0),
            final_tp_r=_env_float("SMC_SIGNAL_FINAL_TP_R", 4.0),
            leg2_lot_size=_env_float("SMC_SIGNAL_LEG2_LOT", 0.5),
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
            state_db_path=Path(_env("SMC_SIGNAL_DB_PATH", "output/signal_state.db")),
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
