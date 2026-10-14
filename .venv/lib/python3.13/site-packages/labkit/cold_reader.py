"""cold_reader — what every cold-reader probe shares: the newcomer, the answer.

The protocol reader, the glance reader, the terms judge and the code
navigator all hand a cold agent a prompt and read back one JSON object. One
home for the parts they share (CODE-004 One home per piece of logic): who the
reader is, how it hands its answer back, how the answer is loaded and held
to the asked-for keys, and how a number or a yes/no in it is read. An
answer that is not the asked-for shape is refused with a sentence, never
scored as wrong (CODE-001 Fail loud).
"""

from __future__ import annotations

import json
from typing import cast

#: who every reader is — a newcomer, not a colleague: a colleague's patience
#: hid jargon in protocol-reading rounds 7 and 8 (2026-10-07)
NEWCOMER = (
    "You are a new student who knows basic statistics, but not this lab, "
    "its tools or its words."
)


def answer_contract(answer_path: str) -> str:
    """The sentence that tells the agent where its JSON answer goes."""
    return (
        f"Write the JSON to {answer_path} (a single Bash `cat > … <<'EOF'`), "
        "then reply with the same JSON."
    )


def asked_keys(questions: tuple[tuple[str, str], ...]) -> str:
    """The questions as the bullet list a prompt shows: `- "key": question`."""
    return "\n".join(f'- "{k}": {q}' for k, q in questions)


def load_answer(text: str, keys: list[str], what: str) -> dict[str, object]:
    """The answer as a JSON object holding every asked-for key. Raises
    ValueError naming `what` when it is not JSON, not an object, or lacks a
    key."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{what} answer is not JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{what} answer is not a JSON object")
    missing = [k for k in keys if k not in data]
    if missing:
        raise ValueError(f"{what} answer lacks {missing}")
    return cast(dict[str, object], data)  # an object, its keys strings: JSON says so


def read_number(raw: object) -> float | None:
    """The number an answer wrote (digits, a decimal comma allowed), or None
    when it wrote none or something that is not a number — not answering
    the number is a wrong answer, not a malformed one."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return float(str(raw).replace(",", "."))
    except ValueError:
        return None


def number_matches(raw: object, truth: float | None, tol: float) -> bool | None:
    """Whether the answer's number equals the run's within `tol`; None when
    the run has no number to hold it to."""
    if truth is None:
        return None
    read = read_number(raw)
    return read is not None and abs(read - truth) <= tol


def read_verdict(data: dict[str, object], key: str, what: str) -> bool | None:
    """A yes/no the answer gives: true, false or null. Raises ValueError for
    anything else ("true" as a string is a malformed answer, not a wrong
    one)."""
    value = data[key]
    if value is None or isinstance(value, bool):
        return value
    raise ValueError(f"{what} answer: {key} must be true, false or null, not {value!r}")


def verdict_matches(said: bool | None, truth: bool | None) -> bool | None:
    """Whether the answer's yes/no equals the run's; None when the run does
    not say."""
    return None if truth is None else said is truth


def read_unclear(data: dict[str, object], what: str) -> list[str]:
    """The answer's list of terms it could not place. Raises ValueError when
    `unclear` is not a list."""
    value = data["unclear"]
    if not isinstance(value, list):
        raise ValueError(f"{what} answer: unclear must be a list, not {value!r}")
    return [str(u) for u in cast(list[object], value)]
