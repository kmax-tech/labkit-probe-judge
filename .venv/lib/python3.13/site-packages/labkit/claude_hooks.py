"""claude-hook — the three Claude Code hooks a lab repo installs.

    claude-hook pre-run       PreToolUse  (matcher: Bash)
    claude-hook post-change   PostToolUse (matcher: Bash|Write|Edit)
    claude-hook stop          Stop
    claude-hook sessions [--run RUN_ID]   the session log: which session, which transcript, which runs

The three hooks read the hook's JSON event on stdin and answer the way
Claude Code expects: `pre-run` and `stop` block with exit 2 (the stderr
text goes back to the agent), `post-change` is `additionalContext` on
stdout and exit 0.

Why these exist (2026-10-05): the rules that matter — "preflight before a
full run", "protocol-check after writing a protocol" — lived in the skill
text, in the agent's memory. The write hooks that did exist matched only
the Write and Edit tools; a protocol written through a Bash heredoc got no
check at all, and no hook at all stood between the agent and
`python 01_measure.py`. A rule the agent has to remember is the weak layer;
this is the layer that does not depend on remembering.

pre-run
    The command is a run start when it names a .py file that opens a run
    (`runlog.run(` / `runlog.Run(`) and is not one of the throwaway stages
    (`--show`, `--probe`, `--eval-only`). For that script's area (the
    nearest directory above it with a PROTOCOL-*.md) `preflight` runs:
      · protocol frozen (`frozen = true`) + blockers           → exit 2, blocked
      · protocol unfrozen (a pilot by declaration) + blockers  → context only
      · clean                                                   → one line
    `LABKIT_PREFLIGHT=skip` in the command string skips the gate; it is
    visible in the transcript, like `--no-verify` on a commit.
    The gate follows the cost tier (LAB-017 The number of audits follows the cost tier): at `cost = "seconds"` preflight
    does not run before a command — a rerun of seconds is the probe — and
    the hook only says whether the success criterion is written, which is
    what `runlog` will demand of a full run there. A `minutes`/`hours`/
    undeclared protocol keeps the gate above.

post-change
    Every file the repo now reports as changed (git status, untracked
    included) plus the tool's own file_path, filtered to PROTOCOL-*.md and
    notes/messung/*.md (not 00-*), is checked with protocol-check or
    notes-check. A per-session cache of content hashes keeps a file that was
    already checked at this content from being reported after every later
    command.

stop
    Before the agent ends its turn: every changed PROTOCOL-*.md (git status)
    whose "Answer to the question" cites a run goes through `finalize
    --if-reported`. Blockers → exit 2, and the findings go back to the agent,
    which keeps working — the number it just wrote back is checked in the
    session that still knows why it is there, not at the next commit
    (2026-10-07). Once per stop: when the agent was already sent back by
    this hook (`stop_hook_active`), it may stop; the commit gate still holds.

session log
    Every stop also appends one line to the repo's `.git/labkit-sessions.jsonl`
    (inside .git: local, never committed): the session id, the transcript
    path, the time, and the runs whose run_id dates from after this
    session's previous stop (or its first transcript record). `claude-hook
    sessions --run RUN_ID` finds the session — and so the transcript — a run
    came from: what the agent read and decided before it, for debugging
    (2026-10-07; Claude Code deletes transcripts after `cleanupPeriodDays`).

Exit codes: pre-run 0 or 2 (block); stop 0 or 2 (keep working); post-change 0; usage errors and
unexpected failures 1, loud on stderr, never swallowed.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from collections.abc import Callable
from pathlib import Path

from labkit import (
    console,
    finalize,
    notes_check,
    preflight,
    protocol_block,
    protocol_check,
    runs,
)
from labkit.repo import area_protocols, git_run
from labkit.scope_sha import file_digest

# The template's throwaway stages: none of them opens a run, and the probe
# is what comes BEFORE preflight, so gating it would invert the order.
THROWAWAY_FLAGS = re.compile(r"(^|\s)--(show|probe|eval-only)\b")
PY_TOKEN = re.compile(r"[\w./~-]+\.py")
# A .py file is RUN when an interpreter precedes it (`python`, `python3.12`,
# `.venv/bin/python`, flags between allowed), when it starts a command
# segment (`./x.py`, after `;`, `&&`, `|`, `(`, `runlog start --`, `nohup`,
# `time`), never when it is merely named (`sed -n 1,5p lib/x.py`, a path in
# a heredoc): uniagent 2026-10-10, 85 of 272 hook lines in one session said
# "opens a run" about a lib module someone was reading.
INTERPRETER = re.compile(r"(?:^|/)python[\d.]*$")
SEGMENT_START = {";", "&&", "||", "|", "(", "--", "nohup", "time", "exec"}
STRIP = "\"'`();"  # around a token: quotes, parentheses, a trailing ;
OPENS_RUN = re.compile(r"runlog\.(run|Run)\(")
PROTOCOL_IN_SCRIPT = re.compile(r"PROTOCOL-[\w.-]+\.md")
SKIP_TOKEN = "LABKIT_PREFLIGHT=skip"
PROTOCOL_NAME = re.compile(r"^PROTOCOL-.*\.md$")


def _read_event() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    return json.loads(raw)


def _context(event_name: str, text: str) -> None:
    """Hand text back to the agent as additionalContext."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event_name,
                    "additionalContext": text,
                }
            },
            ensure_ascii=False,
        )
    )


def _capture(fn: Callable[..., int], *args: object) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*args)
    return rc, buf.getvalue().rstrip()


# ---------------------------------------------------------------- pre-run


def find_area(script: Path, stop: Path | None = None) -> Path | None:
    """The nearest directory above `script` holding a PROTOCOL-*.md."""
    for d in script.resolve().parents:
        if area_protocols(d):
            return d
        if stop is not None and d == stop.resolve():
            return None
    return None


def executed_py(command: str) -> list[str]:
    """The .py paths the command RUNS, in order: preceded by an interpreter
    (flags in between allowed) or starting a command segment, or `./x.py`.
    A .py path that is only named — read, edited, written in a heredoc — is
    not among them."""
    tokens = command.split()
    out: list[str] = []
    for i, raw in enumerate(tokens):
        tok = raw.strip(STRIP)
        if not PY_TOKEN.fullmatch(tok):
            continue
        j = i - 1
        while j >= 0 and tokens[j].startswith("-") and tokens[j] not in SEGMENT_START:
            j -= 1  # interpreter flags: python -u x.py
        before = tokens[j].strip(STRIP) if j >= 0 else None
        runs = (
            tok.startswith("./")
            or before is None
            or before in SEGMENT_START
            or INTERPRETER.search(before) is not None
        )
        if runs and (j == i - 1 or (before is not None and INTERPRETER.search(before))):
            out.append(tok)
    return out


def run_scripts(command: str, cwd: Path) -> list[Path]:
    """The .py files the command runs that open a run — resolved and existing."""
    out = []
    for tok in executed_py(command):
        p = Path(os.path.expanduser(tok))
        if not p.is_absolute():
            p = cwd / p
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if OPENS_RUN.search(text):
            out.append(p.resolve())
    return out


def protocol_named_in(script: Path, area: Path) -> Path | None:
    """The single PROTOCOL-*.md the script names, if it names exactly one
    and it exists in the area — the series case where preflight would
    otherwise refuse to pick."""
    names = sorted(set(PROTOCOL_IN_SCRIPT.findall(script.read_text(encoding="utf-8"))))
    if len(names) != 1:
        return None
    p = area / names[0]
    return p if p.is_file() else None


def pre_run(event: dict) -> int:  # noqa: C901 complexity baseline 2026-10-08
    """PreToolUse hook on Bash: a full measure run gets its area's preflight first; blockers refuse the command (exit 2)."""
    if event.get("tool_name", "Bash") != "Bash":
        return 0
    command = (event.get("tool_input") or {}).get("command") or ""
    if not command or THROWAWAY_FLAGS.search(command):
        return 0
    cwd = Path(event.get("cwd") or os.getcwd())
    scripts = run_scripts(command, cwd)
    if not scripts:
        return 0
    if SKIP_TOKEN in command:
        _context(
            "PreToolUse",
            f"claude-hook pre-run: {SKIP_TOKEN} — preflight "
            f"gate skipped on request; the transcript carries it.",
        )
        return 0

    project = os.environ.get("CLAUDE_PROJECT_DIR")
    stop = Path(project) if project else None
    blocked: list[str] = []
    notes: list[str] = []
    for script in scripts:
        area = find_area(script, stop)
        if area is None:
            notes.append(
                f"{script.name}: opens a run, but no PROTOCOL-*.md "
                f"above it — unbound runs keep no number (LAB-003 No run without an intent paragraph)."
            )
            continue
        protocol = protocol_named_in(script, area)
        texts = [
            p.read_text(encoding="utf-8")
            for p in ([protocol] if protocol else area_protocols(area))
        ]
        head = f"preflight {area.name}" + (
            f" --protocol {protocol.name}" if protocol else ""
        )
        try:
            heads = [protocol_block.head(t) for t in texts]
        except protocol_block.BlockError as exc:
            notes.append(f"{head}: protocol head unreadable — {exc}")
            continue
        tiers = {h.cost for h in heads}
        if tiers == {"seconds"}:
            missing = sorted(
                {
                    m
                    for t in texts
                    for m in protocol_check.seconds_registration_missing(t)
                }
            )
            if not missing:
                notes.append(
                    f"{head}: cost seconds — gate not run, the rerun is "
                    f"the probe; registration written (LAB-017 The number of audits follows the cost tier)."
                )
            else:
                notes.append(
                    f"{head}: cost seconds, but {', '.join(missing)} still "
                    f"empty or a placeholder — runlog refuses a full run "
                    f"until the registration is written (LAB-003 No run without an intent paragraph, LAB-017 The number of audits follows the cost tier)."
                )
            continue
        rc, out = _capture(preflight.preflight_area, area, protocol)
        frozen = any(h.frozen for h in heads)
        if rc == 1 and frozen:
            blocked.append(
                f"{head}: BLOCKED — the protocol is frozen and "
                f"preflight reports blockers:\n{out}"
            )
        elif rc == 1:
            notes.append(
                f"{head}: blockers, protocol not frozen (pilot) — "
                f"the full run will not start until they are fixed:\n{out}"
            )
        elif rc == 2:
            notes.append(f"{head}: could not run preflight:\n{out}")
        else:
            notes.append(f"{head}: " + (out.splitlines()[-1] if out else "ok"))
    if blocked:
        sys.stderr.write("\n\n".join(blocked) + "\n")
        if notes:
            sys.stderr.write("\n" + "\n".join(notes) + "\n")
        return 2
    if notes:
        _context("PreToolUse", "\n\n".join(notes))
    return 0


# ------------------------------------------------------------ post-change


def _git_changed(repo: Path) -> list[Path]:
    r = git_run(["status", "--porcelain", "--untracked-files=all"], repo)
    if r.returncode != 0:
        raise RuntimeError(f"git status failed in {repo}: {r.stderr.strip()}")
    out = []
    for line in r.stdout.splitlines():
        if len(line) < 4 or line[1] == "D" or line[0] == "D":
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        out.append(repo / path)
    return out


def wants_check(path: Path) -> str | None:
    """Which checker a path belongs to: 'protocol', 'note' or None."""
    if PROTOCOL_NAME.match(path.name):
        return "protocol"
    parts = path.as_posix().split("/")
    if (
        "notes" in parts
        and "messung" in parts
        and parts.index("messung") == parts.index("notes") + 1
        and path.suffix == ".md"
        and not path.name.startswith("00-")
    ):
        return "note"
    return None


def _cache_path(session_id: str | None) -> Path | None:
    if not session_id:
        return None
    d = Path(tempfile.gettempdir()) / "labkit-claude-hook"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{session_id}.json"


def _load_cache(p: Path | None) -> dict:
    if p is None or not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def post_change(event: dict) -> int:  # noqa: C901 complexity baseline 2026-10-08
    """PostToolUse hook: a protocol or a measurement note just written gets its checker; the findings go back as context."""
    project = os.environ.get("CLAUDE_PROJECT_DIR")
    repo = Path(project) if project else Path(event.get("cwd") or os.getcwd())
    candidates: list[Path] = []
    if (repo / ".git").exists():
        candidates.extend(_git_changed(repo))
    fp = (event.get("tool_input") or {}).get("file_path")
    if fp:
        candidates.append(Path(fp))
    seen: set[Path] = set()
    targets: list[tuple[str, Path]] = []
    for c in candidates:
        c = c.resolve()
        if c in seen or not c.is_file():
            continue
        seen.add(c)
        kind = wants_check(c)
        if kind:
            targets.append((kind, c))
    if not targets:
        return 0

    cache_file = _cache_path(event.get("session_id"))
    cache = _load_cache(cache_file)
    reports = []
    for kind, path in targets:
        digest = file_digest(path)
        if cache.get(str(path)) == digest:
            continue
        cache[str(path)] = digest
        fn = protocol_check.main if kind == "protocol" else notes_check.main
        _, out = _capture(fn, [str(path)])
        # The checker gets the absolute path (the hook's cwd is wherever the
        # agent stood); the report shows it repo-relative, as pfad:zeile.
        try:
            out = out.replace(str(path), str(path.relative_to(repo.resolve())))
        except ValueError:
            pass
        if out:
            reports.append(out)
    if cache_file is not None:
        cache_file.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    if reports:
        _context("PostToolUse", "\n".join(reports))
    return 0


def session_log(repo: Path) -> Path | None:
    """`.git/labkit-sessions.jsonl` of the repo (the common git dir, so a
    worktree logs into its main repo); None outside git."""
    r = git_run(["rev-parse", "--git-common-dir"], repo)
    if r.returncode != 0:
        return None
    common = Path(r.stdout.strip())
    return (common if common.is_absolute() else repo / common) / "labkit-sessions.jsonl"


def read_sessions(log: Path) -> list[dict]:
    """The log's records; a line that is not JSON names its number."""
    out = []
    for n, line in enumerate(log.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{log}:{n}: not JSON — {exc.msg}") from exc
    return out


def _transcript_start(transcript: str | None) -> datetime | None:
    """The first record's timestamp, in local time (run_ids are local)."""
    if not transcript or not Path(transcript).is_file():
        return None
    with open(transcript, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                stamp = json.loads(line).get("timestamp")
                if isinstance(stamp, str):
                    utc = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                    return utc.astimezone().replace(tzinfo=None)
                return None
    return None


def record_session(repo: Path, event: dict, now: datetime | None = None) -> dict | None:
    """Append this stop to the session log; returns the record (None without
    a session id or outside git)."""
    session = event.get("session_id")
    log = session_log(repo)
    if not session or log is None:
        return None
    now = now or datetime.now()
    earlier = (
        [r for r in read_sessions(log) if r.get("session") == session]
        if log.is_file()
        else []
    )
    since = (
        datetime.fromisoformat(earlier[-1]["stopped"])
        if earlier
        else _transcript_start(event.get("transcript_path"))
    )
    session_runs = sorted(
        str(d.relative_to(repo))
        # where areas live (experiments/<area>, or flat at the root) — not a
        # walk through .venv and data on every stop
        for d in [*repo.glob("experiments/*/runs/*"), *repo.glob("*/runs/*")]
        if d.is_dir()
        and (started := runs.run_started(d.name)) is not None
        and (since is None or started >= since.replace(microsecond=0))
        and started <= now
    )
    record = {
        "session": session,
        "transcript": event.get("transcript_path"),
        "stopped": now.isoformat(timespec="seconds"),
        "runs": session_runs,
    }
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def sessions(argv: list[str]) -> int:
    """Print the session log, or the session(s) a run came from."""
    run = argv[argv.index("--run") + 1] if "--run" in argv else None
    repo = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    log = session_log(repo)
    if log is None or not log.is_file():
        print(
            f"claude-hook: no session log in {repo} — no session has stopped here yet"
        )
        return 1
    hits = [
        r
        for r in read_sessions(log)
        if run is None or any(Path(x).name == run for x in r.get("runs", []))
    ]
    for r in hits:
        print(
            f"{r['stopped']}  {r['session']}  {r.get('transcript')}  runs: {', '.join(r.get('runs') or []) or '—'}"
        )
    if run is not None and not hits:
        print(f"claude-hook: no logged session made run {run}")
        return 1
    return 0


def stop(event: dict) -> int:
    """Stop hook: a number written back in this session gets finalize; blockers send the agent back once (exit 2)."""
    project = os.environ.get("CLAUDE_PROJECT_DIR")
    repo = Path(project) if project else Path(event.get("cwd") or os.getcwd())
    if not (repo / ".git").exists():
        return 0
    record_session(repo, event)
    if event.get("stop_hook_active"):
        return 0  # sent back once already; no loop
    protocols = [
        c.resolve()
        for c in _git_changed(repo)
        if c.is_file() and wants_check(c) == "protocol"
    ]
    if not protocols:
        return 0
    rc, out = _capture(finalize.main, ["--if-reported", *map(str, protocols)])
    if rc == 0:
        return 0
    print(
        "finalize reports blockers for a number written back in this session — "
        "fix them before you stop (a commit would be refused the same way):\n" + out,
        file=sys.stderr,
    )
    return 2


# -------------------------------------------------------------------- cli


def main(argv: list[str]) -> int:
    """Command line of `claude-hook`: dispatch the hook named in argv, the event JSON on stdin."""
    if not argv or argv[0] in ("-h", "--help"):
        print((__doc__ or "").strip().splitlines()[0])
        print(
            "usage: claude-hook pre-run | post-change | stop   (hook event JSON on stdin)\n"
            "       claude-hook sessions [--run RUN_ID]"
        )
        return 0 if argv else 1
    if argv[0] == "sessions":
        return sessions(argv[1:])
    event = _read_event()
    if argv[0] == "pre-run":
        return pre_run(event)
    if argv[0] == "post-change":
        return post_change(event)
    if argv[0] == "stop":
        return stop(event)
    print(f"claude-hook: unknown event {argv[0]!r}", file=sys.stderr)
    return 1


def cli() -> None:
    """Console entry point of `claude-hook`."""
    console.exit_with(main)


if __name__ == "__main__":
    cli()
