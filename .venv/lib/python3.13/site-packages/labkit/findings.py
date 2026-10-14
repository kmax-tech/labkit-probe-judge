"""findings — an audit's findings as data the person decides, not as prose.

`labkit-audit` (MODE preflight or analysis) writes what it found into the
area, one file per audit:

    experiments/<NN>-<name>/audits/2026-10-12T15-33-preflight.toml

    [audit]
    date = "2026-10-12T15:33"
    mode = "preflight"
    model = "opus"
    scope_sha = "fa45c7618423"
    blockers = 1
    warnings = 2
    notes = 1

    [[finding]]
    grade = "BLOCKER"
    text = "BLOCKER · scripts/01_measure.py:42 · … · LAB-038 What the prompt demands · …"
    status = "open"      # open | fixed | accepted | deferred | dismissed
    reason = ""          # owed for accepted, deferred and dismissed

The person edits `status` and `reason`; nothing else writes the file.
A full run at `minutes`/`hours` needs a preflight record whose `scope_sha`
is the code's stamp now, every finding decided (`audit_coverage`, held
by runlog's freeze gate and by `preflight`). `preflight` reads every
findings file of the area: a finding still `open`
is a warning before the freeze and a blocker once `frozen = true`
(LAB-015 Preflight audit before freezing: every finding is decided), a `deferred`
finding anywhere in the repo is printed as a reminder and never counted.

Why (uniagent, 2026-10-12, 23 preflight and 21 analysis audits read by
hand): a finding deferred in area 16 as "its own task" bit in area 17; the
same finding was accepted three times in three areas; 13 of 44 audit lines
end in "accepted/dismissed" and what they decided is lost in a 400-character
protocol line. With the findings as data the deferred ones stay visible and
an audit's yield (fixed / accepted / dismissed per class) can be counted
instead of read.

Reading is loud: an unknown status, a decided status without a reason, a
file without its `[audit]` table raise FindingsError naming the file and
the field — a findings file nobody can read is not "no findings".
"""

from __future__ import annotations

import json
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

DIR = "audits"
STATUSES = ("open", "fixed", "accepted", "deferred", "dismissed")
REASON_OWED = ("accepted", "deferred", "dismissed")
GRADES = ("BLOCKER", "WARNING", "NOTE")
MODES = ("preflight", "analysis")


class FindingsError(ValueError):
    """A findings file that cannot be read as such; the message names file and field."""


@dataclass(frozen=True)
class Finding:
    """One finding of one audit and what the person decided about it."""

    grade: str
    text: str
    status: str
    reason: str


@dataclass(frozen=True)
class Record:
    """One audit's findings file."""

    path: Path
    date: str
    mode: str
    model: str
    scope_sha: str
    verdict: tuple[int, int, int]
    findings: tuple[Finding, ...]

    @property
    def open(self) -> list[Finding]:
        """The findings nobody has decided yet."""
        return [f for f in self.findings if f.status == "open"]

    @property
    def deferred(self) -> list[Finding]:
        """The findings put off as somebody's later task."""
        return [f for f in self.findings if f.status == "deferred"]


def _s(value: str) -> str:
    """A TOML basic string: json's escaping is a subset of TOML's."""
    return json.dumps(value, ensure_ascii=False)


def write(
    area: Path,
    mode: str,
    model: str,
    scope_sha: str,
    verdict: tuple[int, int, int],
    findings: list[tuple[str, str]],
    now: float | None = None,
) -> Path:
    """Write the audit's findings file into AREA/audits/ and return its path.
    Every finding starts `open`. Never overwrites: the name carries the minute."""
    if mode not in MODES:
        raise ValueError(f"mode {mode!r} — one of {', '.join(MODES)}")
    when = time.localtime(now)
    stamp = time.strftime("%Y-%m-%dT%H-%M", when)
    folder = area / DIR
    folder.mkdir(exist_ok=True)
    path = folder / f"{stamp}-{mode}.toml"
    n = 2
    while path.exists():
        path = folder / f"{stamp}-{mode}-{n}.toml"
        n += 1
    b, w, k = verdict
    lines = [
        "# written by labkit-audit — decide each finding: set status and reason",
        "[audit]",
        f"date = {_s(time.strftime('%Y-%m-%dT%H:%M', when))}",
        f"mode = {_s(mode)}",
        f"model = {_s(model)}",
        f"scope_sha = {_s(scope_sha)}",
        f"blockers = {b}",
        f"warnings = {w}",
        f"notes = {k}",
    ]
    for grade, text in findings:
        if grade not in GRADES:
            raise ValueError(f"grade {grade!r} — one of {', '.join(GRADES)}")
        lines += [
            "",
            "[[finding]]",
            f"grade = {_s(grade)}",
            f"text = {_s(text)}",
            'status = "open"',
            'reason = ""',
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _audit_table(path: Path, data: dict) -> dict:
    """The `[audit]` table of a findings file, held to its shape."""
    audit = data.get("audit")
    if not isinstance(audit, dict):
        raise FindingsError(f"{path}: no [audit] table")
    for key in ("date", "mode", "model", "scope_sha"):
        if not isinstance(audit.get(key), str):
            raise FindingsError(f"{path}: [audit] {key} is missing or not a string")
    for key in ("blockers", "warnings", "notes"):
        if not isinstance(audit.get(key), int) or isinstance(audit.get(key), bool):
            raise FindingsError(f"{path}: [audit] {key} is missing or not an integer")
    if audit["mode"] not in MODES:
        raise FindingsError(
            f"{path}: [audit] mode {audit['mode']!r} — one of {', '.join(MODES)}"
        )
    return audit


def _finding(path: Path, i: int, row: object) -> Finding:
    """The i-th `[[finding]]` table, held to grade, status and the owed reason."""
    if not isinstance(row, dict):
        raise FindingsError(f"{path}: finding {i} is not a table")
    for key in ("grade", "text", "status", "reason"):
        if not isinstance(row.get(key), str):
            raise FindingsError(
                f"{path}: finding {i}: {key} is missing or not a string"
            )
    if row["grade"] not in GRADES:
        raise FindingsError(
            f"{path}: finding {i}: grade {row['grade']!r} — one of {', '.join(GRADES)}"
        )
    if row["status"] not in STATUSES:
        raise FindingsError(
            f"{path}: finding {i}: status {row['status']!r} — one of {', '.join(STATUSES)}"
        )
    if row["status"] in REASON_OWED and not row["reason"].strip():
        raise FindingsError(
            f"{path}: finding {i}: status {row['status']!r} owes a reason"
        )
    return Finding(row["grade"], row["text"], row["status"], row["reason"].strip())


def read(path: Path) -> Record:
    """The findings file at PATH; raises FindingsError on anything it cannot hold to."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise FindingsError(f"{path}: not TOML ({exc})") from exc
    audit = _audit_table(path, data)
    rows = data.get("finding", [])
    if not isinstance(rows, list):
        raise FindingsError(f"{path}: `finding` must be [[finding]] tables")
    return Record(
        path,
        audit["date"],
        audit["mode"],
        audit["model"],
        audit["scope_sha"],
        (audit["blockers"], audit["warnings"], audit["notes"]),
        tuple(_finding(path, i, row) for i, row in enumerate(rows, start=1)),
    )


def area_records(area: Path) -> list[Record]:
    """Every findings file of AREA, oldest first; a file that cannot be read raises."""
    folder = area / DIR
    if not folder.is_dir():
        return []
    return [read(p) for p in sorted(folder.glob("*.toml"))]


def audit_coverage(area: Path, sha: str, mode: str) -> str | None:
    """Why no audit of MODE covers the area's code stamped SHA, or None: a
    record with that `mode` whose `scope_sha` is SHA, every finding of it
    decided. The head's audit line is written by hand; this is what makes
    "the frozen code was audited" a fact instead of a line (2026-10-14: after
    fixing the audit's findings a cold agent stamped the new sha, and no
    audit had seen that code). `preflight` for the freeze (runlog, preflight),
    `analysis` for the report (report-check).

    Raises:
        FindingsError: A findings file of AREA cannot be read.
        ValueError: MODE is not one of MODES.
    """
    if mode not in MODES:
        raise ValueError(f"audit mode {mode!r} is not one of {', '.join(MODES)}")
    records = [r for r in area_records(area) if r.mode == mode]
    covering = [r for r in records if r.scope_sha == sha]
    if not covering:
        seen = ", ".join(sorted({r.scope_sha for r in records})) or "none"
        return (
            f"no {mode} audit saw the code as it is now (scope sha {sha}; "
            f"audited: {seen}) — a change after the audit owes a new one: "
            f"`labkit-audit <area> --mode {mode}`"
        )
    undecided = [f for r in covering for f in r.open]
    if undecided:
        return (
            f"{len(undecided)} finding(s) of the {mode} audit of {sha} still "
            f"`open` — decide each (fixed / accepted / deferred / dismissed)"
        )
    return None


def repo_records(experiments: Path) -> list[tuple[Path, Record]]:
    """(area, record) for every findings file under EXPERIMENTS, by area then date."""
    out = []
    for folder in sorted(experiments.glob(f"*/{DIR}")):
        if folder.is_dir():
            out += [(folder.parent, r) for r in area_records(folder.parent)]
    return out


def deferred_elsewhere(
    area: Path, experiments: Path
) -> list[tuple[Path, Record, Finding]]:
    """Deferred findings in other areas of the repo — "its own task" that
    nobody picked up (uniagent 16 → 17, 2026-10-08)."""
    return [
        (other, rec, f)
        for other, rec in repo_records(experiments)
        if other.resolve() != area.resolve()
        for f in rec.deferred
    ]
