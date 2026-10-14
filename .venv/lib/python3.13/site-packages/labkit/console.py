"""console — the one exit of every labkit command line.

`exit_with(main)` calls `main(sys.argv[1:])` and exits with its code. A reader
that closes the pipe early (`protocol-check --contract P | head`) raises
BrokenPipeError inside print or at the interpreter's final flush; Python
then prints a traceback and exits 120, which a cloud agent read as a crash
of the command (Haiku 5.5, 2026-10-13). A closed pipe is the reader's
choice, not an error of ours: stdout is pointed at /dev/null so the final
flush cannot raise, and the exit code is 0.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable


def exit_with(main: Callable[[list[str]], int]) -> None:
    """Exit with `main(argv)`'s code; a pipe closed by the reader is exit 0."""
    try:
        code = main(sys.argv[1:])
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        code = 0
    sys.exit(code)
