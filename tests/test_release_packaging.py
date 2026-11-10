# SPDX-License-Identifier: Apache-2.0
"""The distribution must ship the runtime, and not the research tooling.

`scripts/` was in the wheel's `include` list from `v0.6.0`, which meant every
`pip install verilore` carried the release checks, the benchmark harnesses and
the scale fixtures. Measured: 54 files, 590 KB of 1,328 KB unpacked -- 44% of the
distribution -- for code that no runtime path imports.

Three tests here. They are cheap and they need no model and no database, so they run
in the same instant as the rest of the suite and fail loudly if the boundary is
reopened by accident.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


def _config() -> dict:
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)


def test_the_wheel_does_not_ship_research_tooling():
    """`scripts*` must not come back.

    Regression guard with a reason: it was there for seven releases and nobody
    noticed because it only ever showed up as a slightly larger install.
    """
    include = _config()["tool"]["setuptools"]["packages"]["find"]["include"]
    assert "scripts*" not in include, (
        f"scripts* is back in the wheel include list {include}. It ships release and "
        "benchmark tooling no runtime imports, which measured at 44% of the "
        "unpacked distribution."
    )


def test_the_runtime_surface_is_still_included():
    """Removing bloat must not remove the product.

    Both halves matter: the packages, and the single-file modules the console
    scripts and the local runtime entry point need. `mindpalace_runtime` going
    missing is the failure that once made every command silently 6 seconds on an
    installed package.
    """
    config = _config()
    include = set(config["tool"]["setuptools"]["packages"]["find"]["include"])
    modules = set(config["tool"]["setuptools"]["py-modules"])

    assert {"verilore*"} <= include, include
    for required in (
        "verilore_sdk",
        "verilore_errors",
    ):
        assert required in modules, f"{required} is no longer a py-module; the wheel loses it"

    scripts = config["project"]["scripts"]
    assert scripts["verilore"] == "verilore.cli.main:app", scripts
    assert scripts["verilore-proof"] == "verilore.proof_cli:main", scripts
    assert scripts["verilore-mcp"] == "verilore.mcp_server:main", scripts


def test_nothing_outside_scripts_imports_the_scripts_package():
    """The reason the exclusion is safe, asserted rather than assumed.

    Three test modules import `scripts.benchmark` to check the frozen benchmark and
    the release workflow -- they run from a checkout, where `scripts/` is present,
    which is fine. Nothing that ships in the wheel may do the same, because the
    wheel no longer contains it.
    """
    shipped = [ROOT / "verilore"]
    shipped += [
        ROOT / f"{name}.py"
        for name in (
            "verilore_sdk",
            "verilore_errors",
        )
    ]

    offenders: list[str] = []
    for path in shipped:
        files = path.rglob("*.py") if path.is_dir() else [path]
        for file in files:
            tree = ast.parse(file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    offenders += [
                        f"{file.relative_to(ROOT)}:{node.lineno} import {a.name}"
                        for a in node.names
                        if a.name == "scripts" or a.name.startswith("scripts.")
                    ]
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module == "scripts" or module.startswith("scripts."):
                        offenders.append(f"{file.relative_to(ROOT)}:{node.lineno} from {module}")
    assert not offenders, (
        "shipped code imports the scripts package, which the wheel no longer "
        f"contains: {offenders}"
    )


def test_each_console_script_declares_the_extra_it_needs():
    """A console script that cannot run from its declared install is a packaging bug.

    This is not hypothetical. The wheel CI job asserted `verilore-mcp --help`
    against a **bare** install, which cannot supply `mcp` -- it is a declared extra.
    The job failed with `ModuleNotFoundError: No module named 'mcp'`, and its
    `|| import verilore.mcp_server` fallback could not have saved it, for the same reason.

    `typer` is the interesting counter-case, and the reason this test is worth having.
    It is also an extra, so `verilore` ought to be uninstallable without it -- but a
    bare install *does* get typer, because `transformers` requires it. So the CLI's
    availability depends on an unrelated package's dependency graph, and this test
    pins the declaration rather than the accident.

    Every dependency a console script's module needs must therefore be a base
    dependency or reachable through an extra. The mapping is stated here rather than
    remembered, so adding a console script, or moving an import, has to be deliberate.
    """
    config = _config()
    base = {_requirement_name(d) for d in config["project"]["dependencies"]}
    extras = {
        name: {_requirement_name(d) for d in reqs}
        for name, reqs in config["project"].get("optional-dependencies", {}).items()
    }

    expectations = {
        # console script -> (what it needs, the extra that provides it)
        "verilore": ({"typer"}, "cli"),
        "verilore-proof": (set(), None),
        "verilore-mcp": ({"mcp"}, "mcp"),
    }

    scripts = config["project"]["scripts"]
    assert set(scripts) == set(
        expectations
    ), f"console scripts changed to {sorted(scripts)}; update this mapping deliberately"

    for script, (needed, extra) in expectations.items():
        available = set(base) | (extras.get(extra, set()) if extra else set())
        missing = needed - available
        assert not missing, (
            f"`{script}` needs {sorted(missing)}, which a "
            f"'verilore{'[' + extra + ']' if extra else ''}' install does not "
            f"provide. Base: {sorted(base)}; {extra!r} extra: "
            f"{sorted(extras.get(extra, [])) if extra else 'nothing extra'}."
        )

    # The portability claim rests on this one staying dependency-free: someone handed
    # a receipt may install the wheel and nothing else.
    assert not expectations["verilore-proof"][0] & base, (
        "verilore-proof gained a base dependency; verifying a receipt must need no "
        "database, model, server or network"
    )


def _requirement_name(requirement: str) -> str:
    """`sqlalchemy[asyncio]>=2.0.0` -> `sqlalchemy`."""
    name = requirement.split(";")[0].strip()
    for separator in (">=", "==", "~=", "<", ">", "[", "(", " "):
        name = name.split(separator)[0]
    return name.strip().lower()


def test_pypi_description_has_no_relative_links():
    """PyPI renders the description with no repository around it, so a relative
    link there is a broken link. Every link in docs/pypi.md is absolute https."""
    import re

    readme = _config()["project"]["readme"]
    path = readme["file"] if isinstance(readme, dict) else readme
    assert path == "docs/pypi.md", f"the PyPI description is {path}, not docs/pypi.md"
    text = (ROOT / path).read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 60, "docs/pypi.md is a landing page, not a manual"

    markdown_links = re.findall(r"\]\(([^)\s]+)", text)
    html_links = re.findall(r"""<a\s[^>]*href=["']([^"']+)""", text)
    targets = markdown_links + html_links
    assert targets, "docs/pypi.md links nowhere; it should link the README and the guide"
    relative = [target for target in targets if not target.startswith("https://")]
    assert not relative, f"relative or non-https links in docs/pypi.md: {relative}"


def _ci_jobs() -> dict:
    import yaml

    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    return workflow["jobs"]


def _resolve(job: dict, value) -> set[str]:
    """A job setting, with `${{ matrix.x }}` expanded to every value x takes,
    from the matrix lists and from `include` entries alike."""
    import re

    value = str(value)
    reference = re.fullmatch(r"\$\{\{\s*matrix\.(\w+)\s*\}\}", value)
    if not reference:
        return {value}
    key = reference.group(1)
    matrix = (job.get("strategy") or {}).get("matrix") or {}
    values = {str(v) for v in matrix.get(key, [])}
    values |= {str(entry[key]) for entry in matrix.get("include", []) if key in entry}
    return values


def _python_versions_ci_runs() -> set[str]:
    """Every Python version some CI job sets up, including a matrix's."""
    import re

    versions: set[str] = set()
    for job in _ci_jobs().values():
        for step in job.get("steps", []):
            value = (step.get("with") or {}).get("python-version")
            if value is not None:
                versions |= {v for v in _resolve(job, value) if re.fullmatch(r"3\.\d+", v)}
    return versions


def _install_jobs() -> dict[str, dict]:
    """The jobs that install the built wheel the way a person does."""
    jobs = _ci_jobs()
    return {name: jobs[name] for name in ("python-versions", "distros", "macos")}


def test_metadata_names_only_what_is_tested():
    """The classifiers claim Python versions and an OS; CI is the evidence for each."""
    import re

    classifiers = _config()["project"]["classifiers"]
    tested = _python_versions_ci_runs()
    claimed = {
        c.rsplit(" :: ", 1)[1]
        for c in classifiers
        if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c)
    }
    assert claimed, "no Python version classifier"
    assert claimed <= tested, f"classifiers claim {claimed - tested}, which no CI job runs"
    assert not any(c.startswith("License ::") for c in classifiers), (
        "PEP 639: the SPDX `license` field replaces License classifiers; setuptools "
        "refuses both together"
    )


def test_operating_systems_claimed_are_the_ones_ci_installs_on():
    """An OS classifier is a promise that `pip install verilore` works there."""
    classifiers = set(_config()["project"]["classifiers"])
    claimed = {c for c in classifiers if c.startswith("Operating System ::")}
    runners: set[str] = set()
    for job in _install_jobs().values():
        runners |= _resolve(job, job["runs-on"])
    proven = set()
    if any(r.startswith("ubuntu") for r in runners):
        proven.add("Operating System :: POSIX :: Linux")
    if any(r.startswith("macos") for r in runners):
        proven.add("Operating System :: MacOS")
    assert claimed, "no Operating System classifier"
    assert claimed <= proven, f"classifiers claim {claimed - proven}, which no install job runs"


def test_every_platform_the_quickstart_names_is_installed_on_in_ci():
    """docs/quickstart.md tells each system how to get uv and a container engine;
    each one it names is a CI job that installs the wheel there and runs it."""
    quickstart = (ROOT / "docs" / "quickstart.md").read_text(encoding="utf-8")
    section = quickstart.split("## Your system", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| ") and "---" not in line]
    named = {row.split("|")[1].strip() for row in rows[1:]}
    assert named, "the quickstart's system table is missing"

    jobs = _install_jobs()
    images = {
        entry["image"].split(":")[0] for entry in jobs["distros"]["strategy"]["matrix"]["include"]
    }
    mac_chips = {entry["chip"] for entry in jobs["macos"]["strategy"]["matrix"]["include"]}
    arm_linux = _resolve(jobs["python-versions"], jobs["python-versions"]["runs-on"])

    proof = {
        "macOS, Apple silicon": "Apple silicon" in mac_chips,
        "macOS, Intel": "Intel" in mac_chips,
        "Ubuntu, WSL": "ubuntu" in images,
        "Debian": "debian" in images,
        "Fedora": "fedora" in images,
        "Arch": "archlinux" in images,
    }
    assert named == set(proof), f"the table names {sorted(named)}; CI proves {sorted(proof)}"
    unproven = sorted(name for name, ok in proof.items() if not ok)
    assert not unproven, f"named in the quickstart with no CI job installing there: {unproven}"
    assert "64-bit ARM Linux" in section and any(r.endswith("-arm") for r in arm_linux)


def test_requires_python_admits_exactly_the_tested_versions():
    """An install on a Python no CI job runs must be refused by the installer, with
    a plain "requires Python" message, not attempted and failed deep in a resolver
    (onnxruntime had no wheel for 3.15, and that is how Fedora 45 met it)."""
    import re

    spec = _config()["project"]["requires-python"]
    bounds = dict(re.findall(r"(>=|<)\s*3\.(\d+)", spec))
    assert ">=" in bounds and "<" in bounds, f"requires-python needs both bounds: {spec!r}"
    admitted = {f"3.{minor}" for minor in range(int(bounds[">="]), int(bounds["<"]))}
    tested = _python_versions_ci_runs()
    assert admitted <= tested, f"requires-python admits {admitted - tested}, which no CI job runs"
