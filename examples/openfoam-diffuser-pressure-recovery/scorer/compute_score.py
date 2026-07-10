"""Deterministic grader for the planar diffuser pressure-recovery task.

Reads the submitted design from /tmp/output/diffuser_design.json, rebuilds
and solves the fixed hidden cases at the four disclosed operating
velocities, and scores the result against precomputed anchors in
scorer/data/anchors.json.

Reward philosophy (calibrated so a merely-valid design scores low):
  - validity / feasibility / mesh / solver gates:   0.19 total
  - attachment (graded, per velocity):              0.06
  - outlet flow uniformity (graded, worst case):    0.06
  - pressure-recovery objective (per velocity):     0.36
  - worst-case robustness across velocities:        0.33

Pressure-recovery credit is normalized per velocity between the
published reference-design anchor (0 credit) and the feasible-max
anchor (full credit), raised to GAMMA, and multiplied by the same
velocity's attachment credit — separated designs cannot buy recovery
with raw Cp.  All anchors are real measured solver results — see
scorer/calibrate_anchors.py.
"""

from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _case  # noqa: E402

SUBMISSION_PATH = "/tmp/output/diffuser_design.json"
ANCHORS_PATH = Path(__file__).resolve().parent / "data" / "anchors.json"

GAMMA = 3.0                       # sub-linear credit exponent
SEPARATION_SOFT_LIMIT = 0.002     # full attachment credit at/below this
SEPARATION_HARD_LIMIT = 0.012     # zero attachment credit at/above this

WEIGHTS = {
    "file_valid": 0.02,
    "schema_valid": 0.02,
    "bounds_valid": 0.02,
    "geometry_feasible": 0.02,
    "mesh_valid": 0.03,
    "solver_health": 0.08,        # split evenly across velocities
    "separation": 0.06,           # split evenly across velocities
    "outlet_uniformity": 0.06,    # worst case across velocities
    "pressure_recovery": 0.36,    # split evenly across velocities
    "robustness_worst_case": 0.33,
}


def clip01(x):
    return max(0.0, min(1.0, x))


def normalized_cp(cp, velocity, anchors):
    key = f"{velocity:g}"
    lo = anchors["cp_reference_baseline_by_velocity"][key]
    hi = anchors["cp_feasible_max_by_velocity"][key]
    if hi <= lo:
        raise ValueError("invalid anchors: hi <= lo")
    return clip01((cp - lo) / (hi - lo))


def separation_credit(backflow_fraction):
    if backflow_fraction <= SEPARATION_SOFT_LIMIT:
        return 1.0
    if backflow_fraction >= SEPARATION_HARD_LIMIT:
        return 0.0
    span = SEPARATION_HARD_LIMIT - SEPARATION_SOFT_LIMIT
    return clip01(1.0 - (backflow_fraction - SEPARATION_SOFT_LIMIT) / span)


def uniformity_credit(nonuniformity, anchors):
    lo = anchors["nonuniformity_full_credit"]
    hi = anchors["nonuniformity_zero_credit"]
    if nonuniformity <= lo:
        return 1.0
    if nonuniformity >= hi:
        return 0.0
    return clip01(1.0 - (nonuniformity - lo) / (hi - lo))


def compute_score():
    criteria = {name: 0.0 for name in WEIGHTS}
    details = {"criteria": criteria, "notes": []}

    anchors = json.loads(ANCHORS_PATH.read_text())

    design, errors = _case.load_design(SUBMISSION_PATH)
    if design is None:
        details["notes"].extend(errors)
        return finish(details)
    criteria["file_valid"] = 1.0
    criteria["schema_valid"] = 1.0

    berr = _case.bounds_errors(design)
    if berr:
        details["notes"].extend(berr)
        return finish(details)
    criteria["bounds_valid"] = 1.0

    gerr = _case.geometry_errors(design)
    if gerr:
        details["notes"].extend(gerr)
        return finish(details)
    criteria["geometry_feasible"] = 1.0

    velocities = _case.OPERATING_VELOCITIES
    per_velocity = {}
    solver_ok = 0
    with tempfile.TemporaryDirectory(prefix="lbx-diffuser-grade-") as tmp:
        # mesh validity is independent of solver outcome (same parametric
        # mesh at every velocity)
        mesh_ok = _case.validate_mesh(design, Path(tmp) / "mesh_check")
        for vel in velocities:
            work = Path(tmp) / f"case_u{vel:g}"
            try:
                metrics = _case.evaluate_design(design, vel, work)
            except _case.CaseError as exc:
                details["notes"].append(f"U={vel:g}: {exc}")
                per_velocity[f"{vel:g}"] = {"failed": str(exc)}
                continue
            solver_ok += 1
            per_velocity[f"{vel:g}"] = metrics

    details["per_velocity"] = per_velocity
    criteria["mesh_valid"] = 1.0 if mesh_ok else 0.0
    criteria["solver_health"] = solver_ok / len(velocities)

    solved = {
        v: m for v, m in per_velocity.items() if "failed" not in m
    }
    if len(solved) < len(velocities):
        # Any unusable operating point voids the physics objective: a
        # diffuser that cannot be evaluated across the stated envelope
        # is not a usable engineering answer.
        details["notes"].append(
            "one or more operating points unusable; physics credit voided"
        )
        return finish(details)

    sep_credits = []
    cp_credits = []
    worst_nonuniformity = 0.0
    for vel in velocities:
        m = solved[f"{vel:g}"]
        sep = separation_credit(m["backflow_fraction"])
        sep_credits.append(sep)
        # Recovery credit is scaled by attachment at the same velocity:
        # a separated design cannot buy recovery with its raw Cp (on this
        # short domain a mild separation bubble barely dents Cp, so the
        # constraint must be enforced in the reward, not just implied by
        # the physics).
        cp_credits.append(
            (normalized_cp(m["cp"], vel, anchors) ** GAMMA) * sep
        )
        worst_nonuniformity = max(worst_nonuniformity, m["outlet_nonuniformity"])

    criteria["separation"] = sum(sep_credits) / len(sep_credits)
    criteria["pressure_recovery"] = sum(cp_credits) / len(cp_credits)
    criteria["robustness_worst_case"] = min(cp_credits)
    criteria["outlet_uniformity"] = uniformity_credit(worst_nonuniformity, anchors)

    return finish(details)


def finish(details):
    criteria = details["criteria"]
    score = sum(WEIGHTS[name] * clip01(value) for name, value in criteria.items())
    score = clip01(score)
    if not math.isfinite(score):
        score = 0.0
    details["score"] = score
    details["weights"] = WEIGHTS
    return details


def main():
    details = compute_score()
    print(json.dumps(details, indent=2))
    out = Path("/tmp/output")
    try:
        out.mkdir(parents=True, exist_ok=True)
        (out / "score_details.json").write_text(json.dumps(details, indent=2))
    except OSError:
        pass
    print(f"SCORE: {details['score']:.6f}")
    return details["score"]


if __name__ == "__main__":
    main()
