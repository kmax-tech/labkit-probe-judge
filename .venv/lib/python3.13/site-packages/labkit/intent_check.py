"""intent-check — do the metrics report every promise the protocol made?

The most frequent blocker class of the first audits (2026-09-08, areas
62-65) was "registered without implementation": a fork with no branch in
the code, an admissibility condition printed but never compared to its threshold, a
three-conjunct criterion implemented as one conjunct, gate metrics written
next to the content numbers the gate was meant to suppress. Reading catches
this late; a set comparison catches it mechanically.

The contract (LAB-004 Identifiers make the intent addressable): every registration that promises the
code something — a verdict, a branch, an abort, a control — carries an id
in the protocol text (`[C1]` criterion, `[A1]` admissibility condition,
`[B1]` registered branch; the alphabet is `promises`), and every id
reappears as a lowercase key in the reportable run's metrics.json
(`c1_pass`, `a1_pass`, `b1_branch`, or the bare id). This command checks the two sets
against each other, in both directions:

- an id with no metrics key: the promise has no implementation evidence;
- a metrics key in the id namespace with no registration: something was
  built that nobody registered.

Letters that are metric names (F, P, R, Q, H) are never ids: in the F
namespace an `f1_score` in the metrics would "satisfy" a registered promise
that has no implementation at all.

Existence, not correctness: a key `a1_pass` proves the stage reports, not
that it computes the right thing — the semantic half stays with the
preflight audit (LAB-015 Preflight audit before freezing), which works the same ids.

Since 2026-10-06 the alphabet lives in `promises`: the letters C
(criterion), A (admissibility), B (branch), and the promise block that
makes them data. With a block, three more checks run here — text and block
name the same ids, every declared key is reported exactly, and the run
recorded this very block.

A protocol without ids exits 0 with a note: nothing is promised.

WHICH run answers is decided by the binding, not by the directory: the
protocol's head carries an id and a run records the id it belongs to, so
only completed runs with that id take part in the automatic choice
(`docs/protocol-run-binding.md`). `protocol.path` never selects — it goes
stale by design. A protocol without a stamped id binds nothing; then the
run is named with --metrics.
"""

from __future__ import annotations

import ast
from pathlib import Path

from labkit import console, promises, protocol_block
from labkit.runs import (
    COMPLETED,
    MetricsError,
    bound_answering_run,
    read_metrics,
    read_run_config,
    run_facts,
)
from labkit.repo import layout_root
from labkit.scope_sha import area_files, imported_repo_helpers

# The alphabet lives in `promises`; these names stay importable from here
# because code_check and tools outside labkit (befundregister) use them.
ID_IN_PROTOCOL = promises.ID_IN_PROTOCOL
ID_KEY = promises.ID_KEY
ids_in_prose = promises.ids_in_prose
reported_intent_ids = promises.reported_ids


def protocol_id_of(text: str) -> str | None:
    """The stamped id of the protocol's head, None while it is unstamped.
    A missing or malformed head raises protocol_block.BlockError."""
    return protocol_block.head(text).id


def main(argv: list[str]) -> int:
    """intent-check: every registered promise id reports as a key of the
    answering run's metrics.json. Exit 0 all keys present, 1 findings (a key
    missing or extra), 2 no check (no bound run, unreadable artefact, no
    stamped id). `finalize` treats 1 and 2 alike as a blocker."""
    try:
        return _main(argv)
    except ValueError as exc:  # read_metrics / RunConfigError
        print(f"intent-check: {exc}")
        return 2


def _main(argv: list[str]) -> int:  # noqa: C901 complexity baseline 2026-10-08
    if not argv or argv[0] in ("-h", "--help"):
        print((__doc__ or "").strip().splitlines()[0])
        print("usage: intent-check <PROTOCOL-*.md> [--metrics FILE]")
        print(
            "  --metrics FILE  metrics.json to check against. Default: "
            "the newest COMPLETED run bound to this protocol's id that "
            "reports intent keys; required while the protocol's id is "
            "unstamped."
        )
        return 0 if argv else 2

    protocol = Path(argv[0])
    metrics_arg = None
    if len(argv) >= 3 and argv[1] == "--metrics":
        metrics_arg = Path(argv[2])
    elif len(argv) > 1:
        print(f"intent-check: unexpected argument {argv[1]!r}")
        return 2

    if not protocol.is_file():
        print(f"intent-check: no such protocol: {protocol}")
        return 2
    text = protocol.read_text(encoding="utf-8")
    try:
        pid = protocol_id_of(text)
    except protocol_block.BlockError as exc:
        print(f"{protocol}: {exc}")
        return 2
    try:
        block = promises.parse_block(text)
    except promises.PromiseError as exc:
        print(f"{protocol}: promise block: {exc}")
        return 2
    if block is not None:
        only_prose, only_block = promises.prose_mismatch(text, block)
        for i in only_prose:
            print(
                f"{protocol}: [{i}] appears in the text but not in the "
                f"promise block — a promise must be data to be checked."
            )
        for i in only_block:
            print(
                f"{protocol}: [{i}] is in the promise block but never "
                f"named in the text — say what it promises where the "
                f"reader looks."
            )
        if only_prose or only_block:
            return 1

    earlier = promises.earlier_ids(text)
    if earlier:
        print(
            f"{protocol}: intent ids {', '.join(earlier)} — {promises.EARLIER_IDS_HELP}"
        )
        return 2
    reg = ids_in_prose(text)
    if not reg:
        print(
            "intent-check: no intent ids registered ([C1]/[A1]/[B1] — "
            "LAB-004 Identifiers make the intent addressable); nothing to hold the metrics against."
        )
        return 0

    if metrics_arg is not None:
        chosen = choose_explicit(protocol, metrics_arg, pid)
    elif pid is not None:
        chosen = choose_bound(protocol, pid)
    else:
        print(
            f"intent-check: {protocol.name} has no stamped id ([protocol] "
            f"id) — no run is bound to it; name the run with --metrics FILE."
        )
        return 2
    if isinstance(chosen, int):
        return chosen
    mpath = chosen
    try:
        metrics = read_metrics(mpath)
    except MetricsError as exc:
        print(f"intent-check: {exc}")
        return 2
    led = reported_intent_ids(metrics)

    missing = sorted(reg - led)
    unregistered = sorted(led - reg)
    for i in missing:
        print(
            f"{protocol}: [{i.upper()}] registered, but {mpath.name} has no "
            f"'{i}'/'{i}_*' key — the promise has no implementation "
            f"evidence in the metrics."
        )
    for i in unregistered:
        print(
            f"{mpath}: key '{i}'/'{i}_*' is in the intent-id namespace, but "
            f"the protocol registers no [{i.upper()}] — built without a "
            f"registration."
        )
    block_findings = (
        check_block_against_run(block, mpath, metrics) if block is not None else []
    )
    for f in block_findings:
        print(f)
    if missing or unregistered or block_findings:
        return 1
    print(
        f"intent-check: {len(reg)} id(s) registered, all report in "
        f"{mpath.name}."
        + (
            f" Promise block {block.sha} is the one the run recorded."
            if block is not None
            else ""
        )
    )
    return 0


def check_block_against_run(
    block: "promises.PromiseTables", mpath: Path, metrics: dict
) -> list[str]:
    """Guaranteed-tier findings for a protocol WITH a promise block.

    Two things the prose check cannot see: every declared key is reported
    exactly (a `c1_pass` promise is not answered by `c1_debug`), and the
    run recorded THIS block — same constants, same scopes, same keys. A
    block edited after the run would otherwise hold today's thresholds
    against yesterday's number.
    """
    out = []
    for p in block.promises:
        if p.key not in metrics:
            out.append(
                f"{mpath}: [{p.id}] declares key '{p.key}', which the "
                f"run does not report."
            )
    cfg = read_run_config(mpath.parent) or {}
    recorded = cfg.get("promises")
    drift = promises.block_drift(recorded, block)
    if drift:
        out.append(f"{mpath.parent.name}: {drift}.")
    out += promised_constant_mismatches(
        block, cfg.get("config") or {}, mpath.parent.name
    )
    return out


def promised_constant_mismatches(
    block: promises.PromiseTables, run_config: dict, run_name: str
) -> list[str]:
    """The constants the protocol promised (a margin, a threshold) whose value
    differs from the one the run recorded under the same name, or is absent.

    The script is meant to read its thresholds from the block
    (`promises.constants`). One that keeps its own copy — `min_f1 = 0.5`
    against 0.6 in the protocol — judged by a threshold nobody registered
    (Durchstich 2026-10-06). Exact, but only as far as the script records
    the value in its run config; a copy it never records stays invisible
    here (0.70.0). Since 0.71.0 a missing constant is a finding too: runlog
    refuses such a run before mkdir, so a record without it is an old run
    or a hand-written one.
    """
    out = []
    for r in promises.constant_records(block, run_config):
        if r.state == "different":
            out.append(
                f"{run_name}: [{r.promise_id}] declares {r.name} = {r.promised!r}, "
                f"the run used {r.name} = {r.recorded!r} — read "
                f"it with promises.all_constants(), not a second copy."
            )
        elif r.state == "missing":
            out.append(
                f"{run_name}: [{r.promise_id}] declares {r.name} = {r.promised!r}, "
                f"the run recorded no constant of that name — a run under "
                f"labkit 0.71 or later cannot start without it; an older run is "
                f"checked and reproduced with its pinned version (0.70.0 was the "
                f"last that let it pass)."
            )
    return out


# --- which metrics file answers: named explicitly, or chosen by binding -----
#
# Each returns the chosen metrics.json, or an int: the exit code, with the
# reason already printed. `_main` only dispatches, then checks.


def choose_explicit(protocol: Path, metrics_arg: Path, pid: str | None) -> Path | int:
    """`--metrics FILE`: the named file, if it may answer for this protocol."""
    if not metrics_arg.is_file():
        print(f"intent-check: no such metrics file: {metrics_arg}")
        return 2
    # An explicit file still has to be a file that MAY answer for this
    # protocol. Naming one was always a seatbelt, never a proof of
    # belonging — where the run records a binding, that proof now
    # exists and is checked (2026-09-26).
    facts = run_facts(metrics_arg.parent)
    # A run that did not complete has numbers on disk and no finish —
    # "nothing may report it" (protocol-run-binding.md); naming the file
    # must not be a loophole around completion.
    if facts is None or facts["state"] != COMPLETED:
        state = facts["state"] if facts else "no config.json"
        why = (facts or {}).get("why") or (
            "an incomplete run's numbers may not be reported, even when named explicitly"
        )
        print(
            f"intent-check: {metrics_arg.parent.name} is not completed ({state}) — {why}."
        )
        return 2
    if facts["protocol_id"]:
        if pid and facts["protocol_id"] != pid:
            print(
                f"intent-check: {metrics_arg} belongs to protocol "
                f"{facts['protocol_id']}, this protocol is {pid} — "
                f"holding one protocol's promises against another "
                f"protocol's run answers nothing."
            )
            return 2
        if pid is None:
            print(
                f"intent-check: WARNING — {metrics_arg} is bound to "
                f"{facts['protocol_id']}, but {protocol.name} carries no "
                f"stamped id to hold it against. Checking anyway, unverified."
            )
    else:
        print(
            f"intent-check: WARNING — {metrics_arg} records no binding "
            f"(unbound run); nothing proves it belongs to {protocol.name}. "
            f"Checking anyway, unverified."
        )
    return metrics_arg


def choose_bound(protocol: Path, pid: str) -> Path | int:
    """The newest completed run bound to `pid` — `runs.bound_answering_run`,
    its outcome told the operator; 2 when no choice stands."""
    choice = bound_answering_run(protocol.parent, pid)
    if choice.run_dir is None:
        # blocker: no completed bound run, or a newer run whose binding
        # cannot be read — either way nothing may answer (run_dir is None
        # whenever blocker is set, 0.74.0)
        print(
            f"intent-check: {choice.blocker} ({protocol.name}) — nothing to hold "
            f"the promises against."
        )
        if choice.exclusions:
            print(f"  {len(choice.exclusions)} other run(s) in {protocol.parent}:")
            for x in choice.exclusions:
                print(f"    {x.run_dir.name}: {x.why}")
        else:
            print(f"  no runs in {protocol.parent} yet.")
        print("  Name one explicitly with --metrics FILE if you know it belongs here.")
        return 2
    if not choice.reports_intent_keys:
        print(
            f"intent-check: {choice.run_dir.name} is the newest bound run, and no "
            f"bound run reports an intent key — a probe or producer run, not an "
            f"answer; every promise below will read as unimplemented."
        )
    if choice.skipped_newer:
        print(
            f"intent-check: using {choice.run_dir.name}/metrics.json "
            f"(newest bound run with intent keys; skipped {choice.skipped_newer} "
            f"newer bound run(s) without any)."
        )
    return choice.run_dir / "metrics.json"


def cli() -> None:
    """Entry point for the installed `intent-check` command."""
    console.exit_with(main)


if __name__ == "__main__":
    cli()


# --- preflight half: ids against the CODE, before any run exists ----------
#
# main() above answers the report-time question (do the METRICS report every
# promise?) and needs a runs/*/metrics.json. Before the run that file does not
# exist, so the same promise goes unchecked exactly when checking it is still
# cheap. code_ids() answers the earlier question from the source: does the code
# even MENTION the key it is supposed to report? An id that appears nowhere in
# the scripts cannot report at run time — that is mechanical, not a judgement.

ID_LITERAL = promises.ID_LITERAL


def code_ids(area: Path, suffixed_only: bool = False) -> dict[str, list[str]]:
    """Intent ids the area's source mentions, mapped id -> ["file:line", ...].

    Reads the string literals, not the syntax: a metric key reaches
    metrics.json as `"c1_pass"` however it is assembled, and a literal is
    what every assembly path has in common.

    `suffixed_only` keeps `"a1_pass"` and drops a bare `"a65"`. A bare id in
    the namespace is ambiguous — area 72 named its source sessions `"s65"`,
    `"s68"`, `"s69"` after the areas they came from, and reading those as
    unregistered promises produced three findings and no defect (2026-09-10).
    For "registered but absent from the code" every literal counts; for the
    reverse direction only an unmistakable metric key does.

    Keyword arguments count too: `r.metrics(c1_pass=acc >= MIN)` reaches
    metrics.json as `"c1_pass"` without ever being a string literal, and
    reading literals only reported a correct script as "no script mentions
    'c1'" — a blocker against correct code (2026-10-06, found in the first
    promise-block run). Only
    keyword names in CALLS count, not assignments: a local `c1_pass = …`
    is not yet a reported key. A file that does not parse keeps its literal
    hits and loses only the keyword half.
    """
    hits: dict[str, list[str]] = {}
    for key, where in code_keys(area).items():
        if suffixed_only and "_" not in key:
            continue
        m = ID_KEY.match(key)
        assert m is not None, f"code_keys returned a non-id key {key!r}"
        hits.setdefault(m.group(1), []).extend(where)
    for locs in hits.values():
        locs.sort()
    return hits


def code_keys(area: Path) -> dict[str, list[str]]:
    """Full intent keys the area's source mentions, key -> ["file:line", ...].

    The same scan as `code_ids` (string literals, keyword arguments in
    calls), but keeping the whole key: a promise block declares `c1_pass`,
    and `"c1_passed"` in the code answers the id, not the key. Preflight
    holds the block's keys to this, before any run (Durchstich 2026-10-06:
    a renamed key surfaced only after the run).
    """
    hits: dict[str, list[str]] = {}
    # The imported repo-local code counts as the area's: a shared helper
    # under src/ or lib/ may write a registered key, and reading the area's
    # scripts alone made four promises "absent" (2026-10-07). The house rule
    # (CODE-016 The experiment area reconstructs itself) now wants every id
    # literal in the area script, because an id in shared code is counted
    # for every importing area; the scan stays transitive so a repo that
    # has not moved yet is checked, not waved through.
    root = layout_root(area)
    own = area_files(area)
    for path in own + imported_repo_helpers(area, root):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for lineno, line in enumerate(source.splitlines(), 1):
            for m in ID_LITERAL.finditer(line):
                key = (m.group(1) + (m.group(2) or "")).lower()
                hits.setdefault(key, []).append(f"{_where(path, area, root)}:{lineno}")
        for name, lineno in _keyword_names(source, path):
            if ID_KEY.match(name.lower()):
                hits.setdefault(name.lower(), []).append(
                    f"{_where(path, area, root)}:{lineno}"
                )
    return hits


def _where(path: Path, area: Path, root: Path) -> str:
    """An area file by its name, an imported one by its repo path."""
    if path.parent.parent == area:
        return path.name
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _keyword_names(source: str, path: Path) -> list[tuple[str, int]]:
    """(name, line) of every keyword argument in a call; [] if unparsable."""
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    return [
        (kw.arg, kw.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg is not None
    ]
