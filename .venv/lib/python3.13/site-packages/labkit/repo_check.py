"""labkit-check — is this lab repo on the labkit it pins, and is the pin current?

    .venv/bin/labkit-check [REPO] [--offline]

Five lines, one question each, every line ending in OK, STALE or what could
not be decided; the reference problems follow, one per line. Exit 0 when
every line is OK, 1 when any is STALE, 2 when a line could not be decided
(no pin, a source that cannot be read).

    pin        requirements.txt and requirements.lock: v0.84.0 from git+file:///…/labkit   OK
    installed  0.84.0                                                                        OK
    latest     v0.84.0 at /…/labkit                                                          OK
    hook       .githooks/pre-commit from labkit 0.79.0, this labkit is 0.84.0                STALE — .venv/bin/labkit-hooks install
    refs       0 problem(s) in 212 file(s)                                                   OK

It reports and changes nothing: the pin is raised on purpose (the
requirements line `labkit-init` writes says so), never by this command.
`installed` is the labkit this command runs from, so run it from the repo's
venv. A lock that names the commit its requirements tag points at (what
`pip freeze` writes) is the same pin: `pin` resolves the tag at the source
and compares commits. `latest` reads the source the pin names — a local path with `git tag`,
a remote with `git ls-remote --tags` (network; `--offline` skips it).
`refs` holds every `.md` and `.py` outside `.git`, `.venv`, `runs/` and
`data/` to the packaged ledger (`python -m labkit.rules refs`) — except the
areas that are records: a frozen protocol is a registration, a protocol this
labkit cannot read was written under an older pin, and both keep the
identifiers they were written with; the line says how many areas it left out.

The three checks it bundles exist on their own (`labkit-hooks check`,
`python -m labkit.rules refs`, the pin line in `requirements.txt`); what was
missing was one command that asks all of them, plus the two nobody asked:
installed against pinned, pinned against the newest tag (2026-10-12: in all
four active lab repos the installed labkit lagged the pin).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from labkit import console, install_hooks, protocol_block, rules
from labkit.repo import VCS_REQUIREMENT, VERSION_REQUIREMENT, git_run, requirement_lines

PIN_FILES = ("requirements.txt", "requirements.lock")
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
PYPROJECT_VERSION_RE = re.compile(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', re.M)
SKIP_DIRS = frozenset({".git", ".venv", "node_modules", "__pycache__", "runs", "data"})
REMOTE_TIMEOUT_S = 15.0

OK, STALE, UNDECIDED = 0, 1, 2


@dataclass(frozen=True)
class Pin:
    """One `labkit` line of a requirements file: where from, which ref."""

    file: str
    source: str  # `git+file:///path` or `git+https://…`, or "" for `labkit==X.Y.Z`
    ref: str  # a tag `vX.Y.Z`, a commit, or the version of a `==` pin

    @property
    def version(self) -> str | None:
        """The version the ref names, None for a commit."""
        if (m := TAG_RE.match(self.ref)) is not None:
            return ".".join(m.groups())
        return self.ref if re.fullmatch(r"\d+\.\d+\.\d+", self.ref) else None

    @property
    def local_path(self) -> Path | None:
        """The checkout a `git+file://` source names, None for a remote."""
        if self.source.startswith("git+file://"):
            return Path(self.source.removeprefix("git+file://"))
        return None


def version_tuple(version: str) -> tuple[int, ...]:
    """ "0.10.2" → (0, 10, 2) — tags compare numerically, never as strings."""
    if not re.fullmatch(r"\d+(\.\d+)*", version):
        raise ValueError(f"not a version: {version!r}")
    return tuple(int(x) for x in version.split("."))


def read_pins(repo: Path) -> list[Pin]:
    """The labkit pin of every requirements file in REPO that has one.

    A `labkit` line that is neither `labkit @ git+…@ref` nor `labkit==X.Y.Z`
    raises, naming the file: a pin nobody can read is not "no pin".
    """
    pins = []
    for name in PIN_FILES:
        path = repo / name
        if not path.is_file():
            continue
        for line in requirement_lines(path.read_text(encoding="utf-8"), "labkit"):
            if (m := VCS_REQUIREMENT.match(line)) is not None and m.group("ref"):
                pins.append(Pin(name, "git+" + m.group("url"), m.group("ref")))
            elif (m := VERSION_REQUIREMENT.match(line)) is not None:
                pins.append(Pin(name, "", m.group("version")))
            else:
                raise ValueError(
                    f"{name}: the labkit line is not a pin I can read: {line.strip()!r} "
                    "(expected `labkit @ git+<source>@<tag or commit>` or `labkit==X.Y.Z`)"
                )
    return pins


def pinned_version(pin: Pin, cwd: Path) -> str | None:
    """The version PIN names: from the tag, or from pyproject.toml at the
    commit when the source is a local checkout; None when unreadable offline."""
    if pin.version is not None:
        return pin.version
    path = pin.local_path
    if path is None:
        return None
    r = git_run(["-C", str(path), "show", f"{pin.ref}:pyproject.toml"], cwd)
    if r.returncode != 0:
        raise RuntimeError(
            f"{path}: cannot read pyproject.toml at {pin.ref}: {r.stderr.strip()}"
        )
    m = PYPROJECT_VERSION_RE.search(r.stdout)
    if m is None:
        raise RuntimeError(f"{path}: pyproject.toml at {pin.ref} has no version line")
    return m.group(1)


def latest_tag(pin: Pin, cwd: Path, timeout: float = REMOTE_TIMEOUT_S) -> str | None:
    """The newest release tag `vX.Y.Z` at PIN's source, None when it has none.
    A local checkout is read with `git tag`, a remote with `git ls-remote`."""
    path = pin.local_path
    if path is not None:
        r = git_run(["-C", str(path), "tag", "--list", "v*"], cwd)
        where = str(path)
    else:
        r = git_run(
            ["ls-remote", "--tags", pin.source.removeprefix("git+")], cwd, timeout
        )
        where = pin.source
    if r.returncode != 0:
        raise RuntimeError(f"{where}: {r.stderr.strip() or 'git failed'}")
    tags = [
        line.rsplit("/", 1)[-1].removesuffix("^{}")
        for line in r.stdout.split()
        if "/" in line or TAG_RE.match(line)
    ]
    versions = [t for t in set(tags) if TAG_RE.match(t)]
    if not versions:
        return None
    return max(versions, key=lambda t: version_tuple(t[1:]))


def tag_commit(pin: Pin, cwd: Path, timeout: float = REMOTE_TIMEOUT_S) -> str:
    """The commit PIN's tag points at, read at the pin's source: a local
    checkout with `git rev-parse`, a remote with `git ls-remote` (an
    annotated tag peeled to its commit).

    Raises:
        RuntimeError: The source cannot be read or has no such tag.
    """
    path = pin.local_path
    if path is not None:
        r = git_run(["-C", str(path), "rev-parse", f"{pin.ref}^{{commit}}"], cwd)
        where = str(path)
    else:
        ref = f"refs/tags/{pin.ref}"
        r = git_run(
            ["ls-remote", pin.source.removeprefix("git+"), ref, ref + "^{}"],
            cwd,
            timeout,
        )
        where = pin.source
    if r.returncode != 0:
        raise RuntimeError(f"{where}: {r.stderr.strip() or 'git failed'}")
    if path is not None:
        return r.stdout.strip()
    found = {
        ref: sha for sha, ref in (line.split("\t") for line in r.stdout.splitlines())
    }
    commit = found.get(f"refs/tags/{pin.ref}^{{}}") or found.get(f"refs/tags/{pin.ref}")
    if commit is None:
        raise RuntimeError(f"{where}: no tag {pin.ref}")
    return commit


def record_areas(repo: Path) -> list[Path]:
    """The areas `refs` does not read: an area whose protocol is frozen is a
    registration, one whose protocol this labkit cannot read (an older
    standard, a prose head) was written under an older pin — both keep the
    identifiers they were written with (CHANGELOG 0.82.0)."""
    out = set()
    for proto in sorted(repo.rglob("PROTOCOL-*.md")):
        if SKIP_DIRS & set(proto.relative_to(repo).parts):
            continue
        try:
            frozen = protocol_block.head(proto.read_text(encoding="utf-8")).frozen
        except protocol_block.BlockError:
            frozen = True
        if frozen:
            out.add(proto.parent)
    return sorted(out)


def ref_problems(repo: Path) -> tuple[int, int, list[str]]:
    """Every `.md` and `.py` of REPO outside SKIP_DIRS and the record areas,
    held to the packaged ledger: (files read, record areas skipped,
    problems) — see `rules.check_refs`."""
    rows = rules.load_registry(rules.REGISTRY)
    records = record_areas(repo)
    files = sorted(
        f
        for f in repo.rglob("*")
        if f.is_file()
        and f.suffix in (".md", ".py")
        and not (SKIP_DIRS & set(f.relative_to(repo).parts))
        and not any(f.is_relative_to(a) for a in records)
    )
    problems: list[str] = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        problems += rules.check_refs(str(f.relative_to(repo)), text, rows)
    return len(files), len(records), problems


@dataclass(frozen=True)
class Line:
    """One answer of the report: LABEL, WHAT was found, the STATE, a HINT on
    STALE/UNDECIDED, and EXTRA lines printed under it (the reference problems)."""

    label: str
    what: str
    state: int
    hint: str = ""
    extra: tuple[str, ...] = ()

    def __str__(self) -> str:
        verdict = {OK: "OK", STALE: "STALE", UNDECIDED: "UNDECIDED"}[self.state]
        tail = f" — {self.hint}" if self.hint else ""
        return f"{self.label:<10} {self.what:<70} {verdict}{tail}"


def same_pin(pins: list[Pin], cwd: Path, offline: bool) -> Line | None:
    """`pin` when the two files differ only in spelling: requirements.txt
    names a tag, the lock (from `pip freeze`) the commit that tag points at,
    both from one source. None when the pins are not of that shape or the
    commits differ — then they are two pins."""
    tags = [p for p in pins if p.version is not None and TAG_RE.match(p.ref)]
    commits = [p for p in pins if p.version is None]
    if len(tags) != 1 or len(commits) != 1 or tags[0].source != commits[0].source:
        return None
    tag, commit = tags[0], commits[0]
    what = f"{tag.file} {tag.ref}, {commit.file} {commit.ref[:12]} from {tag.source}"
    if offline and tag.local_path is None:
        return Line("pin", what, UNDECIDED, f"{tag.source} not asked (--offline)")
    try:
        resolved = tag_commit(tag, cwd)
    except RuntimeError as exc:
        return Line("pin", what, UNDECIDED, str(exc))
    if resolved != commit.ref:
        return None
    return Line(
        "pin",
        f"{tag.file} and {commit.file}: {tag.ref} (lock: its commit "
        f"{commit.ref[:12]}) from {tag.source}",
        OK,
    )


def pin_line(pins: list[Pin], cwd: Path, offline: bool = False) -> Line:
    """`pin`: the one labkit pin, or why there is none to work with."""
    if not pins:
        return Line(
            "pin",
            "no labkit line in requirements.txt or requirements.lock",
            UNDECIDED,
            "pin labkit (labkit-init writes the line)",
        )
    if len({p.ref for p in pins}) > 1:
        if (same := same_pin(pins, cwd, offline)) is not None:
            return same
        return Line(
            "pin",
            "; ".join(f"{p.file} pins {p.ref}" for p in pins),
            STALE,
            ".venv/bin/pip install -r requirements.txt, then lock",
        )
    pin = pins[0]
    files = " and ".join(p.file for p in pins)
    origin = f" from {pin.source}" if pin.source else ""
    if pin.version is None:
        return Line(
            "pin",
            f"{files}: commit {pin.ref[:12]}{origin}",
            STALE,
            "pin a release tag (vX.Y.Z), not a commit",
        )
    return Line("pin", f"{files}: {pin.ref}{origin}", OK)


def installed_line(pin: Pin | None, want: str | None, installed: str) -> Line:
    """`installed`: this labkit against the version the pin names (WANT)."""
    if pin is None:
        return Line("installed", installed, UNDECIDED, "nothing to compare with")
    if want is None:
        return Line(
            "installed",
            installed,
            UNDECIDED,
            f"the pinned commit's version is not readable from {pin.source}",
        )
    if installed == want:
        return Line("installed", installed, OK)
    return Line(
        "installed",
        f"{installed}, the pin says {want}",
        STALE,
        ".venv/bin/pip install -r requirements.txt",
    )


def latest_line(pin: Pin | None, want: str | None, cwd: Path, offline: bool) -> Line:
    """`latest`: the newest release tag at the pin's source against WANT."""
    if pin is None or not pin.source:
        return Line("latest", "no source to ask", UNDECIDED)
    if offline and pin.local_path is None:
        return Line("latest", f"{pin.source} not asked (--offline)", UNDECIDED)
    try:
        newest = latest_tag(pin, cwd)
    except RuntimeError as exc:
        return Line("latest", str(exc), UNDECIDED)
    where = pin.local_path or pin.source
    if newest is None:
        return Line("latest", f"no release tag at {where}", UNDECIDED)
    if want is not None and version_tuple(newest[1:]) > version_tuple(want):
        return Line(
            "latest",
            f"{newest} at {where}, the pin says {want}",
            STALE,
            "raise the pin on purpose (CHANGELOG first)",
        )
    return Line("latest", f"{newest} at {where}", OK)


def hook_line(repo: Path, installed: str) -> Line:
    """`hook`: what `labkit-hooks check` says."""
    hook = install_hooks.check(repo)
    if hook:
        more = f" (+{len(hook) - 1} more)" if len(hook) > 1 else ""
        return Line("hook", hook[0] + more, STALE, ".venv/bin/labkit-hooks install")
    return Line("hook", f".githooks/pre-commit from labkit {installed}", OK)


def refs_line(repo: Path) -> Line:
    """`refs`: every rule reference in the repo's living files, the problems under it."""
    n_files, n_records, problems = ref_problems(repo)
    skipped = f"; {n_records} frozen or older area(s) not read" if n_records else ""
    if problems:
        return Line(
            "refs",
            f"{len(problems)} problem(s) in {n_files} file(s){skipped}",
            STALE,
            "write the id with its name (python -m labkit.rules refs)",
            tuple(f"    {p}" for p in problems),
        )
    return Line("refs", f"0 problem(s) in {n_files} file(s){skipped}", OK)


def check_repo(repo: Path, offline: bool = False) -> tuple[list[str], int]:
    """The five lines (plus reference problems) and the exit code — see the module docstring."""
    pins = read_pins(repo)
    pin = pins[0] if pins else None
    want = pinned_version(pin, repo) if pin is not None else None
    installed = install_hooks.labkit_version()
    answers = [
        pin_line(pins, repo, offline),
        installed_line(pin, want, installed),
        latest_line(pin, want, repo, offline),
        hook_line(repo, installed),
        refs_line(repo),
    ]
    lines = [s for a in answers for s in (str(a), *a.extra)]
    return lines, max(a.state for a in answers)


def main(argv: list[str]) -> int:
    """`labkit-check [REPO] [--offline]` — print the report, exit with its worst state."""
    ap = argparse.ArgumentParser(
        prog="labkit-check", description=(__doc__ or "").split("\n\n")[0]
    )
    ap.add_argument("repo", nargs="?", type=Path, default=Path("."))
    ap.add_argument(
        "--offline", action="store_true", help="do not ask a remote source for its tags"
    )
    a = ap.parse_args(argv)
    repo = a.repo.resolve()
    if not repo.is_dir():
        print(f"labkit-check: {repo} is not a directory", file=sys.stderr)
        return UNDECIDED
    lines, code = check_repo(repo, offline=a.offline)
    print("\n".join(lines))
    return code


def cli() -> None:
    """Entry point for the installed `labkit-check` command."""
    console.exit_with(main)


if __name__ == "__main__":
    cli()
