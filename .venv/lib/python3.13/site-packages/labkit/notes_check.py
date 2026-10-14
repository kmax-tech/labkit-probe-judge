#!/usr/bin/env python3
"""Check notes/messung/ notes for the declared kind in the meta line.

Every note under notes/messung/ carries a *kind* in its italic meta line,
right after the purpose (LAB-082 In `notes/messung/`):

    Instrument — Entwurf        draft of a measurement instrument, no code yet
    Instrument — implementiert  instrument with carrying code (MUST name it)
    Related-Lesart (<citekey>)  lab reading of a paper against our findings
    Referenzkarte               glossary, register, terminology, source map
    Audit                       design/preflight audit written as a note

The kind is DECLARED, never derived from code mentions: a Referenzkarte can
name dozens of scripts, a draft can cite a prior area's code (found 2026-09-10
across 55 notes: 4 notes naming .py files were drafts, the note naming the
most scripts was a glossary). The checker therefore only verifies presence
and inconsistency, not classification:

  MUST  meta line present (an italic paragraph after the title; a limitation
        blockquote BEFORE it is fine — the Befundregister reads exactly that)
  MUST  kind declared in the meta line; the contract regex is tolerant to
        dash variants:  Instrument\\s*[—–-]\\s*(Entwurf|implementiert)
  MUST  'Instrument — implementiert' names code (a .py file, a function
        call, or an experiments/ path) somewhere in the note
  warn  date in the meta line (YYYY-MM-DD or YYYY-MM)
  warn  a file named related-*.md declares Related-Lesart with a citekey
  warn  an implementiert note whose named .py files all fail to resolve
        inside the repo (code paths rot; resolution is best-effort v1 —
        bare filenames are searched repo-wide, paths relative to the root)

Usage:
    notes-check <repo-root | notes-dir | note.md> ...

Directories are searched for notes/messung/*.md (a path already ending in
messung/ is taken as the notes dir itself; 00-*.md index files are skipped).
Exit 1 if any MUST check fails. Patterns follow the protocol-check contract
doctrine: extend, never move; regression = both lab repos exit 0 after the
2026-09-10 retro-stamp.
"""

import re

from labkit import console
from pathlib import Path

# The contract: kind tokens as they appear in meta lines. German on purpose —
# the notes are German and the tokens are greppable prose, not identifiers.
KIND = re.compile(
    r"Instrument\s*[—–-]\s*(Entwurf|implementiert)"
    r"|Related-Lesart|Referenzkarte|Audit"
)
IMPLEMENTED = re.compile(r"Instrument\s*[—–-]\s*implementiert")
RELATED_WITH_KEY = re.compile(r"Related-Lesart\s*\(([\w:-]+(?:\s*,\s*[\w:-]+)*)\)")
DATE = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b")
# Code evidence for an implemented instrument: a script file, a bare function
# call in backticks, an experiment-area path, or a protocol reference (the
# protocol names the scripts; a synthesis note over documented runs carries only
# that — found 2026-09-10, instrument-mal-modellstaerke).
CODE = re.compile(
    r"[\w./-]+\.py\b|experiments/[\w-]+|`\w+\(\)?`"
    r"|PROTOCOL-[\w-]+"
)
PY_FILE = re.compile(r"[\w./-]+\.py\b")


def meta_paragraph(text: str) -> tuple[int, str] | None:
    """(line number, joined text) of the italic meta paragraph, or None.

    The meta line is the first content paragraph after the `# ` title that
    starts with a single `*`. Blank lines and a leading limitation blockquote
    (`> ...`) are skipped. The paragraph runs to the next blank line (meta
    lines wrap over 2-10 physical lines in the wild).
    """
    lines = text.splitlines()
    i = 0
    # skip up to the title
    while i < len(lines) and not lines[i].startswith("# "):
        i += 1
    i += 1
    while i < len(lines):
        s = lines[i].strip()
        if not s or s.startswith(">"):
            i += 1
            continue
        if s.startswith("*") and not s.startswith("**"):
            start = i
            para = []
            while i < len(lines) and lines[i].strip():
                para.append(lines[i].strip())
                i += 1
            return start + 1, " ".join(para)
        return None
    return None


def repo_root(path: Path) -> Path | None:
    """The nearest directory above `path` that holds a `.git`, or None."""
    for parent in [path, *path.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def unresolved_scripts(text: str, root: Path | None) -> list[str]:
    """Named .py files that cannot be found in the repo (best effort)."""
    if root is None:
        return []
    missing = []
    for name in sorted({m.group(0).lstrip("./") for m in PY_FILE.finditer(text)}):
        p = Path(name)
        if (root / p).exists():
            continue
        if next(root.rglob(p.name), None) is None:
            missing.append(name)
    return missing


def collect_notes(paths: list[str]) -> list[Path]:
    """The measurement notes the arguments name: notes under `notes/messung/` of a repo or directory, or the files given."""
    files: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            base = p if p.name == "messung" else p / "notes" / "messung"
            files.extend(
                f for f in sorted(base.glob("*.md")) if not f.name.startswith("00-")
            )
        else:
            files.append(p)
    return files


def check_file(f: Path) -> tuple[list[str], list[str]]:
    """Return (must_failures, warnings) as printable lines for one note."""
    must, warn = [], []
    text = f.read_text(encoding="utf-8")
    meta = meta_paragraph(text)
    if meta is None:
        must.append(
            f"{f}:1: MISSING (must): no italic meta line after the "
            f"title (*<Zweck> · <Sorte> · … · <Datum>*)"
        )
        return must, warn
    n, para = meta
    kind = KIND.search(para)
    if not kind:
        must.append(
            f"{f}:{n}: MISSING (must): no kind in the meta line "
            f"(Instrument — Entwurf|implementiert · Related-Lesart "
            f"· Referenzkarte · Audit)"
        )
    if not DATE.search(para):
        warn.append(f"{f}:{n}: warning: no date in the meta line")
    if IMPLEMENTED.search(para):
        if not CODE.search(text):
            must.append(
                f"{f}:{n}: MISSING (must): declared 'Instrument — "
                f"implementiert' but names no script, function, or "
                f"experiments/ path"
            )
        else:
            rotten = unresolved_scripts(text, repo_root(f.resolve()))
            if rotten and len(rotten) == len(
                set(m.group(0).lstrip("./") for m in PY_FILE.finditer(text))
            ):
                warn.append(
                    f"{f}:{n}: warning: none of the named scripts "
                    f"resolve in the repo ({', '.join(rotten[:3])}"
                    f"{' …' if len(rotten) > 3 else ''}) — code "
                    f"paths may have rotted"
                )
    if f.name.startswith("related-"):
        if kind and "Related-Lesart" not in kind.group(0):
            warn.append(
                f"{f}:{n}: warning: filename says related-* but the "
                f"declared kind is {kind.group(0)!r}"
            )
        elif "Related-Lesart" in para and not RELATED_WITH_KEY.search(para):
            warn.append(
                f"{f}:{n}: warning: Related-Lesart without a citekey "
                f"— write 'Related-Lesart (<citekey>)'"
            )
    return must, warn


def main(argv: list[str]) -> int:
    """Command line of `notes-check`: check the measurement notes named in argv."""
    if not argv or argv[0] in ("-h", "--help"):
        print((__doc__ or "").strip().splitlines()[0])
        print("usage: notes-check <repo-root | notes-dir | note.md> ...")
        return 0 if argv else 2
    files = collect_notes(argv)
    if not files:
        print("notes-check: no notes/messung/*.md found")
        return 2
    failed = False
    for f in files:
        try:
            must, warn = check_file(f)
        except OSError as exc:
            print(f"{f}: not readable ({exc})")
            failed = True
            continue
        for line in must + warn:
            print(line)
        if must:
            failed = True
        elif not warn:
            print(f"{f}: OK")
    return 1 if failed else 0


def cli() -> None:
    """Entry point for the installed `notes-check` command."""
    console.exit_with(main)


if __name__ == "__main__":
    cli()
