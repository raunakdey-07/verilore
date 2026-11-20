# SPDX-License-Identifier: Apache-2.0
"""The publish workflow can only publish what it was built for, and stores no secret.

It cannot be exercised end to end from a pull request: publishing needs PyPI's
trust, which only the real workflow run on this repository gets. So the
properties that keep it safe are read off the file itself, and a pull request
that touches it runs the build job for real.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "publish.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    # PyYAML reads the bare key `on` as the boolean True.
    return workflow.get("on", workflow.get(True))


def test_the_file_name_is_the_one_pypi_trusts():
    """The pending publishers name `publish.yml`; any other name cannot publish."""
    assert WORKFLOW.exists()


def test_no_secret_or_token_is_used():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in text, "trusted publishing needs no secret; do not add one"
    assert "password" not in text.lower()
    assert "api-token" not in text.lower() and "api_token" not in text.lower()


def test_only_the_publish_jobs_can_mint_a_token():
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read"}
    for name, job in workflow["jobs"].items():
        permissions = job.get("permissions", {})
        if name.startswith("publish-"):
            assert permissions == {"id-token": "write"}, (name, permissions)
        else:
            assert "id-token" not in permissions, f"{name} must not be able to publish"


def test_a_pull_request_never_publishes():
    workflow = _workflow()
    assert "pull_request" in _triggers(workflow), "a PR that changes this file must build it"
    for name, job in workflow["jobs"].items():
        if not name.startswith("publish-"):
            continue
        condition = job["if"]
        assert "pull_request" not in condition, (name, condition)
        assert "release" in condition or "workflow_dispatch" in condition, (name, condition)


def test_each_publish_job_uses_its_trusted_environment():
    """The environment names are part of the pending publisher on each index."""
    jobs = _workflow()["jobs"]
    assert jobs["publish-testpypi"]["environment"]["name"] == "testpypi"
    assert jobs["publish-pypi"]["environment"]["name"] == "pypi"
    testpypi_steps = jobs["publish-testpypi"]["steps"]
    pypi_steps = jobs["publish-pypi"]["steps"]
    assert any(
        s.get("with", {}).get("repository-url") == "https://test.pypi.org/legacy/"
        for s in testpypi_steps
    )
    assert not any("repository-url" in s.get("with", {}) for s in pypi_steps)


def test_every_action_is_pinned_to_a_release():
    """A branch ref (main, master, release/v1) can change under a published release."""
    refs = re.findall(r"uses:\s*([\w.-]+/[\w.-]+)@(\S+)", WORKFLOW.read_text(encoding="utf-8"))
    assert refs
    for action, ref in refs:
        assert re.fullmatch(r"v\d+(\.\d+){0,2}", ref), f"{action}@{ref} is not a release tag"


def test_each_publication_is_installed_back_from_its_index():
    """An upload proves the index accepted the files, not that a person can install
    them. After each publish, the exact version that was built is installed back
    from that index, on Linux and on macOS, and its three commands run."""
    jobs = _workflow()["jobs"]
    assert "version" in jobs["build"].get("outputs", {}), "the build job must say what it built"

    for publish, verify, index in (
        ("publish-testpypi", "verify-testpypi", "https://test.pypi.org/simple/"),
        ("publish-pypi", "verify-pypi", None),
    ):
        job = jobs[verify]
        needs = job["needs"] if isinstance(job["needs"], list) else [job["needs"]]
        assert {"build", publish} <= set(needs), (verify, needs)
        # The same condition as the publish job, so a pull request never runs it.
        assert job["if"] == jobs[publish]["if"], verify
        assert "id-token" not in job.get("permissions", {}), f"{verify} must not be able to publish"

        runners = job["strategy"]["matrix"]["os"]
        assert any(r.startswith("ubuntu") for r in runners), runners
        assert any(r.startswith("macos") for r in runners), runners

        text = "\n".join(str(step.get("run", "")) for step in job["steps"])
        env = yaml.safe_dump([step.get("env", {}) for step in job["steps"]])
        assert "needs.build.outputs.version" in env, f"{verify} must install the built version"
        assert 'verilore=="$VERSION"' in text, f"{verify} must pin the version it installs"
        for command in ("verilore --help", "verilore-proof --help", "verilore-mcp --help"):
            assert command in text, (verify, command)
        if index:
            assert index in text, (verify, index)
            # verilore alone comes from TestPyPI, where anyone may upload a
            # look-alike of a real dependency; every dependency comes from PyPI.
            # Mixing the two indexes cannot do that: uv asks the extra index
            # first and keeps to the first index that has a package, so once
            # verilore was on PyPI, a version only on TestPyPI was never found
            # (v0.12.1), and a version already on PyPI was installed from PyPI
            # and passed without TestPyPI being tried (v0.11.0).
            download = [line for line in text.splitlines() if "pip download" in line]
            assert download, f"{verify} must fetch verilore by itself"
            block = text[text.index("pip download") :]
            assert "--no-deps" in block.split("then")[0], verify
            installs = [line for line in text.splitlines() if "uv tool install" in line]
            assert installs and all(".whl" in line or "$wheel" in line for line in installs), (
                verify,
                installs,
            )
            for flag in ("--extra-index-url", "--index-strategy", "unsafe-best-match"):
                assert flag not in text, (verify, flag)
        else:
            assert "test.pypi.org" not in text, verify


def test_a_testpypi_check_can_be_run_again_for_a_version_already_uploaded():
    """A TestPyPI upload cannot be replaced, so a second run for the same tag (to
    check the install again) skips the upload instead of failing on it. PyPI is
    never re-run: its upload must be the one and only."""
    jobs = _workflow()["jobs"]
    testpypi = [s for s in jobs["publish-testpypi"]["steps"] if "pypi-publish" in s.get("uses", "")]
    pypi = [s for s in jobs["publish-pypi"]["steps"] if "pypi-publish" in s.get("uses", "")]
    assert testpypi[0]["with"].get("skip-existing") is True
    assert "skip-existing" not in pypi[0].get("with", {})
