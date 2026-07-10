#!/usr/bin/env bash
# Public reviewer/debug diagnostic (NOT referenced from instruction.md;
# the agent is never required to run it).
#
# Builds the same deterministic case the grader builds for a candidate
# design and runs mesh generation + mesh checking only (fast, no solve).
#
# Usage: bash case_skeleton_probe.sh /path/to/diffuser_design.json
#
# NOTE: positional parameters are saved and cleared (`set --`) before the
# solver environment is sourced -- OpenFOAM's env scripts consume $1 as a
# build override otherwise (see AUTHOR_NOTES, bug 5).

set -eo pipefail

DESIGN_JSON="${1:?usage: case_skeleton_probe.sh <design.json>}"
CASE_DIR="${2:-/tmp/probe_case}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Locate the case-builder module: alongside the grader in the task image,
# or in the repo checkout when run by a reviewer.
for CAND in /opt/scorer "${SCRIPT_DIR}/../scorer"; do
  if [ -f "${CAND}/_case.py" ]; then
    CASE_MODULE_DIR="${CAND}"
    break
  fi
done
: "${CASE_MODULE_DIR:?could not locate _case.py}"

python3 - "$DESIGN_JSON" "$CASE_DIR" "$CASE_MODULE_DIR" <<'PYEOF'
import json, sys
from pathlib import Path

design_path, case_dir, module_dir = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, module_dir)
import _case

design, errors = _case.load_design(design_path)
if design is None:
    sys.exit("invalid design: " + "; ".join(errors))
errors = _case.bounds_errors(design) + _case.geometry_errors(design)
if errors:
    sys.exit("infeasible design: " + "; ".join(errors))

_case.build_case(design, min(_case.OPERATING_VELOCITIES), case_dir)
rc, _ = _case.run_foam("blockMesh", case_dir, "log.blockMesh")
if rc != 0:
    sys.exit("blockMesh failed; see log.blockMesh")
rc, log = _case.run_foam("checkMesh", case_dir, "log.checkMesh")
mesh = _case.parse_check_mesh(log)
print(json.dumps(mesh, indent=2))
ok = (
    rc == 0 and mesh["mesh_ok"]
    and mesh["max_non_orthogonality"] is not None
    and mesh["max_non_orthogonality"] <= _case.MAX_NON_ORTHOGONALITY
    and (mesh["max_skewness"] or 0.0) <= _case.MAX_SKEWNESS
    and mesh["negative_volume_cells"] == 0
)
print("MESH_PROBE:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
PYEOF
