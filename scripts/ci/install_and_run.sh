#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Raunak Dey
#
# Install the Verilore wheel the way docs/quickstart.md tells a person to on this
# system, then run the first commands with each install. CI runs it inside each
# Linux distribution's own container (Debian, Ubuntu, Fedora, Arch) and on the
# macOS runners; WSL runs the same Linux userlands.
#
#   bash scripts/ci/install_and_run.sh <directory holding the wheel>
#
# Two installs, as the quickstart offers them:
#   uv     `uv tool install --python 3.13`: always, on every system.
#   pipx   with the system's own `python3`, when that Python is one the wheel
#          admits; otherwise skipped, as the quickstart tells that person to use uv.
# Both install from binary wheels only (`--no-build`, `--only-binary=:all:`), so a
# dependency that would need a compiler on someone's laptop fails here instead.
#
# Needs DATABASE_URL pointing at a PostgreSQL with pgvector. It is handed to
# `verilore init --database-url` and then unset, so `remember` and `recall` find
# the database the way a person's later commands do: from the config file init
# wrote. Model-free (VERILORE_LEXICAL=1).

set -euo pipefail

dist_dir="$(cd "${1:?usage: install_and_run.sh <directory holding the wheel>}" && pwd)"
wheel="$(ls "$dist_dir"/verilore-*.whl)"
: "${DATABASE_URL:?DATABASE_URL must point at a PostgreSQL with pgvector}"

as_root() {
  if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi
}

# The same packages docs/quickstart.md names for this system.
if [ "$(uname -s)" = "Darwin" ]; then
  echo "== macOS $(sw_vers -productVersion) ($(uname -m))"
  if [ "$(uname -m)" = "arm64" ]; then
    HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1 brew install uv > /dev/null
  else
    # Homebrew no longer builds Intel bottles for every update, so an Intel Mac
    # may compile from source; uv's own installer is a single download there.
    curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
  # pipx the way its own documentation installs it, with the Python on PATH.
  python3 -m venv "${TMPDIR:-/tmp}/pipx-venv"
  "${TMPDIR:-/tmp}/pipx-venv/bin/pip" install --quiet pipx
  export PATH="${TMPDIR:-/tmp}/pipx-venv/bin:$PATH"
else
  # shellcheck disable=SC1091
  . /etc/os-release
  echo "== ${PRETTY_NAME} ($(uname -m))"
  case " ${ID} ${ID_LIKE:-} " in
    *" debian "* | *" ubuntu "*)
      export DEBIAN_FRONTEND=noninteractive
      as_root apt-get update -qq
      as_root apt-get install -y -qq python3 python3-venv pipx ca-certificates > /dev/null
      # Debian and Ubuntu do not package uv; the quickstart installs it with pipx.
      PIPX_BIN_DIR=/usr/local/bin pipx install uv > /dev/null
      ;;
    *" fedora "*)
      as_root dnf install -y -q python3 pipx uv
      # Fedora's uv sets python-downloads = "manual" in /etc/uv/uv.toml, so it
      # fetches a Python only when asked; the quickstart's Fedora row asks.
      uv python install 3.13
      ;;
    *" arch "*)
      as_root pacman -Syu --noconfirm --needed python python-pipx uv > /dev/null
      ;;
    *)
      echo "no install recipe for ${ID}: add one here and in docs/quickstart.md" >&2
      exit 1
      ;;
  esac
fi

# The Python range the wheel itself declares, read from the wheel.
read -r low high < <(python3 - "$wheel" <<'PY'
import re, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    meta = next(n for n in z.namelist() if n.endswith(".dist-info/METADATA"))
    text = z.read(meta).decode()
spec = re.search(r"^Requires-Python: (.+)$", text, re.M).group(1)
low = re.search(r">=\s*3\.(\d+)", spec).group(1)
high = re.search(r"<\s*3\.(\d+)", spec).group(1)
print(low, high)
PY
)
system_minor="$(python3 -c 'import sys; print(sys.version_info[1])')"
echo "system python3: 3.${system_minor}; the wheel admits 3.${low} to 3.$((high - 1))"

work="$(mktemp -d)"
installs=()

# 1. uv, with the Python the README names. uv downloads it when it is missing.
export UV_TOOL_DIR="$work/uv-tools" UV_TOOL_BIN_DIR="$work/uv-bin"
uv tool install --python 3.13 --no-build "$wheel"
installs+=("uv:$UV_TOOL_BIN_DIR")

# 2. pipx, with the system's own Python, when the wheel admits it.
if [ "$system_minor" -ge "$low" ] && [ "$system_minor" -lt "$high" ]; then
  export PIPX_HOME="$work/pipx" PIPX_BIN_DIR="$work/pipx-bin"
  pipx install --python "$(command -v python3)" --pip-args="--only-binary=:all:" "$wheel"
  installs+=("pipx:$PIPX_BIN_DIR")
else
  echo "pipx: skipped; python3 3.${system_minor} is outside what the wheel admits," \
    "and the quickstart sends this system to uv"
fi

# The first commands, with each install. Outside any checkout, so only the
# installed package can answer, and with nothing exported but the data dir.
cd "$work"
database_url="$DATABASE_URL"
unset DATABASE_URL
export VERILORE_LEXICAL=1 VERILORE_RUNTIME=0
for entry in "${installs[@]}"; do
  how="${entry%%:*}"
  bin="${entry#*:}"
  echo "== the first commands, installed with ${how}"
  export VERILORE_DATA_DIR="$work/data-${how}"
  # The compiled dependencies load in the environment the tool runs in.
  tool_python="$(dirname "$(readlink -f "$bin/verilore")")/python"
  "$tool_python" -c "import sys, onnxruntime, tokenizers, asyncpg, psycopg2; print('python', sys.version.split()[0])"
  "$bin/verilore" --help > /dev/null
  "$bin/verilore-proof" --help > /dev/null
  "$bin/verilore-mcp" --help > /dev/null
  "$bin/verilore" init --database-url "$database_url"
  "$bin/verilore" remember "The primary datastore is PostgreSQL." --key datastore
  "$bin/verilore" recall "What is the primary datastore?"
done
echo "== ok: ${installs[*]%%:*}"
