"""Run smc_engine on OHLC and emit chart-qualified AlertPayload rows."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from smc_bot_signal.config import SignalBotConfig
from smc_bot_webhook.payload import AlertPayload

logger = logging.getLogger("smc_bot_signal.engine")


def _as_utc_ts(value: object) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


@dataclass
class SignalEngine:
    cfg: SignalBotConfig

    def scan(
        self, df: pd.DataFrame, symbol: str, *, timeframe: str | None = None
    ) -> list[AlertPayload]:
        """Detect first-touch OB signals on the latest closed bar."""
        if df is None or df.empty or len(df) < 30:
            return []
        tf = (timeframe or self.cfg.timeframe or "M15").upper()
        if tf in ("15", "M15"):
            tf = "M15"

        try:
            from smc_engine.displacement import calculate_atr
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
            try:
                obs = detect_order_blocks(df, swings, structure, atr=atr)
            except TypeError:
                obs = detect_order_blocks(df, swings, structure)
        except Exception:
            logger.exception("engine pipeline failed symbol=%s", symbol)
            return []

        last_ts = _as_utc_ts(df.index[-1])
        close = float(df["close"].iloc[-1])
        atr_last = atr.iloc[-1]
        if pd.isna(atr_last) or float(atr_last) <= 0:
            return []
        atr_v = float(atr_last)

        out: list[AlertPayload] = []
        for ob in obs.events:
            if not ob.is_first_test_at(last_ts):
                continue
            ft = ob.first_touch_timestamp
            if ft is None:
                continue
            ft_ts = _as_utc_ts(ft)
            # Second resolution — engine/index may differ in ns.
            if int(ft_ts.timestamp()) != int(last_ts.timestamp()):
                continue

            try:
                payload = self._ob_to_payload(
                    ob,
                    symbol=symbol.upper(),
                    tf=tf,
                    last_ts=last_ts,
                    close=close,
                    atr_v=atr_v,
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
        if abs(close - entry) > self.cfg.entry_proximity_atr * atr_v:
            return None

        sign = 1.0 if is_long else -1.0
        tp1 = entry + sign * self.cfg.tp1_r * risk
        tp2 = entry + sign * self.cfg.tp2_r * risk
        tp3 = entry + sign * self.cfg.tp3_r * risk

        bar_time = int(last_ts.timestamp())
        ob_id = int(getattr(ob, "id", -1))
        bos_id = int(getattr(ob, "structure_event_id", -1))
        level = float(getattr(ob, "price", entry))
        side = "long" if is_long else "short"

        return AlertPayload(
            prefix="SMC",
            version="v1",
            event="chart_qualified",
            symbol=symbol,
            tf=tf,
            dir=side,
            level=level,
            bar_time=bar_time,
            ob_id=ob_id,
            bos_id=bos_id,
            state="chart-qualified",
            reason="ob_first_touch",
            entry=float(entry),
            sl=float(sl),
            tp1=float(tp1),
            tp2=float(tp2),
            tp3=float(tp3),
            score=None,
            raw_payload="smc_bot_signal",
        )
