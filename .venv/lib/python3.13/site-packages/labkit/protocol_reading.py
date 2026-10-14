"""protocol_reading — how well a person can read a protocol, measured four ways.

The checks hold a protocol to its registration; nothing measured whether a
person can read it. A reader's assessment of uniagent's protocols
(2026-10-07): strong in content, but about 65 lines of form before the
first sentence for a person, ids and keys in the summary, results as
`key value · key value · …` chains. Four measurements, all cheap:

- **form** (mechanical, static evidence — never proof of readability):
  prose lines before the first field, `·` chains of more than two items,
  the longest field, intent ids / metric keys / run_ids inside the Summary,
  whether the answer carries a table;
- **reader** (an agent that sees only the protocol): `reader_prompt` asks
  what was found, its number, whether the criterion and the admissibility
  conditions held, how far it holds, what comes next and what it could not
  place; `score_reader_answer` holds the checkable answers to the run;
- **glance** (an agent that sees only the first lines of the file):
  `glance`, `glance_prompt`, `score_glance_answer` — what a reader who
  stops early takes away, and mechanically which Summary fields those
  lines hold;
- **terms**: the reader's unclear terms against two layers — the Summary
  must be plain itself, elsewhere a term may be explained in Terms or a
  glossary it links (`terms_coverage`, occurrence = static evidence;
  `terms_judge_prompt` asks a reader whether `entry_for`'s entry explains it).

Reading time comes from the reader's transcript (agent_transcript); what
every probe shares (the newcomer, the answer's shape) is in `cold_reader`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from labkit.cold_reader import (
    NEWCOMER,
    answer_contract,
    asked_keys,
    load_answer,
    number_matches,
    read_number,
    read_unclear,
    read_verdict,
    verdict_matches,
)
from labkit.protocol_check import fields

#: what a reader of the Summary should not have to decode
SUMMARY_CODES = re.compile(
    r"\[[CAB]\d+\]|\b[cab]\d+_\w+|\b\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}_[0-9a-f]+\b"
)
CHAIN = re.compile(r"·")
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")


@dataclass(frozen=True)
class Form:
    """Mechanical readability facts of one protocol (static evidence)."""

    lines: int
    prose_before_first_field: (
        int  # non-blank lines above the first field, the head block excluded
    )
    chains: int  # field values with more than two `·` items
    longest_field: int  # characters of the longest field value
    summary_codes: int  # ids, metric keys, run_ids inside the Summary section
    answer_has_table: bool


def _section(text: str, name: str) -> str:
    m = re.search(rf"^## {name}\b.*?(?=^## |\Z)", text, re.M | re.S)
    return m.group(0) if m else ""


def form(text: str) -> Form:
    """The mechanical readability facts of one protocol (static evidence)."""
    lines = text.splitlines()
    found = fields(text)
    first = found[0].line if found else len(lines) + 1
    before, fence = 0, False
    for ln in lines[: first - 1]:
        if ln.strip().startswith("```"):
            fence = not fence
            continue
        if (
            not fence
            and ln.strip()
            and not ln.startswith("#")
            and not ln.strip().startswith("<!--")
        ):
            before += 1
    answer = next((f for f in found if f.name == "answer to the question"), None)
    answer_rows = lines[answer.line : answer.last + 6] if answer else []
    return Form(
        lines=len(lines),
        prose_before_first_field=before,
        chains=sum(1 for f in found if len(CHAIN.findall(f.value)) >= 2),
        longest_field=max((len(f.value) for f in found), default=0),
        summary_codes=len(SUMMARY_CODES.findall(_section(text, "Summary"))),
        answer_has_table=any(TABLE_ROW.match(r) for r in answer_rows),
    )


READER_QUESTIONS = (
    (
        "first_lines",
        "After the first 10 lines only: what had you understood? One sentence, or null.",
    ),
    (
        "question",
        "What did this experiment want to find out? One sentence, your words.",
    ),
    ("result", "What came out? One or two sentences, your words."),
    (
        "number",
        "The one number the result rests on, as written (digits only), or null.",
    ),
    (
        "criterion_held",
        "Did the success criterion registered before the run hold — true, false, or null if the protocol does not say?",
    ),
    (
        "admissible",
        "Did every admissibility condition (the checks that must pass before any verdict) hold — true, false, or null?",
    ),
    ("holds", "How far does the result hold — what limits it? One sentence."),
    ("next", "What happens next, according to the protocol? One sentence, or null."),
    (
        "unclear",
        "Every term, abbreviation, code or file name a newcomer would have to look up — a list, [] if none.",
    ),
    ("effort", "How hard was this protocol to read, 1 (easy) to 5 (very hard)?"),
)


def reader_prompt(protocol_text: str, answer_path: str) -> str:
    """The prompt for a cold reader: the protocol, the questions, the file."""
    return (
        f"{NEWCOMER} Below is one experiment protocol — read it to learn what "
        "was found, and nothing else: no files, no tools except writing your "
        "answer. Answer only from the protocol.\n\n"
        "Answer with one JSON object with exactly these keys:\n"
        f"{asked_keys(READER_QUESTIONS)}\n\n"
        f"{answer_contract(answer_path)}\n\n"
        "----- PROTOCOL -----\n"
        f"{protocol_text}\n"
        "----- END -----\n"
    )


@dataclass(frozen=True)
class Truth:
    """What the run says, to hold a reader's answers to; None: it does not say."""

    number: float | None
    criterion_held: bool | None
    admissible: bool | None


_PASS_KEY = re.compile(r"([ca])\d+_pass")


def metric_number(metrics: dict[str, object], key: str) -> float | None:
    """The metric under `key` as a number; None when it is absent or not a
    number (a bool is not a number here)."""
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def truth_from_metrics(metrics: dict[str, object], number_key: str | None) -> Truth:
    """What the run says, to hold a reader to: whether the criterion held
    (`criterion_pass` when the run reports it, else every `c<i>_pass`),
    whether every admissibility condition held (`a<i>_pass`), and the number
    under `number_key`. Raises ValueError when a pass flag is not true/false
    or the named number is missing — a verdict from a subset of the
    conjuncts, or a probe whose number key has a typo, would score nothing
    and look clean."""
    flags: dict[str, list[bool]] = {"c": [], "a": []}
    for key, value in metrics.items():
        m = _PASS_KEY.fullmatch(key)
        if m:
            if not isinstance(value, bool):
                raise ValueError(f"metrics: {key} is {value!r}, not true/false")
            flags[m.group(1)].append(value)
    crit = metrics.get("criterion_pass")
    if crit is not None and not isinstance(crit, bool):
        raise ValueError(f"metrics: criterion_pass is {crit!r}, not true/false")
    if crit is None:
        crit = all(flags["c"]) if flags["c"] else None
    number = None
    if number_key is not None:
        number = metric_number(metrics, number_key)
        if number is None:
            raise ValueError(f"metrics: no number under {number_key!r}")
    return Truth(number, crit, all(flags["a"]) if flags["a"] else None)


@dataclass(frozen=True)
class ReaderScore:
    """The full reader's answer held to the run."""

    number_ok: bool | None  # None: the run has no number to hold it to
    number_read: float | None
    criterion_ok: bool | None = None
    admissible_ok: bool | None = None
    correct: int = 0  # checkable answers right
    checkable: int = 0  # answers the run could decide
    unclear: list[str] = field(default_factory=list[str])
    effort: int | None = None
    answers: dict[str, object] = field(default_factory=dict[str, object])


def score_reader_answer(
    answer_text: str, truth: Truth, tol: float = 0.006
) -> ReaderScore:
    """Hold the full reader's answer to the run. Raises ValueError with a
    sentence when the answer is not the asked-for JSON."""
    what = "reader"
    data = load_answer(answer_text, [k for k, _ in READER_QUESTIONS], what)
    number_ok = number_matches(data["number"], truth.number, tol)
    crit = verdict_matches(
        read_verdict(data, "criterion_held", what), truth.criterion_held
    )
    adm = verdict_matches(read_verdict(data, "admissible", what), truth.admissible)
    checks = [c for c in (number_ok, crit, adm) if c is not None]
    effort = data["effort"]
    return ReaderScore(
        number_ok=number_ok,
        number_read=read_number(data["number"]),
        criterion_ok=crit,
        admissible_ok=adm,
        correct=sum(checks),
        checkable=len(checks),
        unclear=read_unclear(data, what),
        effort=effort
        if isinstance(effort, int) and not isinstance(effort, bool)
        else None,
        answers=data,
    )


# --- the glance: what a reader takes away before stopping -------------------
#
# A reader who saw the whole protocol cannot report what it knew at line ten
# (round 9: a reader claimed the result from lines that held the legend).
# The glance reader gets only the first lines of the file, as they are: when
# the head or form text uses them up, that is the finding. Lines are unfair
# between writers — one field per long line holds three times the text of a
# wrapped one — so the excerpt's characters are reported beside it, and
# which Summary fields it holds is checked mechanically (guaranteed: the
# field parser, no judgement).

GLANCE_LINES = 10
SUMMARY_FIELDS = ("result", "limits", "next step")
#: the glance questions a reader answers in words — "answered" counts these
GLANCE_CONTENT_KEYS = ("question", "result", "how_sure", "what_follows")

GLANCE_QUESTIONS = (
    (
        "question",
        "What was investigated? One sentence, or null if these lines do not say.",
    ),
    ("result", "What came out? One sentence, or null."),
    (
        "number",
        "The one number the result rests on, as written (digits only), or null.",
    ),
    (
        "criterion_held",
        "Did the success criterion hold — true, false, or null if these lines do not say?",
    ),
    ("how_sure", "How sure or how limited is the result? One sentence, or null."),
    (
        "what_follows",
        "What follows from it — a decision or a next step? One sentence, or null.",
    ),
    (
        "unclear",
        "Every term, abbreviation, code or file name a newcomer would have to look up — a list, [] if none.",
    ),
)


@dataclass(frozen=True)
class Glance:
    """The first lines of a protocol and which Summary fields they hold."""

    excerpt: str
    lines: int
    chars: int
    summary_fields: tuple[
        str, ...
    ]  # of SUMMARY_FIELDS, those whose label is in the excerpt


def glance(text: str, lines: int = GLANCE_LINES) -> Glance:
    """The first `lines` lines of the file as they are, and which of the
    Summary's fields begin inside them."""
    head = text.splitlines()[:lines]
    inside = tuple(
        name
        for name in SUMMARY_FIELDS
        if any(f.name == name and f.line <= lines for f in fields(text))
    )
    excerpt = "\n".join(head)
    return Glance(excerpt, len(head), len(excerpt), inside)


def glance_prompt(excerpt: str, answer_path: str) -> str:
    """The prompt for a reader who sees only the first lines."""
    return (
        f"{NEWCOMER} Below are the FIRST LINES of an experiment protocol, "
        "nothing more — a reader who stops here. Answer only from these lines; "
        "where they do not say, answer null. No files, no tools except "
        "writing your answer.\n\n"
        "Answer with one JSON object with exactly these keys:\n"
        f"{asked_keys(GLANCE_QUESTIONS)}\n\n"
        f"{answer_contract(answer_path)}\n\n"
        "----- FIRST LINES -----\n"
        f"{excerpt}\n"
        "----- (the protocol continues; you stopped here) -----\n"
    )


@dataclass(frozen=True)
class GlanceScore:
    """The glance reader's answer held to the run."""

    number_ok: bool | None  # None: the run has no number
    criterion_ok: bool | None  # None: the run reports no criterion
    answered: tuple[str, ...]  # of GLANCE_CONTENT_KEYS, those not null
    unclear: list[str]


def score_glance_answer(
    answer_text: str, truth: Truth, tol: float = 0.006
) -> GlanceScore:
    """Hold the glance answer to the run. A null where the run has a value
    counts as not taken away, the same as a wrong one. Raises ValueError
    when the answer is not the asked-for JSON."""
    what = "glance"
    data = load_answer(answer_text, [k for k, _ in GLANCE_QUESTIONS], what)
    return GlanceScore(
        number_ok=number_matches(data["number"], truth.number, tol),
        criterion_ok=verdict_matches(
            read_verdict(data, "criterion_held", what), truth.criterion_held
        ),
        answered=tuple(k for k in GLANCE_CONTENT_KEYS if data[k]),
        unclear=read_unclear(data, what),
    )


# --- terms: is an unclear term explained where the reader would look? -------
#
# Two layers (2026-10-07): a term in the Summary must be plain there — the
# Terms field cannot rescue it; a term in the technical part may be
# explained in Terms or in a glossary note it links. Whether a term OCCURS
# there is checked here — static evidence, never proof of an explanation;
# whether the entry explains it is a reader's judgement (`terms_judge_prompt`).
# Ids are matched as patterns: digit runs become NN, so an entry
# `beschaffungsantrag-NN` covers `beschaffungsantrag-09`.

_LINK = re.compile(r"\]\(([^)\s#]+\.md)(?:#[^)\s]*)?\)")
_DIGITS = re.compile(r"\d+")
_SPLIT = re.compile(r"\s*(?:/|\(|\)|,|;)\s*")


def normalize_term(term: str) -> str:
    """Casefolded, quotes and backticks gone, digit runs as `nn`."""
    t = term.strip().strip("`'\"“”„").casefold()
    return _DIGITS.sub("nn", t.replace("`", ""))


def _variants(term: str) -> list[str]:
    """The term and the parts a reader lists it by ("A / B (C)"), normalized;
    short abbreviations (CI, N) included."""
    parts = [term, *_SPLIT.split(term)]
    return [n for n in (normalize_term(p) for p in parts) if n]


def _occurs(variant: str, text: str) -> bool:
    """Whether a normalized term occurs in normalized text as a word of its
    own — "rag" does not occur in "paragraph"."""
    return re.search(rf"(?<!\w){re.escape(variant)}(?!\w)", text) is not None


def _normalized_section(text: str, name: str) -> str:
    """The section's text, normalized like a term (`normalize_term`)."""
    return normalize_term(_section(text, name))


def glossary_text(text: str, protocol_path: str | None) -> str:
    """The Terms field's value plus every note it links (read relative to the
    protocol). Raises FileNotFoundError naming a linked note that is gone."""
    terms = next((f for f in fields(text) if f.name.startswith("terms")), None)
    if terms is None:
        return ""
    out = [terms.value]
    if protocol_path is not None:
        base = Path(protocol_path).parent
        for target in _LINK.findall(terms.value):
            note = (base / target).resolve()
            if not note.is_file():
                raise FileNotFoundError(f"Terms links {target}, which is not at {note}")
            out.append(note.read_text(encoding="utf-8"))
    return "\n".join(out)


@dataclass(frozen=True)
class TermHit:
    """Where one unclear term occurs."""

    term: str
    in_summary: bool  # the Summary uses it: Terms does not count there
    in_terms: bool  # it occurs in Terms or a linked glossary (static evidence)


def terms_coverage(
    text: str, unclear: list[str], protocol_path: str | None = None
) -> list[TermHit]:
    """Which of the reader's unclear terms occur in the Summary, and which in
    Terms or a glossary it links — occurrence as a word of its own, static
    evidence that an explanation is there, not proof."""
    summary = _normalized_section(text, "Summary")
    glossary = normalize_term(glossary_text(text, protocol_path))
    hits: list[TermHit] = []
    for term in unclear:
        vs = _variants(term)
        hits.append(
            TermHit(
                term,
                in_summary=any(_occurs(v, summary) for v in vs),
                in_terms=any(_occurs(v, glossary) for v in vs),
            )
        )
    return hits


def terms_judge_prompt(pairs: list[tuple[str, str]], answer_path: str) -> str:
    """Ask a reader whether each entry explains its term (the semantics the
    occurrence check cannot see)."""
    body = "\n\n".join(f"TERM: {t}\nENTRY: {e}" for t, e in pairs)
    return (
        f"{NEWCOMER} For each term below you get the entry a protocol gives "
        "for it. Does the entry let you understand the term — what it is, in "
        "plain words? A mere mention, a code, or a pointer elsewhere is not an "
        "explanation.\n\n"
        "Answer with one JSON object mapping each term exactly as given to "
        "true (explained) or false (not explained). No files, no other "
        f"tools.\n{answer_contract(answer_path)}\n\n"
        f"{body}\n"
    )


_LABEL = re.compile(r"^(?:- )?\*{1,2}([^*]+)\*{1,2}")
_INLINE_ENTRY = re.compile(r"(?=(?<![*\w])\*[^*\s][^*]*\*\s+(?:—|=|\())")


def _entries(glossary: str) -> list[str]:
    """Glossary text as entries: a bullet with its continuation lines, and
    inside a long line every `*term* — …` segment (a Terms field is one
    line that defines several terms)."""
    bullets: list[str] = []
    for line in glossary.splitlines():
        if line.startswith("- ") or not bullets or not line.startswith("  "):
            bullets.append(line.strip())
        else:
            bullets[-1] += " " + line.strip()
    out: list[str] = []
    for b in bullets:
        out.extend(seg.strip() for seg in _INLINE_ENTRY.split(b) if seg.strip())
    return out


def entry_for(term: str, glossary: str) -> str | None:
    """The glossary entry that defines the term — the one whose label (the
    bold or italic words it opens with) names it — else the first entry that
    mentions it, else None. Ids match as patterns."""
    vs = _variants(term)
    entries = _entries(glossary)
    labelled = [(e, m.group(1)) for e in entries if (m := _LABEL.match(e))]
    for e, label in labelled:  # the label names the term exactly
        if set(vs) & set(_variants(label)):
            return e
    for e, label in labelled:  # the term is part of a longer label
        if any(_occurs(v, normalize_term(label)) for v in vs):
            return e
    for e in entries:
        if any(_occurs(v, normalize_term(e)) for v in vs):
            return e
    return None
