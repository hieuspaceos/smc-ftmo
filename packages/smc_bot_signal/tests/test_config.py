"""Config.from_env tests."""

from __future__ import annotations

import pytest

from smc_bot_signal.config import SignalBotConfig


def test_from_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(monkeypatch.__dict__.get("_setitem", {})) if False else []:
        pass
    monkeypatch.delenv("CTRADER_CLIENT_ID", raising=False)
    monkeypatch.delenv("SMC_SIGNAL_SYMBOLS", raising=False)
    monkeypatch.delenv("SMC_SIGNAL_DRY_RUN", raising=False)
    cfg = SignalBotConfig.from_env()
    assert cfg.symbols == ("EURUSD",)
    assert cfg.timeframe == "M15"
    assert cfg.scale_in_r == 2.0
    assert cfg.final_tp_r == 4.0
    assert cfg.dry_run is False


def test_from_env_symbols_and_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMC_SIGNAL_SYMBOLS", "EURUSD, GBPUSD")
    monkeypatch.setenv("SMC_SIGNAL_DRY_RUN", "true")
    monkeypatch.setenv("CTRADER_ACCOUNT_ID", "42")
    cfg = SignalBotConfig.from_env()
    assert cfg.symbols == ("EURUSD", "GBPUSD")
    assert cfg.dry_run is True
    assert cfg.ctrader_account_id == 42


def test_require_ctrader_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CTRADER_CLIENT_ID", raising=False)
    monkeypatch.delenv("CTRADER_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("CTRADER_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("CTRADER_ACCOUNT_ID", "0")
    with pytest.raises(RuntimeError, match="Missing required cTrader"):
        SignalBotConfig.from_env(require_ctrader=True)
