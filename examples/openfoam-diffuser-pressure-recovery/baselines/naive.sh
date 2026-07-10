#!/usr/bin/env bash
# Weak calibration baseline: a sensible mid-bounds design that meshes,
# converges, and stays attached — but makes no attempt to optimize
# pressure recovery.  It sits below the published zero-credit reference
# design, so it should earn only the validity/health/guardrail fraction
# of the reward (~0.3), never the physics objective.

set -euo pipefail

mkdir -p /tmp/output
cat > /tmp/output/diffuser_design.json <<'EOF'
{
  "area_ratio": 1.9,
  "length_m": 0.60,
  "wall_blend": 0.5,
  "inflection_position": 0.5
}
EOF
echo "naive baseline design written"
