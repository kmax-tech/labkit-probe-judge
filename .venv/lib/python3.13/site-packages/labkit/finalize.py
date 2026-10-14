"""finalize — the gate after a run, before a number is reported.

Sequences the checks that must pass before results are written back into
the protocol.

    finalize <AREA> [--protocol PROTOCOL-*.md]

Exit codes: 0 clean, 1 findings (at least one blocker), 2 usage error.

What it runs, in order (the same numbers as `finalize_area`, which shows
each step's condition):
  0. protocol       the named PROTOCOL-*.md or the area's only one, and its
                    settings block — the only early end (exit 2)
  1. answering run  the run that answers — the newest completed bound run
                    reporting an intent key, the same choice as intent-check
                    — and every later step checks THAT run. Then its record:
                    the run the answer cites is this one (blocker), the
                    `Answering run` field names it (blocker/warning), its
                    JSONL rows come from this run, the runs it continues or
                    its derived_from lineage (blocker), a model record stands
                    in its lineage (warning), the arm lines match (warning)
  2. intent-check   every registered promise has a metrics key (and vice
                    versa); skipped when the protocol registers no id
  3. declared scopes  every declared promise scope unchanged since the run
  4. open fields    protocol fields still holding a placeholder
  5. frozen source  at protocol `cost = "seconds"` only: the run froze its source
                    (`data=` in config.json) and every source and output file
                    is tracked in git — the two of the three questions the
                    agent audit kept asking that a machine can answer (LAB-017 The number of audits follows the cost tier, 2026-10-05);
                    the third, the counted unit, is the protocol's `Unit` field
  6. area tests     tests/test_<NN>_<name>.py via the repo's interpreter, on
                    every tier: a failing test is a blocker (evaluate() lost
                    its resolution check), a missing one no finding here
  7. criterion n    every `c<i>_n` key in metrics.json equals some input
                    count the run recorded (rows of a data= file, lines of
                    an output) — a warning, not a blocker, until the false
                    alarm rate is known (2026-10-05; the denominator class
                    was 31 of 171 audit findings)

Three grades, decided where each finding is made and summed at the end:
`Findings.block` (exit 1), `Findings.warn` (counted, exit 0), a plain
print (a note, uncounted). "0 blockers, N warnings" sums the warnings of
every station, not the open fields alone.

What it does NOT do: fill fields, edit the protocol, or commit. It is a
read-only gate that reports findings.
"""

from __future__ import annotations

import contextlib
import io
import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from labkit import batch, console, promises, protocol_block
from labkit.runs import (
    RUN_ID,
    bound_answering_run,
    model_provenance_run,
    read_metrics,
    read_outputs,
    read_run_config,
    resolve_recorded,
)
from labkit.repo import (
    area_path,
    choose_protocol,
    git_root,
    git_run,
    no_such_area,
)
from labkit.intent_check import main as intent_check_main, ids_in_prose
from labkit.preflight import area_tests
from labkit.protocol_check import (
    answering_run_field,
    answering_run_open,
    fields,
    open_holes,
)


def _tracked(repo: Path, path: Path) -> bool:
    """Is `path` tracked in `repo`? The exit code is the answer."""
    return git_run(["ls-files", "--error-unmatch", str(path)], repo).returncode == 0


CRITERION_N = promises.CRITERION_N_KEY


def criterion_n_input_mismatches(measurement_run: Path) -> list[str]:  # noqa: C901 complexity baseline 2026-10-08
    """Warnings: a criterion's denominator (`c<i>_n` in metrics.json) that
    matches no input count the run recorded — the size of what was counted,
    not a promised constant (that is `intent_check.promised_constant_mismatches`)."""
    metrics_file = measurement_run / "metrics.json"
    if not metrics_file.is_file():
        return []
    metrics = read_metrics(metrics_file)
    ns = {
        k: v
        for k, v in metrics.items()
        if CRITERION_N.match(k) and isinstance(v, int) and not isinstance(v, bool)
    }
    if not ns:
        return []
    cfg = read_run_config(measurement_run) or {}
    counts: dict[str, int] = {}
    for key, d in (cfg.get("data") or {}).items():
        if isinstance(d, dict) and isinstance(d.get("rows"), int):
            counts[f"data[{key}].rows"] = d["rows"]
    for o in read_outputs(measurement_run) or []:
        if o.lines is not None:
            counts[f"{o.path.name} lines"] = o.lines
    if not counts:
        return [
            f"{', '.join(sorted(ns))} present, but the run recorded no input count "
            f"(no data= rows, no output lines) to hold them to"
        ]
    out = []
    for k, n in sorted(ns.items()):
        if n not in counts.values():
            out.append(
                f"{k} = {n} matches no recorded count "
                f"({', '.join(f'{a} = {b}' for a, b in sorted(counts.items()))}) — "
                f"a denominator that is not the input is the audits' most "
                f"frequent real finding"
            )
    return out


def provenance_findings(
    area: Path, measurement_run: Path
) -> tuple[list[str], list[str]]:
    """(blockers, warnings) for a run of seconds: source frozen, files tracked."""
    blockers: list[str] = []
    warnings: list[str] = []
    cfg = read_run_config(measurement_run) or {}
    data = cfg.get("data") or {}
    if not data:
        blockers.append(
            "source not frozen — the run carries no `data=`; pass "
            "data={name: path} to runlog.run so sha and rows are recorded"
        )
    sources = [
        resolve_recorded(v["path"], measurement_run)
        for v in data.values()
        if isinstance(v, dict) and v.get("path")
    ]
    registered = read_outputs(measurement_run)
    outputs: list[Path] = [o.path for o in registered or []]
    if registered is None:
        warnings.append(
            "no outputs.json — the run registered no output file (run.output)"
        )
    repo = git_root(area)
    if repo is None:
        warnings.append(
            "not a git repository — cannot tell whether source and output are committed"
        )
        return blockers, warnings
    for f in sources:
        if not f.exists():
            blockers.append(f"{f} is gone — the run's rows cannot be re-derived")
        elif not _tracked(repo, f):
            blockers.append(
                f"source {f} is not tracked in git — commit it, or the number "
                f"cannot be re-derived"
            )
    # The output rows are born after the run, so on every first pass they are
    # untracked by construction: a warning that names the command, not a
    # blocker that sends the agent round the loop (2026-10-05, five probes).
    for f in outputs:
        if not f.exists():
            blockers.append(f"{f} is gone — the run's rows cannot be re-derived")
        elif not _tracked(repo, f):
            warnings.append(
                f"output {f.name} is not yet tracked — `git add {f}` before "
                f"the commit that cites the number"
            )
    return blockers, warnings


@dataclass
class Findings:
    """What the stations found: every blocker as one line, repeated in the
    summary — inside a commit hook the sections run to 20 lines and the one
    blocker drowned in the middle (usability probe 2026-10-07)."""

    blocked: list[str] = field(default_factory=list)
    warnings: int = 0

    def block(self, msg: str) -> None:
        """Print a blocker and keep it for the summary."""
        print(f"  BLOCKER: {msg}")
        self.blocked.append(msg)

    def warn(self, msg: str) -> None:
        """Print a warning and count it for the summary."""
        print(f"  warning: {msg}")
        self.warnings += 1


def answering_run(
    findings: Findings, area: Path, pid: str | None, ids_registered: bool
) -> Path | None:
    """The run every station holds the protocol to — `runs.bound_answering_run`,
    ONE choice for every station: intent-check skips newer runs without
    intent keys (a probe), so checking scopes or provenance on the newest
    run judged the probe while the numbers came from the measurement
    (review 2026-10-07). A blocker here is the finding; the exclusions are
    printed for the operator."""
    if pid is None:
        findings.block("no stamped protocol id ([protocol] id) — no run is bound to it")
        return None
    choice = bound_answering_run(area, pid)
    if choice.run_dir is None:
        findings.block(choice.blocker or f"no completed run bound to {pid}")
        for x in choice.exclusions:
            print(f"    {x.run_dir.name}: {x.why}")
        return None
    if ids_registered and not choice.reports_intent_keys:
        findings.block(
            f"{choice.run_dir.name}: no bound run reports an intent key — the "
            f"newest is a probe or producer run, not an answer"
        )
    note = (
        f" (skipped {choice.skipped_newer} newer bound run(s) without intent keys)"
        if choice.skipped_newer
        else ""
    )
    print(f"  {choice.run_dir.name}: completed{note}")
    return choice.run_dir


def cited_run_mismatch(text: str, measurement_run: Path) -> str | None:
    """A blocker when the protocol's answer cites runs and not the one the
    checks hold; None when it cites that run or none."""
    cited = cited_runs(text)
    if cited and measurement_run.name not in cited:
        return (
            f'"Answer to the question" cites {", ".join(cited)}, '
            f"but the run that answers is {measurement_run.name} — cite the run "
            f"the checks hold, or rerun"
        )
    return None


def answering_run_field_mismatch(
    text: str, measurement_run: Path
) -> tuple[str, str] | None:
    """("block" | "warn", message): the `Answering run` line names another
    run than the one the checks hold (block), or is still "none yet"
    (warn: write it with protocol-fill). None when it names that run or
    the protocol has no such line. The field is a readable projection of
    `runs.bound_answering_run`, never a second binding — so it is held to
    the choice, not consulted for it."""
    value = answering_run_field(text)
    if value is None or measurement_run.name in value:
        return None
    if answering_run_open(value):
        return (
            "warn",
            f'"Answering run" not written yet — `protocol-fill --from-run '
            f"{measurement_run.name}` writes it with the number once this finalize is clean",
        )
    return (
        "block",
        f'"Answering run" names {value.split()[0]}, but the run that answers is '
        f"{measurement_run.name} — the field is a projection of the binding; "
        f"protocol-fill it with the run the checks hold",
    )


def model_provenance_gap(measurement_run: Path) -> str | None:
    """Why the run's model cannot be named from its record, or None: its
    metrics show model calls (`llm_retries` recorded, or `model_calls` > 0)
    while no run in its lineage recorded `models_resolved` — the alias was
    not under `model`/`*_model`, the keys runlog resolves (uniagent areas
    14–17 recorded it as `judge`; round 15, 2026-10-08). Static evidence:
    a run without those keys may still have called a model."""
    try:
        metrics = read_metrics(measurement_run / "metrics.json")
    except (OSError, ValueError):
        return None
    calls = metrics.get("model_calls")
    called = "llm_retries" in metrics or (isinstance(calls, int) and calls > 0)
    if not called:
        return None
    try:
        if model_provenance_run(measurement_run) is not None:
            return None
    except ValueError as exc:
        return (
            f"model provenance: the lineage of {measurement_run.name} is broken — {exc}"
        )
    return (
        f"{measurement_run.name} called a model, but no run in its lineage recorded "
        f"models_resolved — record the alias under `model` (runlog resolves it); "
        f"a spec under another key is not provenance labkit can hold"
    )


def row_provenance_findings(measurement_run: Path) -> tuple[list[str], list[str]]:
    """(blockers, notes): every JSONL output of the run is held to the runs
    its rows name (`_prov.run`): rows may come from this run, from the runs
    it continues (a resumed file, named in outputs.json), or — for a
    derived run — from its derived_from lineage. Rows from any other run
    are a blocker: a file of two measurements. Rows without `_prov` are a
    note (a Store without `prov`), not proof of anything (2026-10-09)."""
    blockers, notes = [], []
    cfg = read_run_config(measurement_run) or {}
    allowed = {measurement_run.name}
    parent = cfg.get("derived_from")
    seen = 0
    while isinstance(parent, str) and parent and parent not in allowed and seen < 50:
        allowed.add(parent)
        pcfg = read_run_config(measurement_run.parent / parent) or {}
        parent = pcfg.get("derived_from")
        seen += 1
    for entry in read_outputs(measurement_run) or []:
        if entry.path.suffix != ".jsonl" or not entry.path.is_file():
            continue
        try:
            rr = batch.row_runs(entry.path)
        except ValueError as exc:
            blockers.append(f"{entry.path.name}: {exc}")
            continue
        ok = allowed | set(entry.continues)
        foreign = sorted(r for r in rr.runs if r not in ok)
        if foreign:
            blockers.append(
                f"{entry.path.name}: {sum(rr.runs[r] for r in foreign)} row(s) from "
                f"{', '.join(foreign)} — a run this run neither is, continues nor "
                f"derives from; a file of two measurements"
            )
        if entry.continues:
            notes.append(
                f"{entry.path.name}: continues {', '.join(entry.continues)} "
                f"({', '.join(f'{r}: {n}' for r, n in sorted(rr.runs.items()))} rows)"
            )
        if rr.unstamped:
            notes.append(
                f"{entry.path.name}: {rr.unstamped} row(s) without _prov — written "
                f"outside a run or by a Store without prov; their run is unknown"
            )
    return blockers, notes


ARM_LINE = re.compile(
    r"[Aa]rm\s+`?(?P<arm>[\w-]+)`?\s*[:=]\s*`?(?P<profile>[\w./-]+\.toml)`?"
    r"\s*@\s*`?(?P<sha>[0-9a-f]{8,64})`?(?:\s*,\s*model\s*=\s*`?(?P<model>[\w.:@-]+)`?)?"
)


def arm_findings(text: str, area: Path, measurement_run: Path) -> list[str]:
    """Warnings: every arm the protocol names as `Arm `x`: <profile>.toml @
    <fingerprint>, model=<alias>` is held to the answering run — the profile
    file exists in the repo, and fingerprint and alias stand somewhere in
    the run's config.json. The line is what a reader of the protocol gets
    instead of opening the register (2026-10-09: "what are before and
    after?" was answered 60 lines below the criterion, and the fingerprint
    nowhere but in the run). No arm line: nothing claimed, nothing checked."""
    out: list[str] = []
    cfg = read_run_config(measurement_run)
    if cfg is None:
        return out
    recorded = json.dumps(cfg, ensure_ascii=False)
    root = git_root(area) or area
    for m in ARM_LINE.finditer(text):
        arm, profile, sha, model = m.group("arm", "profile", "sha", "model")
        if not (root / profile).is_file():
            out.append(
                f"arm `{arm}`: the protocol names {profile}, no such file under {root}"
            )
        if sha not in recorded:
            out.append(
                f"arm `{arm}`: the protocol names fingerprint {sha}, the answering run "
                f"recorded no such value — the profile changed after the stamp, or "
                f"the run did not record its fingerprints"
            )
        if model and model not in recorded:
            out.append(
                f"arm `{arm}`: the protocol names model={model}, the answering run "
                f"recorded no such alias"
            )
    return out


def check_completion(
    findings: Findings, area: Path, text: str, pid: str | None
) -> Path | None:
    """Station 1: the run every later station holds the protocol to — chosen,
    shown, and held to the run the answer cites. Returns it, or None."""
    measurement_run = answering_run(findings, area, pid, bool(ids_in_prose(text)))
    if measurement_run is not None:
        mismatch = cited_run_mismatch(text, measurement_run)
        if mismatch:
            findings.block(mismatch)
        graded = answering_run_field_mismatch(text, measurement_run)  # (grade, message)
        if graded is not None:
            grade, message = graded
            (findings.block if grade == "block" else findings.warn)(message)
        gap = model_provenance_gap(measurement_run)
        if gap:
            findings.warn(gap)
        blockers, notes = row_provenance_findings(measurement_run)
        for b in blockers:
            findings.block(b)
        for n in notes:
            print(f"  {n}")
        for w in arm_findings(text, area, measurement_run):
            findings.warn(w)
    return measurement_run


def check_intent_keys_in_metrics(
    findings: Findings, protocol: Path, text: str, measurement_run: Path | None
) -> None:
    """Station 2: every registered intent id reports as a key of the answering
    run's metrics.json (intent-check). Not code_check.check_intent_ids, which
    holds the promises to the code before any run."""
    if not ids_in_prose(text):
        print("  no intent ids registered — nothing to check")
        return
    args = [str(protocol)] + (
        ["--metrics", str(measurement_run / "metrics.json")]
        if measurement_run is not None
        else []
    )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = intent_check_main(args)
    for line in buf.getvalue().splitlines():
        print(f"  {line}")
    if rc != 0:
        findings.block("intent-check failed (see its lines above)")


def check_declared_scopes(
    findings: Findings, area: Path, measurement_run: Path, text: str = ""
) -> None:
    """Station 3: a promise's declared scope edited after the run: today's code is not
    the code that produced the number; until 2026-10-06 only recheck saw it
    (Durchstich). An answering run that recorded no block is a blocker
    (standard 0.19, `promises.promise_tables_owed`: every reportable run is held to
    a registration that is data) — it came from a labkit that let it pass,
    or the block was added after the run."""
    recorded = (read_run_config(measurement_run) or {}).get("promises")
    if recorded is None and text and not promises.registers_ids(text):
        print("  n/a — the protocol registers no promise id (a count), nothing to hold")
        return
    if recorded is None:
        owed = promises.promise_tables_owed(None, frozen=False, full_run=True)
        findings.block(
            f"{measurement_run.name} recorded no promise block: {owed} — a run "
            f"under labkit 0.70.0 or earlier is checked and reproduced with "
            f"its pinned version; a block added after the run is a new registration"
        )
        return
    drift = promises.scope_drift(recorded, area)
    for d in drift:
        findings.block(
            f"declared scope changed since {measurement_run.name}: {d} — rerun before reporting"
        )
    if not drift:
        print(
            f"  {len(recorded['ids'])} declared scope(s) unchanged since {measurement_run.name}"
        )


# the stamp's blanks may wrap lines; an HTML comment (`<!-- labkit:route -->`)
# is a marker, not a blank
_PLACEHOLDER = re.compile(r"<(?!!--)[^<>]{3,}>")


def readme_placeholders(area: Path) -> list[str]:
    """Lines of the area's README.md still holding a stamped `<…>` placeholder.
    A README that still carries the stamp's blanks tells a reader nothing and
    looks as if it did (code-navigation round 11). No README: nothing."""
    readme = area / "README.md"
    if not readme.is_file():
        return []
    text = readme.read_text(encoding="utf-8")
    # a `<path>/<id>` inside a code span or a fenced block is an example, not a
    # blank (cloud probe 2026-10-12, draw 4: a gate line and a reword for nothing)
    scan = re.sub(
        r"```.*?```|`[^`\n]*`",
        lambda m: " " * len(m.group()),
        text,
        flags=re.S,
    )
    out = []
    for m in _PLACEHOLDER.finditer(scan):
        line = text.count("\n", 0, m.start()) + 1
        out.append(f"README.md:{line}: {' '.join(m.group(0).split())[:70]}")
    return out


ROUTE_START = "<!-- labkit:route -->"
ROUTE_END = "<!-- /labkit:route -->"
#: What the README's route must point to: the stations a reader takes after
#: the protocol — which run (`runlog`), which values (`labkit-params`), where
#: the ids are decided, the proof (CODE-016 The experiment area reconstructs
#: itself). The README points; it copies no question, answer, run id or
#: threshold — each has its one home, and a copy went stale within a day
#: (area 08, 2026-10-08).
ROUTE_STATIONS = (
    "runlog",
    "labkit-params",
    "scripts/01_measure.py:evaluate_rows",
    "config.json",
)


def readme_route(area: Path, protocol_name: str) -> list[str]:
    """Why the README's route block cannot lead a reader: no block between
    the markers, the protocol or a station not named, or
    `scripts/01_measure.py` without an `evaluate_rows`. No README: nothing.
    The block is checked, never written — finalize reads only; the stamp
    writes it."""
    readme = area / "README.md"
    if not readme.is_file():
        return []
    text = readme.read_text(encoding="utf-8")
    start, end = text.find(ROUTE_START), text.find(ROUTE_END)
    if start < 0 or end < start:
        return [
            f"README.md: no {ROUTE_START} … {ROUTE_END} block — the route "
            f"(protocol · runlog · labkit-params · evaluate_rows · config.json) "
            f"is what a reader opens first"
        ]
    block = text[start:end]
    out = []
    if protocol_name not in block:
        out.append(f"README.md route: does not name {protocol_name}")
    for station in ROUTE_STATIONS:
        if station not in block:
            out.append(f"README.md route: does not name {station}")
    script = area / "scripts" / "01_measure.py"
    if not script.is_file():
        out.append("README.md route: scripts/01_measure.py does not exist")
    elif not any(
        isinstance(n, ast.FunctionDef) and n.name == "evaluate_rows"
        for n in ast.parse(script.read_text(encoding="utf-8")).body
    ):
        out.append("README.md route: scripts/01_measure.py defines no evaluate_rows")
    return out


def check_open_fields(
    findings: Findings, protocol: Path, text: str, head: protocol_block.Head
) -> None:
    """Station 4: fields of the protocol still empty or a placeholder, and
    the README's route block (CODE-016)."""
    holes = open_holes(text, head)
    for lineno, label in holes:
        findings.warn(f"{protocol.name}:{lineno}: {label}")
    stale = readme_placeholders(protocol.parent)
    for line in stale:
        findings.warn(f"{line} — a stamped placeholder, fill or delete the line")
    route = readme_route(protocol.parent, protocol.name)
    for line in route:
        findings.warn(line)
    if not holes and not stale and not route:
        print("  all fields filled")


def check_provenance(findings: Findings, area: Path, measurement_run: Path) -> None:
    """Station 5: the run's source frozen in the run, source and output
    tracked in git."""
    b, w = provenance_findings(area, measurement_run)
    for line in b:
        findings.block(line)
    for line in w:
        findings.warn(line)
    if not b and not w:
        print("  source frozen in the run; source and output tracked in git")


def check_area_tests(findings: Findings, area: Path) -> None:
    """Station 6: the area's own tests. The resolution check runs again before a number leaves: a later edit
    of evaluate() that mutes the criterion is caught here too — on every
    tier, seconds included, where preflight is not owed (2026-10-07). A
    missing test is no finding here; preflight owes it at the freeze."""
    tests = area_tests(area, git_root(area) or area)
    if tests.state == "none":
        print(f"  none ({tests.pattern})")
    elif tests.state == "ok":
        print(f"  ok — {', '.join(t.name for t in tests.files)}")
    elif tests.state == "no-pytest":
        findings.warn("pytest is not installed in this interpreter — tests not run")
    else:
        for ln in tests.tail:
            print(f"  {ln}")
        findings.block(
            f"{', '.join(t.name for t in tests.files)} failed — evaluate() no longer holds its resolution check"
        )


def check_criterion_n(findings: Findings, measurement_run: Path) -> None:
    """Station 7: a criterion's denominator that matches no recorded input count."""
    w = criterion_n_input_mismatches(measurement_run)
    for line in w:
        findings.warn(line)
    if not w:
        print("  every c<i>_n equals a recorded input count (or there is none)")


def report(findings: Findings) -> int:
    """The summary: every blocker once more, then the exit code (0 clean, 1
    findings)."""
    print()
    if findings.blocked:
        print(
            f"finalize: {len(findings.blocked)} blocker(s), {findings.warnings} warning(s) — fix the blockers before reporting:"
        )
        for msg in findings.blocked:
            print(f"  - {msg}")
        return 1
    if findings.warnings:
        print(
            f"finalize: 0 blockers, {findings.warnings} warning(s) — review the warnings above before reporting."
        )
        return 0
    print("finalize: all clear.")
    return 0


NO_RUN = "  no completed run to check"


def header(title: str) -> None:
    """Print a station's header line."""
    print(f"── {title} ──")


def finalize_area(area: Path, protocol: Path | None = None) -> int:
    """Run finalize on an area. Returns 0 (clean or warnings only),
    1 (a blocker) or 2 (no protocol to hold the area to).

    The flow — every condition that decides whether a step runs is in this
    function; one level down is how a step works, not whether it runs. A
    measurement run is one execution of the experiment's script, a folder
    under `runs/` bound to this protocol — not this function, and not the
    protocol itself.

    0. Choose the protocol and read its settings block. Ends at once with 2
       when the named file is missing, the folder holds several protocols
       and none is named, or the settings block cannot be read.
    1. completion — choose the measurement run the later steps examine
       (`measurement_run`); none bound is a blocker, and steps 3, 5 and 7
       then skip.
    2. intent-check — always; with a measurement run it reads its metrics.
    3. declared scopes — only with a run.
    4. open fields — always; warnings only: protocol placeholders and
       stamped `<…>` placeholders left in the area's README.
    5. provenance — only for cost = seconds, and only with a run.
    6. area tests — always.
    7. criterion n — only with a run; warnings only.

    A blocker never stops a step: all of them run, then the summary lists
    every blocker again. Warnings alone end with 0.
    """
    # 0. protocol and settings — the only early end
    chosen = choose_protocol(area, protocol, "finalize")
    if chosen is None:
        return 2
    text = chosen.read_text(encoding="utf-8")
    try:
        head = protocol_block.head(text)
    except protocol_block.BlockError as exc:
        print(f"finalize: {chosen.name}: {exc}")
        return 2
    findings = Findings()

    # 1. completion — the run every later step examines
    header(f"completion: {chosen.name}")
    measurement_run = check_completion(findings, area, text, head.id)

    # 2. intent-check — always
    header("intent-check")
    check_intent_keys_in_metrics(findings, chosen, text, measurement_run)

    # 3. declared scopes — only with a run
    header("declared scopes")
    if measurement_run is None:
        print(NO_RUN)
    else:
        check_declared_scopes(findings, area, measurement_run, text)

    # 4. open fields — always
    header(f"open fields: {chosen.name}")
    check_open_fields(findings, chosen, text, head)

    # 5. provenance — only for cost = seconds, and only with a run
    header("frozen source and tracked files")
    if head.cost != "seconds":
        print(
            "  n/a — protocol cost is not 'seconds' (the agent audit covers provenance there)"
        )
    elif measurement_run is None:
        print(NO_RUN)
    else:
        check_provenance(findings, area, measurement_run)

    # 6. area tests — always
    header("area tests")
    check_area_tests(findings, area)

    # 7. criterion n — only with a run
    header("criterion n")
    if measurement_run is None:
        print(NO_RUN)
    else:
        check_criterion_n(findings, measurement_run)

    return report(findings)  # 1 if any step found a blocker, else 0


def cited_runs(text: str) -> list[str]:
    """The run ids the protocol's "Answer to the question" cites — a number
    written back. Empty while the field is a placeholder or cites none."""
    for f in fields(text):
        if f.name == "answer to the question" and not f.placeholder:
            return sorted({m.group(0) for m in RUN_ID.finditer(f.value)})
    return []


def if_reported(protocols: list[Path]) -> int:
    """`finalize` for every protocol whose answer cites a run — the commit
    gate: a number written back does not enter the history unchecked
    (review 2026-10-07: nothing showed whether finalize ever ran). Returns
    the worst exit code; protocols without a cited run are skipped."""
    worst = 0
    for protocol in protocols:
        try:
            text = protocol.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"finalize: {protocol}: {exc}")
            worst = max(worst, 2)
            continue
        if not cited_runs(text):
            continue
        print(f"═══ finalize {protocol} (its answer cites a run) ═══")
        worst = max(worst, finalize_area(protocol.parent, protocol))
    return worst


def main(argv: list[str]) -> int:
    """Command line of `finalize`: check one area, or every protocol whose answer cites a run (`--if-reported`)."""
    if not argv or argv[0] in ("-h", "--help"):
        print((__doc__ or "").strip().splitlines()[0])
        print("usage: finalize <AREA> [--protocol PROTOCOL-*.md]")
        print(
            "       finalize --if-reported PROTOCOL-*.md ...   (the commit gate: only "
            "protocols whose answer cites a run)"
        )
        return 0 if argv else 2
    if argv[0] == "--if-reported":
        return if_reported([Path(a) for a in argv[1:]])

    area = area_path(argv[0])
    protocol = None
    rest = argv[1:]
    while rest:
        if rest[0] == "--protocol" and len(rest) >= 2:
            protocol = Path(rest[1])
            rest = rest[2:]
            continue
        print(f"finalize: unexpected argument {rest[0]!r}")
        return 2

    if not area.is_dir():
        print(f"finalize: {no_such_area(area)}")
        return 2

    return finalize_area(area, protocol)


def cli() -> None:
    """Console entry point of `finalize`."""
    console.exit_with(main)


if __name__ == "__main__":
    cli()
