"""One alias at a time per serving endpoint — the lock that batch.Store isn't.

A serving endpoint is a GPU slot, not a service. On a swap proxy several
aliases resolve to the same slot: asking for an alias that is not loaded
unloads the running model and loads the wanted one (measured 2026-09-08:
~5 minutes per swap). Two stages against the same endpoint with DIFFERENT
aliases therefore do not run in parallel — they evict each other, over and
over.

Why this is a defect and not an inconvenience. The damage does not stay in
the wallclock; it arrives in a reported number:

    swap thrashing -> llm.complete runs into timeouts -> exhausted retries
    return empty answers -> rounds without a parsed mechanism -> the stop
    rule "more than 2 of 96 rounds empty => the parser is the finding"
    counts them

That rule then measures operational noise and calls it parser quality
(2026-09-08: a judge test fired next to a running probe did exactly this;
it was filed as an operator slip, which is what a missing interlock looks
like from the inside).

What was mistaken for protection: `batch.Store` takes a lock on the OUTPUT
FILE — it says nothing about who is using the model. And "stages stay
staggered" is a sentence in a protocol and a code comment, i.e. an
intention. Any second process breaks it: another terminal, another area, a
test fired alongside.

The rule here, in one line: **same alias may share, a different alias is
refused — and a process never blocks itself.** One script that runs the
generator stage and then the judge stage holds two aliases in one pid: that IS
the staggering the rule wants, so own-pid records are not conflicts. Sharing an alias costs throughput, never a swap; a second alias
costs the run. Refusal is immediate (SystemExit) rather than a wait — a
queue in front of a five-minute swap is the same trap with a nicer name.

Scope, honestly: the lease is a local directory, so it interlocks the
processes on THIS machine. A run started from another host is invisible to
it. Ambiguity resolves conservatively: a holder whose liveness cannot be
decided counts as alive — a wrong refusal costs a message, a wrong
admission costs the run.

Writing is atomic and serialised (review 2026-10-06). A record is written
to a temporary name and renamed into place, so a reader never sees half a
record; check-and-write runs under an `flock` on the endpoint directory, so
two processes on this machine cannot both pass the check. The re-read after
writing stays for lease directories on a shared filesystem, where `flock`
may not hold. An unreadable record is NOT deleted on sight: within
`UNREADABLE_GRACE_S` it counts as a holder (undecidable = busy); older than
that it is damage, removed with a message — otherwise one broken file would
block the slot forever.

Deliberate exception, like `--no-verify`: `LABKIT_NO_ENDPOINT_LEASE=1`.
"""

from __future__ import annotations

import atexit
import contextlib
import fcntl
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import uuid
from pathlib import Path
from collections.abc import Iterator

from labkit import runs

_HELD: set[tuple[str, str]] = set()  # (endpoint, alias) held by this process
_FILES: dict[tuple[str, str], Path] = {}
_MUTEX = threading.Lock()
#: an unreadable record younger than this counts as a holder
UNREADABLE_GRACE_S = 60.0


def lease_dir() -> Path:
    """Where leases live. `LABKIT_LEASE_DIR` overrides (tests, shared FS)."""
    env = os.environ.get("LABKIT_LEASE_DIR")
    return Path(env) if env else Path.home() / ".labkit" / "leases"


def _slug(text: str) -> str:
    """A readable file-name form of TEXT — not an identity: `a-b` and `a_b`
    share one."""
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_") or "default"


def endpoint_dir(endpoint: str) -> str:
    """The lease directory's name for ENDPOINT: one per serving slot.

    The URL is made canonical first (scheme and host in lower case, no
    trailing slash: `HTTP://Host/v1/` is `http://host/v1`), then named by a
    digest of it, with a readable slug in front. The slug alone was the
    identity until 2026-10-14: `http://h/a-b` and `http://h/a_b` shared a
    directory (one slot's lease refused the other), and `Host` and `host`
    had two (no interlock at all).
    """
    u = urllib.parse.urlsplit(endpoint.strip())
    canonical = urllib.parse.urlunsplit(
        (u.scheme.lower(), u.netloc.lower(), u.path.rstrip("/"), u.query, "")
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    return f"{_slug(canonical)[:60]}-{digest}"


def _script() -> str:
    return Path(sys.argv[0]).name or "python"


def holders(endpoint: str) -> list[dict]:
    """Live lease records for this endpoint; stale ones are removed on the way.

    A record whose process is gone is deleted (a crashed run must not block
    the slot forever). A record whose liveness is undecidable is kept and
    returned — see the module docstring on the failure direction.
    """
    d = lease_dir() / endpoint_dir(endpoint)
    out: list[dict] = []
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.json")):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except FileNotFoundError:  # released between glob and read
            continue
        except (OSError, json.JSONDecodeError) as exc:
            try:
                age = time.time() - f.stat().st_mtime
            except FileNotFoundError:
                continue
            if age < UNREADABLE_GRACE_S:
                out.append(
                    {
                        "alias": None,
                        "pid": None,
                        "script": f.name,
                        "started": "",
                        "unreadable": str(exc),
                    }
                )
            else:
                print(
                    f"endpoint_lease: removing unreadable lease record {f} "
                    f"({exc}; {age:.0f}s old)",
                    file=sys.stderr,
                )
                f.unlink(missing_ok=True)
            continue
        if rec.get("pid") == os.getpid():
            out.append(rec)
            continue
        if runs.is_alive(rec.get("pid"), rec.get("script")) is False:
            f.unlink(missing_ok=True)
            continue
        out.append(rec)
    return out


@contextlib.contextmanager
def _locked(d: Path) -> Iterator[None]:
    """Exclusive flock on the endpoint directory for check-and-write."""
    with open(d / ".lock", "a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _order(rec: dict) -> tuple[str, str]:
    """Who came first: the start time, then the record's random token — a
    total order. On the second alone two writers in the same second each
    saw the other as no younger and both yielded (review 2026-10-14)."""
    return (str(rec.get("started", "")), str(rec.get("token", "")))


def _conflict(endpoint: str, alias: str) -> dict | None:
    """The oldest live holder of a DIFFERENT alias, or None."""
    others = [
        h
        for h in holders(endpoint)
        if h.get("alias") != alias and h.get("pid") != os.getpid()
    ]
    return min(others, key=_order) if others else None


def _refuse(endpoint: str, alias: str, other: dict) -> None:
    since = other.get("started", "?")
    raise SystemExit(
        f"llm: endpoint {endpoint} is leased to alias '{other.get('alias')}' "
        f"(pid {other.get('pid')}, {other.get('script')}, since {since}) — "
        f"refusing to run '{alias}' against it.\n"
        f"  This endpoint is ONE model slot: a second alias makes both stages "
        f"swap the model back and forth (~5 min each), the timeouts come back "
        f"as empty answers, and an admissibility condition counts them as a parser finding.\n"
        f"  Let that stage finish, use the same alias, or — if you really mean "
        f"to share the slot — set LABKIT_NO_ENDPOINT_LEASE=1."
    )


def acquire(alias: str, endpoints: list[str] | None) -> None:
    """Lease every endpoint this alias may use. Idempotent, refuses on conflict.

    Called by `llm.complete` on every call; the work happens once per
    (endpoint, alias) and per process. Backends without an endpoint
    (claude-cli) lease nothing.
    """
    if os.environ.get("LABKIT_NO_ENDPOINT_LEASE") == "1":
        return
    for endpoint in endpoints or []:
        key = (endpoint, alias)
        with _MUTEX:
            if key in _HELD:
                continue
            d = lease_dir() / endpoint_dir(endpoint)
            d.mkdir(parents=True, exist_ok=True)
            with _locked(d):
                _lease_one(d, endpoint, alias)
            _HELD.add(key)
            _FILES[key] = d / f"{_slug(alias)}.{os.getpid()}.json"


def _lease_one(d: Path, endpoint: str, alias: str) -> None:
    """Check and write one record; caller holds the directory lock."""
    other = _conflict(endpoint, alias)
    if other is not None:
        _refuse(endpoint, alias, other)
    rec = {
        "alias": alias,
        "pid": os.getpid(),
        "script": _script(),
        "endpoint": endpoint,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "token": uuid.uuid4().hex,
        "argv": " ".join(sys.argv)[:300],
    }
    f = d / f"{_slug(alias)}.{os.getpid()}.json"
    runs.write_atomic(f, json.dumps(rec))
    # On a shared filesystem flock may not hold, and two processes can pass
    # the check at the same moment. Re-read after writing: whoever is not
    # the oldest live holder yields.
    other = _conflict(endpoint, alias)
    if other is not None and _order(other) < _order(rec):
        f.unlink(missing_ok=True)
        _refuse(endpoint, alias, other)


def release_all() -> None:
    """Drop this process' leases. Registered atexit; safe to call twice."""
    with _MUTEX:
        for key, f in list(_FILES.items()):
            f.unlink(missing_ok=True)
            _FILES.pop(key, None)
            _HELD.discard(key)


atexit.register(release_all)
