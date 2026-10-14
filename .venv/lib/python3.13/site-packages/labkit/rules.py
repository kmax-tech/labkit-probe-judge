"""The lab standard's rules: their ledger, their heads, and every reference to them.

`docs/standard.md` states each rule once, under a head line
`- **LAB-nnn · Title.** *(was §2.A12)* …` (also `### LAB-nnn · Title` and a bold
paragraph `**LAB-nnn · Title**`). `docs/rules.tsv` is the ledger: one row per
identifier ever given — `id alias title status`. Three families, never mixed:
labkit assigns every `LAB` number (the shipped lab standard); a lab's own rules
carry `LOCAL` numbers in the lab's own ledger; the coding style carries `CODE`.
All three are checked with the same code (`check --standard … --registry …`).

What holds, as in the standard's identifier rules 1–8:

- `check_registry`: ids and aliases unique, every active id stated by exactly one
  head with the ledger's title and alias, no head the ledger does not hold as active;
- `check_ledger`: the ledger only grows — no row removed, no alias rewritten, no
  id revived or reused, a new id above the highest ever given;
- `check_refs`: every reference to a rule exists, is not retired, and carries
  the rule's name (its first clause or at least two words of it); an old §-id
  appears only inside its alias mark.

A number the shipped ledger skips (2, 70, 73, 78, 80, 81, 99) belonged to a
rule the authoring lab keeps to itself; it lives on under the same number in
that lab's `LOCAL` ledger and is never given again here (identifier rule 2: a
new id is the highest ever given + 1).

    python -m labkit.rules check
    python -m labkit.rules check --standard PATH --registry PATH --prefix LOCAL --prefix LAB
    python -m labkit.rules ledger BEFORE AFTER
    python -m labkit.rules refs [--status active] PATH...
    python -m labkit.rules show `LAB-015`
"""

from __future__ import annotations

import argparse
import re
import sys

from labkit import console
from pathlib import Path
from typing import NamedTuple

STANDARD = Path(__file__).resolve().parent / "docs" / "standard.md"
REGISTRY = Path(__file__).resolve().parent / "docs" / "rules.tsv"
REGISTRY_HEADER = ("id", "alias", "title", "status")
PREFIXES = ("LAB", "LOCAL", "CODE")
STATUSES = ("active", "retired")  # plus moved:<where>

RULE_ID_RE = re.compile(r"^(LAB|LOCAL|CODE)-(\d{3})$")
RULE_HEAD_RE = re.compile(r"^(?:- |### |## )?\*{0,2}((?:LAB|LOCAL|CODE)-\d{3}) · (.*)$")
# the English standard writes "was", a German house standard "war"
ALIAS_MARK_RE = re.compile(r"\s*\*\((?:was|war) (§[^)]+)\)\*")
TRAIL_DATE_RE = re.compile(r"\s*\([^)]*\d{4}-\d{2}-\d{2}[^)]*\)\s*$")
HEADING_RE = re.compile(r"^#{1,3} ")
REGISTER_START, REGISTER_END = "<!-- register:start", "<!-- register:end"
CODE_RE = re.compile(r"\b((?:LAB|LOCAL|CODE)-\d{3})\b")
LEGACY_ID_RE = re.compile(r"§\d+\.[A-Z]?\d+[a-z]?|§\d+\.[A-Z]\b")
ALIAS_IN_TEXT_RE = re.compile(r"\((?:was|war) §[^)]+\)")
CLAUSE_CUT_RE = re.compile(r"[:,;—]| – | \(")
LEGACY_EXAMPLE_MARK = (
    "rule-ref: legacy-example"  # a line that shows an old §-id as an example
)


class RuleRow(NamedTuple):
    """One ledger row: an identifier once given to a rule, never taken back."""

    id: str  # LAB-nnn / LOCAL-nnn / CODE-nnn
    alias: str  # the old §-id it replaced, "" when there was none
    title: str  # the rule's name
    status: str  # active | retired | moved:<where it lives now>


class RuleHead(NamedTuple):
    """A rule as its head line in a document states it."""

    id: str
    title: str
    alias: str  # from the "*(was §…)*" mark, "" when absent
    line: int  # 1-based


def load_registry(path: Path) -> list[RuleRow]:
    """The ledger rows of PATH; a malformed line raises — the ledger is never guessed at."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or tuple(lines[0].split("\t")) != REGISTRY_HEADER:
        raise ValueError(f"{path}: header must be {chr(9).join(REGISTRY_HEADER)!r}")
    rows = []
    for n, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        cells = line.split("\t")
        if len(cells) != 4:
            raise ValueError(
                f"{path}:{n}: expected 4 tab-separated cells, got {len(cells)}"
            )
        rows.append(RuleRow(*cells))
    return rows


def _rule_title(raw: str) -> str:
    """The name in a head line: no bold markers, alias mark, adoption date or end punctuation."""
    raw = ALIAS_MARK_RE.sub("", raw)
    title = raw.split("**", 1)[0] if "**" in raw else raw
    title = TRAIL_DATE_RE.sub("", " ".join(title.split())).rstrip(".:,").strip()
    return TRAIL_DATE_RE.sub("", title).strip()


def rule_heads(doc: str) -> list[RuleHead]:
    """Every rule head of DOC in document order; a bold title may wrap onto the next line.

    Lines inside a generated register block and inside fenced code are not heads.
    """
    lines = doc.splitlines()
    heads, register, fence, i = [], False, False, 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            fence = not fence
        elif line.startswith(REGISTER_START):
            register = True
        elif line.startswith(REGISTER_END):
            register = False
        elif not (register or fence) and (m := RULE_HEAD_RE.match(line)):
            raw, n = m.group(2), i + 1
            if (
                line.lstrip().startswith(("- **", "**"))
                and "**" not in raw
                and i + 1 < len(lines)
            ):
                raw += " " + lines[i + 1].strip()
                i += 1
            alias = ALIAS_MARK_RE.search(raw)
            heads.append(
                RuleHead(
                    m.group(1), _rule_title(raw), alias.group(1) if alias else "", n
                )
            )
        i += 1
    return heads


def _valid_status(status: str) -> bool:
    return status in STATUSES or (
        status.startswith("moved:") and len(status) > len("moved:")
    )


def _ledger_problems(rows: list[RuleRow]) -> list[str]:
    """What is wrong with a ledger on its own: duplicate ids or aliases, malformed rows."""
    problems = []
    ids = [r.id for r in rows]
    problems += [
        f"{d}: id given twice in the ledger"
        for d in sorted({i for i in ids if ids.count(i) > 1})
    ]
    aliases = [r.alias for r in rows if r.alias]
    problems += [
        f"{d}: alias given to two ids"
        for d in sorted({a for a in aliases if aliases.count(a) > 1})
    ]
    for r in rows:
        if not RULE_ID_RE.match(r.id):
            problems.append(
                f"{r.id}: not of the form {'/'.join(PREFIXES)}-nnn (three digits)"
            )
        if not _valid_status(r.status):
            problems.append(
                f"{r.id}: status {r.status!r} is not active|retired|moved:<where>"
            )
        if r.status == "active" and not r.title:
            problems.append(f"{r.id}: active without a title")
    return problems


def _head_problems(h: RuleHead, row: RuleRow | None) -> list[str]:
    """What is wrong with one head against its ledger row."""
    if row is None:
        return [f"line {h.line}: {h.id} is not in the ledger"]
    if row.status != "active":
        return [f"line {h.line}: {h.id} is {row.status} in the ledger, yet stated here"]
    problems = []
    if h.title != row.title:
        problems.append(
            f"line {h.line}: {h.id} head says {h.title!r}, ledger says {row.title!r}"
        )
    if h.alias != row.alias:
        problems.append(
            f"line {h.line}: {h.id} alias mark {h.alias or '(none)'} ≠ ledger {row.alias or '(none)'}"
        )
    return problems


def check_registry(
    rows: list[RuleRow], heads: list[RuleHead], prefixes: tuple[str, ...]
) -> list[str]:
    """Invariants between a ledger and one document's rule heads; [] when they hold.

    Only ids of PREFIXES are held to the document: a ledger may list ids that
    another document states (the house ids in labkit's ledger, say).
    """
    problems = _ledger_problems(rows)
    by_id = {r.id: r for r in rows}
    held = tuple(p + "-" for p in prefixes)
    seen: dict[str, int] = {}
    for h in heads:
        if h.id.startswith(held):
            seen[h.id] = seen.get(h.id, 0) + 1
            problems += _head_problems(h, by_id.get(h.id))
    problems += [f"{i}: {n} rule heads carry this id" for i, n in seen.items() if n > 1]
    problems += [
        f"{r.id}: active in the ledger but no rule head states it"
        for r in rows
        if r.id.startswith(held) and r.status == "active" and r.id not in seen
    ]
    return problems


def check_ledger(before: list[RuleRow], after: list[RuleRow]) -> list[str]:
    """The ledger only grows: no row removed, no alias rewritten, no id revived or reused.

    BEFORE is the committed ledger, AFTER the working one. A new id must lie
    above the highest id ever given in its prefix.
    """
    problems = []
    now = {r.id: r for r in after}
    for r in before:
        if r.id not in now:
            problems.append(
                f"{r.id}: removed from the ledger — retire it, never delete"
            )
            continue
        if now[r.id].alias != r.alias:
            problems.append(f"{r.id}: alias changed {r.alias!r} → {now[r.id].alias!r}")
        if r.status in ("retired",) and now[r.id].status != r.status:
            problems.append(
                f"{r.id}: was retired, now {now[r.id].status} — an id is never reused"
            )
    old = {r.id for r in before}
    for prefix in PREFIXES:
        top = max(
            (int(r.id.split("-")[1]) for r in before if r.id.startswith(prefix + "-")),
            default=0,
        )
        for r in after:
            if (
                r.id.startswith(prefix + "-")
                and r.id not in old
                and int(r.id.split("-")[1]) <= top
            ):
                problems.append(
                    f"{r.id}: new id at or below the highest ever given ({prefix}-{top:03d}) — "
                    f"the next one is {prefix}-{top + 1:03d}"
                )
    return problems


def _words(text: str) -> list[str]:
    """TEXT as comparable words: no markup, no edge punctuation, case-folded."""
    text = re.sub(r"[`*_„“”\"']", "", text)
    edge = ".,:;!?()[]—–-·"
    return [w.strip(edge).casefold() for w in text.split() if w.strip(edge)]


def first_clause(title: str) -> str:
    """TITLE up to its first clause break (colon, comma, dash, parenthesis) — a name of its own."""
    return CLAUSE_CUT_RE.split(title, maxsplit=1)[0].strip()


def names_rule(after: str, title: str) -> bool:
    """True when AFTER starts with TITLE's first clause, or with at least two of its words."""
    want, have = _words(title), _words(after)
    n = 0
    while n < len(want) and n < len(have) and have[n] == want[n]:
        n += 1
    return n >= min(2, len(want)) or n >= len(_words(first_clause(title)))


def _line_refs(
    where: str, line: str, rows: list[RuleRow], allowed: tuple[str, ...]
) -> list[str]:
    """Reference problems on one line (see check_refs)."""
    by_id = {r.id: r for r in rows}
    by_alias = {r.alias: r for r in rows if r.alias}
    held = {
        r.id.split("-")[0] for r in rows
    }  # a prefix this ledger does not keep is checked elsewhere
    problems = []
    for m in LEGACY_ID_RE.finditer(
        "" if LEGACY_EXAMPLE_MARK in line else ALIAS_IN_TEXT_RE.sub("", line)
    ):
        row = by_alias.get(m.group())
        problems.append(
            f"{where}: old id {m.group()}"
            + (f" → {row.id} {row.title}" if row else " (no such rule)")
        )
    # an id inside inline code or a bare string literal ("LAB-015") is an argument, not a citation
    scan = re.sub(
        r"`[^`]*`|([\"'])(?:LAB|LOCAL|CODE)-\d{3}\1",
        lambda c: " " * len(c.group()),
        line,
    )
    for m in CODE_RE.finditer(scan):
        row = by_id.get(m.group(1))
        if row is not None and row.status.startswith("moved:"):
            continue  # the ledger it moved to checks it
        if row is None and m.group(1).split("-")[0] in held:
            problems.append(f"{where}: {m.group(1)} is not in the ledger")
        elif row is not None and row.status not in allowed:
            problems.append(
                f"{where}: {row.id} is {row.status}, not {'/'.join(allowed)}"
            )
        elif (
            row is not None and row.title and not names_rule(line[m.end() :], row.title)
        ):
            problems.append(
                f"{where}: {row.id} without its name — write '{row.id} {' '.join(row.title.split()[:4])}…'"
            )
    return problems


def check_refs(
    where: str, text: str, rows: list[RuleRow], allowed: tuple[str, ...] = ("active",)
) -> list[str]:
    """Reference problems in TEXT: an unknown id, an id whose status is not ALLOWED,
    an id without its name, an old §-id outside its alias mark.

    Head lines, fenced code and a generated register are skipped (check_registry
    holds the heads), so a standard is checked like any other file. Ids of a
    prefix the ledger does not keep (CODE in labkit's), and ids the ledger marks
    `moved:<where>`, are left to the ledger that holds them now.
    """
    problems, register, fence = [], False, False
    for n, line in enumerate(text.splitlines(), start=1):
        if line.startswith("```"):
            fence = not fence
        elif line.startswith(REGISTER_START):
            register = True
        elif line.startswith(REGISTER_END):
            register = False
        elif not (register or fence or RULE_HEAD_RE.match(line)):
            problems += _line_refs(f"{where}:{n}", line, rows, allowed)
    return problems


def rule_text(
    rule_id: str, doc: str | None = None, rows: list[RuleRow] | None = None
) -> str:
    """The block of DOC (default: the standard) that states RULE_ID, from its head to the next.

    Raises for an unknown id and says the status of one that is not active:
    an empty answer would look like a rule without text.
    """
    rows = load_registry(REGISTRY) if rows is None else rows
    row = {r.id: r for r in rows}.get(rule_id)
    if row is None:
        raise KeyError(f"{rule_id}: no such rule in the ledger")
    if row.status != "active":
        raise LookupError(f"{rule_id}: {row.status}")
    lines = (STANDARD.read_text(encoding="utf-8") if doc is None else doc).splitlines()
    starts = {h.id: h.line for h in rule_heads("\n".join(lines))}
    if rule_id not in starts:
        raise LookupError(
            f"{rule_id}: active in the ledger but stated nowhere in the standard"
        )
    a = starts[rule_id] - 1
    z = a + 1
    while (
        z < len(lines)
        and not RULE_HEAD_RE.match(lines[z])
        and not HEADING_RE.match(lines[z])
    ):
        z += 1
    return "\n".join(lines[a:z]).rstrip() + "\n"


def paragraph(rule_id: str, lead: str, doc: str | None = None) -> str:
    """The paragraph of RULE_ID's block that begins with LEAD, unindented and unwrapped.

    For text another tool hands on verbatim — the severity legend of
    LAB-015 Preflight audit before freezing goes into every code-check bundle —
    so it is quoted from the standard, not copied by hand. Raises when LEAD
    is not found: a renamed paragraph must not leave a bundle without it.
    """
    block = rule_text(rule_id, doc)
    for para in re.split(r"\n\s*\n", block):
        text = " ".join(para.split())
        if text.startswith(lead):
            return text
    raise LookupError(f"{rule_id}: no paragraph begins with {lead!r}")


def main(argv: list[str]) -> int:
    """`python -m labkit.rules` — see the module docstring; exit 1 on any problem."""
    ap = argparse.ArgumentParser(
        prog="python -m labkit.rules", description=(__doc__ or "").split("\n\n")[0]
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="a standard's rule heads against its ledger")
    c.add_argument("--standard", type=Path, default=STANDARD)
    c.add_argument("--registry", type=Path, default=REGISTRY)
    c.add_argument(
        "--prefix",
        action="append",
        choices=PREFIXES,
        help="ids held to the document (default LAB)",
    )
    led = sub.add_parser(
        "ledger",
        help="the ledger only grows: BEFORE (committed) against AFTER (working)",
    )
    led.add_argument("before", type=Path)
    led.add_argument("after", type=Path)
    r = sub.add_parser(
        "refs", help="every rule reference in PATHS resolves and carries its name"
    )
    r.add_argument("--registry", type=Path, default=REGISTRY)
    r.add_argument(
        "--status",
        action="append",
        help="statuses a reference may point to (default active)",
    )
    r.add_argument("paths", nargs="+", type=Path)
    s = sub.add_parser("show", help="print one rule of the standard")
    s.add_argument("id")
    a = ap.parse_args(argv)

    if a.cmd == "show":
        try:
            print(rule_text(a.id), end="")
        except (KeyError, LookupError) as exc:
            print(exc.args[0], file=sys.stderr)
            return 1
        return 0
    if a.cmd == "check":
        problems = check_registry(
            load_registry(a.registry),
            rule_heads(a.standard.read_text(encoding="utf-8")),
            tuple(a.prefix or ["LAB"]),
        )
        label = f"rules: {a.standard.name} against {a.registry.name}"
    elif a.cmd == "ledger":
        problems = check_ledger(load_registry(a.before), load_registry(a.after))
        label = "rules: ledger"
    else:
        rows = load_registry(a.registry)
        files = [
            f
            for p in a.paths
            for f in ([p] if p.is_file() else sorted(p.rglob("*")))
            if f.is_file()
        ]
        problems = []
        for f in files:
            try:
                text = f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue  # binary file: holds no reference
            problems += check_refs(str(f), text, rows, tuple(a.status or ["active"]))
        label = f"rules: references in {len(files)} file(s)"
    for p in problems:
        print(p)
    print(f"{label}: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    console.exit_with(main)
