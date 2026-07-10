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

# NOTE: nothing from scorer/ is copied into the image.  The public mesh
# probe under /data is fully self-contained, and the hidden pipeline
# (solver settings, BCs, turbulence model, metrics, anchors) must stay
# invisible to the agent -- exposing it would let an attempt replicate
# the grader and bisect the attachment edge exactly.

RUN mkdir -p /tmp/output && chmod 777 /tmp/output
