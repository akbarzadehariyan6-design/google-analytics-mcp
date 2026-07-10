#!/usr/bin/env bash
# Public reviewer/debug diagnostic (NOT referenced from instruction.md;
# the agent is never required to run it).
#
# Builds the same deterministic parametric MESH the grader builds for a
# candidate design and runs mesh generation + mesh checking only (fast,
# no flow solution).  This script is fully self-contained: it does not
# import or reveal the hidden grading pipeline.
#
# Usage: bash case_skeleton_probe.sh /path/to/diffuser_design.json [case_dir]
#
# NOTE: positional parameters are saved and cleared (`set --`) before the
# solver environment is sourced -- OpenFOAM's env scripts consume $1 as a
# build override otherwise.

set -eo pipefail

DESIGN_JSON="${1:?usage: case_skeleton_probe.sh <design.json> [case_dir]}"
CASE_DIR="${2:-/tmp/probe_case}"

python3 - "$DESIGN_JSON" "$CASE_DIR" <<'PYEOF'
import json
import math
import shutil
import sys
from pathlib import Path

design_path, case_dir = sys.argv[1], sys.argv[2]

# --- fixed public geometry / mesh parameters (match the grader) -------
H1 = 0.04
LIN = 0.24
LOUT = 0.36
SPAN = 0.01
NX_IN, NX_DIFF, NX_OUT, NY = 30, 60, 40, 22
Y_GRADING = 0.25
N_PTS = 41
BOUNDS = {
    "area_ratio": (1.40, 3.20),
    "length_m": (0.25, 0.72),
    "wall_blend": (0.0, 1.0),
    "inflection_position": (0.25, 0.75),
}

design = json.loads(Path(design_path).read_text())
errors = []
for key, (lo, hi) in BOUNDS.items():
    v = design.get(key)
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
        errors.append(f"{key} missing or not a finite number")
    elif not (lo <= v <= hi):
        errors.append(f"{key}={v} outside [{lo}, {hi}]")
if errors:
    sys.exit("invalid design: " + "; ".join(errors))

h2 = H1 * design["area_ratio"]
L = design["length_m"]
b = design["wall_blend"]
c = design["inflection_position"]


def contour():
    pts = []
    for i in range(N_PTS):
        xi = i / (N_PTS - 1)
        t = 0.5 * xi / c if xi <= c else 0.5 + 0.5 * (xi - c) / (1.0 - c)
        smooth = t * t * (3.0 - 2.0 * t)
        blend = (1.0 - b) * xi + b * smooth
        pts.append((xi * L, H1 + (h2 - H1) * blend))
    return pts


def fmt(x):
    return f"{x:.9g}"


inner = contour()[1:-1]
x0, x2, x3 = -LIN, L, L + LOUT
verts = [
    (x0, 0.0, 0.0), (0.0, 0.0, 0.0), (x2, 0.0, 0.0), (x3, 0.0, 0.0),
    (x0, H1, 0.0), (0.0, H1, 0.0), (x2, h2, 0.0), (x3, h2, 0.0),
    (x0, 0.0, SPAN), (0.0, 0.0, SPAN), (x2, 0.0, SPAN), (x3, 0.0, SPAN),
    (x0, H1, SPAN), (0.0, H1, SPAN), (x2, h2, SPAN), (x3, h2, SPAN),
]
vtx = "\n".join(f"    ({fmt(x)} {fmt(y)} {fmt(z)})" for x, y, z in verts)


def poly(z):
    return " ".join(f"({fmt(x)} {fmt(y)} {fmt(z)})" for x, y in inner)


block_mesh = f"""FoamFile
{{
    version 2.0; format ascii; class dictionary; object blockMeshDict;
}}
scale 1;
vertices
(
{vtx}
);
blocks
(
    hex (0 1 5 4 8 9 13 12)   ({NX_IN} {NY} 1)   simpleGrading (1 {Y_GRADING} 1)
    hex (1 2 6 5 9 10 14 13)  ({NX_DIFF} {NY} 1) simpleGrading (1 {Y_GRADING} 1)
    hex (2 3 7 6 10 11 15 14) ({NX_OUT} {NY} 1)  simpleGrading (1 {Y_GRADING} 1)
);
edges
(
    polyLine 5 6 ( {poly(0.0)} )
    polyLine 13 14 ( {poly(SPAN)} )
);
boundary
(
    inlet {{ type patch; faces ((0 8 12 4)); }}
    outlet {{ type patch; faces ((3 7 15 11)); }}
    topWall {{ type wall; faces ((4 12 13 5) (5 13 14 6) (6 14 15 7)); }}
    bottomSym {{ type symmetry; faces ((0 1 9 8) (1 2 10 9) (2 3 11 10)); }}
    frontAndBack {{ type empty; faces ((0 4 5 1) (1 5 6 2) (2 6 7 3) (8 9 13 12) (9 10 14 13) (10 11 15 14)); }}
);
"""

control_dict = """FoamFile
{
    version 2.0; format ascii; class dictionary; object controlDict;
}
application blockMesh;
startFrom startTime; startTime 0; stopAt endTime; endTime 1;
deltaT 1; writeControl timeStep; writeInterval 1; writeFormat ascii;
"""

case = Path(case_dir)
if case.exists():
    shutil.rmtree(case)
(case / "system").mkdir(parents=True)
(case / "constant").mkdir()
(case / "system" / "blockMeshDict").write_text(block_mesh)
(case / "system" / "controlDict").write_text(control_dict)
(case / "system" / "fvSchemes").write_text(
    "FoamFile\n{\n    version 2.0; format ascii; class dictionary;"
    " object fvSchemes;\n}\n"
    "ddtSchemes { default steadyState; }\n"
    "gradSchemes { default Gauss linear; }\n"
    "divSchemes { default none; }\n"
    "laplacianSchemes { default Gauss linear corrected; }\n"
    "interpolationSchemes { default linear; }\n"
    "snGradSchemes { default corrected; }\n"
)
(case / "system" / "fvSolution").write_text(
    "FoamFile\n{\n    version 2.0; format ascii; class dictionary;"
    " object fvSolution;\n}\n"
)
print(f"case written to {case}")
PYEOF

# --- run mesh generation + checking -----------------------------------
set --
for ENV_SCRIPT in /etc/solver-envs.d/openfoam.sh /usr/share/openfoam/etc/bashrc; do
  if [ -f "$ENV_SCRIPT" ]; then
    source "$ENV_SCRIPT" >/dev/null 2>&1 || true
    break
  fi
done
set -u

cd "$CASE_DIR"
blockMesh > log.blockMesh 2>&1 || { echo "MESH_PROBE: FAIL (blockMesh, see $CASE_DIR/log.blockMesh)"; exit 1; }
checkMesh > log.checkMesh 2>&1 || { echo "MESH_PROBE: FAIL (checkMesh, see $CASE_DIR/log.checkMesh)"; exit 1; }
grep -E "Mesh non-orthogonality Max|Max skewness|negative volume|Mesh OK" log.checkMesh || true
if grep -q "Mesh OK." log.checkMesh; then
  echo "MESH_PROBE: PASS"
else
  echo "MESH_PROBE: FAIL (mesh checks, see $CASE_DIR/log.checkMesh)"
  exit 1
fi
