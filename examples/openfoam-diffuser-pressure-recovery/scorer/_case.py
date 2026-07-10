"""Deterministic OpenFOAM case builder/runner/parser for the planar
diffuser pressure-recovery task.

This module is the single source of truth for how a candidate design is
turned into a solver case and how physical metrics are extracted from the
solved fields.  It is used by:

  * scorer/compute_score.py       (hidden grading)
  * solution/design_search.py     (oracle search)
  * scorer/calibrate_anchors.py   (anchor measurement)
  * data/case_skeleton_probe.sh   (public reviewer/debug diagnostic)

Determinism rules honoured here:
  - serial execution only (no decomposePar / MPI)
  - fixed blockMesh parametric mesh (no snappyHexMesh)
  - fixed schemes, solver settings, BCs, ICs, turbulence model
  - fixed iteration budget with fixed residual controls
  - all field/mesh parsing done directly in Python from ascii files
    (no dependency on postProcess function objects, see AUTHOR_NOTES)
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

# ----------------------------------------------------------------------
# Fixed physical / numerical configuration (pinned; do not vary at grade
# time).  Geometry is a 2-D planar half-diffuser with a symmetry plane at
# y = 0: inlet channel -> contoured expansion -> outlet settling channel.
# ----------------------------------------------------------------------

INLET_HALF_HEIGHT_M = 0.04       # h1 (full duct height 0.08 m)
INLET_CHANNEL_LENGTH_M = 0.24    # upstream development channel
OUTLET_CHANNEL_LENGTH_M = 0.36   # downstream settling channel
SPAN_M = 0.01                    # dummy z-thickness (empty patches)

KINEMATIC_VISCOSITY = 1.5e-05    # air at ~20 C [m^2/s]
TURBULENCE_INTENSITY = 0.05
CMU = 0.09

# Disclosed operating velocities [m/s] (must match instruction.md and
# data/duct_specifications.json).
OPERATING_VELOCITIES = [6.0, 10.0, 14.0, 18.0]

# Design-variable bounds (must match instruction.md and public data).
AREA_RATIO_BOUNDS = (1.40, 3.20)
LENGTH_BOUNDS_M = (0.25, 0.72)
WALL_BLEND_BOUNDS = (0.0, 1.0)
INFLECTION_BOUNDS = (0.25, 0.75)

# Mesh resolution (fixed).
N_CELLS_X_INLET = 30
N_CELLS_X_DIFFUSER = 60
N_CELLS_X_OUTLET = 40
N_CELLS_Y = 22
Y_GRADING = 0.25                 # cells shrink toward the top wall
N_CONTOUR_POINTS = 41            # polyLine sampling of the wall contour

# Solver budget / convergence policy (fixed).
MAX_ITERATIONS = 1500
RESIDUAL_P = 1.0e-5
RESIDUAL_OTHERS = 1.0e-6

# Mesh-quality acceptance thresholds used for grading.
MAX_NON_ORTHOGONALITY = 65.0
MAX_SKEWNESS = 4.0

# Separation detection: a diffuser/outlet wall-adjacent cell counts as
# reversed when Ux < -BACKFLOW_UX_FRACTION * U_inlet.
BACKFLOW_UX_FRACTION = 1.0e-3

RUN_TIMEOUT_SEC = 420            # per solver invocation


class CaseError(RuntimeError):
    """Raised when a case cannot be built or run."""


# ----------------------------------------------------------------------
# Design handling
# ----------------------------------------------------------------------

REQUIRED_KEYS = ("area_ratio", "length_m", "wall_blend", "inflection_position")


def load_design(path):
    """Load and structurally validate a design JSON file.

    Returns (design_dict, errors); errors is a list of strings, empty when
    the design parses and every required key is a finite number.  Bounds
    are NOT enforced here -- the scorer grades bounds separately.
    """
    errors = []
    try:
        raw = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return None, ["design file not found"]
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, [f"design file is not valid JSON: {exc}"]
    if not isinstance(raw, dict):
        return None, ["design file must contain a JSON object"]
    design = {}
    for key in REQUIRED_KEYS:
        if key not in raw:
            errors.append(f"missing required key: {key}")
            continue
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"key {key} must be a number")
            continue
        value = float(value)
        if not math.isfinite(value):
            errors.append(f"key {key} must be finite")
            continue
        design[key] = value
    if errors:
        return None, errors
    return design, []


def bounds_errors(design):
    """Return a list of bound violations (empty when in-bounds)."""
    checks = [
        ("area_ratio", AREA_RATIO_BOUNDS),
        ("length_m", LENGTH_BOUNDS_M),
        ("wall_blend", WALL_BLEND_BOUNDS),
        ("inflection_position", INFLECTION_BOUNDS),
    ]
    errs = []
    for key, (lo, hi) in checks:
        v = design[key]
        if not (lo <= v <= hi):
            errs.append(f"{key}={v} outside [{lo}, {hi}]")
    return errs


def wall_contour(design):
    """Sample the top-wall contour across the diffuser section.

    Returns a list of (x, y) points from (0, h1) to (L, h2) inclusive.
    The blend is a monotone mix of a linear ramp and a smoothstep whose
    inflection is remapped to `inflection_position`.
    """
    h1 = INLET_HALF_HEIGHT_M
    h2 = h1 * design["area_ratio"]
    length = design["length_m"]
    b = design["wall_blend"]
    c = design["inflection_position"]
    pts = []
    for i in range(N_CONTOUR_POINTS):
        xi = i / (N_CONTOUR_POINTS - 1)
        # piecewise-linear remap of xi so the smoothstep midpoint sits at c
        if xi <= c:
            t = 0.5 * xi / c
        else:
            t = 0.5 + 0.5 * (xi - c) / (1.0 - c)
        smooth = t * t * (3.0 - 2.0 * t)
        blend = (1.0 - b) * xi + b * smooth
        pts.append((xi * length, h1 + (h2 - h1) * blend))
    return pts


def geometry_errors(design):
    """Degenerate-geometry checks beyond simple bounds."""
    errs = []
    pts = wall_contour(design)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if y1 < y0 - 1.0e-12:
            errs.append("wall contour is not monotonically expanding")
            break
    # reject sub-grid features: minimum axial cell size must stay sane
    dx = design["length_m"] / N_CELLS_X_DIFFUSER
    if dx <= 0.0:
        errs.append("non-positive diffuser cell size")
    return errs


# ----------------------------------------------------------------------
# Case generation
# ----------------------------------------------------------------------

def _fmt(x):
    return f"{x:.9g}"


def _block_mesh_dict(design):
    h1 = INLET_HALF_HEIGHT_M
    h2 = h1 * design["area_ratio"]
    length = design["length_m"]
    x0 = -INLET_CHANNEL_LENGTH_M
    x2 = length
    x3 = length + OUTLET_CHANNEL_LENGTH_M
    z0, z1 = 0.0, SPAN_M
    contour = wall_contour(design)
    inner = contour[1:-1]

    def poly(zval):
        pts = " ".join(f"({_fmt(x)} {_fmt(y)} {_fmt(zval)})" for x, y in inner)
        return pts

    verts = [
        (x0, 0.0, z0), (0.0, 0.0, z0), (x2, 0.0, z0), (x3, 0.0, z0),
        (x0, h1, z0), (0.0, h1, z0), (x2, h2, z0), (x3, h2, z0),
        (x0, 0.0, z1), (0.0, 0.0, z1), (x2, 0.0, z1), (x3, 0.0, z1),
        (x0, h1, z1), (0.0, h1, z1), (x2, h2, z1), (x3, h2, z1),
    ]
    vtx = "\n".join(f"    ({_fmt(x)} {_fmt(y)} {_fmt(z)})" for x, y, z in verts)
    g = Y_GRADING
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      blockMeshDict;
}}

scale 1;

vertices
(
{vtx}
);

blocks
(
    hex (0 1 5 4 8 9 13 12)   ({N_CELLS_X_INLET} {N_CELLS_Y} 1)    simpleGrading (1 {g} 1)
    hex (1 2 6 5 9 10 14 13)  ({N_CELLS_X_DIFFUSER} {N_CELLS_Y} 1) simpleGrading (1 {g} 1)
    hex (2 3 7 6 10 11 15 14) ({N_CELLS_X_OUTLET} {N_CELLS_Y} 1)   simpleGrading (1 {g} 1)
);

edges
(
    polyLine 5 6 ( {poly(z0)} )
    polyLine 13 14 ( {poly(z1)} )
);

boundary
(
    inlet
    {{
        type patch;
        faces ((0 8 12 4));
    }}
    outlet
    {{
        type patch;
        faces ((3 7 15 11));
    }}
    topWall
    {{
        type wall;
        faces
        (
            (4 12 13 5)
            (5 13 14 6)
            (6 14 15 7)
        );
    }}
    bottomSym
    {{
        type symmetry;
        faces
        (
            (0 1 9 8)
            (1 2 10 9)
            (2 3 11 10)
        );
    }}
    frontAndBack
    {{
        type empty;
        faces
        (
            (0 4 5 1)
            (1 5 6 2)
            (2 6 7 3)
            (8 9 13 12)
            (9 10 14 13)
            (10 11 15 14)
        );
    }}
);
"""


def _control_dict():
    return f"""FoamFile
{{
    version 2.0; format ascii; class dictionary; object controlDict;
}}
application     simpleFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {MAX_ITERATIONS};
deltaT          1;
writeControl    timeStep;
writeInterval   {MAX_ITERATIONS};
purgeWrite      2;
writeFormat     ascii;
writePrecision  10;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable no;
"""


def _fv_schemes():
    return """FoamFile
{
    version 2.0; format ascii; class dictionary; object fvSchemes;
}
ddtSchemes      { default steadyState; }
gradSchemes     { default Gauss linear; }
divSchemes
{
    default                       none;
    div(phi,U)                    bounded Gauss linearUpwind grad(U);
    div(phi,k)                    bounded Gauss upwind;
    div(phi,omega)                bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes   { default corrected; }
wallDist        { method meshWave; }
"""


def _fv_solution():
    return f"""FoamFile
{{
    version 2.0; format ascii; class dictionary; object fvSolution;
}}
solvers
{{
    p
    {{
        solver          GAMG;
        smoother        GaussSeidel;
        tolerance       1e-07;
        relTol          0.01;
    }}
    "(U|k|omega)"
    {{
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-08;
        relTol          0.1;
    }}
}}
SIMPLE
{{
    consistent      yes;
    nNonOrthogonalCorrectors 0;
    residualControl
    {{
        p               {RESIDUAL_P};
        U               {RESIDUAL_OTHERS};
        "(k|omega)"     {RESIDUAL_OTHERS};
    }}
}}
relaxationFactors
{{
    fields    {{ p 0.9; }}
    equations {{ U 0.9; "(k|omega)" 0.8; }}
}}
"""


def _inlet_turbulence(velocity):
    k_in = 1.5 * (TURBULENCE_INTENSITY * velocity) ** 2
    length_scale = 0.07 * 2.0 * INLET_HALF_HEIGHT_M
    omega_in = math.sqrt(k_in) / (CMU ** 0.25 * length_scale)
    return k_in, omega_in


def _field_files(velocity):
    k_in, omega_in = _inlet_turbulence(velocity)
    header = "FoamFile\n{{\n    version 2.0; format ascii; class {cls}; object {obj};\n}}\n"
    U = header.format(cls="volVectorField", obj="U") + f"""
dimensions [0 1 -1 0 0 0 0];
internalField uniform ({_fmt(velocity)} 0 0);
boundaryField
{{
    inlet        {{ type fixedValue; value uniform ({_fmt(velocity)} 0 0); }}
    outlet       {{ type inletOutlet; inletValue uniform (0 0 0); value uniform ({_fmt(velocity)} 0 0); }}
    topWall      {{ type noSlip; }}
    bottomSym    {{ type symmetry; }}
    frontAndBack {{ type empty; }}
}}
"""
    p = header.format(cls="volScalarField", obj="p") + """
dimensions [0 2 -2 0 0 0 0];
internalField uniform 0;
boundaryField
{
    inlet        { type zeroGradient; }
    outlet       { type fixedValue; value uniform 0; }
    topWall      { type zeroGradient; }
    bottomSym    { type symmetry; }
    frontAndBack { type empty; }
}
"""
    k = header.format(cls="volScalarField", obj="k") + f"""
dimensions [0 2 -2 0 0 0 0];
internalField uniform {_fmt(k_in)};
boundaryField
{{
    inlet        {{ type fixedValue; value uniform {_fmt(k_in)}; }}
    outlet       {{ type inletOutlet; inletValue uniform {_fmt(k_in)}; value uniform {_fmt(k_in)}; }}
    topWall      {{ type kqRWallFunction; value uniform {_fmt(k_in)}; }}
    bottomSym    {{ type symmetry; }}
    frontAndBack {{ type empty; }}
}}
"""
    omega = header.format(cls="volScalarField", obj="omega") + f"""
dimensions [0 0 -1 0 0 0 0];
internalField uniform {_fmt(omega_in)};
boundaryField
{{
    inlet        {{ type fixedValue; value uniform {_fmt(omega_in)}; }}
    outlet       {{ type inletOutlet; inletValue uniform {_fmt(omega_in)}; value uniform {_fmt(omega_in)}; }}
    topWall      {{ type omegaWallFunction; value uniform {_fmt(omega_in)}; }}
    bottomSym    {{ type symmetry; }}
    frontAndBack {{ type empty; }}
}}
"""
    nut = header.format(cls="volScalarField", obj="nut") + """
dimensions [0 2 -1 0 0 0 0];
internalField uniform 0;
boundaryField
{
    inlet        { type calculated; value uniform 0; }
    outlet       { type calculated; value uniform 0; }
    topWall      { type nutkWallFunction; value uniform 0; }
    bottomSym    { type symmetry; }
    frontAndBack { type empty; }
}
"""
    return {"U": U, "p": p, "k": k, "omega": omega, "nut": nut}


def build_case(design, velocity, case_dir):
    """Write a complete, runnable case for (design, velocity)."""
    case = Path(case_dir)
    if case.exists():
        shutil.rmtree(case)
    (case / "system").mkdir(parents=True)
    (case / "constant").mkdir()
    (case / "0").mkdir()
    (case / "system" / "blockMeshDict").write_text(_block_mesh_dict(design))
    (case / "system" / "controlDict").write_text(_control_dict())
    (case / "system" / "fvSchemes").write_text(_fv_schemes())
    (case / "system" / "fvSolution").write_text(_fv_solution())
    (case / "constant" / "transportProperties").write_text(
        "FoamFile\n{\n    version 2.0; format ascii; class dictionary;"
        " object transportProperties;\n}\n"
        "transportModel Newtonian;\n"
        f"nu [0 2 -1 0 0 0 0] {_fmt(KINEMATIC_VISCOSITY)};\n"
    )
    (case / "constant" / "turbulenceProperties").write_text(
        "FoamFile\n{\n    version 2.0; format ascii; class dictionary;"
        " object turbulenceProperties;\n}\n"
        "simulationType RAS;\n"
        "RAS { RASModel kOmegaSST; turbulence on; printCoeffs off; }\n"
    )
    for name, text in _field_files(velocity).items():
        (case / "0" / name).write_text(text)


# ----------------------------------------------------------------------
# Running
# ----------------------------------------------------------------------

FOAM_ENV_CANDIDATES = (
    "/etc/solver-envs.d/openfoam.sh",       # Alignerr task image
    "/usr/share/openfoam/etc/bashrc",       # Debian/Ubuntu packaged v1912
    "/usr/lib/openfoam/openfoam2412/etc/bashrc",
)


def _foam_env_script():
    override = os.environ.get("FOAM_ENV_SCRIPT")
    if override and Path(override).exists():
        return override
    for cand in FOAM_ENV_CANDIDATES:
        if Path(cand).exists():
            return cand
    raise CaseError("no OpenFOAM environment script found")


def run_foam(command, case_dir, log_name, timeout=RUN_TIMEOUT_SEC):
    """Run a single OpenFOAM utility/solver serially inside the case.

    Sources the solver environment with positional parameters cleared
    (`set --`) and enables `set -u` only afterwards -- both guards are
    load-bearing, see AUTHOR_NOTES 'Bugs found and fixed'.
    """
    env_script = _foam_env_script()
    log_path = Path(case_dir) / log_name
    script = (
        "set -e\n"
        "set --\n"
        f"source '{env_script}' >/dev/null 2>&1 || true\n"
        "set -u\n"
        f"cd '{case_dir}'\n"
        f"{command} > '{log_path}' 2>&1\n"
    )
    proc = subprocess.run(
        ["bash", "-c", script], timeout=timeout,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return proc.returncode, log_path


# ----------------------------------------------------------------------
# Parsing (pure Python; no postProcess dependency)
# ----------------------------------------------------------------------

_LIST_RE = re.compile(
    r"internalField\s+nonuniform\s+List<(scalar|vector)>\s*\n?\s*(\d+)\s*\n?\s*\(",
)


def _read_internal_field(path):
    """Read an ascii internalField (scalar -> floats, vector -> tuples)."""
    text = Path(path).read_text()
    m = _LIST_RE.search(text)
    if not m:
        um = re.search(r"internalField\s+uniform\s+(\(([^)]*)\)|\S+)\s*;", text)
        if um:
            raise CaseError(f"{path}: uniform internalField (solver did not run?)")
        raise CaseError(f"{path}: could not locate internalField list")
    kind, count = m.group(1), int(m.group(2))
    start = m.end()
    depth = 1
    idx = start
    while depth > 0:
        ch = text[idx]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        idx += 1
    body = text[start:idx - 1]
    if kind == "scalar":
        values = [float(tok) for tok in body.split()]
    else:
        values = [
            tuple(float(t) for t in triplet.split())
            for triplet in re.findall(r"\(([^()]*)\)", body)
        ]
    if len(values) != count:
        raise CaseError(f"{path}: expected {count} entries, got {len(values)}")
    return values


def _read_boundary(case_dir):
    """Parse constant/polyMesh/boundary -> {patch: (startFace, nFaces)}."""
    text = (Path(case_dir) / "constant/polyMesh/boundary").read_text()
    patches = {}
    for m in re.finditer(
        r"(\w+)\s*\{([^{}]*)\}", text
    ):
        name, body = m.group(1), m.group(2)
        nf = re.search(r"nFaces\s+(\d+)\s*;", body)
        sf = re.search(r"startFace\s+(\d+)\s*;", body)
        if nf and sf:
            patches[name] = (int(sf.group(1)), int(nf.group(1)))
    return patches


def _read_owner(case_dir):
    text = (Path(case_dir) / "constant/polyMesh/owner").read_text()
    m = re.search(r"\n(\d+)\s*\n\(", text)
    if not m:
        raise CaseError("owner: could not locate face-owner list")
    count = int(m.group(1))
    start = text.index("(", m.start()) + 1
    end = text.index(")", start)
    owners = [int(tok) for tok in text[start:end].split()]
    if len(owners) != count:
        raise CaseError("owner: length mismatch")
    return owners


def _patch_owner_cell_indices(case_dir, patch):
    patches = _read_boundary(case_dir)
    if patch not in patches:
        raise CaseError(f"patch {patch} not found in boundary file")
    start, n = patches[patch]
    owners = _read_owner(case_dir)
    return owners[start:start + n]


def _latest_time_dir(case_dir):
    best = None
    for entry in Path(case_dir).iterdir():
        if entry.is_dir():
            try:
                t = float(entry.name)
            except ValueError:
                continue
            if t > 0 and (best is None or t > best[0]):
                best = (t, entry)
    if best is None:
        raise CaseError("no solved time directory found")
    return best[1]


def parse_check_mesh(log_path):
    text = Path(log_path).read_text(errors="replace")
    result = {
        "mesh_ok": "Mesh OK." in text,
        "max_non_orthogonality": None,
        "max_skewness": None,
        "negative_volume_cells": 0,
    }
    m = re.search(r"Mesh non-orthogonality Max:\s*([0-9.eE+-]+)", text)
    if m:
        result["max_non_orthogonality"] = float(m.group(1))
    m = re.search(r"Max skewness =\s*([0-9.eE+-]+)", text)
    if m:
        result["max_skewness"] = float(m.group(1))
    m = re.search(r"(\d+)\s+cells with negative volume", text)
    if m:
        result["negative_volume_cells"] = int(m.group(1))
    return result


# Residual plateau acceptance: at the higher operating velocities the
# steady solution settles into a benign limit cycle just above the strict
# residualControl targets; a finished run with initial residuals below
# these lax thresholds is still a healthy, usable solution.
LAX_RESIDUAL_LIMIT = 5.0e-4


def parse_solver_log(log_path):
    text = Path(log_path).read_text(errors="replace")
    converged = "SIMPLE solution converged" in text
    # NOTE: must not match the benign startup banner "trapFpe: Floating
    # point exception trapping enabled (FOAM_SIGFPE)".
    diverged = bool(
        re.search(r"Foam::sigFpe|is NaN|FOAM FATAL|FOAM aborting", text)
        and not converged
    )
    finished = converged or text.rstrip().endswith("End")
    last_iter = None
    for m in re.finditer(r"^Time = (\d+)", text, re.MULTILINE):
        last_iter = int(m.group(1))
    last_res = {}
    for field in ("Ux", "p"):
        for m in re.finditer(
            rf"Solving for {field}, Initial residual = ([0-9.eE+-]+)", text
        ):
            last_res[field] = float(m.group(1))
    healthy = converged or (
        finished
        and not diverged
        and last_res.get("p", 1.0) < LAX_RESIDUAL_LIMIT
        and last_res.get("Ux", 1.0) < LAX_RESIDUAL_LIMIT
    )
    return {
        "converged": converged,
        "diverged": diverged,
        "finished": finished,
        "healthy": healthy,
        "iterations": last_iter,
        "final_initial_residuals": last_res,
    }


# ----------------------------------------------------------------------
# Metric extraction
# ----------------------------------------------------------------------

def extract_metrics(case_dir, velocity):
    """Compute Cp, backflow fraction and outlet nonuniformity from the
    solved fields of a completed case."""
    tdir = _latest_time_dir(case_dir)
    p = _read_internal_field(tdir / "p")
    U = _read_internal_field(tdir / "U")
    if any(not math.isfinite(v) for v in p) or any(
        not all(math.isfinite(c) for c in vec) for vec in U
    ):
        raise CaseError("NaN/Inf detected in solved fields")

    inlet_cells = _patch_owner_cell_indices(case_dir, "inlet")
    outlet_cells = _patch_owner_cell_indices(case_dir, "outlet")
    wall_cells = _patch_owner_cell_indices(case_dir, "topWall")

    p_in = sum(p[i] for i in inlet_cells) / len(inlet_cells)
    p_out = sum(p[i] for i in outlet_cells) / len(outlet_cells)
    cp = (p_out - p_in) / (0.5 * velocity * velocity)

    # topWall faces are written block-by-block in boundary declaration
    # order: inlet channel, diffuser, outlet channel.  Skip the inlet
    # channel section; separation is only meaningful downstream of x=0.
    diffuser_wall = wall_cells[N_CELLS_X_INLET:]
    threshold = -BACKFLOW_UX_FRACTION * velocity
    reversed_count = sum(1 for i in diffuser_wall if U[i][0] < threshold)
    backflow_fraction = reversed_count / len(diffuser_wall)

    ux_out = [U[i][0] for i in outlet_cells]
    mean_ux = sum(ux_out) / len(ux_out)
    if abs(mean_ux) < 1.0e-9:
        raise CaseError("degenerate outlet velocity")
    var = sum((u - mean_ux) ** 2 for u in ux_out) / len(ux_out)
    nonuniformity = math.sqrt(var) / abs(mean_ux)

    return {
        "cp": cp,
        "backflow_fraction": backflow_fraction,
        "outlet_nonuniformity": nonuniformity,
        "p_inlet": p_in,
        "p_outlet": p_out,
    }


def validate_mesh(design, work_dir):
    """Mesh-only validation: build, blockMesh, checkMesh, thresholds.

    Returns True when the parametric mesh is usable (independent of any
    solver outcome).
    """
    case_dir = Path(work_dir)
    build_case(design, min(OPERATING_VELOCITIES), case_dir)
    rc, _ = run_foam("blockMesh", case_dir, "log.blockMesh")
    if rc != 0:
        return False
    rc, chk_log = run_foam("checkMesh", case_dir, "log.checkMesh")
    if rc != 0:
        return False
    mesh = parse_check_mesh(chk_log)
    return bool(
        mesh["mesh_ok"]
        and mesh["max_non_orthogonality"] is not None
        and mesh["max_non_orthogonality"] <= MAX_NON_ORTHOGONALITY
        and (mesh["max_skewness"] or 0.0) <= MAX_SKEWNESS
        and mesh["negative_volume_cells"] == 0
    )


def evaluate_design(design, velocity, work_dir):
    """Full deterministic pipeline: build, mesh, check, solve, parse.

    Returns a metrics dict; raises CaseError on unusable results.
    """
    case_dir = Path(work_dir)
    build_case(design, velocity, case_dir)

    rc, _ = run_foam("blockMesh", case_dir, "log.blockMesh")
    if rc != 0:
        raise CaseError("blockMesh failed")
    rc, chk_log = run_foam("checkMesh", case_dir, "log.checkMesh")
    mesh = parse_check_mesh(chk_log)
    if rc != 0 or not mesh["mesh_ok"]:
        raise CaseError("checkMesh reported an unusable mesh")
    if (
        mesh["max_non_orthogonality"] is None
        or mesh["max_non_orthogonality"] > MAX_NON_ORTHOGONALITY
        or (mesh["max_skewness"] or 0.0) > MAX_SKEWNESS
        or mesh["negative_volume_cells"] > 0
    ):
        raise CaseError("mesh quality outside acceptance thresholds")

    rc, sol_log = run_foam("simpleFoam", case_dir, "log.simpleFoam")
    log_info = parse_solver_log(sol_log)
    if rc != 0 or log_info["diverged"] or not log_info["healthy"]:
        raise CaseError("solver failed, diverged, or did not reach a healthy solution")

    metrics = extract_metrics(case_dir, velocity)
    metrics.update(
        {
            "converged": log_info["converged"],
            "iterations": log_info["iterations"],
            "mesh_max_non_orthogonality": mesh["max_non_orthogonality"],
            "mesh_max_skewness": mesh["max_skewness"],
        }
    )
    return metrics


def ideal_cp(area_ratio):
    """Inviscid one-dimensional upper bound for pressure recovery."""
    return 1.0 - 1.0 / (area_ratio * area_ratio)
