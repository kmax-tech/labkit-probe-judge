"""preflight — the gate before freezing a protocol.

Sequences the checks that must pass before `frozen = true`.
Each check prints its own output; preflight adds a summary line and an
exit code that reflects the worst finding.

    preflight <AREA> [--protocol PROTOCOL-*.md]

Exit codes: 0 no blocker (warnings may stand), 1 at least one blocker,
2 usage error. One early end: a protocol head that does not parse ends
station 1 with exit 1 and nothing after it runs.

What it runs, in order:
  1. protocol-check   mandatory fields, placeholders; an unparseable head
                      ends here
  2. cost tier        `cost` in the protocol head — `seconds` makes the agent
                      audit optional before freezing (one audit after the
                      first run suffices, LAB-017 The number of audits follows the cost tier); `minutes`/`hours` ask
                      for it here; an unfilled cost counts as `hours`.
                      Printed, never counted — "audit due" is a reminder,
                      not a blocker; so is the cold-reader line (LAB-102 Cold reader before freezing)
  2b. audit findings  the findings files `labkit-audit` wrote (`audits/*.toml`,
                      `labkit.findings`): a finding still `open` is a warning,
                      a blocker once frozen = true; a `deferred` finding in
                      another area of the repo is printed as a reminder, never
                      counted; an unreadable file is a blocker
  3. code-check       intent ids against the code, and the code the stamp
                      cannot follow (sys.path edits, dynamic loaders, imports
                      outside lib/ and src/ — static evidence, warnings);
                      a line starting with `BLOCKER` is a blocker, any other
                      a warning
  4. scope-sha        audit stamp over the input scope
  5. working tree     uncommitted changes (warning, not a blocker)
  6. hooks            the installed labkit hooks match this labkit (warning)
  7. area tests       tests/test_<NN>_<name>.py via pytest — the resolution
                      check and the parser cases as a permanent test
                      (LAB-016 Resolution check before freezing); a failing test is a blocker, a missing
                      file a warning — a blocker once frozen = true

What it does NOT do: commit, freeze, or change any file. It is a
read-only gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
import subprocess
import sys
from pathlib import Path

from labkit.code_check import check_intent_ids, stamp_coverage_findings
from labkit import console, findings, install_hooks, protocol_block
from labkit.repo import (
    area_path,
    choose_protocol,
    git,
    git_root,
    layout_root,
    no_such_area,
)
from labkit.protocol_check import check_fields, check_protocol_id, repo_protocol_ids
from labkit.scope_sha import AREA_GLOBS, AUDIT_SHA, area_stamp


def _is_dirty(area: Path) -> bool:
    """Uncommitted changes under `area`; False outside a repo. A git that
    fails inside a repo raises (repo.GitError) — it used to read as clean."""
    return bool(git(["status", "--porcelain"], area))


@dataclass(frozen=True)
class AreaTests:
    """What running an area's own tests found."""

    pattern: str  # what was looked for, for the message
    files: list[Path]
    state: str  # "none" | "ok" | "failed" | "no-pytest"
    tail: list[str]  # the last lines of a failing run


def area_test_python(repo: Path) -> str:
    """The Python installation that runs an area's tests: the repo's own
    `.venv`, else the one running labkit. The repo's, not the caller's — the
    tests import the repo's dependencies, and a gate run from another venv
    failed them on a missing package (uniagent, 2026-10-07)."""
    own = repo / ".venv" / "bin" / "python"
    return str(own) if own.is_file() else sys.executable


def area_tests(area: Path, repo: Path) -> AreaTests:
    """Run the area's tests (`tests/test_*<slug>*.py`) — the resolution
    check and the parser cases in their permanent form. One home for
    preflight (before the freeze) and finalize (before a number is
    reported)."""
    # The name the scaffolder stamps: test_<NN>_<name>.py (or test_<name>.py
    # for an unnumbered area), split files as test_<NN>_<name>_<part>.py.
    # A bare *<name>* glob ran area 09's test for area 08, whose name is a
    # prefix of 09's (uniagent, 2026-10-07).
    # `preflight .` passes a relative path whose .name is "" — resolved first,
    # or the pattern read `tests/test_.py` and the area's test was "none"
    # (fallacy-dataset-generation, 2026-10-09)
    area = area.resolve()
    m = re.match(r"^(\d+)-(.+)$", area.name)
    nn, name = (m.group(1), m.group(2)) if m else (None, area.name)
    stem = (f"test_{nn}_" if nn else "test_") + name.replace("-", "_")
    pattern = f"tests/{stem}.py"
    tests_dir = repo / "tests"
    files = (
        sorted({*tests_dir.glob(f"{stem}.py"), *tests_dir.glob(f"{stem}_*.py")})
        if tests_dir.is_dir()
        else []
    )
    if not files:
        return AreaTests(pattern, [], "none", [])
    r = subprocess.run(
        [
            area_test_python(repo),
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            *map(str, files),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if r.returncode == 0:
        return AreaTests(pattern, files, "ok", [])
    if "No module named pytest" in (r.stderr or ""):
        return AreaTests(pattern, files, "no-pytest", [])
    tail = [ln for ln in (r.stdout or "").splitlines() if ln.strip()][-6:]
    return AreaTests(pattern, files, "failed", tail)


def preflight_area(area: Path, protocol: Path | None = None) -> int:  # noqa: C901 complexity baseline 2026-10-08
    """Run all preflight checks. Returns 0 (clean) or 1 (findings)."""
    blockers = 0
    warnings = 0

    protocol = choose_protocol(area, protocol, "preflight")
    if protocol is None:
        return 2

    text = protocol.read_text(encoding="utf-8")

    # -- 1. protocol-check ------------------------------------------------
    print(f"── protocol-check: {protocol.name} ──")
    # The same field report as protocol-check (one home): the head, the
    # owed fields by cut, and the graduation at frozen = true.
    report = check_fields(text)
    if report.head is None:
        print(f"  HEAD (must): {report.head_error}")
        return 1
    missing_must, missing_should = report.missing_must, report.missing_should
    must_holes, should_holes = report.must_holes, report.soft_holes
    id_findings = check_protocol_id(protocol, report.head, repo_protocol_ids(protocol))

    if missing_must:
        for label in missing_must:
            print(f"  MISSING (must): {label}")
        blockers += len(missing_must)
    if must_holes:
        for n, label in must_holes:
            print(f"  {protocol.name}:{n}: PLACEHOLDER (must): {label}")
        blockers += len(must_holes)
    if id_findings:
        for f in id_findings:
            print(f"  {f}")
        blockers += len(id_findings)
    if missing_should:
        for label in missing_should:
            print(f"  missing (should): {label}")
        warnings += len(missing_should)
    if should_holes:
        for n, label in should_holes:
            print(f"  {protocol.name}:{n}: placeholder (should): {label}")
        warnings += len(should_holes)
    if not (
        missing_must or must_holes or id_findings or missing_should or should_holes
    ):
        print("  ok")

    # -- 2. cost tier (printed, never counted) ------------------------------
    print("── cost tier ──")
    tier = report.head.cost
    if tier == "seconds":
        print(
            "  seconds — rerunnable at will: the agent audit is OPTIONAL before "
            "freezing; one audit after the first run, on real output, "
            "suffices (LAB-017 The number of audits follows the cost tier)"
        )
    elif tier is None:
        print(
            "  not filled — treated as `hours`: the experiment-preflight "
            "audit is due before freezing (LAB-015 Preflight audit before freezing); set `cost` in the head "
            "to say otherwise"
        )
    else:
        print(
            f"  {tier} — the experiment-preflight audit is due before freezing (LAB-015 Preflight audit before freezing)"
        )
    print(
        "  a cold reader is due while the prose can still change (LAB-102 Cold reader before freezing): `labkit-audit <AREA> --mode clarity` — static "
        "evidence, never blocks"
    )

    # -- 2b. audit findings (the data behind the audit line) ----------------
    print("── audit findings ──")
    frozen = report.head is not None and report.head.frozen
    try:
        records = findings.area_records(area)
    except findings.FindingsError as exc:
        print(f"  BLOCKER: {exc}")
        blockers += 1
        records = []
    undecided = [(r, f) for r in records for f in r.open]
    grade = "BLOCKER" if frozen else "WARNING"
    for r, f in undecided:
        print(f"  {grade}: undecided in {r.path.name}: {f.text}")
    if undecided:
        print(
            f"  {len(undecided)} finding(s) still `open` — decide each (fixed / accepted / "
            f"deferred / dismissed) before freezing (LAB-015 Preflight audit before freezing)"
            + (" — frozen = true owes it" if frozen else "")
        )
        if frozen:
            blockers += len(undecided)
        else:
            warnings += len(undecided)
    gap = _coverage_gap(area, report.head)
    if gap:
        print(f"  {grade}: {gap} (LAB-015 Preflight audit before freezing)")
        if frozen:
            blockers += 1
        else:
            warnings += 1
    experiments = area.resolve().parent
    try:
        elsewhere = findings.deferred_elsewhere(area, experiments)
    except findings.FindingsError as exc:
        print(f"  WARNING: {exc}")
        warnings += 1
        elsewhere = []
    for other, r, f in elsewhere:
        print(f"  deferred in {other.name} ({r.date}): {f.text} — {f.reason}")
    if elsewhere:
        print(
            f"  {len(elsewhere)} deferred finding(s) elsewhere in the repo — a reminder, "
            f"not counted (uniagent 2026-10-08: one deferred in area 16 bit in 17)"
        )
    if not records and not elsewhere:
        print("  none recorded")
    elif not undecided and not elsewhere:
        print(f"  all decided ({len(records)} audit(s) recorded)")

    # -- 3. code-check (intent ids) ---------------------------------------
    print("── code-check: intent ids, stamp coverage ──")
    code_findings = check_intent_ids(area, protocol) + stamp_coverage_findings(
        area, layout_root(area)
    )
    for f in code_findings:
        print(f"  {f}")
    blockers += sum(1 for f in code_findings if f.startswith("BLOCKER"))
    warnings += sum(1 for f in code_findings if f.startswith("WARNING"))
    if not code_findings:
        print("  ok")

    # -- 4. scope-sha ------------------------------------------------------
    print("── scope-sha ──")
    try:
        sha, _, _ = area_stamp(area)
        print(f"  {sha}")
    except ValueError:
        print(f"  no scripts matching {AREA_GLOBS} in {area} (skipped)")

    # -- 5. working tree ---------------------------------------------------
    print("── working tree ──")
    repo = layout_root(area)
    if _is_dirty(repo):
        print(f"  WARNING: uncommitted changes in {repo}")
        print("  (not a blocker — commit or stash before the run)")
        warnings += 1
    else:
        print("  clean")

    # -- 6. hooks ----------------------------------------------------------
    # The gates that do not depend on the agent remembering: a repo without
    # them (or with an older labkit's) runs on good intentions only.
    print("── hooks ──")
    git_repo = git_root(area)
    if git_repo is None:
        print("  n/a — not a git repo")
    else:
        gaps = install_hooks.check(git_repo)
        for g in gaps:
            print(f"  WARNING: {g}")
        if gaps:
            print("  fix with  .venv/bin/labkit-hooks install")
            warnings += 1
        else:
            print("  installed (this labkit's pre-commit, core.hooksPath, claude-hook)")

    # -- 7. area tests -----------------------------------------------------
    print("── tests ──")
    tests = area_tests(area, repo)
    if not tests.files:
        # Frozen means every gap is owed (protocol-check's graduation); a
        # missing permanent resolution check is such a gap (2026-10-07: it
        # only warned, and a protocol could freeze without any test).
        grade = "BLOCKER" if frozen else "WARNING"
        print(
            f"  {grade}: no {tests.pattern} — the resolution check has no "
            f"permanent form (LAB-016 Resolution check before freezing)"
            + (" and frozen = true owes it" if frozen else "")
        )
        if frozen:
            blockers += 1
        else:
            warnings += 1
    elif tests.state == "ok":
        print(f"  ok — {', '.join(f.name for f in tests.files)}")
    elif tests.state == "no-pytest":
        print("  WARNING: pytest is not installed in this interpreter — tests not run")
        warnings += 1
    else:
        for ln in tests.tail:
            print(f"  {ln}")
        print(
            f"  BLOCKER: {', '.join(f.name for f in tests.files)} failed — an "
            f"unfilled or broken resolution check must not pass the freeze"
        )
        blockers += 1

    # -- summary -----------------------------------------------------------
    print()
    if blockers:
        print(
            f"preflight: {blockers} blocker(s), {warnings} warning(s) "
            f"— fix the blockers before freezing."
        )
        return 1
    if warnings:
        print(f"preflight: 0 blockers, {warnings} warning(s) — review before freezing.")
        return 0
    print("preflight: all clear.")
    return 0


def _coverage_gap(area: Path, head: "protocol_block.Head | None") -> str | None:
    """Why the head's audit line claims an audit no record holds, or None:
    the line names a `scope sha` and no decided preflight record saw that
    code (`findings.audit_coverage`; runlog refuses the full run on the
    same answer). Silent at `seconds`, without a line, and on `n/a`."""
    if head is None or head.cost == "seconds" or not head.preflight_audit:
        return None
    m = AUDIT_SHA.search(head.preflight_audit)
    if m is None:
        return None
    try:
        return findings.audit_coverage(area, m.group(1), "preflight")
    except findings.FindingsError as exc:
        return str(exc)


def main(argv: list[str]) -> int:
    """Command line of `preflight`: the mechanical gate before an area is frozen."""
    if not argv or argv[0] in ("-h", "--help"):
        print((__doc__ or "").strip().splitlines()[0])
        print("usage: preflight <AREA> [--protocol PROTOCOL-*.md]")
        return 0 if argv else 2

    area = area_path(argv[0])
    protocol = None
    rest = argv[1:]
    while rest:
        if rest[0] == "--protocol" and len(rest) >= 2:
            protocol = Path(rest[1])
            rest = rest[2:]
            continue
        print(f"preflight: unexpected argument {rest[0]!r}")
        return 2

    if not area.is_dir():
        print(f"preflight: {no_such_area(area)}")
        return 2

    return preflight_area(area, protocol)


def cli() -> None:
    """Console entry point of `preflight`."""
    console.exit_with(main)


if __name__ == "__main__":
    cli()
