# Tag checklist

The list of things that must be true before a tag exists, re-run for every
tag. The owner alone decides when to cut one.

State when `v0.11.0` was prepared, 2026-11-10:

| | |
|---|---|
| latest tag | **`v0.10.0`**, at `1fad1e8` |
| `pyproject.toml` version | `0.11.0`, the release being prepared |
| schema head | `016`, unchanged since `v0.10.0` |
| migrations shipped since the last tag | none |

## Before a tag

### Version and identity

- [ ] `pyproject.toml` version matches the tag exactly.
- [ ] `CHANGELOG.md` has a dated entry for this version, not `[Unreleased]`.
- [ ] `docs/release-map.md` maps the milestone identifiers to this version.
- [ ] The release notes **lead with the upgrade notes**: new migrations (if
      any), a one-time step such as `verilore reindex`, renamed or removed
      imports and commands, and what a downgrade destroys.
- [ ] `docs/security.md`'s applicability note names **this version**, not a
      branch, and which tag first shipped each migration it relies on.

### Green, on a runner, at the tagged commit

- [ ] A CI run at the exact commit that will be tagged: `success`, every job
      green, nothing skipped.
- [ ] The `Run tests` job's junitxml is attached to that run, and
      `check_evidence --require-head` passed against it — i.e. the "N passed"
      figure in `STATUS.md` came from that run, not from a person.
- [ ] The skip gate passed: every skipped test is on
      `scripts/check_skips.py`'s allowlist, which currently holds exactly two
      entries and both are opt-in.
- [ ] `check_evidence --strict` passes locally against the same tree.

### The upgrade and downgrade claims, re-proven at this commit

- [ ] `$BASE_TAG` archive → `upgrade head` preserves every claim identity; no claim
      is lost; the old receipt still verifies offline; the Memory Pack is
      byte-identical with the clock pinned. (`$BASE_TAG` defaults to v0.10.0 in
      `scripts/release/upgrade_safety.sh`; override with `UPGRADE_BASE_TAG`.)
- [ ] `upgrade head` → `$BASE_HEAD` → `upgrade head` preserves the same, **and** a
      mutation is proven to be caught. A mutation that *survives* is a release
      blocker, not a documentation item. (`$BASE_HEAD` is derived from the base
      tree's migration head by the script.)
- [ ] After tagging, bump `BASE_TAG` in `scripts/release/upgrade_safety.sh` to the
      new tag.
- [ ] The downgrade-destroys-`memory_principals` claim in the CHANGELOG is
      still true at this commit. It is a destructive claim about a user's
      database; it is re-measured or it is not repeated.

### Packaging

- [ ] The wheel builds, and a **bare** install outside the source tree can run
      `verilore-proof verify` on a real receipt with no database and no
      network.
- [ ] `verilore_errors`, the runtime entry point and the verifier all ship.
- [ ] A plain install serves a real MCP session with all tools documented.

### The README's first command actually works

- [ ] Run it, in a clean container, exactly as printed.
- [ ] The README, `docs/quickstart.md` and `docs/pypi.md` install by name from
      PyPI (`uv tool install --python 3.13 verilore`), and the "Installs from
      PyPI" jobs below prove that name installs.

### Publishing to PyPI (trusted publishing; no password or token is stored)

- [ ] One-time, on both pypi.org and test.pypi.org: a **pending publisher**
      for project `verilore`: owner `raunakdey-07`, repository `verilore`,
      workflow `publish.yml`, environment `pypi` (on TestPyPI: `testpypi`).
      After the first upload it becomes the project's active publisher.
- [ ] One-time, in the repository settings: the environments `pypi` and
      `testpypi`; `pypi` has you as a required reviewer and a tag rule `v*`.
- [ ] CI is green on the exact commit being tagged, including "Clean install
      from the built wheel" (`twine check --strict`) and every "Installs on"
      and "Installs and runs on Python" job.
- [ ] Tag that commit, annotated, and push the tag:
      `git tag -a vX.Y.Z <commit> -m "vX.Y.Z" && git push origin vX.Y.Z`.
- [ ] TestPyPI first, with the same tag: Actions -> Publish -> Run workflow,
      target `testpypi`, ref `vX.Y.Z`. The build job refuses a tag that does
      not match the package version. Both "Installs from TestPyPI" jobs must
      pass: they install that exact version back from TestPyPI and run it.
- [ ] PyPI: publish a GitHub Release for the tag. The workflow builds the tag
      and waits for you to approve the `pypi` environment. Both "Installs from
      PyPI" jobs must pass.
- [ ] A version on PyPI can never be re-uploaded, even after deletion. A
      mistake is fixed by a new patch version, not by moving the tag.
- [ ] `mind-palace` on PyPI is a **different project** (a note-taking app at
      0.1.0). Do not let anyone "fix" the install by adding a hyphen.

### Truth

- [ ] Every "N passed" figure in `STATUS.md` and `README.md` names the run that
      produced it.
- [ ] No document claims Verilore outperforms a named system. No
      cross-vendor harness has been run, so no such comparison may exist.
- [ ] Every figure that is development-only says so. Sealed scoring has never
      happened; held-out v1 is burned.
- [ ] `git diff v0.9.0..HEAD -- eval/ docs/performance/baseline-packs.json` is
      **empty**.

## After tagging

- [ ] `scripts/release/check_versioning.py` passes on the tag.
- [ ] A clean checkout of the tag passes `verilore --help`, the upgrade
      fixture and the five-minute path.
- [ ] The tag is annotated with the commit it names and nothing is force-moved
      afterwards.

## Not on this list, deliberately

* **1.0.0.** `docs/release/v1.0.0-readiness.md` is the checklist for that, and
  it currently reports **0 of 8 met**. This file is about tagging the 0.x
  releases, which is a different decision at a different time.