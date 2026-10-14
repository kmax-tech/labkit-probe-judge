"""protocol-fill — fill one stamped placeholder field, matched by its label.

Filling protocol fields by full-text replacement fails in rounds: the quoted
placeholder block never matches exactly (2026-09-09, twice in one day on the
same protocol — three attempts each until a regex sat). The template stamps
every field as `- **Label †:** <placeholder>`, so the LABEL is the stable
handle; this tool matches it, replaces the `<...>` value (multi-line
placeholders included) and leaves everything else byte-identical.

    protocol-fill PROTOCOL-x.md --list
    protocol-fill PROTOCOL-x.md "Meaning of the gold label" "positive = ..."
    protocol-fill PROTOCOL-x.md --line 27 Question "does Y move X?"
    protocol-fill PROTOCOL-x.md --prompts      the Prompt block from the scripts' PROMPT constants
    protocol-fill PROTOCOL-x.md --from-run [RUN_ID]   the Answer, Result, Answering run and Runs lines
                                               from the run's metrics.json (newest completed run by default)

A field that is already filled is refused without --force — overwriting an
answer silently is how two truths happen.

`--from-run` is the write-back LAB-041 Generate numbers, don't retype them
asks for: twelve cold agents (cloud probes 2026-10-12) typed the number into
three protocol lines by hand, and one `--check` failed on the retyping. The
lines carry every metric key and value as the run recorded them, and the
run_id — exactly what `--check` (`recheck.cited`) holds the protocol to. Labels are matched with the †
marker and case ignored; an ambiguous label (same label in Summary and a
section) is refused with the line numbers, disambiguate with --line.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from labkit import console, recheck, runs
from labkit.code_check import prompt_constants
from labkit.protocol_check import (
    RUNS_PLACEHOLDER,
    answering_run_field,
    answering_run_open,
    field_name,
    fields,
    placeholder_fields,
)

# Bullet and indentation of a label line, kept when the line is rewritten.
_LEAD = re.compile(r"^\s*(?:[-*]\s+|\d+[.)]\s+)?")


def fill(
    text: str, field: str, value: str, line_no: int | None = None, force: bool = False
) -> str:
    """Return the protocol text with `field`'s placeholder replaced by `value`.

    Fields are read by `protocol_check.fields` — the one parser of labels
    and placeholders; a second one here mis-read a wrapped label as
    `extremes)` (usability probe 2026-10-07). The label line and its
    continuation lines become one line; everything else stays byte-identical.

    Raises ValueError with a human-readable reason (unknown label, ambiguous
    label, already filled without force) — the CLI prints it verbatim.
    """
    want = field_name(field)
    hits = [
        f
        for f in fields(text)
        if f.name == want and (line_no is None or f.line == line_no)
    ]
    if not hits:
        labels = sorted({lbl for _, lbl in placeholder_fields(text)})
        raise ValueError(
            f"no field labelled {field!r}"
            + (f" at line {line_no}" if line_no else "")
            + (
                ". Open placeholder fields: " + " · ".join(labels)
                if labels
                else ". No placeholder fields left."
            )
        )
    if len(hits) > 1:
        where = ", ".join(str(f.line) for f in hits)
        raise ValueError(
            f"label {field!r} matches lines {where} — disambiguate with --line <n>."
        )
    (f,) = hits
    if not f.placeholder and not force:
        raise ValueError(
            f"line {f.line} ({f.label!r}) is already filled: "
            f"{f.value[:80]!r}. Overwrite with --force."
        )
    lines = text.splitlines()
    lead = _LEAD.match(lines[f.line - 1])
    assert lead is not None, "the pattern matches the empty prefix"
    lines[f.line - 1 : f.last] = [f"{lead.group(0)}**{f.label}:** {value}"]
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


_FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})")
HEAD_TYPE = re.compile(r'^(type\s*=\s*)"<[^"\n]*>"\s*$', re.M)
HEAD_TYPE_LABEL = "type"


def head_type_open(text: str) -> int | None:
    """Line number of the TOML head's `type = "<…>"` placeholder, or None once set.

    The stamp leaves `type` as a placeholder in the head; `--list` named only
    the prose fields, so an agent filled those, hit the hook's "MISSING (must):
    [protocol] type" and edited the head by hand (cloud probe, Haiku 5.5,
    2026-10-13)."""
    m = HEAD_TYPE.search(text)
    return text.count("\n", 0, m.start()) + 1 if m else None


def fill_head_type(text: str, value: str) -> str:
    """Set the head's `type` from its placeholder; one of `protocol_block.TYPES`."""
    from labkit import protocol_block  # lazy: labkit modules import each other

    if value not in protocol_block.TYPES:
        raise ValueError(
            f"type must be one of {' | '.join(protocol_block.TYPES)}, not {value!r}"
        )
    if head_type_open(text) is None:
        raise ValueError(
            "the head's type is already set (edit the TOML head to change it)"
        )
    return HEAD_TYPE.sub(lambda m: f'{m.group(1)}"{value}"', text, count=1)


RUNS_HEADING = re.compile(r"^## Runs\b")

#: the labels `--from-run` writes from the run's metrics.json — `--list` sets
#: them apart, since filling them before the run makes --from-run refuse
WRITTEN_BY_RUN = ("Answer to the question", "Result")


def answer_line(metrics: dict, run_id: str) -> str:
    """`key = value, … (run <id>)` — every reported key and value as the run
    recorded them, so `recheck.cited` finds each number and the run_id."""
    kept = {k: v for k, v in metrics.items() if k not in recheck.LABKIT_KEYS}
    body = ", ".join(f"{k} = {v}" for k, v in kept.items())
    return f"{body} (run {run_id})"


def runs_line(text: str, run_id: str, sentence: str) -> tuple[str, bool]:
    """The Runs section names `run_id`: the stamped `<run_id>` placeholder line
    becomes the entry, else one is appended to the section; a section that
    names the run already is left alone. (text, changed)."""
    lines = text.split("\n")
    heading = next((i for i, ln in enumerate(lines) if RUNS_HEADING.match(ln)), None)
    if heading is None:
        raise ValueError("no `## Runs` section to name the run in")
    end = heading + 1
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    section = range(heading + 1, end)
    if any(run_id in lines[i] for i in section):
        return text, False
    entry = f"- {run_id} — {sentence}"
    for i in section:
        if RUNS_PLACEHOLDER.match(lines[i]):
            lines[i] = entry
            return "\n".join(lines), True
    k = end
    while k > heading + 1 and not lines[k - 1].strip():
        k -= 1
    lines.insert(k, entry)
    return "\n".join(lines), True


def from_run(
    text: str, area: Path, run_id: str | None = None, force: bool = False
) -> tuple[str, list[str], str]:
    """Write the run's number back: the Answer line, the Summary's Result line
    and the Runs entry from `runs/<run_id>/metrics.json` (newest completed
    run when RUN_ID is None). Returns (text, what was filled, run_id). A
    filled Answer or Result is refused without `force` (fill's rule)."""
    run = recheck.run_dir(area, run_id)
    metrics = runs.read_metrics(run / "metrics.json")
    answer = answer_line(metrics, run.name)
    filled: list[str] = []
    for label in WRITTEN_BY_RUN:
        try:
            text = fill(text, label, answer, force=force)
            filled.append(label)
        except ValueError as exc:
            if "no field labelled" in str(exc):
                continue  # a cut without this line (the Summary of a report-grade full form carries it)
            raise
    current = answering_run_field(text)
    if current is not None and run.name not in current:
        if not (answering_run_open(current) or force):
            raise ValueError(
                f'"Answering run" names {current.split()[0]}, not {run.name} — '
                f"--force to replace it"
            )
        text = fill(text, "Answering run", run.name, force=True)
        filled.append("Answering run")
    text, changed = runs_line(
        text, run.name, "the kept run; its metrics.json is the number"
    )
    if changed:
        filled.append("Runs")
    return text, filled, run.name


def fill_prompts(text: str, constants: dict[str, str]) -> str:
    """Return the protocol text with the Prompt field's code block written
    from the scripts' `PROMPT` / `PROMPT_<VARIANT>` constants, `PROMPT`
    first, each under a `── NAME ──` line when there are several.

    The block is what `code-check` holds the script to (prompt drift); three
    of three cold agents wrote it by a Python snippet because the label fill
    could not reach a code block (re-measure 2026-10-07). Replaces the block
    that follows the label (within three lines), or inserts one."""
    if not constants:
        raise ValueError(
            "no PROMPT constant readable in the area's scripts (an f-string "
            "renders at run time and cannot be copied) — write the block by hand"
        )
    hits = [f for f in fields(text) if f.name == "prompt"]
    if len(hits) != 1:
        where = ", ".join(str(f.line) for f in hits) or "none"
        raise ValueError(f"expected one Prompt field, found {where}")
    (f,) = hits
    lines = text.splitlines()
    names = sorted(constants, key=lambda n: (n != "PROMPT", n))
    body: list[str] = []
    for name in names:
        if len(names) > 1:
            body.append(f"── {name} ──")
        body += constants[name].splitlines()
    start = end = f.last  # 0-based index just after the field's value
    for j in range(f.last, min(f.last + 3, len(lines))):
        m = _FENCE.match(lines[j])
        if m:
            k = next(
                (
                    k
                    for k in range(j + 1, len(lines))
                    if lines[k].strip().startswith(m.group(2))
                ),
                None,
            )
            if k is None:
                raise ValueError(f"line {j + 1}: the Prompt block never closes")
            start, end = j, k + 1
            break
    block = ["  ```text", *[f"  {ln}" if ln else "" for ln in body], "  ```"]
    if start == end:  # no block yet: a blank line, then the block
        block = ["", *block]
    lines[start:end] = block
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def _write_back(args: argparse.Namespace, text: str) -> int:
    """`--from-run`: the number from the run's metrics.json into the protocol."""
    try:
        new, filled, run_id = from_run(
            text,
            args.protocol.resolve().parent,
            None if args.from_run == "newest" else args.from_run,
            force=args.force,
        )
    except ValueError as exc:
        print(f"protocol-fill: {exc}")
        return 1
    args.protocol.write_text(new, encoding="utf-8")
    print(
        f"filled from run {run_id}: {', '.join(filled) or 'nothing (all written already)'}"
    )
    return 0


def _list_open(text: str) -> int:
    """`--list`: every open field, the TOML head's `type` first; the fields
    `--from-run` writes last, under their own line. Listed among the rest
    they read as owed before the run: a cold agent filled them with "pending
    run", and --from-run then refused to overwrite them (cloud, 2026-10-14)."""
    holes = placeholder_fields(text)
    head_line = head_type_open(text)
    if head_line is not None:
        holes = [
            (head_line, f"{HEAD_TYPE_LABEL}  (TOML head: exploratory | confirmatory)")
        ] + holes
    if not holes:
        print("no placeholder fields left")
    now = [(n, label) for n, label in holes if label not in WRITTEN_BY_RUN]
    later = [(n, label) for n, label in holes if label in WRITTEN_BY_RUN]
    for n, label in now:
        print(f"{n:4d}  {label}")
    if later:
        print(
            "after the run — `protocol-fill <PROTOCOL> --from-run` writes these; leave them:"
        )
        for n, label in later:
            print(f"{n:4d}  {label}")
    return 0


def assignments_of(field: str | None, value: list[str]) -> list[tuple[str, str]]:
    """The (label, value) pairs a command line asks for: `FIELD VALUE...` is
    one pair, `LABEL=VALUE [LABEL=VALUE ...]` (every word carries `=`; a
    value with spaces is one quoted word) one pair per word. Empty when the
    line names no value. Why the one-call form: seven cold agents filled six
    fields in six calls and named it their largest sink (cloud probes,
    2026-10-13)."""
    if not field:
        return []
    words = [field, *value]
    if all("=" in w for w in words):
        return [(lb, v) for lb, v in (w.split("=", 1) for w in words)]
    if not value:
        return []
    return [(field, " ".join(value))]


def fill_many(
    text: str,
    assignments: list[tuple[str, str]],
    line_no: int | None = None,
    force: bool = False,
) -> str:
    """`fill` (or `fill_head_type` for the head's type) applied in order; the
    first ValueError leaves the caller's file untouched — all or nothing."""
    for label, value in assignments:
        if not label.strip() or not value.strip():
            raise ValueError(f"empty label or value in {label}={value!r}")
        text = (
            fill_head_type(text, value)
            if label.strip().lower() == HEAD_TYPE_LABEL
            else fill(text, label, value, line_no=line_no, force=force)
        )
    return text


def main(argv: list[str]) -> int:
    """Command line of `protocol-fill`: fill placeholder fields by label (one, or several as LABEL=VALUE), or the Prompt block from the script."""

    ap = argparse.ArgumentParser(
        prog="protocol-fill",
        description="Fill stamped placeholder fields in a PROTOCOL-*.md, "
        "matched by label (never by quoting the placeholder text): "
        "`FIELD VALUE...` fills one, `LABEL=VALUE [LABEL=VALUE ...]` "
        "fills several in one call (all or nothing). --list shows what "
        "is still open.",
    )
    ap.add_argument("protocol", type=Path)
    ap.add_argument("field", nargs="?", help="field label († optional), or LABEL=VALUE")
    ap.add_argument(
        "value", nargs="*", help="the field's new value, or further LABEL=VALUE"
    )
    ap.add_argument(
        "--list", action="store_true", help="list open placeholder fields and exit"
    )
    ap.add_argument(
        "--prompts",
        action="store_true",
        help="write the Prompt block from the area scripts' PROMPT constants",
    )
    ap.add_argument(
        "--from-run",
        nargs="?",
        const="newest",
        default=None,
        metavar="RUN_ID",
        help="write the Answer, Result, Answering run and Runs lines from the run's metrics.json "
        "(the area's newest completed run without RUN_ID)",
    )
    ap.add_argument(
        "--line",
        type=int,
        default=None,
        help="line number, when the label is ambiguous",
    )
    ap.add_argument(
        "--force", action="store_true", help="overwrite a field that is already filled"
    )
    args = ap.parse_args(argv)
    if not args.protocol.is_file():
        print(f"protocol-fill: no such file: {args.protocol}")
        return 2
    text = args.protocol.read_text(encoding="utf-8")
    if args.list:
        return _list_open(text)
    if args.prompts:
        try:
            new = fill_prompts(text, prompt_constants(args.protocol.resolve().parent))
        except ValueError as exc:
            print(f"protocol-fill: {exc}")
            return 1
        args.protocol.write_text(new, encoding="utf-8")
        print("filled: Prompt (from the scripts' PROMPT constants)")
        return 0
    if args.from_run is not None:
        return _write_back(args, text)
    assignments = assignments_of(args.field, args.value)
    if not assignments:
        ap.error("need FIELD and VALUE, LABEL=VALUE..., --list or --from-run")
    if args.line is not None and len(assignments) > 1:
        ap.error("--line goes with one FIELD, not with LABEL=VALUE")
    try:
        new = fill_many(text, assignments, line_no=args.line, force=args.force)
    except ValueError as exc:  # all or nothing: the file is untouched
        print(f"protocol-fill: {exc}")
        return 1
    args.protocol.write_text(new, encoding="utf-8")
    print("filled: " + ", ".join(label for label, _ in assignments))
    return 0


def cli() -> None:
    """Entry point for the installed `protocol-fill` command."""
    console.exit_with(main)


if __name__ == "__main__":
    cli()
