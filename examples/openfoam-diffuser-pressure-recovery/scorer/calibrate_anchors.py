"""Measure and write scorer/data/anchors.json from REAL solver runs.

Run this once per solver image (anchors are build-specific measured
values, never hand-typed):

    python3 scorer/calibrate_anchors.py

It executes the oracle design search (solution/design_search.py), then
records:
  - cp_reference_baseline_by_velocity: measured Cp of the PUBLISHED
    reference design at each disclosed velocity (0-credit anchor; the
    same numbers appear in data/public_baseline_summary.json);
  - cp_feasible_max_by_velocity: measured Cp of the oracle's chosen
    design at each velocity (full-credit anchor, by construction the
    oracle therefore normalizes to 1.0);
  - nonuniformity anchors derived from the oracle design's worst outlet
    nonuniformity (full credit at slightly above the oracle's own value).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "solution"))

import design_search  # noqa: E402


def main():
    result = design_search.run_search()
    velocities = sorted(result["metrics"], key=float)
    anchors = {
        "cp_reference_baseline_by_velocity": {
            v: result["reference_metrics"][v]["cp"] for v in velocities
        },
        "cp_feasible_max_by_velocity": {
            v: result["metrics"][v]["cp"] for v in velocities
        },
    }
    worst_nu = max(result["metrics"][v]["outlet_nonuniformity"] for v in velocities)
    anchors["nonuniformity_full_credit"] = round(worst_nu * 1.02, 6)
    anchors["nonuniformity_zero_credit"] = round(worst_nu * 3.0, 6)
    anchors["calibration_design"] = result["design"]
    out = HERE / "data" / "anchors.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(anchors, indent=2) + "\n")
    print(f"wrote {out}")
    print(json.dumps(anchors, indent=2))


if __name__ == "__main__":
    main()
