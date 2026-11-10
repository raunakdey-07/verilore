# Contributing to Verilore

Thank you for taking the time. Bug reports, documentation fixes and pull requests
are all welcome.

## Reporting a bug

Open an issue with what you ran, what you expected and what happened. Paste the
output of `verilore doctor --report`: it lists your OS, Python, Verilore version,
container engine and every health check, with passwords, tokens and secrets
replaced by `***`. Check it before posting anyway.

A security problem is different: do not open a public issue. See
[SECURITY.md](SECURITY.md).

## Setting up

```bash
git clone https://github.com/raunakdey-07/verilore.git && cd verilore
uv venv --python 3.13 && . .venv/bin/activate
uv pip install -e '.[cli,mcp,dev]'
verilore init        # starts a local PostgreSQL with pgvector (Podman or Docker)
pytest -q
```

The same steps on macOS, Linux and WSL. uv, which the README installs Verilore
with, makes the environment and fetches Python 3.13 if you do not have it: a bare
`python` is not on every system (Debian and Ubuntu name it `python3`), and some
systems' own Python is newer than the dependencies support.

The suite needs that database. It fails, rather than skipping everything, when it
cannot reach one, so a green run always means the tests ran.

## Making a change

- **Test first.** A fix arrives as two commits: one that adds a failing test, then
  the change that makes it pass. CI shows the red run and the green one.
- **Style.** `black` and `flake8`, line length 100. `python -m black .` before
  you push; CI runs both.
- **Say what changed.** Add a paragraph to `CHANGELOG.md` under `[Unreleased]`
  for anything a user would notice.
- **Say only what is measured.** A number in a document names the run or the
  file that produced it, and a limitation stays written down until it is fixed.
  `scripts/check_evidence.py` and `scripts/check_doc_paths.py` enforce part of
  this in CI.
- **Database changes** are new migrations. The existing ones are never edited.

Every pull request runs the full CI, including a clean install from the built
wheel and the laptop setup on Podman. A pull request is merged when CI is green
and it has been reviewed.

## License

By contributing, you agree that your contribution is licensed under the
[Apache License 2.0](LICENSE), the same license as the project.
