"""repo — where things are: repo root, an area's protocols, git.

Small questions every gate asks, answered once. Before 2026-10-06 they were
answered five times: each module globbed `PROTOCOL-*.md` itself, three
functions found the repo root by three different rules, and two private
`_git` helpers turned EVERY git failure into an empty string — so a git that
failed to run read as "working tree clean".

Two git calls, by what a non-zero exit means:

    git(args, cwd)      the output; None outside a repo; GitError otherwise
    git_run(args, cwd)  the completed process, for commands whose exit code
                        IS the answer (`ls-files --error-unmatch`,
                        `rev-parse --verify`, `show HEAD:path`)
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

GIT_TIMEOUT_S = 20

# --- requirement lines: the one grammar of a pin (four spellings before, audit 2026-10-13)
_PKG = r"(?P<name>[A-Za-z0-9][A-Za-z0-9._\-]*)"
#: `name @ git+<url>@<ref>` — a VCS pin; the ref is optional, a trailing `# comment` allowed
VCS_REQUIREMENT = re.compile(
    rf"^{_PKG}\s*@\s*git\+(?P<url>[^@\s#]+)(?:@(?P<ref>[^#\s]+))?\s*(?:#.*)?$"
)
#: `-e git+<url>@<ref>#egg=<name>` — how pip freezes an editable VCS install
EDITABLE_REQUIREMENT = re.compile(
    rf"^-e\s+git\+(?P<url>[^@\s#]+)@(?P<ref>[^#\s]+)#egg={_PKG}\s*$"
)
#: `-e /path/to/<name>` — how pip freezes an editable path install
EDITABLE_PATH_REQUIREMENT = re.compile(rf"^-e\s+(?P<path>\S*/{_PKG})/?\s*$")
#: `name==X.Y.Z` — a version pin
VERSION_REQUIREMENT = re.compile(rf"^{_PKG}\s*==\s*(?P<version>\d+\.\d+\.\d+)\s*$")


def requirement_name(line: str) -> str | None:
    """The package a requirements line names, as pip normalises it
    (lowercase, `_` to `-`): a VCS or editable pin, `name==…`, `name @ <url>`.
    None for a blank, a comment or a line of another shape."""
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    for pat in (VCS_REQUIREMENT, EDITABLE_REQUIREMENT, EDITABLE_PATH_REQUIREMENT):
        if (m := pat.match(s)) is not None:
            return m.group("name").lower().replace("_", "-")
    for sep in ("==", " @ "):
        if sep in s:
            return s.split(sep, 1)[0].strip().lower().replace("_", "-")
    return None


def requirement_lines(text: str, name: str) -> list[str]:
    """The lines of a requirements file (or `pip freeze` output) that name `name`."""
    return [ln.strip() for ln in text.splitlines() if requirement_name(ln) == name]


class GitError(RuntimeError):
    """git could not be run, or failed inside a repository."""


def area_path(arg: str) -> Path:
    """The area a command argument names: a directory as given, else the
    bare name as `labkit-init exp` prints it — `01-<name>` or `<name>` — under
    `experiments/` of the working directory or of its repository. Returns
    the argument unchanged when nothing (or more than one area) matches, so
    the caller's "no such area" still speaks (2026-10-07: two agents passed
    `01-docs-per-case` to code-check and were refused)."""
    given = Path(arg)
    if given.is_dir() or given.is_absolute() or "/" in arg:
        return given
    hits: set[Path] = set()
    for base in {Path.cwd(), git_root(Path.cwd()) or Path.cwd()}:
        exp = base / "experiments"
        if (exp / arg).is_dir():
            hits.add((exp / arg).resolve())
        hits.update(p.resolve() for p in exp.glob(f"[0-9]*-{arg}") if p.is_dir())
    return hits.pop() if len(hits) == 1 else given


def no_such_area(area: Path) -> str:
    """The sentence for an area path that is not a directory. A relative
    path resolves against the working directory, so the sentence names it
    (2026-10-07: an agent called code-check from inside the area with the
    repo-relative path and tried four spellings)."""
    where = "" if area.is_absolute() else f" (relative to {Path.cwd()})"
    return (
        f"no such area: {area}{where} — give the area's path or its name "
        f"as `labkit-init exp` printed it (01-<name>)"
    )


def area_protocols(area: Path) -> list[Path]:
    """Every protocol in the area (`PROTOCOL-*.md` directly in it),
    lexicographic — a list, not a first hit.

    The series rule gives every follow-up its own `PROTOCOL-s<N>-<slug>.md`,
    so an area legitimately holds many. Returning `sorted(...)[0]` picked
    one of them wordlessly, and lexicographic order is not temporal order:
    in an area running s1..s13 the pick was always s1. A green check against
    the wrong protocol is worse than no check, so the caller must choose
    (2026-09-26).
    """
    return sorted(area.glob("PROTOCOL-*.md"))


def git_root(path: Path) -> Path | None:
    """The nearest ancestor (or `path`) holding `.git`; None outside a repo."""
    base = path if path.is_dir() else path.parent
    for parent in [base.resolve(), *base.resolve().parents]:
        if (parent / ".git").exists():
            return parent
    return None


def layout_root(path: Path) -> Path:
    """Where an area's repo layout starts: the git root, else the nearest
    ancestor with `CLAUDE.md` or `tests/` (a freshly stamped tree before
    `git init`), else `path` itself."""
    root = git_root(path)
    if root is not None:
        return root
    base = (path if path.is_dir() else path.parent).resolve()  # "." has no parents
    for parent in [base, *base.parents]:
        if (parent / "CLAUDE.md").is_file() or (parent / "tests").is_dir():
            return parent
    return base


def git_run(
    args: list[str], cwd: Path, timeout: float = GIT_TIMEOUT_S
) -> subprocess.CompletedProcess[str]:
    """Run git; the caller reads the exit code. Raises GitError only when
    git itself cannot run (missing binary, timeout)."""
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError(f"git {' '.join(args)} in {cwd}: {exc}") from exc


def git(args: list[str], cwd: Path, timeout: float = GIT_TIMEOUT_S) -> str | None:
    """git's stripped output; None when `cwd` is not inside a repository.

    Any other failure raises GitError with git's own message — an empty
    string here used to mean "clean" whether or not git had run.
    """
    if git_root(cwd) is None:
        return None
    r = git_run(args, cwd, timeout)
    if r.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} in {cwd} failed "
            f"(exit {r.returncode}): {r.stderr.strip()}"
        )
    return r.stdout.strip()


class ProtocolChoiceError(ValueError):
    """No protocol to hold the area to: none named and none or several there."""


def the_protocol(area: Path, protocol: Path | None) -> Path:
    """The protocol a command holds the area to: the named one, else the
    area's only one. Raises ProtocolChoiceError (the message says why and
    lists the candidates) when there is none, or several and none is named
    — a gate never guesses. `choose_protocol` is the printing form."""
    if protocol is not None:
        if not protocol.is_file():
            raise ProtocolChoiceError(f"no such protocol: {protocol}")
        return protocol
    protocols = area_protocols(area)
    if not protocols:
        raise ProtocolChoiceError(f"no PROTOCOL-*.md in {area}")
    if len(protocols) > 1:
        raise ProtocolChoiceError(
            f"{len(protocols)} protocols in {area} — name one with --protocol FILE:\n"
            + "\n".join(f"  {p}" for p in protocols)
        )
    return protocols[0]


def choose_protocol(area: Path, protocol: Path | None, tool: str) -> Path | None:
    """`the_protocol` for a command line: prints why (prefixed with `tool`)
    and returns None instead of raising."""
    try:
        return the_protocol(area, protocol)
    except ProtocolChoiceError as exc:
        print(f"{tool}: {exc}")
        return None
