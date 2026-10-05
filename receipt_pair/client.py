"""A small client for Lemonade's OpenAI-compatible API. Standard library only.

Lemonade serves local models over HTTP. Receipt Pair uses four of its endpoints:

    POST /chat/completions   ask a model (OpenAI-compatible)
    GET  /health             which model is loaded now ("model_loaded")
    POST /unload             unload a model ({"model_name": ...})
    GET  /stats              Lemonade's own speed numbers for the last request

Lemonade keeps one model loaded at a time here, so before a model's turn the client unloads any other model
(as the sealed runs did). Asking for a model that is not loaded loads it.

By default the client only talks to this machine (localhost, 127.0.0.1 or ::1), so a log can never be sent
anywhere else by a typing mistake. Pass allow_remote=True for a Lemonade on another machine you trust.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

DEFAULT_BASE_URL = "http://localhost:13305/api/v1"
# The sealed runs' settings. Greedy decoding with a fixed seed; the reply is JSON of about 60 tokens.
SETTINGS = {"temperature": 0, "max_tokens": 400, "seed": 42}
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


class BackendError(RuntimeError):
    """Lemonade cannot be used; the run stops rather than answering 'not shown' for everything."""


@dataclass
class ModelSpec:
    """A Lemonade model id plus any extra fields to send in the request body."""

    id: str
    extra: dict = field(default_factory=dict)


QWEN = ModelSpec("Qwen3-4B-Instruct-2507-GGUF")
# Gemma 4 can think before it answers; the sealed runs switched that off.
GEMMA = ModelSpec("Gemma-4-E4B-it-GGUF", {"chat_template_kwargs": {"enable_thinking": False}})
DEFAULT_MODELS = (QWEN, GEMMA)


def local_url(url: str, allow_remote: bool = False) -> str:
    """Check that the server address is on this machine (unless allow_remote). Returns it without a trailing slash."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("the Lemonade address must look like http://localhost:13305/api/v1: " + url)
    if parsed.username or parsed.password:
        raise ValueError("give the server address without credentials: " + url)
    if not allow_remote and parsed.hostname not in LOCAL_HOSTS:
        raise ValueError("this Lemonade address is not on this machine (" + str(parsed.hostname) + "). "
                         "Logs stay local unless you pass --allow-remote.")
    return url.rstrip("/")


Transport = Callable[[str, str, Optional[dict], float], dict]


def urllib_transport(method: str, url: str, body: Optional[dict] = None, timeout: float = 600) -> dict:
    """One JSON request, one JSON reply. No proxies: a proxy setting must never route a log off this machine."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


@dataclass
class Chat:
    """The result of one chat request. error is None, or 'backend_error: <ExceptionName>'."""

    text: Optional[str]
    error: Optional[str]
    seconds: float
    stats: Optional[dict] = None
    detail: str = ""


def _detail(error: BaseException) -> str:
    text = str(error)
    if isinstance(error, urllib.error.HTTPError):
        try:
            body = error.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - the detail is only a hint for the person
            body = ""
        finally:
            error.close()
        text = "HTTP " + str(error.code) + (": " + body.strip() if body.strip() else "")
    return " ".join(text.split())[:300]


class LemonadeClient:
    """Talks to one Lemonade server. Pass transport= to replace the network (tests do)."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, transport: Optional[Transport] = None, timeout: float = 600,
                 allow_remote: bool = False, settings: Optional[dict] = None, log: Any = None) -> None:
        self.base_url = local_url(base_url, allow_remote)
        self.transport = transport or urllib_transport
        self.timeout = timeout
        self.settings = dict(SETTINGS if settings is None else settings)
        self.log = log if log is not None else sys.stderr

    def _call(self, method: str, path: str, body: Optional[dict] = None, timeout: Optional[float] = None) -> dict:
        return self.transport(method, self.base_url + path, body, self.timeout if timeout is None else timeout)

    def health(self) -> Optional[dict]:
        try:
            return self._call("GET", "/health", timeout=30)
        except Exception:  # noqa: BLE001
            return None

    def loaded_model(self) -> Optional[str]:
        health = self.health()
        return (health or {}).get("model_loaded") or None

    def unload(self, model_id: str) -> None:
        self._call("POST", "/unload", {"model_name": model_id}, timeout=120)

    def make_only_loaded(self, model_id: str) -> None:
        """Unload any other model so that this one has the memory and the slot (the sealed runs did the same).

        A failure here is reported and ignored: the next chat request loads the model it needs anyway.
        """
        try:
            health = self._call("GET", "/health", timeout=30)
            loaded = (health or {}).get("model_loaded")
            if loaded and loaded != model_id:
                self.unload(loaded)
        except Exception as error:  # noqa: BLE001
            print("unload check failed: " + _detail(error), file=self.log, flush=True)

    def stats(self) -> Optional[dict]:
        try:
            return self._call("GET", "/stats", timeout=30)
        except Exception:  # noqa: BLE001
            return None

    def request_body(self, model: ModelSpec, system: str, user: str) -> dict:
        return {"model": model.id, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                **self.settings, **model.extra}

    def chat(self, model: ModelSpec, system: str, user: str) -> Chat:
        """Ask one model. One retry after a failure, as the sealed runs did; then 'backend_error'."""
        body = self.request_body(model, system, user)
        started = time.time()
        text: Optional[str] = None
        error: Optional[str] = None
        detail = ""
        for attempt in (1, 2):
            try:
                reply = self._call("POST", "/chat/completions", body)
                text, error, detail = (reply["choices"][0]["message"].get("content") or ""), None, ""
                break
            except Exception as failure:  # noqa: BLE001 - any failure of the server or the reply shape
                text, error, detail = None, "backend_error: " + type(failure).__name__, _detail(failure)
        seconds = time.time() - started
        return Chat(text, error, seconds, self.stats() if error is None else None, detail)
