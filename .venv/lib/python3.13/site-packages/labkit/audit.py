"""labkit-audit — the agent audits of an area, through any llm backend.

    labkit-audit <AREA> --mode preflight|analysis|clarity [--protocol FILE]
                 [--model ALIAS] [--timeout S] [--out FILE]

The agent audit of LAB-015 Preflight audit before freezing (preflight, before freezing) and LAB-050 Analysis audit before reporting
(analysis, before a number leaves) as one command — the only runner since
0.79.0; the Claude subagent copy of the instructions is gone. The
instructions ship with the package (`experiment-preflight.agent.md`); the
files they tell the auditor to read are gathered here and inlined — the
area's protocol, `scripts/*.py`, `analysis/*.py`, the repo-local `lib/`
modules they import, and from the lab standard that ships with labkit
exactly the rules the instructions cite (`cited_rules`):
LAB-015 Preflight audit before freezing (the scar table, the severity legend),
LAB-017 The number of audits follows the cost tier,
LAB-004 Identifiers make the intent addressable,
LAB-050 Analysis audit before reporting
— not the whole standard, which cost ~30k tokens per read and was read twice
per audit in uniagent, 2026-10-10. In MODE analysis the answering run's rows come too:
the first 50 and the last 20 lines of every output it registered, numbered,
and its `metrics.json` — the auditor has no tools, so what it is told to
look at must be on the page. One call goes through `labkit.llm` to the alias
the lab's `models.toml` names (`opus` by default, stamped as `claude-cli`).
Synchronous, with a timeout: on expiry the command fails, it never waits on
in the background.

Exit codes are the contract (the auditor's LAST verdict line decides — it
may correct itself below a finding; a disagreement between finding lines
and verdict is printed as a NOTE, 2026-10-09):
    0  no blocker and no warning
    1  findings to decide — a blocker OR a warning (labkit-paper benchmark,
       2026-10-06: the table-led audit found the positional-join fault only
       as a WARNING; an audit that passed on warnings would have let it by)
    2  no audit: a missing file, an unreadable report, a backend failure

The report is printed (and written to --out), and its findings are written
as data into the area — `audits/<date>-<mode>.toml`, one `[[finding]]` per
line, every one `open` (`labkit.findings`); deciding each (fixed / accepted
/ deferred / dismissed, with reason) and stamping the protocol field stays
with the human (LAB-015 Preflight audit before freezing), and `preflight`
holds the file to that. The command prints the stamp's facts — date, scope
sha, counts — to copy from, and what the call cost (`llm.last_usage()`:
prompt and output tokens, USD where the backend prices it) beside the
prompt size on stderr.

Mode `clarity` is the other reader (2026-10-09): the code-clarity agent's
area mode (`code-clarity.agent.md`) reads README, protocol and the measure
script the way a newcomer opens them and reports what that reader would
get wrong — template residue, a term before its definition, a docstring
that omits a conjunct. Static evidence: exit 1 means findings to read, it
stamps nothing and it is no proof the area is clear. Before freezing, while
the prose can still change.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import time
from pathlib import Path
from typing import NamedTuple

from labkit import console, findings, llm, promises, protocol_block, rules
from labkit.repo import ProtocolChoiceError, layout_root, no_such_area, the_protocol
from labkit.runs import bound_answering_run, completed_runs, read_outputs
from labkit.scope_sha import area_files, area_stamp, imported_repo_helpers, repo_imports

AGENT = Path(__file__).with_name("experiment-preflight.agent.md")
CLARITY_AGENT = Path(__file__).with_name("code-clarity.agent.md")
DEFAULT_MODEL = "opus"  # the agent's model; any alias of models.toml works
DEFAULT_TIMEOUT_S = 900  # one call reads the area, the cited rules, the rows
MODES = ("preflight", "analysis", "clarity")
CLARITY = "clarity"
ANALYSIS = "analysis"
STANDARD_LABEL = (
    "labkit/docs/standard.md"  # the shipped standard, wherever labkit is installed
)
ROWS_HEAD, ROWS_TAIL = 50, 20  # what the instructions tell the auditor to read
ROW_WIDTH = 2000  # a longer row (a trace) is cut, marked, never dropped

FINDING = re.compile(r"^[\s>*`-]*\**(BLOCKER|WARNING|NOTE)\**\s*·", re.M)
VERDICT = re.compile(
    r"verdict:\s*(\d+)\s*blockers?(?:\(s\))?,\s*(\d+)\s*warnings?(?:\(s\))?"
    r"(?:,\s*(\d+)\s*notes?(?:\(s\))?)?",
    re.I,
)
CLARITY_FINDING = re.compile(r"^[\s>*`-]*RULE\s*(\d+)\**\s*·", re.M)
CLARITY_VERDICT = re.compile(
    r"verdict:\s*(\d+)\s*findings?(?:\s*\((\d+)\s*would be answered wrong\))?", re.I
)
INLINE_NOTE = (
    "The files you are told to read are inlined below instead of read with "
    "tools; each starts with a `===== FILE: <path> =====` line, the rules of "
    "the standard under one such line, modules further down the import graph "
    "as signatures under one `===== INDEX: … =====` line (not read — name one "
    "in an assignment to have it supplied), and in MODE analysis the answering "
    "run's output rows under `===== ROWS <path> … =====` lines, each row as "
    "`<line>: <row>`. Nothing else is in scope."
)


class AuditError(RuntimeError):
    """No audit could be made — the cause is in the message."""


def instructions(mode: str = "preflight") -> str:
    """The agent's instructions as shipped, without the provenance comment —
    the preflight agent for preflight and analysis, the clarity agent for clarity."""
    agent = CLARITY_AGENT if mode == CLARITY else AGENT
    return re.sub(
        r"^<!--.*?-->\n", "", agent.read_text(encoding="utf-8"), count=1, flags=re.S
    )


def cited_rules(mode: str = "preflight") -> list[str]:
    """The `LAB-nnn` ids the instructions for MODE cite, in order of first
    mention — the part of the standard the auditor gets to read."""
    seen: list[str] = []
    for m in rules.CODE_RE.finditer(instructions(mode)):
        if m.group(1).startswith("LAB-") and m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def standard_excerpt(mode: str = "preflight") -> tuple[str, str]:
    """(label, text): the cited rules' blocks from the shipped standard, each
    from its head to the next. An id the ledger does not know, or whose text
    does not ship, raises — a missing rule must not pass as an audit without it."""
    ids = cited_rules(mode)
    text = "\n".join(rules.rule_text(rid) for rid in ids)
    return f"{STANDARD_LABEL} ({', '.join(ids)} — the rules this audit cites)", text


def run_rows(area: Path, protocol: Path) -> list[tuple[str, str]]:
    """What MODE analysis is told to read of the answering run: `(label,
    text)` per piece — the first ROWS_HEAD and last ROWS_TAIL lines of every
    output the run registered, numbered as `<n>: <row>`, and its
    metrics.json. One `(label, note)` pair says why there is nothing: no
    protocol id, no completed bound run, no registered output."""
    repo = layout_root(area)
    try:
        pid = protocol_block.head(protocol.read_text(encoding="utf-8")).id
    except protocol_block.BlockError as exc:
        raise AuditError(f"{protocol.name}: head unreadable — {exc}") from exc
    if pid is None:
        return [("ROWS", "no rows: the protocol id is still a placeholder")]
    choice = bound_answering_run(area, pid)
    if choice.run_dir is None:
        return [("ROWS", f"no rows: {choice.blocker or 'no completed bound run'}")]
    run_dir = choice.run_dir
    registered = read_outputs(run_dir)
    out: list[tuple[str, str]] = []
    rel_run = run_dir.resolve().relative_to(repo.resolve()).as_posix()
    if not registered:
        out.append((f"ROWS {rel_run}", "no rows: the run registered no output file"))
    for entry in registered or []:
        path = Path(entry.path)
        path = path if path.is_absolute() else repo / path
        if not path.is_file():
            raise AuditError(f"{run_dir.name} registered {entry.path}, which is gone")
        name = (
            path.resolve().relative_to(repo.resolve()).as_posix()
            if path.resolve().is_relative_to(repo.resolve())
            else str(entry.path)
        )
        out.append(rows_excerpt(path, name))
    metrics = run_dir / "metrics.json"
    if metrics.is_file():
        out.append(
            (f"FILE: {rel_run}/metrics.json", metrics.read_text(encoding="utf-8"))
        )
    return out


def rows_excerpt(path: Path, name: str) -> tuple[str, str]:
    """`(label, text)` of one output file: its first ROWS_HEAD and last
    ROWS_TAIL lines as `<line>: <row>`, a gap marked by its size, a row
    longer than ROW_WIDTH cut and marked — never silently dropped."""
    lines = path.read_text(encoding="utf-8").splitlines()
    n = len(lines)
    shown = (
        range(n)
        if n <= ROWS_HEAD + ROWS_TAIL
        else [*range(ROWS_HEAD), *range(n - ROWS_TAIL, n)]
    )
    body: list[str] = []
    last = -1
    for i in shown:
        if i != last + 1:
            body.append(f"… {i - last - 1} line(s) not shown …")
        row = lines[i]
        if len(row) > ROW_WIDTH:
            row = row[:ROW_WIDTH] + f" … [{len(lines[i]) - ROW_WIDTH} more chars]"
        body.append(f"{i + 1}: {row}")
        last = i
    label = f"ROWS {name} ({n} line(s); the first {ROWS_HEAD} and last {ROWS_TAIL} are shown)"
    return label, "\n".join(body)


class Reading(NamedTuple):
    """What the auditor gets: the protocol, the code read in full, the
    standard (its cited rules), and the modules it gets as an index only."""

    protocol: Path
    code: list[Path]  # scripts, analysis files, declared scopes, direct imports
    standard: Path
    indexed: list[Path]  # deeper imports: path and signatures, read on assignment


def declared_scope_files(protocol: Path) -> list[Path]:
    """The files the protocol's `[[promise]]` tables declare as scope
    (`file` or `file:function`, relative to the protocol's directory), each
    once, in order. No tables: none. A declared file that is not there
    raises — a promise resting on a missing file is not audited around."""
    block = promises.parse_block(protocol.read_text(encoding="utf-8"))
    if block is None:
        return []
    out: list[Path] = []
    for p in block.promises:
        for entry in p.scope:
            f = (protocol.parent / entry.split(":", 1)[0]).resolve()
            if not f.is_file():
                raise AuditError(
                    f"{protocol.name}: promise {p.id} declares scope `{entry}`, "
                    f"and {f} is not a file"
                )
            if f not in out:
                out.append(f)
    return out


def gather(area: Path, protocol: Path | None) -> Reading:
    """What the agent reads, by LAB-103 The audit reads by declared scope,
    not by import graph: the area's scripts and analysis files, the files
    the promises declare as scope, the repo-local modules those import
    directly — in full; every deeper module of the import graph as an index.
    Refuses what is missing."""
    if not area.is_dir():
        raise AuditError(no_such_area(area))
    try:
        chosen = the_protocol(area, protocol)
    except ProtocolChoiceError as exc:
        raise AuditError(str(exc)) from exc
    repo = layout_root(area)
    scripts = area_files(area)
    if not scripts:
        raise AuditError(f"{area}: no scripts/*.py or analysis/*.py — nothing to audit")
    code = [p.resolve() for p in scripts]
    code += [f for f in declared_scope_files(chosen) if f not in code]
    code += [f for f in repo_imports(code, repo) if f.resolve() not in code]
    whole = imported_repo_helpers(area, repo)
    indexed = [f for f in whole if f.resolve() not in {c.resolve() for c in code}]
    standard = rules.STANDARD
    if not standard.is_file():
        raise AuditError(
            f"{standard} is missing — labkit was installed without its standard "
            f"(scar table, severity legend); reinstall labkit"
        )
    return Reading(chosen, code, standard, indexed)


def module_index(files: list[Path], repo: Path) -> str:
    """One line per file — path and line count — then its top-level
    `def`/`class` signatures with the first docstring line: what the auditor
    gets instead of the text of a module further down the import graph."""
    out: list[str] = []
    for f in files:
        try:
            rel = f.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            rel = str(f)
        source = f.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(f))
        except SyntaxError as exc:
            raise AuditError(f"{rel}: cannot index it ({exc})") from exc
        out.append(f"{rel} ({len(source.splitlines())} lines)")
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sig = f"def {node.name}({ast.unparse(node.args)})"
            elif isinstance(node, ast.ClassDef):
                sig = f"class {node.name}"
            else:
                continue
            doc = (ast.get_docstring(node) or "").strip().splitlines()
            out.append(f"  {sig}" + (f"  — {doc[0]}" if doc else ""))
    return "\n".join(out)


def gather_clarity(area: Path, protocol: Path | None) -> tuple[Path, list[Path]]:
    """(protocol, [README, the measure script]) the clarity reader gets — its
    reading scope and nothing else: no lib modules, no standard."""
    chosen = gather(area, protocol).protocol
    readme = area / "README.md"
    script = area / "scripts" / "01_measure.py"
    missing = [p.name for p in (readme, script) if not p.is_file()]
    if missing:
        raise AuditError(
            f"{area}: no {', '.join(missing)} — the clarity reading starts there"
        )
    return chosen, [readme, script]


INDEX_LABEL = (
    "INDEX: repo-local modules further down the import graph — not inlined; "
    "name one in a finding's assignment to have it read (LAB-103 The audit "
    "reads by declared scope, not by import graph)"
)


def render(
    mode: str,
    area: Path,
    protocol: Path,
    code: list[Path],
    standard: Path | None,
    indexed: list[Path] | None = None,
) -> str:
    """The one prompt: instructions, MODE line, then every piece verbatim
    under a `===== <label> =====` line — the files, the cited rules of the
    standard (when `standard` is given), the index of the deeper modules
    (when `indexed` is given), in MODE analysis the answering run's rows.
    Clarity: README and script around the protocol, no standard, no index."""
    repo = layout_root(area)

    def rel(p: Path) -> str:
        try:
            return str(p.resolve().relative_to(repo.resolve()))
        except ValueError:
            return str(p)

    def file(p: Path) -> tuple[str, str]:
        return f"FILE: {rel(p)}", p.read_text(encoding="utf-8")

    if mode == CLARITY:
        pieces = [file(p) for p in (code[0], protocol, *code[1:])]
    else:
        pieces = [file(p) for p in (protocol, *code)]
        if standard is not None:
            label, text = standard_excerpt(mode)
            pieces.append((f"FILE: {label}", text))
        if indexed:
            pieces.append((INDEX_LABEL, module_index(indexed, repo)))
        if mode == ANALYSIS:
            pieces += run_rows(area, protocol)
    body = "".join(f"===== {label} =====\n{text}\n" for label, text in pieces)
    return (
        f"{instructions(mode)}\n\nMODE: {mode} · AREA: {rel(area)}\n\n"
        f"{INLINE_NOTE}\n\n{body}"
    )


def parse_clarity(text: str) -> dict:
    """{"findings": N, "wrong": M, "lines": [(rule, line)]} from the LAST
    `verdict: N findings (M would be answered wrong)` line. Raises AuditError
    when no verdict line is readable."""
    matches = list(CLARITY_VERDICT.finditer(text or ""))
    if not matches:
        raise AuditError("the report has no readable `verdict:` line — not a reading")
    m = matches[-1]
    body = (text or "")[: m.start()]
    lines = [
        (int(f.group(1)), line.strip())
        for line in body.splitlines()
        if (f := CLARITY_FINDING.match(line))
    ]
    return {
        "findings": int(m.group(1)),
        "wrong": int(m.group(2) or 0),
        "lines": lines,
    }


def parse(text: str) -> dict:
    """{"verdict": (blockers, warnings, notes), "findings": [(grade, line)]} from
    the LAST verdict line (an auditor may correct itself), findings from the
    text before it. Raises AuditError when no verdict line is readable."""
    matches = list(VERDICT.finditer(text or ""))
    if not matches:
        raise AuditError("the report has no readable `verdict:` line — not an audit")
    m = matches[-1]
    body = (text or "")[: m.start()]
    findings = [
        (f.group(1), line.strip())
        for line in body.splitlines()
        if (f := FINDING.match(line))
    ]
    return {
        "verdict": (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)),
        "findings": findings,
        "scope": scope_list((text or "")[m.end() :]),
    }


def scope_list(tail: str) -> list[str]:
    """The auditor's closing `scope:` list — the files it says determine the
    number, one per line (also accepted on the `scope:` line itself)."""
    lines = tail.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("scope:"):
            first = line.strip().removeprefix("scope:").strip()
            rest = [ln.strip().lstrip("-*• ").strip("`") for ln in lines[i + 1 :]]
            return [
                s
                for s in ([first.strip("`")] if first else []) + rest
                if s and not s.startswith("```")
            ]
    return []


def scope_mismatch(area: Path, listed: list[str]) -> list[str]:
    """Where the auditor's scope and the stamp disagree. The stamp is what a
    later check recomputes, so a file the auditor read as part of the number
    but the stamp misses can change unnoticed (review 2026-10-07: the list
    was asked for and then dropped)."""
    root = layout_root(area)
    _, files, _ = area_stamp(area)
    stamped = {
        f.resolve().relative_to(root.resolve()).as_posix()
        for f in files
        if f.resolve().is_relative_to(root.resolve())
    }
    named = set()
    for s in listed:
        q = Path(s)
        q = q if q.is_absolute() else root / q
        named.add(
            q.resolve().relative_to(root.resolve()).as_posix()
            if q.resolve().is_relative_to(root.resolve())
            else s
        )
    out = [
        f"the auditor read {n} as part of the number, the stamp does not cover it"
        for n in sorted(named - stamped)
    ]
    out += [
        f"the stamp covers {s}, the auditor did not list it as read"
        for s in sorted(stamped - named)
    ]
    return out


def early_for_tier(area: Path, protocol: Path, mode: str) -> list[str]:
    """One WARNING line when a preflight audit comes before the cost tier
    asks for it: at `cost = "seconds"` the first run is the cheaper probe
    and ONE audit in mode analysis after it covers the preflight rows
    (LAB-017 The number of audits follows the cost tier). uniagent area 01,
    2026-10-05: two preflight audits and an analysis audit at seconds, and
    the protocol itself says one after the first run would have done. A
    head this labkit cannot read says nothing here — protocol-check does."""
    if mode != "preflight":
        return []
    try:
        head = protocol_block.head(protocol.read_text(encoding="utf-8"))
    except protocol_block.BlockError:
        return []
    if head.cost != "seconds" or completed_runs(area):
        return []
    return [
        'WARNING · cost = "seconds" and no completed run · the first run is the '
        "cheaper probe; one audit in --mode analysis after it covers the preflight "
        "rows too · LAB-017 The number of audits follows the cost tier · run first, "
        "audit once"
    ]


def stamp_facts(area: Path, verdict: tuple[int, int, int]) -> str:
    """The facts of the protocol's audit field — the human adds the decisions.
    The sha is `scope_sha.area_stamp`, the same a later `scope-sha` recomputes."""
    sha, _, _ = area_stamp(area)
    b, w, n = verdict
    return (
        f"{time.strftime('%Y-%m-%d')} · scope sha {sha} · {b + w + n} findings "
        f"({b} blockers, {w} warnings, {n} notes — decide each: fixed / accepted / deferred / dismissed)"
    )


def main(argv: list[str]) -> int:
    """Command line of `labkit-audit`: audit one area in one mode."""
    ap = argparse.ArgumentParser(
        prog="labkit-audit", description=(__doc__ or "").splitlines()[0]
    )
    ap.add_argument("area", type=Path)
    ap.add_argument("--mode", choices=MODES, required=True)
    ap.add_argument(
        "--protocol", type=Path, help="the protocol, in an area holding several"
    )
    ap.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"models.toml alias (default {DEFAULT_MODEL})",
    )
    ap.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_S,
        help="seconds for the one call",
    )
    ap.add_argument("--out", type=Path, help="also write the report here")
    args = ap.parse_args(argv)
    if args.mode == CLARITY:
        return _clarity(args)
    try:
        protocol, code, standard, indexed = gather(args.area, args.protocol)
        for line in early_for_tier(args.area, protocol, args.mode):
            print(f"labkit-audit: {line}", file=sys.stderr)
        prompt = render(args.mode, args.area, protocol, code, standard, indexed)
        print(
            f"labkit-audit: {args.mode} · {protocol.name} · {len(code)} code file(s) "
            f"in full, {len(indexed)} indexed · "
            f"{args.model} · {len(prompt) // 1000} kB",
            file=sys.stderr,
        )
        report = llm.complete(args.model, prompt, timeout=args.timeout, max_tokens=4096)
        print(f"labkit-audit: tokens · {llm.last_usage().describe()}", file=sys.stderr)
        result = parse(report)
    except (AuditError, llm.BackendError, llm.PromptTruncated, KeyError) as exc:
        # KeyError: llm.resolve on an alias models.toml does not know
        print(f"labkit-audit: {str(exc).strip(chr(39))}", file=sys.stderr)
        return 2
    print(report)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    b, w, _ = result["verdict"]
    sha, _, _ = area_stamp(args.area)
    recorded = findings.write(
        args.area, args.mode, args.model, sha, result["verdict"], result["findings"]
    )
    print(f"\nstamp: {stamp_facts(args.area, result['verdict'])}", file=sys.stderr)
    print(
        f"findings: {recorded} — set status (fixed / accepted / deferred / dismissed) "
        f"and reason for each; preflight reads it",
        file=sys.stderr,
    )
    # the auditor lists what it read in full; the indexed modules are the
    # caller's to add before the list is held to the stamp (LAB-103 The audit reads by declared scope)
    listed_scope = result["scope"] + [str(p) for p in indexed]
    for gap in scope_mismatch(args.area, listed_scope):
        print(f"scope WARNING: {gap}", file=sys.stderr)
    listed = sum(grade in ("BLOCKER", "WARNING") for grade, _ in result["findings"])
    if listed and not (b or w):
        # The verdict line decides — an auditor may correct itself below a
        # finding ("Correction: no finding"). The disagreement is said, so a
        # reader of exit 0 sees the lines were there (2026-10-09).
        print(
            f"verdict NOTE: the verdict line counts 0 blockers and 0 warnings, the "
            f"report lists {listed} BLOCKER/WARNING line(s) above it — read them; the "
            f"verdict line decides",
            file=sys.stderr,
        )
    return 1 if b or w else 0


def _clarity(args: argparse.Namespace) -> int:
    """The clarity reading: README, protocol, measure script → findings to
    read. Exit 1 on any finding, 0 on none, 2 on no reading; no stamp, no
    scope — static evidence, not a gate."""
    try:
        protocol, files = gather_clarity(args.area, args.protocol)
        prompt = render(CLARITY, args.area, protocol, files, None)
        print(
            f"labkit-audit: clarity · {protocol.name} · README + {files[1].name} · "
            f"{args.model} · {len(prompt) // 1000} kB",
            file=sys.stderr,
        )
        report = llm.complete(args.model, prompt, timeout=args.timeout, max_tokens=4096)
        print(f"labkit-audit: tokens · {llm.last_usage().describe()}", file=sys.stderr)
        result = parse_clarity(report)
    except (AuditError, llm.BackendError, llm.PromptTruncated, KeyError) as exc:
        # KeyError: llm.resolve on an alias models.toml does not know
        print(f"labkit-audit: {str(exc).strip(chr(39))}", file=sys.stderr)
        return 2
    print(report)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    n, m = result["findings"], result["wrong"]
    print(
        f"\nclarity: {n} finding(s), {m} would be answered wrong — a reading, "
        f"not a gate; fix what a newcomer would get wrong before freezing",
        file=sys.stderr,
    )
    return 1 if n else 0


def cli() -> None:
    """Entry point for the installed `labkit-audit` command."""
    console.exit_with(main)


if __name__ == "__main__":
    cli()
