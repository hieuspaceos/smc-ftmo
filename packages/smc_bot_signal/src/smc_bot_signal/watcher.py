"""Poll loop: feed → engine → dedup → notify."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from smc_bot_signal.config import SignalBotConfig
from smc_bot_signal.data_feed import MarketDataFeed, feed_from_config
from smc_bot_signal.notify import SignalNotifier, notifier_from_config
from smc_bot_signal.signal_engine import SignalEngine
from smc_bot_signal.state import SignalStateStore

logger = logging.getLogger("smc_bot_signal.watcher")


@dataclass
class Watcher:
    cfg: SignalBotConfig
    feed: MarketDataFeed
    engine: SignalEngine
    state: SignalStateStore
    notifier: SignalNotifier
    last_seen: dict[str, Any] = field(default_factory=dict)

    def run_once(self) -> list[str]:
        """Process all symbols once. Returns list of sent signal_ids."""
        sent_ids: list[str] = []
        for symbol in self.cfg.symbols:
            try:
                ids = self._tick_symbol(symbol)
                sent_ids.extend(ids)
            except Exception:
                logger.exception("tick failed symbol=%s", symbol)
        return sent_ids

    def _tick_symbol(self, symbol: str) -> list[str]:
        df = self.feed.get_ohlc(
            symbol,
            timeframe=self.cfg.timeframe,
            bars=self.cfg.history_bars,
        )
        if df is None or df.empty:
            logger.debug("no data symbol=%s", symbol)
            return []

        last_ts = df.index[-1]
        prev = self.last_seen.get(symbol)
        if prev is not None and prev == last_ts:
            return []
        self.last_seen[symbol] = last_ts

        payloads = self.engine.scan(df, symbol, timeframe=self.cfg.timeframe)
        sent: list[str] = []
        for payload in payloads:
            if not self.state.should_notify(payload.signal_id):
                logger.info("dedup skip signal_id=%s", payload.signal_id)
                continue
            try:
                msg_id = self.notifier.send(payload, m15_data=df)
            except Exception:
                logger.exception(
                    "notify failed signal_id=%s; will retry later",
                    payload.signal_id,
                )
                continue
            if msg_id is None:
                logger.warning(
                    "notify returned no message_id signal_id=%s; not recording dedup",
                    payload.signal_id,
                )
                continue
            self.state.record_alert(
                payload.signal_id,
                symbol=payload.symbol,
                bar_time=payload.bar_time,
            )
            sent.append(payload.signal_id)
            logger.info(
                "notified signal_id=%s msg_id=%s symbol=%s dir=%s",
                payload.signal_id,
                msg_id,
                payload.symbol,
                payload.dir,
            )
        return sent

    def run_forever(self) -> None:
        logger.info(
            "watcher start symbols=%s tf=%s poll=%ss dry_run=%s",
            self.cfg.symbols,
            self.cfg.timeframe,
            self.cfg.poll_interval_seconds,
            self.cfg.dry_run,
        )
        while True:
            self.run_once()
            time.sleep(max(1, int(self.cfg.poll_interval_seconds)))


def build_watcher(
    cfg: SignalBotConfig | None = None,
    *,
    feed: MarketDataFeed | None = None,
    notifier: SignalNotifier | None = None,
    frames: dict[str, pd.DataFrame] | None = None,
) -> Watcher:
    cfg = cfg or SignalBotConfig.from_env()
    return Watcher(
        cfg=cfg,
        feed=feed or feed_from_config(cfg, frames=frames),
        engine=SignalEngine(cfg),
        state=SignalStateStore(cfg.state_db_path, cfg.dedup_window_minutes),
        notifier=notifier or notifier_from_config(cfg),
    )


def main(argv: list[str] | None = None) -> int:
    _ = argv
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_dotenv()
    # Also allow secrets outside repo
    load_dotenv(dotenv_path=Path.home() / ".smc-bot.env", override=False)

    cfg = SignalBotConfig.from_env(require_ctrader=False)
    if cfg.feed_mode in ("ctrader", "auto") and cfg.ctrader_access_token:
        try:
            cfg = SignalBotConfig.from_env(require_ctrader=True)
        except RuntimeError as exc:
            logger.error("%s", exc)
            return 2

    watcher = build_watcher(cfg)
    try:
        watcher.run_forever()
    except KeyboardInterrupt:
        logger.info("stopped by user")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
