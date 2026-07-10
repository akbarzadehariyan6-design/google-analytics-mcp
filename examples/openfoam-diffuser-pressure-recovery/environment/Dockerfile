ARG BASE_IMAGE=lbx-tasks-base
ARG BASE_TAG=runtime-ml-core-py313-local
ARG PROBLEM_DIR=examples/openfoam-diffuser-pressure-recovery

FROM ${BASE_IMAGE}:${BASE_TAG}
USER root

ARG PROBLEM_DIR

# OpenFOAM v2412 is provided by the base image via
# /etc/solver-envs.d/openfoam.sh -- no per-task solver install needed.
# Smoke-test that the solver environment actually loads and the tools
# used by the hidden grader exist.
RUN bash -lc 'set --; source /etc/solver-envs.d/openfoam.sh && \
    command -v blockMesh && command -v checkMesh && command -v simpleFoam'

# Public files visible to the model.
COPY ${PROBLEM_DIR}/data/ /data/

# The deterministic case-builder module backs the public mesh probe.
# Hidden fixtures (scorer/data/anchors.json) are intentionally NOT
# copied into the image -- the grader runs against the repo's scorer
# directory at grade time.
COPY ${PROBLEM_DIR}/scorer/_case.py /opt/scorer/_case.py

RUN mkdir -p /tmp/output && chmod 777 /tmp/output
