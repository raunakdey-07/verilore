#!/usr/bin/env bash
# Upgrade safety: build a previous-release archive, upgrade it to head, prove nothing moved.
#
#   DATABASE_URL=postgresql://... ./scripts/release/upgrade_safety.sh
#
# ## Why this is a CI job and not a script somebody runs
#
# Every other thing this project measures is about the code as it is now. This is
# about code that no longer exists meeting code that does, and the only machine
# that can be sure is a fresh one every time. A downgrade test that runs when
# somebody remembers has a habit of not running.
#
# ## What it does, in order
#
#   1. check out BASE_TAG (default v0.11.0) into a temporary tree
#   2. install that release into its own venv (never the editable HEAD install)
#   3. migrate a FRESH database to the base release's head, derived from the base
#      tree's own migration files
#   4. populate it through the base release's own `remember`, including the default
#      corpus, a superseded claim, a conflict and a snapshot
#   5. export a receipt and a Memory Pack with the base release, and record them
#   6. migrate the same database to this branch's head
#   7. assert: the old receipt still verifies offline, claim identities did not
#      move, no claim was lost, and the pack is byte-identical with the clock pinned
#   8. downgrade back to the base head and up again, and assert the same things
#
# Step 4 uses the BASE source tree deliberately. An upgrade test that builds its
# fixture with the NEW code proves nothing: it reads back its own assumptions.
# The base release builds its own fixture with its own code in its own venv --
# that is what this job is meant to prove.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${PYTHON:-python}"
WORK="$(mktemp -d)"
BASE_TAG="${UPGRADE_BASE_TAG:-v0.11.0}"
OLD="$WORK/$BASE_TAG"
BEFORE="$WORK/before"
AFTER="$WORK/after"

export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export VERILORE_RUNTIME=0
export VERILORE_AUTH_MODE=off

cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

say() { printf '  %s\n' "$*"; }

# alembic.ini for a tree: old releases keep migrations/alembic.ini, the new
# layout lives at verilore/migrations/alembic.ini. Pick by what exists.
alembic_ini_for() {
  local tree="$1"
  if [ -f "$tree/verilore/migrations/alembic.ini" ]; then
    echo "$tree/verilore/migrations/alembic.ini"
  elif [ -f "$tree/migrations/alembic.ini" ]; then
    echo "$tree/migrations/alembic.ini"
  else
    echo "::error::no alembic.ini found in $tree" >&2
    return 1
  fi
}

NEW_INI="$(alembic_ini_for "$REPO")"

[ -n "${DATABASE_URL:-}" ] || { echo "::error::DATABASE_URL is required"; exit 1; }

# 1. The previous release, from its tag. Not from a branch: the tag is what users
#    installed, and a branch would drift.
say "checking out $BASE_TAG"
git -C "$REPO" worktree add --detach --force "$OLD" "$BASE_TAG" >/dev/null 2>&1 \
  || { echo "::error::could not check out $BASE_TAG"; exit 1; }

OLD_INI="$(alembic_ini_for "$OLD")"

# The base release builds and runs in its own venv, so the editable HEAD install
# on this branch cannot shadow its imports (for example verilore.api.services
# resolving to HEAD code that references columns the base schema lacks).
BASE_VENV="$WORK/base-venv"
BASE_PY="$BASE_VENV/bin/python"
say "installing $BASE_TAG into its own venv ($OLD[cli,migrations])"
"$PY" -m venv "$BASE_VENV" >/dev/null
# `[migrations]` is required: `env.py` rewrites the sync driver to psycopg2,
# which lives in that extra, not in `[cli]` or the base deps.
"$BASE_PY" -m pip install "$OLD[cli,migrations]"

# The base head revision, derived from the base tree's own migration files --
# never hard-coded, so the job survives the next tag. Derived with the same
# pure-Python logic as scripts/release/check_versioning.py (a head is a
# revision no other migration lists as its down_revision), rather than by
# running `alembic heads` in the base venv: the base venv may lack alembic's
# working directory or a plugin, and a silent `2>/dev/null` made that failure
# look like a hang. Failures here are loud now.
BASE_HEAD="$("$BASE_PY" - "$OLD" <<'PY'
import re, sys
from pathlib import Path

old = Path(sys.argv[1])
versions_dir = old / "verilore" / "migrations" / "versions"
if not versions_dir.is_dir():
    versions_dir = old / "migrations" / "versions"

down_revisions = {}
for path in sorted(versions_dir.glob("*.py")):
    if path.name.startswith("__"):
        continue
    text = path.read_text(encoding="utf-8")
    rev = re.search(r'^revision\s*(?::\s*[^=\n]*)?\s*=\s*"([^"]*)"', text, re.M)
    if not rev:
        continue
    down = re.search(r"^down_revision\s*(?::\s*[^=\n]*)?\s*=\s*(.+)$", text, re.M)
    if down is None:
        downs = []
    else:
        raw = down.group(1).strip()
        if raw in ("None", "none", "()", "[]"):
            downs = []
        elif raw.startswith('"') and raw.endswith('"'):
            downs = [raw[1:-1]]
        elif raw.startswith("'") and raw.endswith("'"):
            downs = [raw[1:-1]]
        else:
            downs = [p.strip().strip("\"'") for p in raw.strip("()[]").split(",") if p.strip()]
    down_revisions[rev.group(1)] = downs

referenced = {d for downs in down_revisions.values() for d in downs}
heads = [rev for rev in down_revisions if rev not in referenced]
if len(heads) != 1:
    print(f"expected exactly one migration head, found: {heads}", file=sys.stderr)
    sys.exit(1)
print(heads[0])
PY
)"
if [ -z "$BASE_HEAD" ]; then
  echo "::error::could not determine the base migration head from $OLD_INI" >&2
  exit 1
fi
say "base migration head: $BASE_HEAD"

# 2. The base release's schema. Migrate a fresh database to the base head.
say "migrating the fresh database to $BASE_TAG's head ($BASE_HEAD)"
( cd "$OLD" && DATABASE_URL="$DATABASE_URL" PYTHONPATH="$OLD" \
    "$BASE_PY" -m alembic -c "$OLD_INI" upgrade "$BASE_HEAD" >/dev/null )

# 3 + 4. Write through the BASE code, and export the proof with the BASE code.
say "populating through $BASE_TAG's own write path and exporting its proof"
SRC="$OLD" "$BASE_PY" "$OLD/scripts/release/make_upgrade_fixture.py" \
  --out "$BEFORE" --label "$BASE_TAG"

# 5. The upgrade, with this branch.
say "upgrading to this branch's head"
"$PY" -m alembic -c "$NEW_INI" upgrade head >/dev/null

# 6a. The RUNTIME-ROLE assertions.
#
#     assert_upgrade.py runs as a superuser, and a superuser bypasses row-level
#     security -- so it cannot see a policy keyed on the wrong column. This
#     project's development database carried exactly that bug for months
#     (`USING (mindpalace_allowed_corpus(id))` on `memory_documents`, whose
#     column is `corpus_id`) and every superuser test passed.
#
#     So the same archive is re-read as `mindpalace_runtime`, through a
#     credential granted to the existing corpora, and the two views must agree.
say "provisioning the least-privileged role and asserting the runtime view"

# Not `>/dev/null` with no check.
#
# This step is what makes every assertion after it meaningful -- without the
# least-privileged role and its policies there is nothing to assert against --
# and a silent failure here surfaces much later as "the server did not start",
# which points at the wrong file entirely. It already cost one debugging round
# trip on CI. The password is not in the output to begin with (the script
# suppresses it), so showing it costs nothing.
if ! psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -v runtime_password=upgrade-safety-role-password \
  -f "$REPO/scripts/db/runtime_roles.sql"; then
  echo "::error::could not provision the least-privileged runtime role."
  echo "::error::Every assertion after it would run against a database"
  echo "::error::with no row-level security, so this is fatal rather than skipped."
  exit 1
fi

# Migration 015 makes a server deployment refuse to start with scope-token
# enforcement off unless the operator acknowledges forgery. The server started
# below (assert_runtime_role.py) runs in server mode, so this job must prove the
# upgrade works in the secure configuration: rotate a real scope secret into the
# upgraded database, enable enforcement as the owner role, and hand the secret
# to the server through the environment -- exactly as a real deployment does.
SCOPE_SECRET=$(openssl rand -hex 32)
if ! psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -c "INSERT INTO memory_server_secrets (name, value) VALUES ('scope_hmac_secret', '$SCOPE_SECRET') ON CONFLICT (name) DO UPDATE SET value = EXCLUDED.value; SELECT mp_set_scope_token_enforcement(true);"; then
  echo "::error::could not rotate the scope secret or enable enforcement."
  echo "::error::The server started below would refuse to start, which would mask"
  echo "::error::the real upgrade assertion. Fatal rather than skipped."
  exit 1
fi
export VERILORE_SCOPE_SECRET="$SCOPE_SECRET"
export VERILORE_ENFORCE_SCOPE_TOKEN=on

# Same scheme, host, port and database; a different identity. The scheme is kept
# because a driver-qualified URL (`postgresql+asyncpg://`) is what the engine
# expects, and userinfo is the only part that changes.
SCHEME="${DATABASE_URL%%://*}"
REST="${DATABASE_URL##*@}"
RUNTIME_URL="${SCHEME}://mindpalace_runtime:upgrade-safety-role-password@${REST}"

if [ -z "$REST" ] || [ "$REST" = "$DATABASE_URL" ]; then
  echo "::error::could not build a runtime-role URL from DATABASE_URL"
  exit 1
fi

# The credential is issued, and the grants happen, INSIDE the assertion script.
# That is not tidiness: the operator step being asserted is "before the grant
# this reader sees one corpus, after the grant it sees them all", and the only way
# to observe the first half is to be the process that performs the second.
VERILORE_SUPERUSER_URL="$DATABASE_URL" \
"$PY" "$REPO/scripts/release/assert_runtime_role.py" \
  --superuser-url "$DATABASE_URL" \
  --runtime-url "$RUNTIME_URL" \
  --before "$BEFORE"

#     Proven, not assumed. Session 5 mutated migration 008 to key the
#     `memory_documents` policy on `id` instead of `corpus_id` -- the defect
#     this project's development database carried -- and the job exited 1.
#
#     Two details of that mutation matter, and both were learned the hard way.
#
#     A blanket `column = "id"` for every table is NOT the test: PostgreSQL
#     rejects it at migration time with `column "id" does not exist` on
#     `ingestion_manifest`, so it proves the migration runs, not that the gate
#     can see a policy. `memory_documents` has BOTH columns, which is exactly
#     why the real defect survived: PostgreSQL accepted the statement and the
#     policy filtered on the wrong thing.
#
#     And it was caught by the claim-identity comparison, not by recall. Under
#     the mutation the runtime role answered recall, explain and history
#     normally, because those read `memory_claims`, whose policy still names
#     `corpus_id`. Only the document-identity read -- superuser 5, runtime 0 --
#     showed the loss. A gate that asserted "the API works" would have passed
#     this broken schema.
#
say "asserting the runtime view"
# 6b. The archive assertions.
say "asserting the upgrade preserved the archive"
SRC="$REPO" "$PY" "$REPO/scripts/release/make_upgrade_fixture.py" \
  --out "$AFTER" --label head --export-only
"$PY" "$REPO/scripts/release/assert_upgrade.py" --before "$BEFORE" --after "$AFTER"

# 7. The round trip. A downgrade that loses memory is a release blocker; a
#    downgrade that destroys tenants is a documented consequence, not a failure,
#    so the assertions after it are about memory, not about principals.
say "downgrading to $BASE_HEAD and back up again"
"$PY" -m alembic -c "$NEW_INI" downgrade "$BASE_HEAD" >/dev/null
"$PY" -m alembic -c "$NEW_INI" upgrade head >/dev/null

ROUND="$WORK/roundtrip"
SRC="$REPO" "$PY" "$REPO/scripts/release/make_upgrade_fixture.py" \
  --out "$ROUND" --label roundtrip --export-only
"$PY" "$REPO/scripts/release/assert_upgrade.py" --before "$BEFORE" --after "$ROUND" \
  --skip-runtime

git -C "$REPO" worktree remove --force "$OLD" >/dev/null 2>&1 || true
say "upgrade safety: passed"
