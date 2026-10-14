"""code_navigation — how fast a newcomer finds their way in a repo's code, measured.

The protocol probes measure whether a person can read what a run found; this
one measures whether a person can find where the code does a thing. A cold
agent gets the repo and a few questions that describe a behaviour, never a
name ("where is decided which of the repeated answers counts?"), and answers
each with `path:line`. Two measures:

- **found** (guaranteed): the answer's file and line fall inside the symbol
  that is the truth — a function, a class or a module-level name, resolved
  from the source with `ast`, so a truth that no longer exists refuses to
  score instead of scoring wrong;
- **effort** (from the agent's transcript, `agent_transcript`): tool calls
  by tool, files read, seconds.

Questions and truth live in a TOML file:

    [[question]]
    id = "majority"
    question = "When a model step asks the same question several times, ..."
    truth = ["src/agent/model/call.py:majority"]   # any of them counts

A truth names a symbol, or — for logic that has no name of its own — a line
range, `path:L120-L135`; a range is only as good as the commit it was read
on, so a question file with ranges belongs to that commit. A flow question
asks for the steps of an entry point in order and is scored by how many of
its registered steps the answer names in the right order:

    [[flow]]
    id = "finalize_steps"
    question = "List, in order, the checks ..."
    steps = [["completion", "complet"], ["intent ids", "intent|promis"]]
"""

from __future__ import annotations

import ast
import re
import tomllib
from typing import cast
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from labkit import agent_transcript
from labkit.cold_reader import answer_contract, load_answer


class NavigationError(ValueError):
    """A question file or a truth that cannot be used; the message names it."""


@dataclass(frozen=True)
class Question:
    """A "where does the code do X?" question and the places that answer it."""

    id: str
    question: str
    truth: tuple[str, ...]  # "path:symbol", path relative to the repo


def load_questions(path: Path) -> list[Question]:
    """The questions of a TOML file. Raises NavigationError naming the entry."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    out: list[Question] = []
    for n, q in enumerate(data.get("question", []), 1):
        missing = [k for k in ("id", "question", "truth") if k not in q]
        if missing:
            raise NavigationError(f"{path.name}: question {n} lacks {missing}")
        if not q["truth"]:
            raise NavigationError(f"{path.name}: question {q['id']} has no truth")
        out.append(Question(q["id"], q["question"], tuple(q["truth"])))
    return out


@dataclass(frozen=True)
class Choice:
    """A question about how the code behaves, answered from a fixed set of
    choices — the control flow understood, not a place found."""

    id: str
    question: str
    choices: tuple[str, ...]
    truth: frozenset[str]  # the choices that are right, all of them


def load_choices(path: Path) -> list[Choice]:
    """The `[[choice]]` questions of a TOML file (none is fine). Raises
    NavigationError when a truth is not among the choices."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    out: list[Choice] = []
    for c in data.get("choice", []):
        missing = [k for k in ("id", "question", "choices", "truth") if k not in c]
        if missing:
            raise NavigationError(f"{path.name}: a choice lacks {missing}")
        stray = set(c["truth"]) - set(c["choices"])
        if not c["truth"] or stray:
            raise NavigationError(
                f"{path.name}: choice {c['id']}: truth {sorted(stray) or '[]'} "
                f"is not a non-empty subset of its choices"
            )
        out.append(
            Choice(c["id"], c["question"], tuple(c["choices"]), frozenset(c["truth"]))
        )
    return out


@dataclass(frozen=True)
class ChoiceScore:
    """One behaviour answer held to its truth."""

    right: bool  # exactly the right choices
    missed: tuple[str, ...]  # right choices the answer left out
    invented: tuple[str, ...]  # choices the answer picked that are not right


def score_choices(answer_text: str, choices: list[Choice]) -> dict[str, ChoiceScore]:
    """Per behaviour question: right or not, and which choices were missed
    or invented (a dependency or a path the code does not have). Raises
    ValueError when an answer is missing, not a list, or names something
    that is not one of the choices."""
    data = load_answer(answer_text, [c.id for c in choices], "navigation")
    out: dict[str, ChoiceScore] = {}
    for c in choices:
        picked = data[c.id]
        if not isinstance(picked, list) or not all(
            isinstance(x, str) for x in cast(list[object], picked)
        ):
            raise ValueError(f"navigation answer: {c.id} must be a list of choices")
        names = cast(list[str], picked)  # checked just above: a list of strings
        stray = set(names) - set(c.choices)
        if stray:
            raise ValueError(
                f"navigation answer: {c.id} names {sorted(stray)}, not among its choices"
            )
        got = frozenset(names)
        out[c.id] = ChoiceScore(
            got == c.truth,
            tuple(x for x in c.choices if x in c.truth - got),
            tuple(x for x in c.choices if x in got - c.truth),
        )
    return out


@dataclass(frozen=True)
class HumanAnswer:
    """One behaviour question as a person answered it at the keyboard."""

    id: str
    picked: tuple[str, ...]
    seconds: float  # from showing the question to the accepted answer
    help_questions: int  # questions the person asked an assistant meanwhile


def parse_picks(text: str, choice: Choice) -> tuple[str, ...]:
    """The choices a person typed as numbers ("1,3" or "2"). Raises
    ValueError with a sentence when a number is not one of the choices."""
    picks: list[str] = []
    for part in text.replace(" ", "").split(","):
        if not part.isdigit() or not 1 <= int(part) <= len(choice.choices):
            raise ValueError(
                f"{part!r} is not a number between 1 and {len(choice.choices)}"
            )
        picks.append(choice.choices[int(part) - 1])
    return tuple(dict.fromkeys(picks))


def human_session(
    choices: list[Choice],
    ask: Callable[[str], str],
    clock: Callable[[], float],
    count_help: bool,
) -> list[HumanAnswer]:
    """Put each question to a person, one at a time, and time it. `ask`
    shows a text and returns what the person typed; a mistyped answer is
    asked again (the time runs on). With `count_help` the person also says
    how many questions they asked an assistant for it."""
    out: list[HumanAnswer] = []
    for n, c in enumerate(choices, 1):
        listing = "\n".join(f"  {i}. {x}" for i, x in enumerate(c.choices, 1))
        start = clock()
        while True:
            typed = ask(
                f"\nQuestion {n} of {len(choices)}: {c.question}\n{listing}\n"
                "Your answer (numbers, comma-separated if several): "
            )
            try:
                picked = parse_picks(typed, c)
                break
            except ValueError as exc:
                ask(f"  {exc} — press Enter and answer again ")
        seconds = clock() - start
        helped = 0
        if count_help:
            while True:
                typed = ask(
                    "  How many questions did you ask the assistant for this one? "
                )
                if typed.strip().isdigit():
                    helped = int(typed.strip())
                    break
        out.append(HumanAnswer(c.id, picked, round(seconds, 1), helped))
    return out


def symbol_span(repo: Path, truth: str) -> tuple[str, int, int]:
    """(path, first line, last line) of `path:symbol` — a function, class or
    module-level assignment; `Class.method` for a method. Raises
    NavigationError when the file or the symbol is not there."""
    path, _, symbol = truth.partition(":")
    source = repo / path
    if not source.is_file():
        raise NavigationError(f"truth {truth}: no file {source}")
    lines = re.fullmatch(r"L(\d+)-L(\d+)", symbol)
    if lines:
        first, last = int(lines.group(1)), int(lines.group(2))
        length = len(source.read_text(encoding="utf-8").splitlines())
        if not 1 <= first <= last <= length:
            raise NavigationError(
                f"truth {truth}: not a range inside {path} ({length} lines)"
            )
        return path, first, last
    if not symbol:
        return path, 1, len(source.read_text(encoding="utf-8").splitlines())
    nodes: list[ast.stmt] = ast.parse(source.read_text(encoding="utf-8")).body
    node: ast.stmt | None = None
    for part in symbol.split("."):
        node = next((n for n in nodes if _names(n) and part in _names(n)), None)
        if node is None:
            raise NavigationError(f"truth {truth}: no {part!r} in {path}")
        nodes = node.body if isinstance(node, ast.ClassDef) else []
    assert node is not None
    first = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
    return path, first, node.end_lineno or node.lineno


def _names(node: ast.stmt) -> set[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, ast.Assign):
        return {t.id for t in node.targets if isinstance(t, ast.Name)}
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return {node.target.id}
    return set()


def nav_prompt(
    repo: Path,
    questions: list[Question],
    answer_path: str,
    flows: tuple[Flow, ...] = (),
    choices: tuple[Choice, ...] = (),
) -> str:
    """The prompt for a cold agent finding its way in `repo`."""
    asks = "\n".join(f'- "{q.id}" ("path:line"): {q.question}' for q in questions)
    if flows:
        asks += "\n" + "\n".join(
            f'- "{f.id}" (a list of short strings, one per step, in order): {f.question}'
            for f in flows
        )
    if choices:
        asks += "\n" + "\n".join(
            f'- "{c.id}" (a list of every choice that is right, from: '
            f"{', '.join(repr(x) for x in c.choices)}): {c.question}"
            for c in choices
        )
    return (
        f"You are new to the code repository at {repo}. Answer the questions "
        "below about where the code does things and how it behaves. Look "
        "around the repository as you normally would — read, search, list — "
        "but change nothing and run nothing that writes or runs the code.\n\n"
        "Answer with one JSON object with one key per question below. A place "
        'is "path:line" (path relative to the repository root, the line where '
        "the code doing it starts), or null if you could not find it.\n"
        f"{asks}\n\n"
        f"{answer_contract(answer_path)}\n"
    )


_PLACE = re.compile(r"^\s*`?(?:\./)?([^\s:`]+):(\d+)")


@dataclass(frozen=True)
class Found:
    """One navigation answer held to its truth."""

    id: str
    answer: str | None
    file_right: bool
    found: bool  # file right and the line inside the truth's span
    truth: str  # the truth spans, "path:first-last"


def score_nav_answer(
    answer_text: str, questions: list[Question], repo: Path
) -> list[Found]:
    """Hold each answer to its truth. Raises ValueError when the answer is
    not the asked-for JSON, NavigationError when a truth no longer exists."""
    data = load_answer(answer_text, [q.id for q in questions], "navigation")
    out: list[Found] = []
    for q in questions:
        spans = [symbol_span(repo, t) for t in q.truth]
        raw = data[q.id]
        if raw is not None and not isinstance(raw, str):
            raise ValueError(f'navigation answer: {q.id} must be "path:line" or null')
        place = raw.removeprefix(str(repo) + "/") if raw else ""
        m = _PLACE.match(place) if place else None
        path, line = (m.group(1), int(m.group(2))) if m else (None, None)
        if path is not None:
            path = _full_path(repo, path, [p for p, _, _ in spans])
        file_right = any(path == p for p, _, _ in spans)
        found = any(
            path == p and line is not None and a <= line <= b for p, a, b in spans
        )
        out.append(
            Found(
                q.id,
                raw,
                file_right,
                found,
                ", ".join(f"{p}:{a}-{b}" for p, a, b in spans),
            )
        )
    return out


def _full_path(repo: Path, path: str, truths: list[str]) -> str:
    """The answer's path, or the truth path it names by its tail alone
    (`runlog.py` for `labkit/runlog.py`) when that tail names exactly one
    file in the repo — a reader who drops the package folder still found
    the file; an ambiguous tail stays as written and does not count."""
    if path in truths:
        return path
    for truth in truths:
        if truth.endswith("/" + path):
            same_tail = [
                f
                for f in repo.rglob(Path(path).name)
                if ".venv" not in f.parts and f.as_posix().endswith("/" + path)
            ]
            if len(same_tail) == 1:
                return truth
    return path


@dataclass(frozen=True)
class Flow:
    """A question for an entry point's steps in order, with a pattern per step."""

    id: str
    question: str
    steps: tuple[tuple[str, str], ...]  # (name, regex a mention of the step matches)


def load_flows(path: Path) -> list[Flow]:
    """The flow questions of a TOML file (none is fine)."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    out: list[Flow] = []
    for f in data.get("flow", []):
        missing = [k for k in ("id", "question", "steps") if k not in f]
        if missing:
            raise NavigationError(f"{path.name}: a flow lacks {missing}")
        for name, pattern in f["steps"]:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise NavigationError(
                    f"{path.name}: flow {f['id']}, step {name!r}: bad pattern ({exc})"
                ) from exc
        out.append(Flow(f["id"], f["question"], tuple((n, r) for n, r in f["steps"])))
    return out


def flow_in_order(answer: list[str], flow: Flow) -> int:
    """How many registered steps the answer names in the registered order —
    the longest run of steps whose first mentions do not fall back through
    the answer (two steps named in one item both count)."""
    first: list[int] = []
    for _, pattern in flow.steps:
        hit = next(
            (i for i, item in enumerate(answer) if re.search(pattern, item, re.I)),
            None,
        )
        if hit is not None:
            first.append(hit)
    best: list[int] = []  # longest non-decreasing subsequence of `first`
    for x in first:
        i = next((k for k, v in enumerate(best) if v > x), len(best))
        best[i : i + 1] = [x]
    return len(best)


def score_flows(answer_text: str, flows: list[Flow]) -> dict[str, tuple[int, int]]:
    """Per flow question, (steps named in order, steps registered). Raises
    ValueError when a flow is unanswered or not a list of strings."""
    data = load_answer(answer_text, [f.id for f in flows], "navigation")
    out: dict[str, tuple[int, int]] = {}
    for f in flows:
        steps = data[f.id]
        if not isinstance(steps, list) or not all(
            isinstance(s, str) for s in cast(list[object], steps)
        ):
            raise ValueError(f"navigation answer: {f.id} must be a list of strings")
        named = cast(list[str], steps)  # checked just above: a list of strings
        out[f.id] = (flow_in_order(named, f), len(f.steps))
    return out


@dataclass(frozen=True)
class Effort:
    """What the agent did to find its answers."""

    seconds: int
    calls: int
    by_tool: dict[str, int] = field(default_factory=dict[str, int])
    files_opened: list[str] = field(
        default_factory=list[str]
    )  # files read by Read or a shell command, no repeats


def effort(transcript: Path, repo: Path) -> Effort:
    """What the agent did to find its answers, from its transcript."""
    calls, first, last = agent_transcript.read_calls(transcript)
    by_tool: dict[str, int] = {}
    opened: list[str] = []
    for c in calls:
        by_tool[c.tool] = by_tool.get(c.tool, 0) + 1
        reads = (
            [c.text]
            if c.tool == "Read"
            else agent_transcript.shell_reads(c.text)
            if c.tool == "Bash"
            else []
        )
        for f in reads:
            rel = f.removeprefix(str(repo) + "/").removeprefix("./")
            if rel not in opened:
                opened.append(rel)
    return Effort(round(last - first), len(calls), by_tool, opened)
