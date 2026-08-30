# smc_bot_core

Shared core for SMC bot packages:
- `BotDB`: SQLite helper with thread-safe per-call connections (Phase 01)
- `Settings`: typed config dataclass + env loading
- Re-export `AlertPayload`, `compute_signal_id`, `parse_payload`

Used by `smc_bot_webhook`, `smc_bot_dashboard`, etc.

## Install (workspace mode)

Inside workspace root:
```bash
pip install -e packages/smc_bot_core
```

## Notes

During the refactor (Phases 01-04), `BotDB` and payload models live
**transitionally** in `bot.storage.db` and `bot.webhook.payload`.
After all packages are split out, the canonical implementation moves
permanently into `smc_bot_core.db` and `smc_bot_core.models`.
