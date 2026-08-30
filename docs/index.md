# Documentation Index

## Setup guides

- [cloudflare-access-setup.md](cloudflare-access-setup.md) — Phase 01 + Phase 05 deploy
  behind Cloudflare Tunnel + Access + 2FA email allowlist.

- [mt5-bridge-setup.md](mt5-bridge-setup.md) — Phase 06: MQL5 EA compilation,
  shared folder options (Syncthing / SMB / local), round-trip verification,
  FTMO safety guard documentation, rollback procedure.

## Design system

- [design-system.md](design-system.md) — Color palette + typography + spacing
  tokens from `ak-ui-ux-pro-max` (Fira Code + Fira Sans, primary `#2563EB`).

## Plans

- [../plans/260830-bot-alert-replay/plan.md](../plans/260830-bot-alert-replay/plan.md) —
  master 6-phase plan.

- [../plans/260830-bot-alert-replay/architecture.md](../plans/260830-bot-alert-replay/architecture.md) —
  target data flow + component responsibilities.

- Per-phase sub-plans in `../plans/260830-bot-alert-replay/`:
  - `phase-01-webhook-receiver.md`
  - `phase-02-bot-storage-and-telegram.md`
  - `phase-03-rulebook-gate-validator.md`
  - `phase-04-backtest-replay-and-csv.md`
  - `phase-05-streamlit-dashboard.md`
  - `phase-06-demo-mt5-execution.md`

- [../plans/refactor-2026-08-31.md](../plans/refactor-2026-08-31.md) — workspace
  reorg plan (post Phase 06) that produced the current packages/ layout.

## Other

- [../README.md](../README.md) — root workspace README with install + run instructions.
