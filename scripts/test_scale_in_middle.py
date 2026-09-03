"""Quick unit test for ScaleInMiddleExit + its R outcomes."""
import sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.scale_in_middle_exit import ScaleInMiddleExit


def run(scenario_name, prices, side="long", entry=1.1000, sl=1.0950):
    print(f"\n--- {scenario_name} ---")
    obj = ScaleInMiddleExit(entry=entry, sl=sl, side=side)
    actions_log = []
    for i, p in enumerate(prices):
        actions = obj.update(p)
        if actions:
            actions_log.append((i, p, [a[0] for a in actions]))
    print(f"  final state={obj.state}  realized_r={obj.realized_r:.2f}")
    print(f"  actions_log: {actions_log}")
    assert obj.closed, "Should be closed by end of test"
    return obj.realized_r


# Entry=1.1000, sl=1.0950, sl_distance=0.0050
# 2R = 1.1100; 3R = 1.1150; 4R = 1.1200
# 1R trigger (leg2 entry) = 1.1050
# BE = 1.1000

# Scenario 1: SL before 2R
r1 = run("SL before 2R", [1.0980, 1.0960, 1.0950, 1.0930, 1.0920])
print(f"  EXPECTED: -1.0R")
assert abs(r1 - (-1.0)) < 0.01, f"Expected -1R got {r1}"

# Scenario 2: Hit 4R without retracement (monotonic up)
r2 = run("Hit 4R no retrace", [1.1100, 1.1150, 1.1200, 1.1250, 1.1300])
print(f"  EXPECTED: +3.0R (1R locked + 0.5 * 4R leg1 rem)")
assert abs(r2 - 3.0) < 0.01, f"Expected 3R got {r2}"

# Scenario 3: Hit 2R -> retrace to 1R -> hit 4R (leg2 opens)
r3 = run("2R -> 1R retrace -> leg2 open -> 4R",
         [1.1100, 1.1150,    # 2R peak then 3R, await retrace
          1.1090, 1.1050,    # 1R: leg2 opens
          1.1150, 1.1200])   # 4R: close both
print(f"  EXPECTED: +4.5R (1R locked + 2R leg1 rem + 1.5R leg2)")
assert abs(r3 - 4.5) < 0.01, f"Expected 4.5R got {r3}"

# Scenario 4: Hit 2R, retrace to 1R (leg2 opens), then cascade to BE.
r4 = run("2R -> 1R trigger leg2 -> cascade to BE",
         [1.1100,   # 2R peak: lock +1R, leg1 SL->BE, await retrace
          1.1150,   # 3R: still in awaiting_retracement
          1.1080,   # 1.6R: still > leg2_entry_r
          1.1050,   # 1R: leg2 opens @ 1R with 0.5 lot
          1.0990])  # BE hit: leg1 rem @ 0R, leg2 SL hit = -0.5R -> +0.5R
print(f"  EXPECTED: +0.5R (1R locked - 0.5R leg2)")
assert abs(r4 - 0.5) < 0.01, f"Expected 0.5R got {r4}"

# Scenario 5: Hit 2R then leg1 rem at BE without retrace (leg2 never opens).
r5 = run("2R -> direct BE (no retrace)",
         [1.1100, 1.1150,   # 2R peak then 3R, await
          1.1090,           # 1.8R: still above 1R trigger
          1.0990])          # below BE -> close before leg2 opens
print(f"  EXPECTED: +1.0R (locked only)")
assert abs(r5 - 1.0) < 0.01, f"Expected 1R got {r5}"

# Scenario 6: SHORT side mirrored
r6 = run("SHORT: 2R -> 1R retrace -> 4R",
         # side='short', entry=1.1000, sl=1.1050, so 2R-down = 1.0900, 1R-down = 1.0950
         [1.0980, 1.0920, 1.0880, 1.0960, 1.0940, 1.0850, 1.0800],
         side="short", entry=1.1000, sl=1.1050)
print(f"  EXPECTED SHORT: +4.5R")
assert abs(r6 - 4.5) < 0.01, f"Expected 4.5R got {r6}"

print("\nAll ScaleInMiddleExit unit tests PASSED")
