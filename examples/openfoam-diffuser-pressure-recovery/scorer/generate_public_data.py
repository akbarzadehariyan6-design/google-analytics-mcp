"""Generate the measured public data files from REAL solver runs.

Writes (from the repo task directory):
  - data/public_baseline_summary.json   (naive baseline, all velocities)
  - data/public_calibration_samples.json (diverse non-optimal samples)

Run after any change to the case pipeline or bounds:

    python3 scorer/generate_public_data.py

The published numbers are produced by the same deterministic pipeline
the grader uses, so the public data genuinely bridges the hidden
anchors (env pre-flight hidden-vs-public divergence check).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "solution"))

import _case  # noqa: E402
import design_search  # noqa: E402

# Deliberately non-optimal, spread across the design space.  None of
# these is the oracle design; the separated ones illustrate the failure
# mode the task penalizes.
SAMPLES = {
    "gentle_long": {
        "area_ratio": 1.6, "length_m": 0.72,
        "wall_blend": 0.5, "inflection_position": 0.5,
    },
    "moderate_short": {
        "area_ratio": 1.9, "length_m": 0.35,
        "wall_blend": 0.0, "inflection_position": 0.5,
    },
    "aggressive_short_separated": {
        "area_ratio": 2.8, "length_m": 0.25,
        "wall_blend": 0.0, "inflection_position": 0.5,
    },
    "aggressive_smooth_separated": {
        "area_ratio": 3.0, "length_m": 0.72,
        "wall_blend": 1.0, "inflection_position": 0.5,
    },
}


def measure(design, tmp):
    per_v = {}
    for vel in _case.OPERATING_VELOCITIES:
        key = f"{vel:g}"
        try:
            m = _case.evaluate_design(design, vel, Path(tmp) / "pub_case")
        except _case.CaseError as exc:
            per_v[key] = {"unusable": str(exc)}
            continue
        per_v[key] = {
            "cp": round(m["cp"], 4),
            "reversed_wall_fraction": round(m["backflow_fraction"], 3),
            "outlet_nonuniformity": round(m["outlet_nonuniformity"], 3),
        }
    return per_v


def main():
    data_dir = HERE.parent / "data"
    with tempfile.TemporaryDirectory(prefix="lbx-diffuser-pub-") as tmp:
        reference = design_search.REFERENCE_DESIGN
        baseline = {
            "description": (
                "Measured performance of the published reference design (a "
                "sound but unoptimized straight-walled, full-length "
                "diffuser). This is the zero-credit level of the pressure-"
                "recovery scale: matching or undershooting it earns no "
                "recovery credit."
            ),
            "design": reference,
            "performance_by_velocity": measure(reference, tmp),
        }
        (data_dir / "public_baseline_summary.json").write_text(
            json.dumps(baseline, indent=2) + "\n"
        )
        print("wrote public_baseline_summary.json")

        samples = {
            "description": (
                "Measured performance of assorted NON-optimal sample designs "
                "produced by the same fixed evaluation pipeline that grades "
                "submissions. Use these to calibrate the recovery/attachment "
                "tradeoff; none of them is the reference design."
            ),
            "samples": {},
        }
        for name, design in SAMPLES.items():
            samples["samples"][name] = {
                "design": design,
                "performance_by_velocity": measure(design, tmp),
            }
            print(f"measured sample: {name}")
        (data_dir / "public_calibration_samples.json").write_text(
            json.dumps(samples, indent=2) + "\n"
        )
        print("wrote public_calibration_samples.json")


if __name__ == "__main__":
    main()
