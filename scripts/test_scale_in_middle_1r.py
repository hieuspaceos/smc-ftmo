"""Unit test ScaleInMiddle1RExit."""
import sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.scale_in_middle_1r_exit import ScaleInMiddle1RExit


def run(name, prices, side="long", entry=1.1000, sl=1.0950):
    print(f"\n--- {name} ---")
    obj = ScaleInMiddle1RExit(entry=entry, sl=sl, side=side)
    log = []
    for i, p in enumerate(prices):
        actions = obj.update(p)
        if actions:
            log.append((i, p, [a[0] for a in actions]))
    print(f"  final={obj.state}  realized_R={obj.realized_r:.2f}")
    print(f"  log={log}")
    assert obj.closed
    return obj.realized_r


# 2R=1.1100, 1R=1.1050, BE=1.1000

# 1. SL before 2R -> -1R
r1 = run("SL before 2R", [1.0980, 1.0960, 1.0950])
assert abs(r1 - (-1.0)) < 1e-6, f"got {r1}"

# 2. 4R no retrace -> +3R
r2 = run("4R no retrace", [1.1100, 1.1150, 1.1200, 1.1250])
assert abs(r2 - 3.0) < 1e-6, f"got {r2}"

# 3. 2R -> 1R retrace leg2 -> 4R -> +6R (1 + 2 + 3)
r3 = run("2R -> 1R retrace -> 4R", [1.1100, 1.1150, 1.1080, 1.1050, 1.1150, 1.1200])
assert abs(r3 - 6.0) < 1e-6, f"got {r3}"


# 4. Hit 2R, retrace to 1R (leg2 opens), then cascade to BE.
# Total = 1 locked + 0 leg1 rem + -1 leg2 = 0R breakeven.
r4a = run("2R -> 1R retr -> BE cascade -> 0R",
          [1.1100, 1.1150, 1.1080, 1.1050, 1.0990])
assert abs(r4a - 0.0) < 1e-6, f"got {r4a}"

# 5. 2R -> 1R retrace -> leg2 open -> leg1 BE hit + leg2 SL hit (cascade)
# already tested in #4.


# SHORT side mirrored
r6 = run("SHORT: 2R -> 1R -> 4R", [1.0980, 1.0920, 1.0880, 1.0960, 1.0940, 1.0900, 1.0800],
         side="short", entry=1.1000, sl=1.1050)
assert abs(r6 - 6.0) < 1e-6, f"got {r6}"

print("\nAll ScaleInMiddle1RExit tests PASSED")
