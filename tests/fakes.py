"""A stand-in for a Lemonade server, in memory. No sockets: the client calls this instead of the network."""

import json

BASE = "http://localhost:13305/api/v1"


def reply_json(verdict, turn_id=None, quote="", reason="r"):
    """The JSON text a model is asked to produce."""
    return json.dumps({"reason": reason, "turn_id": turn_id, "quote": quote, "verdict": verdict})


class FakeLemonade:
    """Answers the four endpoints the client uses, and keeps a record of every call.

    replies: {model id: reply text, or a function(request body) -> reply text}
    """

    def __init__(self, replies=None):
        self.replies = dict(replies or {})
        self.loaded = None
        self.calls = []          # (method, path, body)
        self.fail = {}           # path -> how many times to raise OSError before working
        self.stats = {"tokens_per_second": 12.5, "time_to_first_token": 0.4}

    def __call__(self, method, url, body=None, timeout=600):
        assert url.startswith(BASE), url
        path = url[len(BASE):]
        self.calls.append((method, path, body))
        if self.fail.get(path, 0) > 0:
            self.fail[path] -= 1
            raise OSError("connection refused")
        if (method, path) == ("GET", "/health"):
            return {"status": "ok", "model_loaded": self.loaded}
        if (method, path) == ("POST", "/unload"):
            if body["model_name"] == self.loaded:
                self.loaded = None
            return {"status": "success"}
        if (method, path) == ("GET", "/stats"):
            return dict(self.stats)
        if (method, path) == ("POST", "/chat/completions"):
            assert [m["role"] for m in body["messages"]] == ["system", "user"]
            self.loaded = body["model"]
            reply = self.replies[body["model"]]
            text = reply(body) if callable(reply) else reply
            return {"choices": [{"message": {"role": "assistant", "content": text}}]}
        raise AssertionError("unexpected call: " + method + " " + path)

    def chats(self):
        return [body["model"] for method, path, body in self.calls if path == "/chat/completions"]

    def sequence(self):
        """The calls that change what is loaded, in order: ('chat', model) and ('unload', model)."""
        out = []
        for method, path, body in self.calls:
            if path == "/chat/completions":
                out.append(("chat", body["model"]))
            elif path == "/unload":
                out.append(("unload", body["model_name"]))
        return out
