"""labkit-hooks — install the hooks that make a lab repo use its own tools.

    labkit-hooks install [REPO]    write them (idempotent; other hooks kept)
    labkit-hooks check [REPO]      exit 1 when one is missing or from another labkit

The hooks come with the pinned labkit, so raising the pin and running
`install` again brings hooks that match the commands they call (2026-10-07;
before, the scaffolder in the house dotfiles wrote its own copy once, and
existing repos never got a newer one).

    .githooks/pre-commit     protocol-check on staged protocols; finalize
                             --if-reported on a written-back answer; the
                             shim guard test where a repo has it; then the
                             repo's own .githooks/pre-commit.local, if any
                             (the repo owns it, labkit-hooks never writes it)
    git core.hooksPath       set to .githooks (it used to be a manual step
                             per clone, and the hook silently did nothing)
    .claude/settings.json    claude-hook pre-run · post-change · stop

Each hook names the labkit version that wrote it; `check` compares.
"""

from __future__ import annotations

import json

from labkit import console
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from labkit.repo import git_root, git_run

MARK = "# installed by labkit-hooks"


def labkit_version() -> str:
    """The installed labkit's version, or "unknown" outside an installed package."""
    try:
        return version("labkit")
    except PackageNotFoundError:
        return "unknown"


def pre_commit() -> str:
    """The pre-commit script of this labkit version."""
    return f"""#!/bin/sh
{MARK} {labkit_version()} — reinstall: .venv/bin/labkit-hooks install
# Escape hatch for a deliberate exception: git commit --no-verify

fail=0
staged_protocols=$(git diff --cached --name-only --diff-filter=ACMR | grep -E '(^|/)PROTOCOL-[^/]*\\.md$')

# 1. Mandatory fields on every staged protocol.
if [ -n "$staged_protocols" ]; then
    if [ ! -x .venv/bin/protocol-check ]; then
        echo "pre-commit: .venv/bin/protocol-check missing — install labkit into .venv"
        echo "(.venv/bin/pip install -r requirements.txt)."
        fail=1
    # shellcheck disable=SC2086 # word-splitting over the file list is intended
    elif ! .venv/bin/protocol-check $staged_protocols; then
        echo ""
        echo "pre-commit: must fields missing (see above) — fill them, or justify as"
        echo "'<field>: n/a — <why>'."
        fail=1
    fi
fi

# 2. A number written back: a staged protocol whose answer cites a run goes
#    through finalize — it must hold, and cite the run the checks hold.
if [ -n "$staged_protocols" ] && [ -x .venv/bin/finalize ]; then
    # shellcheck disable=SC2086
    if ! .venv/bin/finalize --if-reported $staged_protocols; then
        echo ""
        echo "pre-commit: finalize reports blockers for a written-back number (see above)."
        fail=1
    fi
fi

# 3. Guard test, where a repo has it: the shared helpers resolve to labkit.
if [ -f tests/test_shared_helpers_come_from_labkit.py ] && [ -x .venv/bin/python ]; then
    out=$(.venv/bin/python -m unittest discover -s tests -p "test_shared_helpers_come_from_labkit.py" 2>&1) || {{
        echo "$out"
        echo ""
        echo "pre-commit: guard test fails (does something shadow the labkit package?)."
        fail=1
    }}
fi

# 4. The repo's own checks: .githooks/pre-commit.local belongs to the repo
#    and is never written by labkit-hooks (uniagent, 2026-10-07: a replay
#    test of its runs lived in the hook and an install would have erased it).
if [ -x .githooks/pre-commit.local ]; then
    .githooks/pre-commit.local || fail=1
fi

exit $fail
"""


def _hook(name: str, timeout: int, message: str) -> dict:
    return {
        "type": "command",
        "command": f'"${{CLAUDE_PROJECT_DIR:-.}}/.venv/bin/claude-hook" {name}',
        "timeout": timeout,
        "statusMessage": f"claude-hook {name}: {message}",
    }


#: event -> (matcher or None, hook)
CLAUDE_HOOKS = {
    "PreToolUse": ("Bash", _hook("pre-run", 120, "preflight before a run")),
    "PostToolUse": ("Bash|Write|Edit", _hook("post-change", 60, "check what changed")),
    "Stop": (None, _hook("stop", 120, "finalize a written-back number")),
}


#: a hook command that calls one of these was written by a labkit install —
#: this version's or an earlier one (uniagent 2026-10-10: a jq one-liner
#: running `protocol-check` on every PROTOCOL write survived three installs
#: and doubled every report beside `claude-hook post-change`)
LABKIT_COMMANDS = ("claude-hook", "protocol-check", "notes-check")


def _ours(entry: dict) -> bool:
    return any(
        cmd in h.get("command", "")
        for h in entry.get("hooks", [])
        for cmd in LABKIT_COMMANDS
    )


def stale_entries(current: dict) -> list[str]:
    """Every hook in `current` a labkit install wrote that is not this
    version's — one line per hook: event and the command's first 70 chars."""
    wanted = {json.dumps(hook, sort_keys=True) for _, hook in CLAUDE_HOOKS.values()}
    out = []
    for event, entries in (current.get("hooks") or {}).items():
        for entry in entries:
            if not _ours(entry):
                continue
            for h in entry.get("hooks", []):
                if json.dumps(h, sort_keys=True) not in wanted:
                    out.append(f"{event}: {h.get('command', '')[:70]}")
    return out


def merged_settings(current: dict) -> dict:
    """`current` with labkit's hooks — this version's and any earlier
    install's (`LABKIT_COMMANDS`) — replaced by this version's; every other
    key and every foreign hook kept."""
    out = dict(current)
    hooks = {
        event: [e for e in entries if not _ours(e)]
        for event, entries in (out.get("hooks") or {}).items()
    }
    hooks = {event: entries for event, entries in hooks.items() if entries}
    for event, (matcher, hook) in CLAUDE_HOOKS.items():
        entry: dict = {"hooks": [hook]}
        if matcher:
            entry = {"matcher": matcher, **entry}
        hooks[event] = hooks.get(event, []) + [entry]
    out["hooks"] = hooks
    return out


def _settings(repo: Path) -> tuple[Path, dict]:
    path = repo / ".claude" / "settings.json"
    if not path.is_file():
        return path, {}
    try:
        return path, json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"labkit-hooks: {path} is not valid JSON ({exc}) — repair it first"
        )


def install(repo: Path) -> list[str]:
    """Write the hooks; returns what was done."""
    done = []
    hook = repo / ".githooks" / "pre-commit"
    hook.parent.mkdir(exist_ok=True)
    text = pre_commit()
    if hook.is_file() and MARK not in hook.read_text(encoding="utf-8"):
        # A hook labkit did not write may carry the repo's own checks:
        # kept beside, never erased in silence.
        kept = hook.with_name("pre-commit.before-labkit")
        if kept.exists():
            raise SystemExit(
                f"labkit-hooks: {hook} was not written by labkit-hooks and "
                f"{kept.name} exists already — move the repo's own steps to "
                f".githooks/pre-commit.local, remove {kept.name}, run install again"
            )
        hook.rename(kept)
        done.append(
            f"kept the previous hook as {kept.relative_to(repo)} — move its "
            f"repo-specific steps to .githooks/pre-commit.local (executable)"
        )
    if not hook.is_file() or hook.read_text(encoding="utf-8") != text:
        hook.write_text(text, encoding="utf-8")
        done.append(f"wrote {hook.relative_to(repo)}")
    hook.chmod(hook.stat().st_mode | 0o755)
    r = git_run(["config", "core.hooksPath", ".githooks"], repo)
    if r.returncode != 0:
        raise SystemExit(
            f"labkit-hooks: git config failed in {repo}: {r.stderr.strip()}"
        )
    done.append("git core.hooksPath = .githooks")
    path, current = _settings(repo)
    wanted = merged_settings(current)
    if wanted != current:
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(wanted, indent=2) + "\n", encoding="utf-8")
        done.append(
            f"wrote {path.relative_to(repo)} (claude-hook pre-run · post-change · stop)"
        )
    return done


def check(repo: Path) -> list[str]:
    """What is missing or from another labkit version; empty means installed."""
    out = []
    hook = repo / ".githooks" / "pre-commit"
    if not hook.is_file():
        out.append(".githooks/pre-commit is missing")
    elif hook.read_text(encoding="utf-8") != pre_commit():
        first = next(
            (
                ln
                for ln in hook.read_text(encoding="utf-8").splitlines()
                if ln.startswith(MARK)
            ),
            "",
        )
        was = first.removeprefix(MARK).split("—")[0].strip()
        out.append(
            f".githooks/pre-commit is from labkit {was}, this labkit is {labkit_version()}"
            if was
            else ".githooks/pre-commit was not written by labkit-hooks"
        )
    r = git_run(["config", "--get", "core.hooksPath"], repo)
    if r.stdout.strip() != ".githooks":
        out.append(
            "git core.hooksPath is not .githooks — the pre-commit hook never runs"
        )
    _, current = _settings(repo)
    stale = stale_entries(current)
    for line in stale:
        out.append(f".claude/settings.json: a hook from an earlier labkit — {line}")
    if not stale and merged_settings(current) != current:
        out.append(".claude/settings.json lacks this labkit's claude-hook entries")
    return out


def main(argv: list[str]) -> int:
    """Command line of `labkit-hooks`: install or check a repo's git hooks."""
    if not argv or argv[0] in ("-h", "--help"):
        print((__doc__ or "").strip().splitlines()[0])
        print("usage: labkit-hooks install [REPO] | check [REPO]")
        return 0 if argv else 2
    cmd, where = argv[0], Path(argv[1]) if len(argv) > 1 else Path(".")
    repo = git_root(where)
    if repo is None:
        print(f"labkit-hooks: {where} is not inside a git repo")
        return 2
    if cmd == "install":
        for line in install(repo):
            print(f"labkit-hooks: {line}")
        return 0
    if cmd == "check":
        gaps = check(repo)
        for g in gaps:
            print(f"labkit-hooks: {g}")
        if gaps:
            print("labkit-hooks: fix with  .venv/bin/labkit-hooks install")
        return 1 if gaps else 0
    print(f"labkit-hooks: unknown command {cmd!r}")
    return 2


def cli() -> None:
    """Entry point for the installed `labkit-hooks` command."""
    console.exit_with(main)


if __name__ == "__main__":
    cli()
