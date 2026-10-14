"""agent_transcript — what a coding agent did, read from its session transcript.

The usability probe asked the agent to log its own steps; the log is
self-report — lines get batched, written late, or forgotten, and a file
read without a log line is invisible (re-measure 2026-10-07: one agent
reported seven minutes, its log spanned two). The transcript the agent
harness writes is the measurement instead: one JSON record per message,
each tool call with its input, each result with its output, every record
with a timestamp.

Read here (Claude Code's JSONL, one record per line):

- `timestamp` (ISO 8601, UTC) on every record;
- `type = "assistant"`: `message.content[]` blocks of `type = "tool_use"`
  with `id`, `name`, `input`;
- `type = "user"`: `message.content[]` blocks of `type = "tool_result"`
  with `tool_use_id`, `content` (a string or text blocks);
- `type = "assistant"`: `message.usage` with the model call's token counts
  (`input_tokens`, `output_tokens`, `cache_read_input_tokens`,
  `cache_creation_input_tokens`); a key the record lacks counts as 0.

Two tiers, as everywhere in labkit:

- **measured** — wall-clock (first to last record), tool time (call to its
  result), the number of calls, which labkit commands ran, the tokens the
  model calls cost (`Tokens`: output, cache read, the largest context one
  call read — 2026-10-11: the usability probes averaged 2.9 M cache-read
  tokens per agent and no score said so);
- **heuristic** — which files a shell command read (the verbs `cat`, `head`,
  `tail`, `sed`, `less`, `wc`, `nl` and their arguments), and whether a
  result was a refusal (a line `pre-commit: …`, `finalize: N blocker(s)`
  with N > 0, a must-field verdict of `protocol-check`). A read hidden in a
  Python one-liner is caught only when it names the path.
"""

from __future__ import annotations

import gzip
import json
import re
import shlex
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

#: The console commands of labkit an agent may run; counted per name.
LABKIT_COMMANDS = (
    "protocol-check",
    "protocol-fill",
    "code-check",
    "preflight",
    "finalize",
    "report-check",
    "intent-check",
    "recheck",
    "runlog",
    "scope-sha",
    "labkit-hooks",
)
#: Shell verbs whose file arguments are reads.
READ_VERBS = frozenset({"cat", "head", "tail", "sed", "less", "wc", "nl"})
#: A result that is a gate's refusal, line-anchored so a `cat` of the hook
#: script (whose echo lines contain the same words) does not count.
REFUSAL = re.compile(
    r"^pre-commit: |^finalize: [1-9]\d* blocker|: must fields missing or empty",
    re.M,
)


class TranscriptError(ValueError):
    """The file is not a transcript this module can read; names the line."""


@dataclass(frozen=True)
class Call:
    """One tool call of the agent and its result."""

    at: float  # seconds since the epoch, the tool_use record's timestamp
    tool: str  # Bash, Read, Edit, Write, ...
    text: str  # the shell command, or the file path for file tools
    seconds: float | None  # until its result; None when no result came back
    output: str  # the result text ("" when none)


@dataclass(frozen=True)
class Tokens:
    """What the model calls of one transcript cost, summed over the assistant
    records' `usage` blocks (measured). Every call reads its whole context
    again, so `cache_read` grows with the square of the conversation while
    `output` is what the agent wrote."""

    calls: int  # assistant records carrying a usage block
    input: int  # uncached prompt tokens
    output: int
    cache_read: int
    cache_creation: int
    context_max: int  # the largest context one call read: input + cache read + creation


@dataclass(frozen=True)
class TranscriptTrace:
    """What the transcript shows; see the module docstring for the tiers."""

    wall_seconds: int  # first to last record
    tool_seconds: int  # sum over calls of call → result
    calls: int
    commands: dict[str, int]  # labkit command → runs
    refusals: int  # results carrying a gate's refusal (heuristic)
    tokens: Tokens
    files_read: list[str] = field(default_factory=list)  # in order, no repeats
    source_reads: list[str] = field(
        default_factory=list
    )  # reads of labkit source / the standard


def _stamp(record: dict, n: int) -> float:
    raw = record.get("timestamp")
    if not isinstance(raw, str):
        raise TranscriptError(f"line {n}: record without a timestamp")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError as exc:
        raise TranscriptError(f"line {n}: timestamp {raw!r} is not ISO 8601") from exc


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def records(path: Path) -> list[tuple[int, dict]]:
    """(line number, record) for every non-empty line of a transcript
    (plain or gzipped JSONL); a line that is not a JSON object names itself."""
    raw = (
        gzip.decompress(path.read_bytes()).decode("utf-8")
        if path.suffix == ".gz"
        else path.read_text(encoding="utf-8")
    )
    out: list[tuple[int, dict]] = []
    for n, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TranscriptError(f"{path.name}:{n}: not JSON — {exc.msg}") from exc
        if not isinstance(record, dict):
            raise TranscriptError(f"{path.name}:{n}: a record is a JSON object")
        out.append((n, record))
    return out


def tokens(path: Path) -> Tokens:
    """The token counts of one transcript, summed over its assistant records'
    `usage` blocks; a `usage` that is not an object, or a count that is not
    an integer, names its line."""
    calls = inp = out = read = created = context_max = 0
    for n, record in records(path):
        if record.get("type") != "assistant":
            continue
        usage = (record.get("message") or {}).get("usage")
        if usage is None:
            continue
        if not isinstance(usage, dict):
            raise TranscriptError(f"{path.name}:{n}: `usage` is not an object")
        counts = {}
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        ):
            v = usage.get(key, 0)
            if v is None:
                v = 0
            if not isinstance(v, int) or isinstance(v, bool):
                raise TranscriptError(
                    f"{path.name}:{n}: usage.{key} is {v!r}, not an integer"
                )
            counts[key] = v
        calls += 1
        inp += counts["input_tokens"]
        out += counts["output_tokens"]
        read += counts["cache_read_input_tokens"]
        created += counts["cache_creation_input_tokens"]
        context_max = max(
            context_max,
            counts["input_tokens"]
            + counts["cache_read_input_tokens"]
            + counts["cache_creation_input_tokens"],
        )
    return Tokens(
        calls=calls,
        input=inp,
        output=out,
        cache_read=read,
        cache_creation=created,
        context_max=context_max,
    )


def read_calls(path: Path) -> tuple[list[Call], float, float]:
    """(calls in order, first stamp, last stamp) of one transcript."""
    uses: dict[str, tuple[float, str, str]] = {}
    order: list[str] = []
    results: dict[str, tuple[float, str]] = {}
    stamps: list[float] = []
    for n, record in records(path):
        at = _stamp(record, n)
        stamps.append(at)
        content = (record.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                inp = block.get("input") or {}
                text = (
                    inp.get("command") or inp.get("file_path") or inp.get("path") or ""
                )
                uses[block["id"]] = (at, str(block.get("name")), str(text))
                order.append(block["id"])
            elif block.get("type") == "tool_result":
                results[block["tool_use_id"]] = (at, _text(block.get("content")))
    if not stamps:
        raise TranscriptError(f"{path.name}: no records")
    calls = []
    for uid in order:
        at, tool, text = uses[uid]
        done = results.get(uid)
        calls.append(
            Call(
                at=at,
                tool=tool,
                text=text,
                seconds=(done[0] - at) if done else None,
                output=done[1] if done else "",
            )
        )
    return calls, min(stamps), max(stamps)


_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")
_SEPARATORS = frozenset({"&&", "||", ";", "|", "&", "(", ")"})
_WRITES = frozenset({">", ">>", ">|"})


def _strip_heredocs(command: str) -> str:
    """The command without heredoc bodies: their lines are input data (a
    Python script, a file's text), not shell — `from labkit import recheck`
    in a body is no run of `recheck`."""
    lines = command.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        out.append(lines[i])
        tags = [m.group(2) for m in _HEREDOC.finditer(lines[i])]
        i += 1
        for tag in tags:
            while i < len(lines) and lines[i].strip() != tag:
                i += 1
            i += 1  # the terminator
    return "\n".join(out)


def _pieces(command: str) -> list[tuple[list[str], str]]:
    """(words, the separator after them) for each simple command."""
    text = _strip_heredocs(command).replace("\n", " ; ")
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = text.split()
    out: list[tuple[list[str], str]] = [([], "")]
    for tok in tokens:
        if tok in _SEPARATORS:
            out[-1] = (out[-1][0], tok)
            out.append(([], ""))
        else:
            out[-1][0].append(tok)
    return [(w, op) for w, op in out if w]


def segments(command: str) -> list[list[str]]:
    """The simple commands of a shell line, as word lists (heuristic: a
    quote-aware split at `&&`, `||`, `;`, `|`, newlines; heredoc bodies cut)."""
    return [w for w, _ in _pieces(command)]


def _verb(words: list[str]) -> str:
    return words[0].rsplit("/", 1)[-1]


def shell_reads(command: str) -> list[str]:
    """File arguments of the read verbs in a shell command (heuristic).

    A segment that writes (`cat > f`) is no read; arguments after a
    redirection are its target, not input."""
    out: list[str] = []
    for words in segments(command):
        if _verb(words) not in READ_VERBS or any(w in _WRITES for w in words):
            continue
        args = []
        for w in words[1:]:
            if w.startswith((">", "<")) or w in (">&", "<&"):
                break
            if not w.startswith("-") and not w.isdigit():
                args.append(w)
        if _verb(words) == "sed" and args:
            args = args[1:]  # the script, e.g. `1,40p`
        out += [a for a in args if "=" not in a and "$" not in a]
    return out


def labkit_commands(command: str) -> list[str]:
    """The labkit console commands a shell line runs, by command position."""
    return [_verb(w) for w in segments(command) if _verb(w) in LABKIT_COMMANDS]


#: Reading labkit's code without opening a file: an introspection call.
_INTROSPECTION = re.compile(
    r"inspect\.(getsource|signature)\([^)]*\)?|site-packages/labkit\S*"
)


def trace(path: Path, root: Path, source: re.Pattern[str]) -> TranscriptTrace:
    """The transcript of one agent working in `root`; `source` names what
    counts as reading labkit's source or the standard. Refuses a transcript
    that never mentions `root` — the wrong file measures the wrong agent."""
    calls, first, last = read_calls(path)
    if not any(str(root) in c.text for c in calls):
        raise TranscriptError(
            f"{path.name}: no call mentions {root} — not this probe's transcript"
        )
    commands: dict[str, int] = {}
    files: list[str] = []
    for c in calls:
        if c.tool == "Bash":
            for name in labkit_commands(c.text):
                commands[name] = commands.get(name, 0) + 1
            read = shell_reads(c.text)
        elif c.tool in ("Read", "Grep", "Glob") and c.text:
            read = [c.text]
        else:
            read = []
        for f in read:
            rel = f.removeprefix(str(root) + "/").removeprefix("./")
            if rel not in files:
                files.append(rel)
    hits = [f for f in files if source.search(f)] + [
        m.group(0)
        for c in calls
        if c.tool == "Bash"
        for m in _INTROSPECTION.finditer(c.text)
    ]
    return TranscriptTrace(
        wall_seconds=round(last - first),
        tool_seconds=round(sum(c.seconds for c in calls if c.seconds is not None)),
        calls=len(calls),
        commands=commands,
        refusals=sum(1 for c in calls if REFUSAL.search(c.output)),
        tokens=tokens(path),
        files_read=files,
        source_reads=hits,
    )


def _log_step(words: list[str]) -> bool:
    """Bookkeeping, not work: `cd`, the log appends, the time stamp."""
    return (
        _verb(words) in ("cd", "touch", "date", "echo", "printf")
        or words[0].startswith("L=")
        or any("$L" in w or w.endswith(".log.md") for w in words)
    )


def describe_tokens(t: Tokens) -> str:
    """One line: `12 calls · output 3,831 · context max 267,129 · cache read
    75,841,155`, or `no usage recorded` for a transcript without one."""
    if not t.calls:
        return "no usage recorded"
    return (
        f"{t.calls} calls · output {t.output:,} · context max {t.context_max:,} · "
        f"cache read {t.cache_read:,}"
    )


def timeline(path: Path) -> list[str]:
    """One line per call: elapsed since the first record, duration, tool,
    the command without its bookkeeping (cd, log appends) and heredoc
    bodies; REFUSED where the result carries a gate's refusal. The last
    line is what the model calls cost (`describe_tokens`)."""
    calls, first, _ = read_calls(path)
    out = []
    for c in calls:
        text = c.text
        if c.tool == "Bash":
            work = [(w, op) for w, op in _pieces(text) if not _log_step(w)]
            text = (
                " ".join(
                    " ".join(w) + (f" {op}" if op else "") for w, op in work
                ).rstrip(" ;&|")
                or "(log only)"
            )
        dur = f"{c.seconds:5.1f}s" if c.seconds is not None else "   n/a"
        e = round(c.at - first)
        flag = " REFUSED" if REFUSAL.search(c.output) else ""
        out.append(f"{e // 60:2d}:{e % 60:02d} {dur} {c.tool:<6} {text[:110]}{flag}")
    out.append(f"tokens: {describe_tokens(tokens(path))}")
    return out
