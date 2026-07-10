#!/usr/bin/env bash
# Oracle solution: derive the reference diffuser design from the public
# problem definition by running the real solver search, then write the
# required deliverable to /tmp/output/diffuser_design.json.
#
# NOTE: `set -u` is intentionally NOT enabled before the solver
# environment is sourced (inside _case.run_foam) — OpenFOAM's own env
# scripts reference legitimately-unset variables.  All solver-env
# sourcing in this task goes through _case.run_foam, which applies the
# `set --` and deferred `set -u` guards (see AUTHOR_NOTES).

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p /tmp/output
python3 "${SCRIPT_DIR}/design_search.py" /tmp/output/diffuser_design.json

echo "oracle design written:"
cat /tmp/output/diffuser_design.json
