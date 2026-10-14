"""report-check — the gate after the last step, before a number leaves the area.

    report-check <AREA> [--protocol PROTOCOL-*.md]

Exit codes: 0 clean, 1 a blocker, 2 usage error.

`finalize` holds the run before the number is written back; what follows it
— the analysis audit, the result written into its note, the note held to the
run by `02_analyze.py --check` — had no gate. In the cloud judge probe at
`minutes` (2026-10-14, draw 3) the agent skipped the check and the result
note, and finalize was green. A gate there cannot be finalize itself: finalize
comes before the analysis audit, so it cannot ask for what follows the audit.
report-check comes last and holds the whole chain:

  0. protocol      the named PROTOCOL-*.md or the area's only one; at
                   `cost = "seconds"` nothing is owed here (the short lane
                   ends with finalize, the audit comes when the number is
                   promoted — LAB-017 The number of audits follows the cost
                   tier) and the command exits 0
  1. frozen        `frozen = true`
  2. finalize      `finalize_area` clean (its output is not repeated)
  3. analysis audit  a record `audits/*-analysis.toml` whose `scope_sha` is
                   the area's stamp now, every finding decided
                   (`findings.audit_coverage`) — code changed after the
                   analysis audit owes a new one (LAB-050 Analysis audit
                   before reporting)
  4. the check     `scripts/02_analyze.py --check` exits 0 under the repo's
                   interpreter: the rows recompute to the run's metrics and
                   the note it names carries every number and the run_id
                   (`recheck.holds`; LAB-041 Generate numbers, don't retype
                   them)

Every station runs; the blockers are summed at the end. It reads and runs,
never writes.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import subprocess
from pathlib import Path

from labkit import console, findings, protocol_block
from labkit.finalize import finalize_area
from labkit.preflight import area_test_python
from labkit.repo import choose_protocol, layout_root
from labkit.scope_sha import area_stamp

#: the analysis script the area skeleton stamps; its `--check` holds the note
ANALYZE_SCRIPT = Path("scripts") / "02_analyze.py"


def check_analysis_script(area: Path, repo: Path) -> str | None:
    """Why `02_analyze.py --check` does not pass, or None: missing, or a
    nonzero exit with the last lines it printed."""
    script = area / ANALYZE_SCRIPT
    if not script.is_file():
        return f"no {ANALYZE_SCRIPT} — the check that holds the note to the run is owed"
    r = subprocess.run(
        [area_test_python(repo), str(script), "--check"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if r.returncode == 0:
        return None
    tail = (r.stderr.strip() or r.stdout.strip() or "no output").splitlines()[-3:]
    return f"{ANALYZE_SCRIPT} --check exits {r.returncode}: " + " | ".join(tail)


def report_check(area: Path, protocol: Path | None = None) -> int:
    """Run the stations on AREA; 0 clean, 1 a blocker, 2 no protocol to hold."""
    chosen = choose_protocol(area, protocol, "report-check")
    if chosen is None:
        return 2
    try:
        head = protocol_block.head(chosen.read_text(encoding="utf-8"))
    except protocol_block.BlockError as exc:
        print(f"report-check: {chosen.name}: {exc}")
        return 2
    if head.cost == "seconds":
        print(
            f'report-check: {chosen.name} is at cost = "seconds" — nothing owed here; '
            f"the short lane ends with finalize (LAB-017 The number of audits follows the cost tier)"
        )
        return 0
    blockers: list[str] = []
    if not head.frozen:
        blockers.append(
            f"{chosen.name}: not `frozen = true` — a reported number owes the freeze"
        )
    with contextlib.redirect_stdout(io.StringIO()):
        finalized = finalize_area(area, chosen)
    if finalized != 0:
        blockers.append(f"finalize {area} has blockers — run it to see them")
    try:
        sha = area_stamp(area)[0]
        gap = findings.audit_coverage(area, sha, "analysis")
    except (FileNotFoundError, ValueError) as exc:
        gap = f"the analysis audit cannot be held to the code: {exc}"
    if gap:
        blockers.append(
            f"analysis audit: {gap} (LAB-050 Analysis audit before reporting)"
        )
    failed = check_analysis_script(area, layout_root(area))
    if failed:
        blockers.append(f"{failed} (LAB-041 Generate numbers, don't retype them)")
    for b in blockers:
        print(f"  BLOCKER: {b}")
    print(
        f"report-check {chosen.name}: "
        + (
            f"{len(blockers)} blocker(s)"
            if blockers
            else "clean — frozen, finalized, audited, checked"
        )
    )
    return 1 if blockers else 0


def main(argv: list[str]) -> int:
    """Command line of `report-check`."""
    ap = argparse.ArgumentParser(
        prog="report-check", description=(__doc__ or "").split("\n\n")[0]
    )
    ap.add_argument("area", type=Path)
    ap.add_argument("--protocol", type=Path, default=None)
    a = ap.parse_args(argv)
    if not a.area.is_dir():
        print(f"report-check: {a.area} is not a directory")
        return 2
    return report_check(a.area.resolve(), a.protocol)


def cli() -> None:
    """Console entry point `report-check`."""
    console.exit_with(main)


if __name__ == "__main__":
    cli()
