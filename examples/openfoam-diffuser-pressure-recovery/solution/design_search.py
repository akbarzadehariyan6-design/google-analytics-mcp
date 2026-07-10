"""Oracle design search for the planar diffuser pressure-recovery task.

Derives the reference design from the PUBLIC problem definition (bounds,
disclosed operating velocities) by running the real deterministic solver
pipeline for every candidate — no hard-coded answer.  Used by
solution/solve.sh (oracle) and scorer/calibrate_anchors.py (anchor
measurement).

Search strategy (all solver runs are real):
  Stage 1: coarse (area_ratio, length, blend) sweep at the binding
           worst-case velocity (lowest Re separates first).
  Stage 2: contour refinement (blend, inflection) around the stage-1
           leaders, still at the worst-case velocity.
  Stage 3: full four-velocity evaluation of the finalists; keep only
           candidates attached everywhere; pick the one maximizing the
           worst-case Cp margin over the naive mid-bounds baseline.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scorer"))
import _case  # noqa: E402

# Oracle-side attachment requirement: must not exceed the grading soft
# limit (SEPARATION_SOFT_LIMIT = 0.002) so the oracle earns full
# attachment credit with margin.
ATTACHMENT_LIMIT = 0.002

# Weak calibration baseline (baselines/naive.sh) — a sensible but
# unoptimized mid-bounds design.
NAIVE_DESIGN = {
    "area_ratio": 1.9,
    "length_m": 0.60,
    "wall_blend": 0.5,
    "inflection_position": 0.5,
}

# Published zero-credit reference design: a decent "textbook" diffuser
# (moderate area ratio, full length, straight wall).  Recovery credit
# only starts on genuine improvement over THIS design, not over the
# weaker naive baseline.
REFERENCE_DESIGN = {
    "area_ratio": 2.2,
    "length_m": 0.72,
    "wall_blend": 0.0,
    "inflection_position": 0.5,
}


def make_design(ar, length, blend, infl):
    return {
        "area_ratio": round(ar, 6),
        "length_m": round(length, 6),
        "wall_blend": round(blend, 6),
        "inflection_position": round(infl, 6),
    }


def evaluate(design, velocity, tmp):
    work = Path(tmp) / "search_case"
    try:
        return _case.evaluate_design(design, velocity, work)
    except _case.CaseError:
        return None


def run_search(verbose=True):
    v_lo = min(_case.OPERATING_VELOCITIES)
    velocities = _case.OPERATING_VELOCITIES
    ar_lo, ar_hi = _case.AREA_RATIO_BOUNDS
    len_lo, len_hi = _case.LENGTH_BOUNDS_M

    with tempfile.TemporaryDirectory(prefix="lbx-diffuser-search-") as tmp:
        # ---------------- Stage 1: coarse sweep at worst-case velocity
        stage1 = []
        ars = [ar_lo + f * (ar_hi - ar_lo) for f in (0.35, 0.5, 0.62, 0.72, 0.82, 0.92)]
        lengths = [len_lo + f * (len_hi - len_lo) for f in (0.5, 0.75, 1.0)]
        blends = [0.0, 0.4]
        for ar in ars:
            for length in lengths:
                for blend in blends:
                    d = make_design(ar, length, blend, 0.5)
                    m = evaluate(d, v_lo, tmp)
                    if m is None:
                        continue
                    stage1.append((d, m))
                    if verbose:
                        print(
                            f"stage1 AR={ar:.3f} L={length:.3f} b={blend:.1f}"
                            f" cp={m['cp']:.4f} bf={m['backflow_fraction']:.3f}",
                            flush=True,
                        )
        attached = [
            (d, m) for d, m in stage1
            if m["backflow_fraction"] <= ATTACHMENT_LIMIT
        ]
        if not attached:
            raise RuntimeError("stage 1 found no attached candidates")
        attached.sort(key=lambda dm: -dm[1]["cp"])
        leaders = attached[:3]

        # ---------------- Stage 2: contour refinement at worst-case velocity
        stage2 = list(leaders)
        for d0, _ in leaders[:2]:
            for blend in (0.0, 0.2, 0.35):
                for infl in (0.35, 0.5, 0.65):
                    if blend == d0["wall_blend"] and infl == d0["inflection_position"]:
                        continue
                    d = make_design(
                        d0["area_ratio"], d0["length_m"], blend, infl
                    )
                    m = evaluate(d, v_lo, tmp)
                    if m is None or m["backflow_fraction"] > ATTACHMENT_LIMIT:
                        continue
                    stage2.append((d, m))
                    if verbose:
                        print(
                            f"stage2 AR={d['area_ratio']:.3f} b={blend:.2f}"
                            f" c={infl:.2f} cp={m['cp']:.4f}"
                            f" bf={m['backflow_fraction']:.3f}",
                            flush=True,
                        )
        # walk the area ratio up to the attachment edge on the best
        # contour (coarse ascent, then fine refinement), so the chosen
        # design sits at the true feasible maximum rather than short of it
        best_d = max(stage2, key=lambda dm: dm[1]["cp"])[0]

        def probe_ar(ar):
            d = make_design(
                ar, best_d["length_m"], best_d["wall_blend"],
                best_d["inflection_position"],
            )
            m = evaluate(d, v_lo, tmp)
            ok = m is not None and m["backflow_fraction"] <= ATTACHMENT_LIMIT
            if ok:
                stage2.append((d, m))
            if verbose and m is not None:
                print(
                    f"stage2+ AR={ar:.3f} cp={m['cp']:.4f}"
                    f" bf={m['backflow_fraction']:.3f}"
                    f" {'ok' if ok else 'detached'}",
                    flush=True,
                )
            return ok

        last_ok = best_d["area_ratio"]
        first_bad = None
        ar = last_ok
        while ar < ar_hi - 1.0e-9:
            ar = min(ar_hi, ar + 0.06)
            if probe_ar(ar):
                last_ok = ar
            else:
                first_bad = ar
                break
        if first_bad is not None:
            step = 0.02
            ar = last_ok + step
            while ar < first_bad - 1.0e-9:
                if probe_ar(ar):
                    last_ok = ar
                ar += step

        stage2.sort(key=lambda dm: -dm[1]["cp"])
        seen = set()
        finalists = []
        for d, m in stage2:
            key = tuple(d.values())
            if key not in seen:
                seen.add(key)
                finalists.append(d)
            if len(finalists) == 4:
                break

        # ---------------- reference baseline at all velocities
        reference_metrics = {}
        for vel in velocities:
            m = evaluate(REFERENCE_DESIGN, vel, tmp)
            if m is None:
                raise RuntimeError(f"reference baseline failed at U={vel}")
            reference_metrics[f"{vel:g}"] = m

        # ---------------- Stage 3: full-envelope evaluation of finalists
        best = None
        for d in finalists:
            per_v = {}
            ok = True
            for vel in velocities:
                m = evaluate(d, vel, tmp)
                if m is None or m["backflow_fraction"] > ATTACHMENT_LIMIT:
                    ok = False
                    break
                per_v[f"{vel:g}"] = m
            if not ok:
                if verbose:
                    print(f"stage3 reject {d}", flush=True)
                continue
            worst_margin = min(
                per_v[k]["cp"] - reference_metrics[k]["cp"] for k in per_v
            )
            if verbose:
                print(
                    f"stage3 {d} worst_cp_margin={worst_margin:.4f}",
                    flush=True,
                )
            if best is None or worst_margin > best["worst_margin"]:
                best = {
                    "design": d,
                    "metrics": per_v,
                    "worst_margin": worst_margin,
                }
        if best is None:
            raise RuntimeError("no finalist survived the full envelope")

    return {
        "design": best["design"],
        "metrics": best["metrics"],
        "reference_design": REFERENCE_DESIGN,
        "reference_metrics": reference_metrics,
    }


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/output/diffuser_design.json"
    result = run_search()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result["design"], indent=2) + "\n")
    summary = out.parent / "search_summary.json"
    summary.write_text(json.dumps(result, indent=2) + "\n")
    print(f"wrote {out}")
    print(json.dumps(result["design"], indent=2))


if __name__ == "__main__":
    main()
