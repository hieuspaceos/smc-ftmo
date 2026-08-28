---
phase: 9
title: "Acceptance Cleanup"
status: pending
priority: P2
dependencies: [8]
effort: "1 day"
---

# Phase 9: Acceptance Cleanup

## Overview
Run final behavior/UI verification, remove the legacy dependency only after all gates pass, and document the new engine and known limitations.

## Requirements
- Functional: complete Gates 1–4 from `plan.md`.
- Non-functional: leave no stale imports, misleading docs, or unrecorded behavior delta.

## Related Code Files
- Modify: `requirements.txt`
- Modify: `README.md`
- Create/Modify: `docs/system-architecture.md`
- Create: `reports/phase-12-summary.md`
- Create: `reports/smoke-final.json`
- Create: `reports/test-output.log`
- Create: `reports/app-screenshot.png` when browser capture is available

## Implementation Steps
1. Run full pytest and save output.
2. Run smoke script and save JSON with dataset checksum.
3. Start Streamlit; exercise Run Backtest in browser; verify chart, metrics, and fresh journal state.
4. Run source search for `smartmoneyconcepts` imports.
5. Remove dependency only after all callers are migrated.
6. Update README and architecture docs.
7. Write before/after report separating correctness evidence from economic characterization.
8. Commit/push only when explicitly requested by user.

## Final Report Requirements
- What changed by phase.
- Exact algorithms and locked policies.
- Test/golden/property/performance results.
- Legacy vs new bias/event/trade distributions.
- Economic metrics labeled characterization.
- Known limitations and optional upgrades.
- Rollback procedure.

## Success Criteria
- [ ] Gates 1–4 pass.
- [ ] `smartmoneyconcepts` absent from runtime dependencies/imports.
- [ ] Full test output and smoke JSON saved.
- [ ] Actual Streamlit behavior verified.
- [ ] Docs accurately describe causal activation/lifecycle semantics.
- [ ] No automatic commit/push occurred without user request.

## Risk Assessment
- **Premature dependency removal**: prohibited before Gate 4.
- **Unreviewed economic regression**: report blocks acceptance until human review.
- **Documentation drift**: final consistency search covers old library/API terms.
