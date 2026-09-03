# Phase 05 — Mac mini deploy docs + live smoke

## Overview

| | |
|--|--|
| Priority | P1 |
| Status | pending |
| Depends | Phase 01–04 code complete; user credentials |

Document Mac mini 24/7 ops and run a live demo smoke (user-operated).

## Requirements

### Functional
- Doc: disable sleep, Ethernet, Python 3.11, venv, install packages
- Doc: env file `~/.smc-bot.env` + `chmod 600`
- Doc: Playground token refresh steps
- Doc: launchd plist auto-start + log path
- Smoke checklist: connect → bars → optional Telegram test message
- `SMC_SIGNAL_DRY_RUN=1` first day recommended

### Non-goals
- Automated CI against live cTrader
- Windows/VPS deploy guides (optional appendix only)

## Related files

**Create**
- `docs/deploy-mac-mini-ctrader.md`
- `deploy/mac-mini/com.smc.signal.plist.example`
- `deploy/mac-mini/setup-notes.md` (sleep/pmset commands)
- `packages/smc_bot_signal/.env.example`

**Modify**
- Root README link to deploy doc
- This plan status → complete after smoke notes filed

## Implementation steps

1. Write deploy doc (copy-paste commands)
2. launchd example with `EnvironmentVariables` or `EnvironmentFile` pattern
3. Troubleshooting: token expired, account id wrong, symbol not found, sleep
4. User runs dry-run 24h → enable Telegram → journal 1 week signals vs chart

## Todo

- [ ] deploy doc
- [ ] plist example
- [ ] .env.example
- [ ] smoke checklist in doc
- [ ] user confirmation of first live alert (manual)

## Success criteria

- New machine can follow doc without tribal knowledge
- Dry-run produces log lines on new M15 bars
- At least one real Telegram alert verified by user on demo

## Risks

| Risk | Mitigation |
|------|------------|
| Mac sleep | pmset + caffeinate; doc verify |
| Power loss | UPS note; accept gap |
| Token 30d expiry | calendar reminder + refresh script later |

## Security

- Secrets outside repo
- Rotate secret if ever pasted in chat/screenshot public

## Next

After stable smoke: optional backlog
- Full Pine rulebook gates in engine path
- Token auto-refresh job
- Multi-pair production
- cTrader order bridge (only if user later requests auto-trade)
