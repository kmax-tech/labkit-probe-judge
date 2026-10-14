"""llm — project LLM-backend scaffold (stdlib-only).

Experiments never hardcode endpoints or model ids: cluster addresses change,
and every run must record exactly which model answered. `models.toml` at the
repo root is the single place where backends live.

    import llm
    text = llm.complete("haiku", "Say OK")
    spec = llm.resolve("gpt-oss")     # dict -> put into runlog config, so
                                      # runs.tsv records model+backend+endpoint
                                      # + controls_temperature (see below)

Sampling control differs per backend: 'ollama' accepts a temperature,
'claude-cli' cannot (the CLI exposes no such flag) and REFUSES the argument
rather than ignoring it. resolve() therefore reports 'controls_temperature',
which lands in the run config — so a run is never recorded as deterministic
when the backend never made it so.

'claude-cli' runs with an empty setting-sources list: the operator's
settings and CLAUDE.md files stay out of the call, and provenance() stamps
CLI version + isolation flags (see _CLI_ISOLATION).

models.toml:
    [endpoints]                       # URLs live ONCE, under a name; a srun
    gamma1 = "http://gammaweb07.medien.uni-weimar.de:11490"   # reallocation
    # gamma2 = "http://gammawebNN.medien.uni-weimar.de:11491" # edits HERE only

    [models.haiku]
    backend = "claude-cli"            # subprocess `claude -p` (CLI auth, headless-safe)
    model = "claude-haiku-4-5-20251001"

    [models.gpt-oss]
    backend = "ollama"
    model = "gpt-oss:latest"
    endpoints = ["gamma1"]            # names from [endpoints] or literal URLs
    num_ctx = 32768                   # context window ollama allots; without it
                                      # the server's default applies, and a
                                      # longer prompt is CUT, not refused —
                                      # see _check_prompt_fit

    [models.gpt-oss-vllm]
    backend = "openai"                # any OpenAI-compatible server: vLLM, sglang
    model = "openai/gpt-oss-20b"      # the SERVED model id (vllm serve <id>)
    endpoint = "gamma2"               # api_key_env = "MY_KEY_VAR" if the server
                                      # requires a key: the NAME of an environment
                                      # variable, never the key — the spec lands in
                                      # every run config. A literal `api_key` is
                                      # honoured but recorded verbatim there.
    reasoning = true                  # model thinks before answering: the server
                                      # must run --reasoning-parser so the trace
                                      # arrives in its own field; an answer whose
                                      # content carries no trace field fails loud

Two servers, SAME model: list both names — completions round-robin across
them and fail over when one drops. Model identity and serving endpoint are
different knobs: the model is a measurement parameter, the endpoint is
operations. But two servers are two INSTRUMENT INSTANCES (batch invariance:
the same item can answer differently depending on server state), so record
per row which endpoint answered — `llm.last_endpoint()` after each call —
and report results split by endpoint; the split must sit under the noise
ceiling. A DIFFERENT model on the second server is simply another alias
pointing at the other endpoint name.

What a call cost: `llm.last_usage()` right after `complete` returns — the
token counts the backend reported (`Usage`: prompt, output, cached, USD where
priced), per thread like `last_endpoint()`. A run that records them per row
or per batch can say what it cost; labkit-audit prints them beside the
prompt size.

For specialized calls (logprobs, raw payloads): use resolve(alias) for
endpoint/model and do your own HTTP — never a literal URL in the experiment.
"""

from __future__ import annotations

import http.client
import json
import os
import shlex
import subprocess
import tempfile
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, NamedTuple

from labkit import endpoint_lease


def _find_models_toml() -> Path:
    seeds = [
        Path(sys.argv[0]).resolve().parent if sys.argv[0] else Path.cwd(),
        Path.cwd(),
    ]
    for seed in seeds:
        for d in [seed, *seed.parents]:
            p = d / "models.toml"
            if p.exists():
                return p
    raise FileNotFoundError(
        "models.toml not found (searched upward from script dir and cwd)"
    )


_FROZEN: dict[str, dict] = {}  # alias -> spec, fixed at first use per process


def resolve(alias: str) -> dict:
    """Alias -> full backend spec (put this into runlog's config).

    The spec is FROZEN per process at first use. `models.toml` is shared state:
    a cluster host changes with every allocation, and an experiment running in
    parallel must not have its backend swapped mid-run by whoever edits the
    file — the swap would be silent, and the run's config.json would keep
    naming the model that answered the first half. A new process picks up the
    edit; a running one keeps what it started with.
    """
    if alias in _FROZEN:
        return dict(_FROZEN[alias])
    cfg = tomllib.loads(_find_models_toml().read_text(encoding="utf-8"))
    try:
        spec = dict(cfg["models"][alias])
    except KeyError:
        known = ", ".join(cfg.get("models", {}))
        raise KeyError(f"model alias '{alias}' not in models.toml (known: {known})")
    spec["alias"] = alias
    _check_num_ctx(alias, spec)
    # Endpoint names resolve against [endpoints]; literal URLs pass through.
    # `endpoints = [...]` normalizes to spec["endpoints"] (list) +
    # spec["endpoint"] (first entry, for direct-HTTP callers). Frozen with
    # the rest of the spec: an edit to models.toml never reaches a running
    # process. The string form `endpoint = "..."` is not read since 0.89.0.
    if "endpoint" in spec:
        raise ValueError(
            f"models.toml [models.{alias}]: `endpoint = ...` is not read since "
            f"labkit 0.89.0 — write `endpoints = [{spec['endpoint']!r}]`"
        )
    table = cfg.get("endpoints", {})
    raw_eps = spec.pop("endpoints", None) or []
    eps = []
    for e in raw_eps:
        if "://" in e:
            eps.append(e)
        elif e in table:
            eps.append(table[e])
        else:
            known = ", ".join(table) or "none defined"
            raise KeyError(
                f"endpoint name '{e}' for alias '{alias}' not in "
                f"[endpoints] (known: {known})"
            )
    if eps:
        spec["endpoints"] = eps
        spec["endpoint"] = eps[0]
    # Recorded in every runlog config, so a run never *looks* deterministic
    # when the backend cannot control sampling at all.
    spec["controls_temperature"] = spec["backend"] in ("ollama", "openai")
    # Camera-ready gap closed 2026-08-18: the model NAME is not the model.
    # "qwen2.5:7b" can mean different weights in three months; the digest
    # pins what actually answered. Best-effort — a run must not die because
    # the tags endpoint hiccups; "unavailable" is honest and visible.
    # With several endpoints, all are probed: serving DIFFERENT weights under
    # the same alias would silently mix two models into one run — that is a
    # defect, and the config says so loudly instead of picking one digest.
    if spec["backend"] == "ollama":
        auth = _auth_headers(spec)
        spec["model_digest"] = _aggregate_digests(
            {ep: _ollama_digest(ep, spec["model"], auth) for ep in eps}
            or {"": _ollama_digest("", spec["model"], auth)}
        )
    _FROZEN[alias] = dict(spec)
    return spec


def _check_num_ctx(alias: str, spec: dict) -> None:
    """`num_ctx` is an ollama option and a positive integer; anything else
    raises — on another backend it would be dropped without a word."""
    if "num_ctx" not in spec:
        return
    value = spec["num_ctx"]
    if spec.get("backend") != "ollama":
        raise ValueError(
            f"alias '{alias}': num_ctx is an ollama option, but the backend is "
            f"'{spec.get('backend')}' — an OpenAI-compatible server sets its "
            f"window at start (vllm --max-model-len) and refuses longer prompts"
        )
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(
            f"alias '{alias}': num_ctx must be a positive integer, got {value!r}"
        )


def _aggregate_digests(per_endpoint: dict[str, str]) -> str:
    """One digest value for the run config, from per-endpoint probes.

    All reachable endpoints agree -> that digest. None reachable ->
    "unavailable". Disagreement -> "MISMATCH:..." — visible in every
    config.json, because a mixed-weights run must not look clean.
    """
    seen = sorted({d for d in per_endpoint.values() if d != "unavailable"})
    if not seen:
        return "unavailable"
    if len(seen) == 1:
        return seen[0]
    return "MISMATCH:" + ",".join(seen)


def _digest_from_tags(tags: dict, model: str) -> str:
    """Pure lookup: /api/tags payload -> short digest for `model`.

    Bare names match their :latest entry ("gpt-oss" -> "gpt-oss:latest").
    Unknown model -> "unavailable" rather than a guess.
    """
    want = {model, model if ":" in model else f"{model}:latest"}
    for m in tags.get("models", []):
        if m.get("name") in want or m.get("model") in want:
            # A proxy (KubeAI's ollama route) prefixes the digest with its
            # algorithm — "sha256:f8ceb…" — where ollama itself sends bare hex.
            # Cutting twelve characters off the prefixed form left FIVE hex
            # digits of pin (seen 2026-10-03 against llm.srv.webis.de).
            digest = str(m.get("digest", "")).removeprefix("sha256:")
            return digest[:12] or "unavailable"
    return "unavailable"


def _auth_headers(spec: dict) -> dict[str, str]:
    """Authorization header for a served endpoint, or nothing.

    `api_key_env` names the environment variable that holds the key: the
    spec (and with it every run config) records the NAME, the key itself
    never leaves the process. A literal `api_key` still works for servers
    behind a VPN where the key is not a secret — but it is recorded verbatim.
    A named variable that is not set fails loud: a run must not start
    unauthenticated and die after the first 401, or worse, fall back to an
    unauthenticated endpoint nobody chose.
    """
    env = spec.get("api_key_env")
    if env:
        key = os.environ.get(env)
        if not key:
            raise ValueError(
                f"alias '{spec.get('alias', '?')}': api_key_env = {env!r}, but "
                f"{env} is not set in the environment"
            )
        return {"Authorization": f"Bearer {key}"}
    if spec.get("api_key"):
        return {"Authorization": f"Bearer {spec['api_key']}"}
    return {}


def _ollama_digest(
    endpoint: str, model: str, headers: dict[str, str] | None = None
) -> str:
    try:
        req = urllib.request.Request(
            f"{endpoint.rstrip('/')}/api/tags", headers=headers or {}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return _digest_from_tags(json.loads(r.read().decode("utf-8")), model)
    except Exception:
        return "unavailable"


# A dropped connection is not an experiment result. Retrying transport errors
# belongs in the FAST lane too: a pilot loses just as much work as a scaled run
# when the cluster hiccups (2026-08-12: a socket timeout killed a scoring run at
# 49 of 96 items). Retries are COUNTED, never silent — put `llm.retries()` into
# your run metrics, so a run that limped is distinguishable from one that flew.
class BackendError(RuntimeError):
    """A backend refused a call without a diagnosable reason — retryable.

    The claude CLI can exit non-zero with an EMPTY stderr (seen 2026-08-12:
    two CLI-heavy runs in parallel killed both after hundreds of successful
    calls). That is a hiccup, not a misconfiguration, and it belongs in the
    retry set. A real misconfiguration still fails — just three times, fast.
    """


class PromptTruncated(RuntimeError):
    """The server read less of the prompt than was sent — not retryable.

    ollama fits a prompt longer than its context window by dropping tokens
    and answers anyway; the reply looks like any other. A retry reads the
    same cut prompt, so this error stays out of _TRANSIENT.
    """


_TRANSIENT = (
    TimeoutError,
    ConnectionError,
    urllib.error.URLError,
    http.client.HTTPException,
    subprocess.TimeoutExpired,
    BackendError,
)
_RETRIES = {"n": 0}
_RETRIES_LOCK = threading.Lock()
# network hiccup, model reload, queue, outage — 2026-09-24: two runs died
# after ~3 min of DNS/SSL failures with the old (10, 45, 120) ladder.
_BACKOFF = (10, 45, 120, 300, 300)


def retries() -> int:
    """How many transport retries this process has made (for run metrics)."""
    return _RETRIES["n"]


# Round-robin state per alias, and the endpoint of the most recent attempt.
# Two endpoints are two instrument instances (batch invariance) — callers that
# want per-row provenance read last_endpoint() right after a successful call.
# The endpoint is THREAD-local: under parallel.run each worker sees its own
# call's endpoint, never a neighbour's (the writer thread stamps via the
# record's _prov, prepared in the worker — see parallel._stamped).
_RR: dict[str, int] = {}
_RR_LOCK = threading.Lock()
_TLS = threading.local()


def last_endpoint() -> str:
    """URL that served (or was tried by) this thread's most recent attempt."""
    return getattr(_TLS, "endpoint", "")


class Usage(NamedTuple):
    """The token counts of one completion, as the backend reported them;
    None where it reported nothing. `prompt_tokens` is the whole prompt the
    model read, cache hits included (claude-cli: input + cache creation +
    cache read; ollama: `prompt_eval_count`; OpenAI-style: `prompt_tokens`);
    `cached_tokens` is the part served from a prompt cache (claude-cli:
    cache read; OpenAI-style: `prompt_tokens_details.cached_tokens`; ollama
    says nothing); `cost_usd` only where the backend prices the call
    (claude-cli `total_cost_usd`)."""

    prompt_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    cost_usd: float | None

    def describe(self) -> str:
        """One line for a log: `prompt 61,234 (8,671 cached) · output 1,902 · 0.41 USD`."""

        def n(v: int | None) -> str:
            return "n/a" if v is None else f"{v:,}"

        cached = (
            "" if self.cached_tokens is None else f" ({n(self.cached_tokens)} cached)"
        )
        cost = "" if self.cost_usd is None else f" · {self.cost_usd:.2f} USD"
        return f"prompt {n(self.prompt_tokens)}{cached} · output {n(self.output_tokens)}{cost}"


NO_USAGE = Usage(None, None, None, None)


def last_usage() -> Usage:
    """The token counts of this thread's most recent completion — read right
    after `complete` returns, like `last_endpoint`. NO_USAGE before the first
    call and when the backend reported none. labkit-audit prints it beside
    the prompt size, so every stamp can carry what the audit cost
    (2026-10-11: 30 transcripts, 7 billion cache-read tokens, and no line
    anywhere said what one audit cost)."""
    return getattr(_TLS, "usage", NO_USAGE)


def last_thinking() -> str:
    """The reasoning trace of this thread's most recent completion — what a
    reasoning model wrote before its answer (ollama `thinking`, OpenAI-style
    `reasoning_content`/`reasoning`); "" when the backend returns none. Read
    it right after `complete` returns, like `last_endpoint`: the answer alone
    says what the model decided, the trace says why (uniagent 2026-10-07: a
    false framework `yes` could not be explained because only the answer was
    kept)."""
    return getattr(_TLS, "thinking", "")


# `claude -p` is an agent harness, not an inference API: by default every
# call inherits the operator's ~/.claude/settings.json AND both CLAUDE.md
# files (user + project) into its system prompt. An empty setting-sources
# list drops all of them while OAuth keeps working (verified CLI 2.1.267;
# `--system-prompt` does NOT drop CLAUDE.md, an empty CLAUDE_CONFIG_DIR
# drops the login). 2026-09-23: `language: German` in the operator's
# settings had 45/432 English scenario prompts answered in German.
# No tools either: a judgement is an inference, not an agent session. With
# its read-only tools left on, a long prompt that says "read <file>" can send
# the CLI off to its cwd instead of answering from the inlined text, and the
# answer then depends on what lies there (preflight audit of labkit-paper
# area 03, 2026-10-06). `--tools ""` disables the whole built-in set.
_CLI_ISOLATION = ["--setting-sources", "", "--tools", ""]
#: `claude -p` runs from a neutral directory, never from the repo: the CLI
#: is a harness and reads its cwd (project files, git state) into the
#: conversation. A cold agent observed answers mentioning "labkit" and
#: "Python code" for a one-word judgement when called from the repo root,
#: 3 of 5 times, clean from /tmp (2026-10-05, not reproduced in 7 tries —
#: a sketch, but the cwd is not part of the instrument either way).
_CLI_CWD = tempfile.gettempdir()


def _cli_run(cmd: list[str], timeout: float | None) -> subprocess.CompletedProcess:
    """The one place `claude -p` is spawned: isolated flags, neutral cwd."""
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=_CLI_CWD
    )


def _cli_version() -> str:
    try:
        r = subprocess.run(
            ["claude", "--version"], capture_output=True, text=True, timeout=30
        )
        return r.stdout.strip().split()[0] if r.returncode == 0 else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def provenance(alias: str) -> dict:
    """Per-row provenance stamp for `batch.Store(prov=...)`.

    The facts that die when an output file loses its runs.tsv join: which
    model (name@digest) and which serving instance. `endpoint` is passed as a
    CALLABLE — Store evaluates it per append, because with a multi-endpoint
    alias the answering server differs from row to row. Add the run pointer
    yourself: `{**llm.provenance(alias), "run": run.run_id}`.

    For claude-cli the stamp also carries the CLI version and the isolation
    flags — the system prompt is the harness's own, and these two decide
    what else went into it.
    """
    spec = resolve(alias)
    model = spec["model"]
    if spec.get("model_digest"):
        model += "@" + spec["model_digest"]
    prov = {"model": model, "endpoint": last_endpoint}
    if spec["backend"] == "claude-cli":
        prov["cli_version"] = _cli_version()
        prov["cli_flags"] = shlex.join(_CLI_ISOLATION)
    return prov


def _pick_endpoint(spec: dict) -> str:
    """Next endpoint for this call: round-robin over spec['endpoints'].

    A single endpoint behaves exactly as before. With several, each call
    advances the counter — and because `complete()` re-enters here on retry,
    a dropped server naturally fails over to the next one.
    """
    eps = spec.get("endpoints") or [spec["endpoint"]]
    if len(eps) == 1:
        url = eps[0]
    else:
        key = spec.get("alias", spec.get("model", ""))
        with _RR_LOCK:
            i = _RR.get(key, 0)
            _RR[key] = i + 1
        url = eps[i % len(eps)]
    _TLS.endpoint = url
    return url


def complete(
    alias: str,
    prompt: str,
    *,
    system: str | None = None,
    temperature: float | None = None,
    timeout: int = 300,
    attempts: int = 6,
    raw: bool = False,
    stop: list[str] | None = None,
    max_tokens: int = 512,
) -> str:
    """One text completion, retrying transport failures (see _TRANSIENT).

    `attempts` counts total tries, not extra ones; backoff follows _BACKOFF
    (10 s … 300 s, ~13 min in all, so a short outage is survived). Errors
    that no retry can fix — an unknown alias, a temperature the backend cannot
    honour — are raised immediately. Pass attempts=1 to disable.
    """
    for attempt in range(1, attempts + 1):
        _TLS.thinking = ""  # never a previous call's trace
        _TLS.usage = NO_USAGE  # nor its token counts
        try:
            return _complete_once(
                alias,
                prompt,
                system=system,
                temperature=temperature,
                timeout=timeout,
                raw=raw,
                stop=stop,
                max_tokens=max_tokens,
            )
        except _TRANSIENT as exc:
            if attempt == attempts:
                # Exhausted retries ALWAYS raise BackendError, no matter what
                # the backend threw. Otherwise WHICH exception escapes depends
                # on the backend: claude-cli throws BackendError (a
                # RuntimeError), ollama throws URLError/TimeoutError — no
                # RuntimeErrors. A caller with "except RuntimeError" is then
                # correct on one backend and loses its whole batch on the
                # other (2026-08-14: a DNS hiccup killed a 145-item run after
                # the switch from haiku to the cluster). One documented type =
                # one thing to catch; the original exception stays attached
                # via "from exc".
                if isinstance(exc, BackendError):
                    raise
                raise BackendError(
                    f"{alias}: {type(exc).__name__} after {attempts} attempts: "
                    f"{str(exc)[:200]}"
                ) from exc
            with _RETRIES_LOCK:
                _RETRIES["n"] += 1
            # The backoff must outlive a MODEL LOAD, not just a network
            # hiccup: a 13 GB model takes ~90 s into VRAM, and 5/15 s pauses
            # all fizzle before that (a run died after 5 of 100).
            wait = _BACKOFF[min(attempt - 1, len(_BACKOFF) - 1)]
            print(
                f"llm: {type(exc).__name__} on attempt {attempt}/{attempts} "
                f"({str(exc)[:60]}) — retrying in {wait}s",
                file=sys.stderr,
            )
            time.sleep(wait)
    raise AssertionError("unreachable")


def complete_many(
    alias: str, prompts: list[str], *, workers: int = 4, **kw: Any
) -> list[str]:
    """complete() over many independent prompts, results in input order.

    A thread pool of `workers`; each worker calls complete() with the same
    keyword arguments, so retries and the retry counter behave as in the
    serial case. claude-cli spawns one process per call (~300 MB), which
    bounds `workers` by RAM, not by the API. Independent prompts only — a
    tournament's pairs, never a conversation.
    """
    if workers <= 1 or len(prompts) <= 1:
        return [complete(alias, p, **kw) for p in prompts]
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda p: complete(alias, p, **kw), prompts))


def _complete_once(
    alias: str,
    prompt: str,
    *,
    system: str | None = None,
    temperature: float | None = None,
    timeout: int = 300,
    raw: bool = False,
    stop: list[str] | None = None,
    max_tokens: int = 512,
) -> str:
    """One text completion via the alias' backend. Returns the answer text.

    temperature: only the 'ollama' backend can set it. Passing a value to a
    backend that cannot honour it raises instead of silently ignoring it —
    a run must not be documented as "temperature 0" when nothing set it.

    Dispatches to one adapter per backend; each adapter owns its protocol
    (CLI flags, ollama /api/generate or /api/chat, OpenAI /v1).
    """
    spec = resolve(alias)
    # A serving endpoint is ONE model slot: a second alias against it makes
    # both stages swap the model back and forth, and the timeouts come back as
    # empty answers that an admissibility condition counts as a parser finding. The lease sits
    # HERE and not in the calling script on purpose — a rule a script has to
    # remember is an intention (endpoint_lease's docstring carries the chain).
    endpoint_lease.acquire(alias, spec.get("endpoints"))
    backend = spec["backend"]
    if backend == "claude-cli":
        return _complete_claude_cli(
            alias, spec, prompt, system=system, temperature=temperature, timeout=timeout
        )
    if backend == "ollama" and raw:
        return _complete_ollama_raw(
            spec,
            prompt,
            system=system,
            temperature=temperature,
            timeout=timeout,
            stop=stop,
            max_tokens=max_tokens,
        )
    if backend == "ollama":
        return _complete_ollama_chat(
            alias,
            spec,
            prompt,
            system=system,
            temperature=temperature,
            timeout=timeout,
            stop=stop,
            max_tokens=max_tokens,
        )
    if backend == "openai":
        return _complete_openai(
            alias,
            spec,
            prompt,
            system=system,
            temperature=temperature,
            timeout=timeout,
            raw=raw,
            stop=stop,
            max_tokens=max_tokens,
        )
    raise ValueError(f"unknown backend '{backend}' for alias '{alias}'")


def _chat_messages(system: str | None, prompt: str) -> list[dict]:
    """The chat message list: optional system turn, then the user prompt."""
    return ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]


def _post_json(spec: dict, path: str, payload: dict, timeout: int) -> dict:
    """POST `payload` to the alias' endpoint + `path`; the decoded answer."""
    req = urllib.request.Request(
        _pick_endpoint(spec).rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **_auth_headers(spec)},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _complete_claude_cli(
    alias: str,
    spec: dict,
    prompt: str,
    *,
    system: str | None,
    temperature: float | None,
    timeout: int,
) -> str:
    """`claude -p`, isolated from the operator's settings (_CLI_ISOLATION)."""
    if temperature is not None:
        raise ValueError(
            f"alias '{alias}' uses backend 'claude-cli', which has no "
            f"temperature flag — it cannot honour temperature="
            f"{temperature}. Pass temperature=None and document the run "
            f"as backend-default sampling, or use an ollama alias."
        )
    cmd = [
        "claude",
        "-p",
        prompt,
        "--model",
        spec["model"],
        "--output-format",
        "json",
        *_CLI_ISOLATION,
    ]
    if system:
        cmd += ["--append-system-prompt", system]
    r = _cli_run(cmd, timeout)
    if r.returncode != 0:
        detail = r.stderr.strip() or r.stdout.strip() or "no output on stderr or stdout"
        raise BackendError(f"claude-cli exit {r.returncode}: {detail[:300]}")
    return _cli_result(r.stdout)


def _cli_result(stdout: str) -> str:
    """The answer text of a `claude -p --output-format json` reply; its
    `usage` and `total_cost_usd` go to `last_usage()`. Anything but that JSON
    object is a backend failure, named with what came instead."""
    try:
        body = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise BackendError(
            f"claude-cli: stdout is not the JSON reply of --output-format json "
            f"({exc.msg}): {stdout.strip()[:200]!r}"
        ) from exc
    if not isinstance(body, dict) or "result" not in body:
        raise BackendError(
            f"claude-cli: JSON reply without a `result` field: {stdout.strip()[:200]!r}"
        )
    if body.get("is_error"):
        raise BackendError(f"claude-cli: is_error — {str(body['result'])[:300]}")
    usage = body.get("usage") or {}
    counted = [
        usage.get(k)
        for k in (
            "input_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
    ]
    _TLS.usage = Usage(
        prompt_tokens=sum(int(v) for v in counted if v is not None)
        if any(v is not None for v in counted)
        else None,
        output_tokens=usage.get("output_tokens"),
        cached_tokens=usage.get("cache_read_input_tokens"),
        cost_usd=body.get("total_cost_usd"),
    )
    return str(body["result"]).strip()


#: how long ollama keeps the model loaded after a call. Without it ollama
#: evicts the model between two calls (default 5 min) and every call pays a
#: reload — ~13 GB for gpt-oss; that once drove a run into the timeout after
#: 5 of 100 items. No caller ever set another value (audit 2026-10-13).
OLLAMA_KEEP_ALIVE = "10m"


def _ollama_options(
    spec: dict, temperature: float | None, stop: list[str] | None, max_tokens: int
) -> dict[str, object]:
    """The `options` of an ollama request, for /api/generate and /api/chat
    alike. `num_predict` is never left out: a completion has no natural end
    and without a token budget it writes until the context is full (a pilot
    stalled 12 min on one call; until 2026-08-19 the chat path — the one
    every experiment takes — set only `temperature`, and a server log showed
    `n_gen = 3520` at a nominal 2048, the request aborted after almost three
    minutes, which looked like an overloaded cluster)."""
    options: dict[str, object] = {"num_predict": max_tokens}
    if temperature is not None:
        options["temperature"] = temperature
    if stop:
        options["stop"] = stop
    if "num_ctx" in spec:
        options["num_ctx"] = spec["num_ctx"]
    return options


def _warn_empty(alias: str, detail: str) -> None:
    """Said aloud, decided by the caller: a reasoning model that put its
    trace in its own field and nothing in `content` thought and said
    nothing — a MISSING measurement that would come back as an empty string
    and look like a model answer to the parser. Silently lost items are the
    most expensive error type."""
    print(
        f"llm: {alias} returned EMPTY content ({detail}) — count as unreadable, "
        f"not as an answer",
        file=sys.stderr,
    )


def _complete_ollama_raw(
    spec: dict,
    prompt: str,
    *,
    system: str | None,
    temperature: float | None,
    timeout: int,
    stop: list[str] | None,
    max_tokens: int,
) -> str:
    """ollama /api/generate with raw=true: the prompt goes untemplated."""
    # /api/generate with raw=true sends the prompt UNTEMPLATED — the
    # model sees exactly our text, the way a paper's own
    # "### Instruction/### Response" scaffold assumes. Through /api/chat
    # ollama would wrap that scaffold in the model's chat template on
    # top, and the model answers in chat register (preambles, meta
    # commentary). A completion needs a stop sequence, or it writes the
    # next instruction itself.
    if system:
        raise ValueError(
            "raw=True sends one untemplated prompt; fold "
            "any system text into the prompt itself"
        )
    payload: dict[str, object] = {
        "model": spec["model"],
        "prompt": prompt,
        "raw": True,
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": _ollama_options(spec, temperature, stop, max_tokens),
    }
    body = _post_json(spec, "/api/generate", payload, timeout)
    _TLS.usage = _ollama_usage(body)
    _check_prompt_fit(spec, len(prompt), _TLS.usage)
    return body["response"].strip()


def _ollama_usage(body: dict) -> Usage:
    """ollama counts `prompt_eval_count` and `eval_count`; it omits the
    first when the whole prompt came from its cache, hence None."""
    return Usage(
        prompt_tokens=body.get("prompt_eval_count"),
        output_tokens=body.get("eval_count"),
        cached_tokens=None,
        cost_usd=None,
    )


#: characters per prompt token above which a prompt counts as cut. Tokenizers
#: average 3-6 characters per token on English and code (repetitive English
#: read 5.2 on gpt-oss:20b, leguin, 2026-10-11); a ratio of 10 means
#: more than half the prompt never reached the model. Floor, not estimate:
#: a prompt cut by a third passes — the exact check needs `num_ctx`.
TRUNCATION_CHARS_PER_TOKEN = 10
#: prompts shorter than this are not checked by ratio: a short prompt fits
#: every context window, and chat-template tokens skew its ratio
TRUNCATION_MIN_CHARS = 4000


def _check_prompt_fit(spec: dict, prompt_chars: int, usage: Usage) -> None:
    """Raise PromptTruncated when ollama read less than the whole prompt.

    ollama cuts a prompt longer than its context window and answers what is
    left; nothing in the reply but `prompt_eval_count` shows it. Two tests:
    with `num_ctx` set, a count that reaches the window is a cut (ollama
    0.23.1 trims to exactly the window and answers with HTTP 200: a
    25,272-character prompt at num_ctx 2048 read 2,048, leguin, 2026-10-11); without it, a count far below the prompt's
    length (TRUNCATION_CHARS_PER_TOKEN). A reply without the count (whole
    prompt from cache) cannot be judged and passes.
    """
    read = usage.prompt_tokens
    if read is None or read <= 0:
        return
    alias = spec.get("alias", spec.get("model", "?"))
    window = spec.get("num_ctx")
    if window is not None and read >= window:
        raise PromptTruncated(
            f"{alias}: ollama read {read:,} prompt tokens, the whole num_ctx "
            f"window of {window:,} — the prompt was cut to fit, and nothing is "
            f"left to answer with. Raise num_ctx in models.toml or shorten the prompt."
        )
    if (
        prompt_chars >= TRUNCATION_MIN_CHARS
        and prompt_chars / read > TRUNCATION_CHARS_PER_TOKEN
    ):
        hint = (
            f"num_ctx is {window:,}"
            if window is not None
            else "no num_ctx is set, so the server default applies"
        )
        raise PromptTruncated(
            f"{alias}: ollama read {read:,} prompt tokens of a {prompt_chars:,}-"
            f"character prompt ({prompt_chars / read:.0f} characters per token; "
            f"a whole prompt reads at 3-6) — the server cut it to its context "
            f"window, and {hint}. Set num_ctx in models.toml."
        )


def _complete_ollama_chat(
    alias: str,
    spec: dict,
    prompt: str,
    *,
    system: str | None,
    temperature: float | None,
    timeout: int,
    stop: list[str] | None,
    max_tokens: int,
) -> str:
    """ollama /api/chat — the path every templated experiment takes."""
    payload: dict[str, object] = {
        "model": spec["model"],
        "messages": _chat_messages(system, prompt),
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": _ollama_options(spec, temperature, stop, max_tokens),
    }
    body = _post_json(spec, "/api/chat", payload, timeout)
    _TLS.usage = _ollama_usage(body)
    _check_prompt_fit(spec, len(system or "") + len(prompt), _TLS.usage)
    message = body.get("message") or {}
    content = (message.get("content") or "").strip()
    _TLS.thinking = (message.get("thinking") or "").strip()
    if not content:
        _warn_empty(
            alias,
            f"done_reason={body.get('done_reason')!r}, "
            f"eval_count={body.get('eval_count')}, thinking={len(_TLS.thinking)} chars",
        )
    return content


def _complete_openai(
    alias: str,
    spec: dict,
    prompt: str,
    *,
    system: str | None,
    temperature: float | None,
    timeout: int,
    raw: bool,
    stop: list[str] | None,
    max_tokens: int,
) -> str:
    """Any OpenAI-compatible server (vLLM, sglang, …) via /v1/chat/completions."""
    # Any OpenAI-compatible server: vLLM, sglang, ... Same completion
    # semantics as the ollama chat path. `keep_alive` does not apply (the
    # server owns model residency); `raw` has no untemplated route here.
    # Model pinning: /v1 exposes no weights digest — the served model id
    # plus the server launch command (revision, quantization) are the pin,
    # both belong in the run config.
    if raw:
        raise ValueError(
            "raw=True needs ollama's /api/generate — the "
            "OpenAI-compatible API has no untemplated path"
        )
    payload: dict[str, object] = {
        "model": spec["model"],
        "messages": _chat_messages(system, prompt),
        "max_tokens": max_tokens,
        "stream": False,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if stop:
        payload["stop"] = stop
    body = _post_json(spec, "/v1/chat/completions", payload, timeout)
    usage = body.get("usage") or {}
    _TLS.usage = Usage(
        prompt_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
        cached_tokens=(usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
        cost_usd=None,
    )
    first = (body.get("choices") or [{}])[0]
    message = first.get("message") or {}
    content = (message.get("content") or "").strip()
    # Reasoning models: with a server-side --reasoning-parser the
    # thinking trace sits in its own field (reasoning_content; newer
    # vLLM: reasoning) and content is the bare answer — the same split
    # ollama delivers as "thinking". WITHOUT the flag the trace lands IN
    # content; marker parsers appear to survive that, but parse_letter
    # then reads the first free-standing A/B of the DELIBERATION instead
    # of the answer. models.toml therefore declares `reasoning = true`;
    # content without a trace field is the signature of a server missing
    # the parser flag — fail immediately, no retry changes a server
    # config.
    reasoning = (
        message.get("reasoning_content") or message.get("reasoning") or ""
    ).strip()
    _TLS.thinking = reasoning
    if spec.get("reasoning") and content and not reasoning:
        raise ValueError(
            f"{alias}: reasoning = true, but the answer carries content "
            f"without reasoning_content/reasoning — the server runs "
            f"without --reasoning-parser and mixes the thinking trace "
            f"into the answer. Fix the server cmd (swap-models.toml), or "
            f"set reasoning = false if this model truly writes no trace."
        )
    if not content:
        _warn_empty(
            alias,
            f"finish_reason={first.get('finish_reason')!r}, reasoning={len(reasoning)} chars",
        )
    return content
