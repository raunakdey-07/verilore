![Verilore](https://verilore.vercel.app/logo-light.svg)

[Website](https://verilore.vercel.app/) · [GitHub](https://github.com/raunakdey-07/verilore) · [Changelog](https://github.com/raunakdey-07/verilore/blob/main/CHANGELOG.md)

Give a model only what your team approved, and check what it wrote. Point
Verilore at a folder of brand rules, campaign briefs and product facts, in
Markdown, Word, PowerPoint or PDF: it keeps every version, hands a model only the
current, approved lines a task needs, checks a draft for banned words and wrong
prices and dates, and names the document behind each line. Every answer carries
its source, the time it was true and the exact characters that support it, and a
receipt verifies offline.

## Install

```bash
uv tool install --python 3.13 verilore
```

Or, with a Python from 3.11 to 3.14, `pipx install verilore`.

Verilore runs on macOS and Linux, and on Windows through WSL 2, with Python 3.11
to 3.14 (3.13 at most on an Intel Mac). uv downloads 3.13 if you do not have it,
which also covers a system whose own Python is newer, such as Fedora 45's 3.15
(Fedora's uv downloads only when asked: run `uv python install 3.13` first).
It needs PostgreSQL 15 or newer with pgvector: with Podman or Docker installed,
`verilore init` starts one for you, and to use one you already run, pass
`verilore init --database-url ...`.
[Your system](https://github.com/raunakdey-07/verilore/blob/main/docs/quickstart.md#your-system)
says how to get uv and Podman on each.

## Quickstart

```bash
verilore init
verilore ingest-repo ./brand-kit --corpus brand
verilore brief --corpus brand --task "Instagram caption for the winter offer" --max-tokens 500
verilore check draft.txt --corpus brand --channel Instagram
verilore recall "What does the Assam Gold tin cost?" --corpus brand
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
