#!/usr/bin/env bash
# Master Smith on a Linux cloud box (2026-10-21): Blender 5.2.2 from the official tarball, a venv with the
# requirements, the PRIVATE data repo (kevinpbuckley/proteus-mkii-cloud: the jobs under cloud-data/out, the results)
# beside this one, and cloud/env.sh for every later shell. Idempotent; run from anywhere: bash cloud/setup.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BL=/opt/blender-5.2.2
DATA_REPO="${PROTEUS_DATA_REPO:-$(cd "$ROOT/.." && pwd)/proteus-mkii-cloud}"

if [ ! -x "$BL/blender" ]; then
  mkdir -p /opt && cd /opt
  curl -fsSL -o blender.tar.xz https://download.blender.org/release/Blender5.2/blender-5.2.2-linux-x64.tar.xz
  tar -xJf blender.tar.xz && rm blender.tar.xz && mv blender-5.2.2-linux-x64 "$BL"
fi
# a headless Blender still links the X11/GL libraries; whichever of these works is fine, none of them is fatal here
(apt-get install -y -q libxi6 libxrender1 libxfixes3 libxxf86vm1 libgl1 libsm6 libxkbcommon0 libegl1 >/dev/null 2>&1 \
  || sudo apt-get install -y -q libxi6 libxrender1 libxfixes3 libxxf86vm1 libgl1 libsm6 libxkbcommon0 libegl1 >/dev/null 2>&1 \
  || echo "apt-get unavailable; if Blender will not start, see CLOUD.md 'If Blender will not start'")

# the data repo: cloned by the routine as a second source (a sibling folder), else cloned here
if [ ! -d "$DATA_REPO/cloud-data/out" ]; then
  git clone -q https://github.com/kevinpbuckley/proteus-mkii-cloud "$DATA_REPO" \
    || echo "cannot reach the private data repo at $DATA_REPO; see CLOUD.md 'Set up'"
fi

cd "$ROOT"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

cat > cloud/env.sh <<EOF
# source this in every shell (written by cloud/setup.sh)
export BLENDER_BIN=$BL/blender
export DATA_REPO=$DATA_REPO
export MASTERSMITH_DATA=$DATA_REPO/cloud-data
export JOBS=$DATA_REPO/cloud-data/out
export RESULTS=$DATA_REPO/cloud-data/results
export MASTERSMITH_LOCAL_MODELS_DIR=$DATA_REPO/cloud-data/local-models
export PYTHONIOENCODING=utf-8
export MS="$ROOT/.venv/bin/python -m mastersmith.ms"
EOF
# shellcheck disable=SC1091
source cloud/env.sh
mkdir -p "$MASTERSMITH_LOCAL_MODELS_DIR" "$RESULTS"

echo "== Blender"; "$BLENDER_BIN" -b --version 2>&1 | head -1 || echo "Blender will not start: see CLOUD.md 'If Blender will not start'"
echo "== ms";      $MS models 2>&1 | head -2
if [ -n "${FAL_KEY:-}" ]; then echo "FAL_KEY: set"; else echo "FAL_KEY: MISSING - the environment must carry it; never print it"; fi
echo "== jobs";    ls "$JOBS"
