# Quickstart

Commands only. Each one is the command, not a description of it. The README
explains why; this is for the person who already read it and wants the list.

```bash
# 1. Install. PyPI publishing is planned for v0.11; until then, from GitHub.
#    Verilore runs on Python 3.11 to 3.14; uv downloads 3.13 if you do not have it
#    (on Fedora, see the table below).
uv tool install --python 3.13 git+https://github.com/raunakdey-07/verilore
# or, with a Python from 3.11 to 3.14: pipx install git+https://github.com/raunakdey-07/verilore

# 2. Set up. With Podman or Docker installed, this starts a local PostgreSQL,
#    applies the schema, creates the corpus `default` and records the database
#    for every later command. Running it again changes nothing.
verilore init

# 3. Write one fact and ask about it.
verilore remember "Production uses PostgreSQL." --key datastore
verilore recall "What database does production use?"
```

The first `recall` downloads the embedding model, about 90 MB, once. After that
it works offline. To never download it, set `VERILORE_LEXICAL=1` before step 3
— see [runtime.md](runtime.md#model-free-lexical-mode).

Nothing needs exporting: `init` records the database in
`~/.verilore/config.toml` and every command reads it. The container it creates
is `verilore-postgres`, listening on 127.0.0.1:5432 only, with its data in the
`verilore-pgdata` volume. To use a PostgreSQL you already run, run
`verilore init --database-url postgresql://...` once instead. When something is
wrong, `verilore doctor` checks each piece in order and says which one failed.

## Your system

Verilore runs on macOS and Linux, and on Windows through WSL 2. Step 1 needs uv
and step 2 needs Podman (or Docker); this is how each system gets them. CI
installs Verilore on every system in the table and runs `init`, `remember` and
`recall` there.

| System | uv, for step 1 | Podman, for step 2 |
|---|---|---|
| macOS, Apple silicon | `brew install uv` | `brew install podman && podman machine init && podman machine start` |
| macOS, Intel | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | Docker Desktop, or Podman's installer from podman.io, then `podman machine init && podman machine start` |
| Ubuntu, WSL | `sudo apt install pipx && pipx ensurepath && pipx install uv` | `sudo apt update && sudo apt install -y podman` |
| Debian | `sudo apt install pipx && pipx ensurepath && pipx install uv` | `sudo apt update && sudo apt install -y podman` |
| Fedora | `sudo dnf install uv && uv python install 3.13` | `sudo dnf install -y podman` |
| Arch | `sudo pacman -S uv` | `sudo pacman -S podman` |

After `pipx ensurepath` or uv's installer, open a new terminal so `uv` is on your
PATH. Fedora's uv package downloads a Python only when asked, so the Fedora row
asks for 3.13 once. Homebrew no longer builds Intel bottles for every update, so on an Intel
Mac it may compile from source; uv's installer and Podman's own avoid that.

- **Python.** Verilore runs on Python 3.11 to 3.14, and on Intel Macs 3.11 to
  3.13 (onnxruntime publishes nothing newer for them). `--python 3.13` in step 1
  covers both, and a system whose own Python is newer, such as Fedora 45 with 3.15.
- **Docker instead of Podman** works everywhere: Docker Desktop on macOS, and on
  Windows with WSL integration turned on for your distribution.
- **No container engine?** Point Verilore at a PostgreSQL with pgvector you
  already run: `verilore init --database-url postgresql://...`. On a Mac,
  Postgres.app includes pgvector: run `createdb verilore` with its command-line
  tools, then `verilore init --database-url postgresql://localhost:5432/verilore`.
  That is how CI runs the macOS jobs.
- **WSL.** Run every command inside your Linux distribution (Ubuntu by default),
  not in PowerShell. Windows outside WSL is not supported.
- **64-bit ARM Linux** (a Raspberry Pi 5, an ARM server, WSL on Windows on ARM)
  takes the same commands as its distribution; CI runs it too.

Working on Verilore itself? Install from a clone, then run the same steps:

```bash
git clone https://github.com/raunakdey-07/verilore.git && cd verilore
uv venv --python 3.13 && . .venv/bin/activate
uv pip install -e '.[cli,mcp,dev]'
```

Corpus management: `verilore ingest-repo <path> --delete-removed`,
`verilore corpus reset <name> --yes`, `verilore corpus delete <name> --yes`,
and `verilore posture`.

## Getting a document in

`remember` is for facts. A folder of Markdown goes in with `ingest-repo`, and
plain Markdown needs no annotation: list items, numbered entries and `Key: Value`
lines become claims, each quoted from the file. A `claims:` block in the
frontmatter, as below, is for when you want to name the keys yourself.
[authoring.md](authoring.md) is the reference, and it is the third thing worth
reading.

```bash
mkdir -p ./docs
cat > ./docs/deployment.md <<'EOF'
---
title: Deployment architecture
claims:
  - key: architecture.datastore
    value: PostgreSQL
    claim: The primary datastore is PostgreSQL.
    evidence: The primary datastore is PostgreSQL.
---

# Deployment architecture

The primary datastore is PostgreSQL. It runs in three availability zones.
EOF

verilore ingest-repo ./docs
verilore recall "What is the primary datastore?"
```

Both commands run in-process. Nothing needs a server started.

## When it answers nothing

A document becomes memory from its headings, list items and `Key: Value` lines, or
from an authored `claims:` block. Prose with none of those is stored and searchable
but answers nothing, and comes back named in the output as `no_claims_declared`. An
authored `evidence:` quote must appear verbatim in the document.
[authoring.md](authoring.md) has the rejection messages and what causes each one.

## What to read next

Nothing. That is the whole first hour. When you need more, the
[README](../README.md#documentation) table says which one.
---

## The full walkthrough

Moved out of README.md on 2026-10-14 when it was cut from 883 lines to about
200. Every `$ ` line above is extracted and run against a built wheel by
scripts/cleanroom_quickstart.py, in the "Clean install from the built wheel" CI job.

`requirements.txt` installs the onnxruntime backend and takes about 216 MB. Adding
the `[torch]` extra makes it roughly 1.35 GB instead, to load the same weights
through sentence-transformers; see [the runtime](../docs/runtime.md#the-onnx-backend)
for why the default is the smaller one. To download no model weights at all, set
`VERILORE_LEXICAL=1` from the start: the product then never imports a model, at
the cost of needing shared vocabulary between question and record, which is
[model-free mode](../docs/runtime.md#model-free-lexical-mode).

One thing does arrive on its own: the first `recall` downloads the embedding model
(about 90 MB, once, to the Hugging Face cache) the way a browser fetches a font.
That needs network on that first call and roughly 30 seconds. After that it works
offline. If you would rather it never arrives, set `VERILORE_LEXICAL=1` and Mind
Palace reads with no model at all — see
[model-free mode](../docs/runtime.md#model-free-lexical-mode).

### 2. Check it

```console
$ verilore init
Verilore is ready.
  corpus: default

Record your first memory:

  verilore remember "Production uses PostgreSQL."

Then ask about it:

  verilore recall "What database does production use?"
```

### 3. Remember

A statement becomes authoritative memory with exact-substring evidence, through
the same archive a synced document uses.

```console
$ verilore remember "The production datastore changed from SQLite to PostgreSQL." --key datastore
Remembered.
  version: 5aae989d3134 (new)
  corpus:  default
  path:    memory/datastore-aa7e5b234e1d.md
```

`--key` is how you tell Verilore that two statements are about the same fact.
Remembering the same key with new text supersedes the old value — that is what
`history` shows you.

Remembering the same statement twice changes nothing:

```console
$ verilore remember "The production datastore changed from SQLite to PostgreSQL." --key datastore
Already remembered. Nothing changed, so no new version was recorded.
  version: 5aae989d3134
  corpus:  default
```

Identity is derived from content, so a retry after a lost response converges
instead of duplicating. The filename is the key plus a digest of the key, so two
different facts can never reduce to one document and silently supersede each
other.

### 4. Recall

```console
$ verilore recall "What datastore does production use?"
The production datastore changed from SQLite to PostgreSQL.
   source: memory/datastore-aa7e5b234e1d.md @ 5aae989d3134
   time:   true as of 2026-10-08 03:40 UTC

Ask for the basis with: verilore explain "<question>"
```

Answer, source, and when it was true — that is the default. `--json` gives the
canonical response if a program wants it instead of a person.

Verilore never invents an answer. A question the archive does not cover
abstains rather than guessing:

```console
$ verilore recall "What is our incident response SLA?"
No memory matched that question.
  NO_RELEVANT_MEMORY

Nothing was invented: Verilore records only what was remembered.
```

### 5. Explain

```console
$ verilore explain "What datastore does production use?"
ANSWER
  The production datastore changed from SQLite to PostgreSQL.

TIME
  answer true at:       2026-10-08 03:41 UTC

EVIDENCE
  memory/datastore-aa7e5b234e1d.md > The production datastore changed from SQLite to PostgreSQL.
    "The production datastore changed from SQLite to PostgreSQL."
    characters 0-59 of version 5aae989d3134

HISTORY
  2026-10-08 03:40 UTC  recorded  The production datastore changed from SQLite to PostgreSQL.

VERIFICATION
  receipt available: yes (1 receipt(s))
  authoritative digest: 2c3077bd8d76627348c569dc5bd2227a08696b0aa54bf3f733f71f5abd3b1aa8
  export and verify offline with:
    verilore receipt "What datastore does production use?" -o receipt.json
    verilore verify receipt.json
  Authenticity is not established without a trust anchor you pinned yourself.

This explains the recorded provenance and temporal basis for the memory. It does not establish that the original source was factually correct.
```

`characters 0-59` is the whole claim, and it is an exact span of the archived
text — not a paraphrase, and not a summary of one.

### 6. History

Memory is not only what is true now. It is what was true when.

```console
$ verilore remember "The production datastore is now distributed CockroachDB." --key datastore
Remembered.
  version: 062167c43040 (modified)
  corpus:  default
  path:    memory/datastore-aa7e5b234e1d.md

$ verilore history datastore
2026-10-08 03:40 UTC  recorded  The production datastore changed from SQLite to PostgreSQL.
2026-10-08 03:41 UTC  The production datastore changed from SQLite to PostgreSQL.
            superseded by  The production datastore is now distributed CockroachDB.

current now: The production datastore is now distributed CockroachDB.
```

And the answer before the change is still reachable:

```console
$ verilore recall "What datastore does production use?" \
    --as-of 2026-10-08T03:40:59Z
The production datastore changed from SQLite to PostgreSQL.
   source: memory/datastore-aa7e5b234e1d.md @ 5aae989d3134
   time:   true as of 2026-10-08 03:40 UTC
```

### 7. Receipt and verify

```console
$ verilore receipt "What datastore does production use?" -o receipt.json
Receipt written to receipt.json
Verify it anywhere with: verilore verify receipt.json

$ verilore verify receipt.json
VERIFIED

Integrity:      verified
Provenance:     verified
Temporal state: verified
Supersession:   verified (1 receipt(s))
Authenticity:   not established (supply --trusted-digest to check it)

This means the receipt still matches the memory it describes. It does not mean the original claim was factually true.
```

Verification needs no server, no database, no embedding model and no network.
Hand the file to someone who has never heard of Verilore:

<!-- `verilore` is NOT on PyPI. It is distributed as a source install from
the repository; see the README quickstart for the install command. -->

```console
$ pip install "verilore @ git+https://github.com/raunakdey-07/verilore.git"
$ verilore-proof verify receipt.json
VERIFIED

Integrity:
  authoritative artifact: MATCH
  receipt: MATCH

Provenance:
  claim: MATCH
  evidence: MATCH
  document: MATCH

Temporal state:
  valid_at: MATCH
  supersession: MATCH

Trust:
  authenticity: NOT ESTABLISHED (no trust anchor supplied)

query: What datastore does production use?
receipts checked: 1
memory pack digest: 2c3077bd8d76627348c569dc5bd2227a08696b0aa54bf3f733f71f5abd3b1aa8

This means the artifact still represents the state the receipt describes.
It does not establish that the original source was factually correct.
```

The receipt file carries the response it describes, so no `--pack` and no second
artifact are needed. `verilore-proof` is `argparse` over the standard library,
which is why it works on a bare install.

Tampering is caught and named:

```console
$ verilore verify tampered-receipt.json
REJECTED

Reason:
  the artifact no longer matches the digest the receipt recorded

The receipt describes memory that has since changed, or the artifact has been altered.
Re-issue it with: verilore receipt "<question>" -o receipt.json
```

### 8. Connect an agent

MCP is nearly invisible. Point an agent at `verilore-mcp` and it can recall and
explain the same memory:

```console
$ verilore-mcp
```

```json
{
  "mcpServers": {
    "verilore": {
      "command": "verilore-mcp",
      "env": { "DATABASE_URL": "postgresql://mpadmin:secret@localhost:5432/verilore" }
    }
  }
}
```

An agent asks `memory_recall` for an answer and `memory_explain` when it wants to
know why the answer is trustworthy. Both return the same authoritative memory the
CLI and the SDK do, with the same receipt. OpenCode, Zed and Claude Code each take
a different shape of the same block; [connecting an agent](mcp.md) has all three,
what comes back, and the two argument mistakes that cost a debugging session.

The arguments are one object deep, and **both** `request` and `request.corpus` are
required. This is the shape that works, and the shape an agent will get wrong if
it is not shown:

```json
{
  "name": "memory_recall",
  "arguments": {
    "request": {
      "corpus": "default",
      "query": "Which datastore did we choose?"
    }
  }
}
```

Passing `{"question": "..."}` instead fails with
`1 validation error ... request Field required`, and so does passing `request`
without `corpus`. The full argument schema — including `as_of`, `intent` and
`budget` — is available from the server itself:

```bash
verilore-mcp   # then ask the client for tools/list, or read inputSchema
```

Fifteen tools are advertised. `memory_recall`, `memory_explain`, `memory_current`,
`memory_history`, `memory_changes`, `memory_evidence`, `memory_as_of` and
`memory_replay` all take that same `request` object; `search`, `sync_repo`,
`list_corpora`, `memory_pack` and `memory_snapshot` take their own.

---

## From Python

```python
from verilore import Verilore

client = Verilore()                              # no configuration required

client.remember("We will use PostgreSQL as the primary datastore.", key="decision.datastore")
result = client.recall("Which datastore did we choose?")

for memory in result.current_memories:
    print(memory.claim, memory.path, memory.status)

explained = client.explain("Which datastore did we choose?")
print(explained.receipt["memory_pack_digest"])     # why it was returned, provably
```

Two complete runnable versions:

- [`examples/decision-memory/`](../examples/decision-memory/) — the whole product in one
  file, from `remember` to `verify`.
- [`examples/project-log/`](../examples/project-log/) — this project's own decision log
  as memory. The questions a contributor actually asks, answered with the evidence
  attached, and honestly abstained on where nothing was decided.

### Against a service someone else runs

```python
client = Verilore(base_url="http://127.0.0.1:8000")
```

Everything above works unchanged over HTTP.

### Sharing the warm runtime with a script

```python
client = Verilore(runtime=True)     # opt in; off by default
```

Optional, and rarely needed: a long-running application has the model resident
already, so this would only add a socket hop. It is for short-lived scripts that
would otherwise pay the model import per process. Every result is identical either
way, which is asserted rather than assumed.

---

## Surfaces

One service, four doors. They cannot disagree, and there is a permanent test that
proves it.

| Surface | Entry point |
|---|---|
| CLI | `verilore remember \| recall \| explain \| history \| receipt \| verify` |
| Python SDK | `Verilore().remember() / .recall() / .explain() / .history()` |
| REST | `POST /api/memory/remember`, `POST /api/memory/query`, … |
| MCP | `memory_recall`, `memory_explain`, and the archive operations |

Every one returns the same authoritative memory, the same evidence, the same
temporal state and the same receipt.

`POST /api/memory/remember` takes a statement and nothing else. Reading a file is
a decision for a trusted operator at their own machine — `verilore remember
--file` and the SDK's `file=` do it, and the HTTP endpoint deliberately does not,
because a path would let any caller with a credential read a file relative to the
server and recall its contents. A credential says which corpora you may reach; it
does not say you may read the server's filesystem.

### The full memory API

The five commands above are the product. The rest exists when you need it:

```bash
verilore memory current     --corpus C --query "..."   # what is true now
verilore memory changes     --corpus C                 # what changed
verilore memory evidence    --corpus C --claim-id ID   # why one claim holds
verilore memory as-of       --corpus C --as-of T       # what was true at T
verilore memory snapshot    --corpus C                 # freeze a state
verilore memory replay      --corpus C --snapshot-id ID # read a frozen state
verilore memory pack        --corpus C                 # bounded context for a model
verilore memory feed        --corpus C                 # durable change feed
```

These commands read the local database in-process, like the five commands above.
Pass `--base-url http://host:8000` (or set `VERILORE_BASE_URL`) only when a
separate Verilore service holds the memory. `verilore serve --run` starts
that service.

`verilore memory query` exposes the full operation: intent selection, an
explicit budget, and selectors such as `--claim-id` and `--snapshot-id`.

---

## Errors

Failures answer what happened, why, and what to run.

```console
$ verilore recall "..."   # with the database stopped
error: The memory database is unavailable. (database_unavailable)
  why: Verilore could not connect to PostgreSQL at localhost:5432.
  fix: verilore init
  more: verilore doctor   ·   rerun with --debug for the full traceback
```

`--verbose` appends the underlying exception's type and message. It is never
the only thing you see, and never the first thing. `--debug` (or
`VERILORE_DEBUG=1`) adds the full traceback, for the case where one line of
detail is not enough.

A refused connection is never a stack trace. The database not answering is an
ordinary situation, and the answer to it is a sentence and a command.

When the database is local and stopped, Verilore starts it for you: it
looks for a container publishing the configured port and starts the stopped
one it finds. `verilore init` also creates the `verilore-postgres` container
when there is none, so it is one command on a machine that has never run
Verilore. A database on another host is never touched. Every failure exits 1
(2 for a mistyped command), and `verilore doctor --report` prints a block to
paste into an issue, with every password and token replaced by `***`.

---

## Project structure

```text
verilore/            the package; the only top-level name the wheel installs
  api/               FastAPI app, services, and the authoritative memory model
    models/          the public v1 contract; no persistence models exposed
    routers/         REST adapters
    services/        memory archive, ingestion, retrieval, relevance
  cli/               Typer CLI, rendering, error text
  migrations/        Alembic migrations
  sdk.py             the Python SDK (`from verilore import Verilore`)
  errors.py          the error taxonomy
  mcp_server.py      MCP server
  pack.py            dependency-free portable memory reader
  receipt.py         the receipt contract, standard library only
  proof.py           proof construction and verification
  proof_cli.py       standalone verifier, no optional dependencies
  runtime.py         the background runtime's entry point
verilore_sdk.py      deprecated shim for `verilore.sdk`; removed in v0.12
verilore_errors.py   deprecated shim for `verilore.errors`; removed in v0.12
tests/               the suite, against real PostgreSQL
examples/            runnable examples
docs/                status, operations, research, release notes
scripts/             benchmarks, probes, release checks
```
## Connecting an agent over MCP

There is no `verilore mcp` command. The server is an executable named
`verilore-mcp`, installed by the `[mcp]` extra, and it speaks JSON-RPC over
stdin/stdout — a client starts it, you do not type at it. It used to print
nothing at all for `--help`; it prints usage now.

```console
$ pip install 'verilore[mcp]'

$ verilore credential issue my-agent -c default -r read_write
$ export VERILORE_MCP_CREDENTIAL=mpk_...

$ verilore-mcp --help
```

`VERILORE_MCP_CREDENTIAL` takes the raw `mpk_...` secret. Mint one with
`verilore credential issue <name> -c <corpus> -r read_write`; the corpus and
role must match what the agent will touch. It is an environment variable rather
than a tool argument on purpose — a caller that could pass its own credential
would need no authorization at all.

An agent can then write memory with the `memory_remember` tool, whose arguments
are `statement`, `corpus`, and optionally `key` and `file`
([authoring.md](authoring.md#memory_remember)).
