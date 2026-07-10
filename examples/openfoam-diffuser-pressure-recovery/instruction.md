# Planar Diffuser Pressure-Recovery Design

You are designing the expansion section of a two-dimensional planar
diffuser for a low-speed air duct. The duct carries air (kinematic
viscosity 1.5e-5 m^2/s) from a straight inlet channel of full height
0.08 m, through a contoured symmetric expansion of your design, into a
straight outlet settling channel. Your goal is to maximize static
pressure recovery across the whole operating envelope while keeping the
flow attached and the delivered outlet flow acceptably uniform.

## Deliverable

Write exactly one file:

    /tmp/output/diffuser_design.json

containing a single JSON object with exactly these four numeric fields
(SI units, plain numbers, no strings):

```json
{
  "area_ratio": 1.9,
  "length_m": 0.60,
  "wall_blend": 0.5,
  "inflection_position": 0.5
}
```

A starter copy of this template is provided at
`/data/diffuser_design_template.json`.

## Geometry parameterization

The duct is symmetric about its centerline; the design controls the
half-height contour h(x) of the expansion section, which runs from
x = 0 (inlet-channel exit, half-height h1 = 0.04 m) to x = length_m
(outlet-channel entry, half-height h2 = area_ratio * h1):

- `area_ratio` — outlet-to-inlet area ratio (h2/h1). Bounds: [1.4, 3.2].
- `length_m` — axial length of the expansion section in meters.
  Bounds: [0.25, 0.72].
- `wall_blend` — shape mix in [0.0, 1.0]: 0.0 gives a straight (conical)
  wall ramp; 1.0 gives a smoothstep-blended wall; intermediate values
  interpolate linearly between the two.
- `inflection_position` — normalized axial location in [0.25, 0.75] of
  the smoothstep midpoint (only meaningful when wall_blend > 0).

The precise contour: with xi = x / length_m in [0, 1], and t the
piecewise-linear remap of xi that sends [0, c] to [0, 0.5] and [c, 1]
to [0.5, 1] (c = inflection_position),

    h(xi) = h1 + (h2 - h1) * [ (1 - b) * xi + b * (3 t^2 - 2 t^3) ]

with b = wall_blend. The contour must be monotonically expanding (it is,
for any parameters within bounds). The inlet channel (length 0.24 m)
and outlet channel (length 0.36 m) are fixed and not part of the design.

## Operating envelope

The design is evaluated at four fixed inlet bulk velocities:
**6, 10, 14, and 18 m/s** (duct-height Reynolds numbers roughly
3.2e4 to 9.6e4). All four operating points count; the worst-performing
point carries substantial extra weight.

## Evaluation

Your design is evaluated with a fixed, deterministic viscous
flow-analysis pipeline (identical settings for every submission — only
your four numbers change the outcome). Scoring, in physical terms:

- **Validity and feasibility (small fraction of credit):** the file
  parses against the schema, all four values are within bounds, the
  geometry is non-degenerate, and the resulting flow analysis completes
  in a healthy state at every operating point. A submission whose flow
  analysis fails, diverges, or produces non-physical values at ANY of
  the four velocities forfeits all physics credit.
- **Attachment (graded, strict):** the fraction of the expansion/outlet
  wall showing reversed near-wall flow must stay at or below 0.002 for
  full credit at each velocity; credit falls to zero by 0.010.
- **Outlet uniformity (graded):** the delivered outlet velocity profile
  should be as uniform as practical; the worst operating point governs.
- **Pressure recovery (majority of credit):** the static pressure-
  recovery coefficient Cp = (p_outlet - p_inlet) / (0.5 * rho * U^2),
  measured between the duct inlet and outlet planes, is scored at each
  velocity against a fixed internal scale that awards ZERO at the
  recovery level of the published reference design (see
  `/data/public_baseline_summary.json` — a sound straight-walled,
  full-length diffuser) and full credit at the best achievable recovery
  within the stated bounds. Credit grows strongly sub-linearly, so
  small improvements over the reference earn very little. The minimum
  across the four velocities (worst-case robustness) carries the
  LARGEST single weight in the rubric — a design that excels at three
  velocities but degrades at one is scored primarily by that one.

There is no partial credit for designs that trade attachment for raw
recovery: at each velocity the recovery credit is scaled by that
velocity's attachment credit, so a separated design forfeits its
recovery credit no matter how high its raw Cp is.

## Public files

Available under `/data`:

- `diffuser_design_template.json` — deliverable schema starter.
- `duct_specifications.json` — geometry, fluid, bounds, velocities.
- `public_baseline_summary.json` — measured performance of the
  published reference design at all four velocities (this is the
  zero-credit level of the recovery scale).
- `public_calibration_samples.json` — measured performance of several
  non-optimal sample designs across the design space, including
  separated and attached examples, to help you calibrate the
  recovery/attachment tradeoff.

## Constraints and notes

- One-dimensional inviscid theory bounds recovery at
  Cp_ideal = 1 - 1/area_ratio^2; real viscous recovery is lower, and
  aggressive expansions separate — most severely at the LOWEST
  velocity (lowest Reynolds number), not the highest.
- Larger area ratios raise the ideal recovery but risk separation;
  longer diffusers delay separation but the length bound is fixed.
- Submit exactly the four schema fields; extra fields are ignored.
- Final answers must be under /tmp/output as specified above.
