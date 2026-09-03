"""Run smc_engine + rule-book gates; emit chart-qualified only when entry_allowed.

Critical: ``detect_order_blocks(df, structure, expansion)`` — never swings as arg2.
Fail-closed without displacement + D/H4 bias alignment + score >= min.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from smc_bot_signal.config import SignalBotConfig
from smc_bot_signal.rulebook_gate import score_setup
from smc_bot_webhook.payload import AlertPayload

logger = logging.getLogger("smc_bot_signal.engine")


def _as_utc_ts(value: object) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _ohlc_resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df.empty:
        return df
    return (
        df.resample(rule, label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
        .dropna(how="any")
    )


def _detect_tf_bias(df: pd.DataFrame, *, swing_length: int) -> str | None:
    if df is None or len(df) < max(30, swing_length * 2):
        return None
    try:
        from smc_engine.context import compute_bias_series
        from smc_engine.structure import detect_structure
        from smc_engine.swings import detect_swings

        left = right = max(2, swing_length // 2)
        swings = detect_swings(df, left=left, right=right)
        if not swings.events:
            return None
        structure = detect_structure(df, swings)
        last = compute_bias_series(structure).iloc[-1]
        if last == "bull":
            return "bull"
        if last == "bear":
            return "bear"
    except Exception:
        logger.exception("bias detect failed")
    return None


def _pd_zone_for_side(
    df: pd.DataFrame, structure: object, *, side: str
) -> tuple[bool, str]:
    try:
        from smc_engine.context import (
            compute_dealing_range_context,
            context_snapshot,
            is_in_pd_zone,
        )

        ctx = compute_dealing_range_context(df, structure)  # type: ignore[arg-type]
        zone = str(context_snapshot(ctx).get("zone", "neutral"))
        return bool(is_in_pd_zone(zone, side)), zone
    except Exception:
        return False, "neutral"


@dataclass
class SignalEngine:
    cfg: SignalBotConfig

    def scan(
        self, df: pd.DataFrame, symbol: str, *, timeframe: str | None = None
    ) -> list[AlertPayload]:
        if df is None or df.empty or len(df) < 80:
            return []
        tf = (timeframe or self.cfg.timeframe or "M15").upper()
        if tf in ("15", "M15"):
            tf = "M15"

        try:
            from smc_engine.displacement import calculate_atr, detect_range_expansion
            from smc_engine.order_blocks import detect_order_blocks
            from smc_engine.structure import detect_structure
            from smc_engine.swings import detect_swings
        except ImportError:
            logger.exception("smc_engine import failed")
            return []

        try:
            swings = detect_swings(
                df, left=self.cfg.swing_left, right=self.cfg.swing_right
            )
            atr = calculate_atr(df)
            try:
                structure = detect_structure(df, swings, atr=atr)
            except TypeError:
                structure = detect_structure(df, swings)
            expansion = detect_range_expansion(
                df, atr, multiplier=self.cfg.displacement_atr_mult
            )
            # CORRECT: (df, structure, expansion)
            obs = detect_order_blocks(df, structure, expansion)
        except Exception:
            logger.exception("engine pipeline failed symbol=%s", symbol)
            return []

        last_ts = _as_utc_ts(df.index[-1])
        close = float(df["close"].iloc[-1])
        atr_last = atr.iloc[-1]
        if pd.isna(atr_last) or float(atr_last) <= 0:
            return []
        atr_v = float(atr_last)

        try:
            disp_last = bool(expansion.qualified.iloc[-1])
        except Exception:
            disp_last = False

        bias_d = _detect_tf_bias(
            _ohlc_resample(df, "1D"), swing_length=self.cfg.htf_swing_length
        )
        bias_h4 = _detect_tf_bias(
            _ohlc_resample(df, "4h"), swing_length=self.cfg.htf_swing_length
        )
        if bias_d == "bull" and bias_h4 == "bull":
            bias_side: str | None = "long"
        elif bias_d == "bear" and bias_h4 == "bear":
            bias_side = "short"
        else:
            bias_side = None
            if self.cfg.require_bias_aligned:
                logger.info(
                    "stand_aside bias D=%s H4=%s symbol=%s — no emit",
                    bias_d,
                    bias_h4,
                    symbol,
                )

        out: list[AlertPayload] = []
        for ob in obs.events:
            if not ob.is_first_test_at(last_ts):
                continue
            ft = ob.first_touch_timestamp
            if ft is None:
                continue
            if int(_as_utc_ts(ft).timestamp()) != int(last_ts.timestamp()):
                continue

            side = "long" if ob.direction == "bullish" else "short"
            if ob.direction not in ("bullish", "bearish"):
                continue

            displacement = disp_last
            if not displacement:
                try:
                    act_pos = int(ob.activation_pos)
                    if 0 <= act_pos < len(expansion.qualified):
                        displacement = bool(expansion.qualified.iloc[act_pos])
                        if act_pos > 0:
                            displacement = displacement or bool(
                                expansion.qualified.iloc[act_pos - 1]
                            )
                except Exception:
                    displacement = False

            bias_aligned = bias_side == side
            if self.cfg.require_bias_aligned and not bias_aligned:
                continue
            if self.cfg.require_displacement and not displacement:
                continue

            in_pd, pd_zone = _pd_zone_for_side(df, structure, side=side)
            score, reasons, entry_allowed = score_setup(
                {
                    "displacement": displacement,
                    "bias_aligned": bias_aligned,
                    "sweep_clean": False,
                    "in_pd_zone": in_pd,
                    "first_test": True,
                    "pd_zone": pd_zone,
                },
                min_score=self.cfg.min_confluence_score,
            )
            if not entry_allowed:
                logger.info(
                    "gate block symbol=%s side=%s score=%s reasons=%s",
                    symbol,
                    side,
                    score,
                    reasons,
                )
                continue

            try:
                payload = self._ob_to_payload(
                    ob,
                    symbol=symbol.upper(),
                    tf=tf,
                    last_ts=last_ts,
                    close=close,
                    atr_v=atr_v,
                    score=float(score),
                    reason=";".join(reasons)[:200] or "rulebook_ok",
                )
            except Exception:
                logger.exception(
                    "payload build failed symbol=%s ob_id=%s",
                    symbol,
                    getattr(ob, "id", None),
                )
                continue
            if payload is not None:
                out.append(payload)
        return out

    def _ob_to_payload(
        self,
        ob: object,
        *,
        symbol: str,
        tf: str,
        last_ts: pd.Timestamp,
        close: float,
        atr_v: float,
        score: float | None = None,
        reason: str = "ob_first_touch",
    ) -> AlertPayload | None:
        direction = getattr(ob, "direction", "")
        is_long = direction == "bullish"
        is_short = direction == "bearish"
        if not is_long and not is_short:
            return None

        top = float(getattr(ob, "top"))
        bottom = float(getattr(ob, "bottom"))
        entry = top if is_long else bottom
        buf = self.cfg.sl_atr_buffer * atr_v
        sl = (bottom - buf) if is_long else (top + buf)
        risk = abs(entry - sl)
        if risk <= 0:
            return None

        sl_atr = risk / atr_v
        if sl_atr < self.cfg.min_sl_atr or sl_atr > self.cfg.max_sl_atr:
            return None
        # Absolute pip floor (EURUSD live: >= 10 pips)
        pip_size = 0.01 if symbol.upper().startswith("XAU") else 0.0001
        if symbol.upper().startswith("BTC"):
            pip_size = 1.0
        if self.cfg.min_sl_pips > 0 and (risk / pip_size) < self.cfg.min_sl_pips:
            return None
        if abs(close - entry) > self.cfg.entry_proximity_atr * atr_v:
            return None

        sign = 1.0 if is_long else -1.0
        tp1 = entry + sign * self.cfg.tp1_r * risk
        tp2 = entry + sign * self.cfg.tp2_r * risk
        tp3 = entry + sign * self.cfg.tp3_r * risk

        return AlertPayload(
            prefix="SMC",
            version="v1",
            event="chart_qualified",
            symbol=symbol,
            tf=tf,
            dir="long" if is_long else "short",
            level=float(getattr(ob, "price", entry)),
            bar_time=int(last_ts.timestamp()),
            ob_id=int(getattr(ob, "id", -1)),
            bos_id=int(getattr(ob, "structure_event_id", -1)),
            state="chart-qualified",
            reason=reason,
            entry=float(entry),
            sl=float(sl),
            tp1=float(tp1),
            tp2=float(tp2),
            tp3=float(tp3),
            score=score,
            raw_payload="smc_bot_signal",
        )
