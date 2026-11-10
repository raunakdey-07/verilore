# Verilore

Memory for AI applications that remembers what changed, what was true when, and
why to believe the recorded state. Add Verilore to an application, record a fact,
and get back an answer with its source, the time it was true, and the exact
characters that support it. Export a receipt and verify it on a machine that has
never heard of Verilore.

## Install

```bash
pipx install verilore
# or
uv tool install verilore
```

Verilore needs Python 3.11 or newer and PostgreSQL 15 with pgvector. With Podman
or Docker installed, `verilore init` starts that database for you; to use a
PostgreSQL you already run, pass `verilore init --database-url ...`.

## Quickstart

```bash
verilore init
verilore ingest-repo ./docs --corpus project
verilore recall "What is the primary datastore?" --corpus project
verilore explain "What is the primary datastore?" --corpus project
```

`init` sets up the database and records it for every later command, so nothing
needs exporting. Something wrong? Run `verilore doctor`.

From Python:

```python
from verilore import Verilore

client = Verilore("default")
client.remember("Support answers within one business day.", key="support.sla")
memory = client.recall("What is the support SLA?").current_memories[0]
print(f"{memory.claim}  [{memory.status}]")
```

## Links

- [README](https://github.com/raunakdey-07/verilore#readme): what it is, and what it refuses to do
- [Integration guide](https://github.com/raunakdey-07/verilore/blob/main/docs/integration/guide.md): wiring it into an app
- [Changelog](https://github.com/raunakdey-07/verilore/blob/main/CHANGELOG.md)
- [License: Apache-2.0](https://github.com/raunakdey-07/verilore/blob/main/LICENSE)
