"""The Lemonade client, against an in-memory fake server and a patched urllib. No network."""

import io
import json
import unittest
import urllib.error
import urllib.request
from unittest import mock

from receipt_pair import client as lemonade

from .fakes import BASE, FakeLemonade, reply_json


def make(fake=None, **kwargs):
    fake = fake or FakeLemonade({lemonade.QWEN.id: reply_json("not_shown"), lemonade.GEMMA.id: reply_json("not_shown")})
    return fake, lemonade.LemonadeClient(transport=fake, log=io.StringIO(), **kwargs)


class Defaults(unittest.TestCase):
    def test_the_sealed_settings(self):
        self.assertEqual(lemonade.SETTINGS, {"temperature": 0, "max_tokens": 400, "seed": 42})

    def test_the_default_models_are_the_two_the_sealed_runs_used(self):
        self.assertEqual([m.id for m in lemonade.DEFAULT_MODELS], ["Qwen3-4B-Instruct-2507-GGUF", "Gemma-4-E4B-it-GGUF"])

    def test_gemma_has_thinking_off_and_qwen_has_no_extras(self):
        self.assertEqual(lemonade.GEMMA.extra, {"chat_template_kwargs": {"enable_thinking": False}})
        self.assertEqual(lemonade.QWEN.extra, {})

    def test_the_default_address(self):
        self.assertEqual(lemonade.DEFAULT_BASE_URL, "http://localhost:13305/api/v1")


class LocalOnly(unittest.TestCase):
    def test_addresses_on_this_machine_are_allowed(self):
        for url in ("http://localhost:13305/api/v1", "http://127.0.0.1:8000/api/v1/", "http://[::1]:13305/api/v1"):
            self.assertEqual(lemonade.local_url(url), url.rstrip("/"))

    def test_other_machines_are_refused_unless_allowed(self):
        for url in ("http://192.168.1.20:13305/api/v1", "https://example.com/api/v1", "http://lemonade.lan/api/v1"):
            with self.assertRaises(ValueError):
                lemonade.local_url(url)
            self.assertEqual(lemonade.local_url(url, allow_remote=True), url.rstrip("/"))

    def test_bad_addresses_are_refused(self):
        for url in ("localhost:13305", "ftp://localhost/api", "http://user:pw@localhost/api", ""):
            with self.assertRaises(ValueError):
                lemonade.local_url(url, allow_remote=True)

    def test_the_client_refuses_a_remote_address_by_default(self):
        with self.assertRaises(ValueError):
            lemonade.LemonadeClient(base_url="http://10.0.0.5:13305/api/v1")
        lemonade.LemonadeClient(base_url="http://10.0.0.5:13305/api/v1", allow_remote=True)


class Chat(unittest.TestCase):
    def test_the_request_body(self):
        fake, c = make()
        c.chat(lemonade.GEMMA, "SYSTEM TEXT", "USER TEXT")
        method, path, body = next(call for call in fake.calls if call[1] == "/chat/completions")
        self.assertEqual(method, "POST")
        self.assertEqual(body["model"], "Gemma-4-E4B-it-GGUF")
        self.assertEqual(body["messages"], [{"role": "system", "content": "SYSTEM TEXT"}, {"role": "user", "content": "USER TEXT"}])
        self.assertEqual((body["temperature"], body["max_tokens"], body["seed"]), (0, 400, 42))
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})

    def test_qwen_gets_no_extra_fields(self):
        fake, c = make()
        c.chat(lemonade.QWEN, "s", "u")
        body = next(call[2] for call in fake.calls if call[1] == "/chat/completions")
        self.assertNotIn("chat_template_kwargs", body)

    def test_a_good_reply_comes_back_with_text_and_stats(self):
        fake, c = make(FakeLemonade({lemonade.QWEN.id: "hello"}))
        chat = c.chat(lemonade.QWEN, "s", "u")
        self.assertEqual((chat.text, chat.error), ("hello", None))
        self.assertEqual(chat.stats["tokens_per_second"], 12.5)
        self.assertGreaterEqual(chat.seconds, 0)

    def test_one_retry_after_a_failure(self):
        fake, c = make()
        fake.fail["/chat/completions"] = 1
        chat = c.chat(lemonade.QWEN, "s", "u")
        self.assertIsNone(chat.error)
        self.assertEqual(len([call for call in fake.calls if call[1] == "/chat/completions"]), 2)

    def test_two_failures_are_a_backend_error_with_a_detail(self):
        fake, c = make()
        fake.fail["/chat/completions"] = 5
        chat = c.chat(lemonade.QWEN, "s", "u")
        self.assertEqual(chat.error, "backend_error: OSError")
        self.assertIsNone(chat.text)
        self.assertIn("connection refused", chat.detail)
        self.assertEqual(len([call for call in fake.calls if call[1] == "/chat/completions"]), 2)

    def test_an_http_error_reports_its_code_and_body(self):
        def transport(method, url, body=None, timeout=600):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b'{"error": "model not downloaded"}'))
        c = lemonade.LemonadeClient(transport=transport, log=io.StringIO())
        chat = c.chat(lemonade.QWEN, "s", "u")
        self.assertEqual(chat.error, "backend_error: HTTPError")
        self.assertIn("HTTP 404", chat.detail)
        self.assertIn("model not downloaded", chat.detail)

    def test_a_reply_of_the_wrong_shape_is_a_backend_error(self):
        c = lemonade.LemonadeClient(transport=lambda *a, **k: {"unexpected": True}, log=io.StringIO())
        self.assertEqual(c.chat(lemonade.QWEN, "s", "u").error, "backend_error: KeyError")

    def test_empty_content_is_empty_text_not_an_error(self):
        c = lemonade.LemonadeClient(transport=lambda *a, **k: {"choices": [{"message": {"content": None}}]}, log=io.StringIO())
        chat = c.chat(lemonade.QWEN, "s", "u")
        self.assertEqual((chat.text, chat.error), ("", None))


class OneModelAtATime(unittest.TestCase):
    def test_another_model_is_unloaded_first(self):
        fake, c = make()
        fake.loaded = "Gemma-4-E4B-it-GGUF"
        c.make_only_loaded("Qwen3-4B-Instruct-2507-GGUF")
        self.assertIn(("POST", "/unload", {"model_name": "Gemma-4-E4B-it-GGUF"}), fake.calls)
        self.assertIsNone(fake.loaded)

    def test_the_same_model_is_left_alone(self):
        fake, c = make()
        fake.loaded = "Qwen3-4B-Instruct-2507-GGUF"
        c.make_only_loaded("Qwen3-4B-Instruct-2507-GGUF")
        self.assertFalse([call for call in fake.calls if call[1] == "/unload"])

    def test_nothing_loaded_means_nothing_to_unload(self):
        fake, c = make()
        c.make_only_loaded("Qwen3-4B-Instruct-2507-GGUF")
        self.assertFalse([call for call in fake.calls if call[1] == "/unload"])

    def test_a_failed_health_check_is_reported_and_ignored(self):
        fake, c = make()
        fake.fail["/health"] = 1
        c.make_only_loaded("Qwen3-4B-Instruct-2507-GGUF")
        self.assertIn("unload check failed", c.log.getvalue())

    def test_loaded_model_and_stats_helpers(self):
        fake, c = make()
        fake.loaded = "x"
        self.assertEqual(c.loaded_model(), "x")
        self.assertEqual(c.stats()["tokens_per_second"], 12.5)
        fake.fail["/health"] = 1
        self.assertIsNone(c.loaded_model())


class TheRealTransport(unittest.TestCase):
    """urllib is patched: the request that would go out is inspected, and nothing is sent."""

    def run_transport(self, method, body, reply=b'{"ok": true}'):
        seen = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return reply

        class Opener:
            def open(self, request, timeout=None):
                seen["request"], seen["timeout"] = request, timeout
                return Response()

        def build_opener(*handlers):
            seen["handlers"] = handlers
            return Opener()

        with mock.patch.object(urllib.request, "build_opener", side_effect=build_opener):
            result = lemonade.urllib_transport(method, BASE + "/chat/completions", body, timeout=7)
        return result, seen

    def test_a_post_with_a_json_body(self):
        result, seen = self.run_transport("POST", {"model": "m", "text": "café"})
        request = seen["request"]
        self.assertEqual(result, {"ok": True})
        self.assertEqual((request.get_method(), request.full_url), ("POST", BASE + "/chat/completions"))
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"model": "m", "text": "café"})
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(seen["timeout"], 7)

    def test_a_get_has_no_body(self):
        _, seen = self.run_transport("GET", None)
        self.assertIsNone(seen["request"].data)
        self.assertEqual(seen["request"].get_method(), "GET")

    def test_the_real_urllib_machinery_end_to_end_without_a_socket(self):
        """Real Request, real opener, real response handling; only the last step (the socket) is replaced."""
        import email.message
        import urllib.response
        seen = {}

        class Response(urllib.response.addinfourl):
            msg = "OK"

        def http_open(handler, request):
            seen["method"], seen["url"], seen["data"] = request.get_method(), request.full_url, request.data
            seen["type"] = request.get_header("Content-type")
            return Response(io.BytesIO(b'{"choices": [{"message": {"content": "hello"}}]}'), email.message.Message(), request.full_url, 200)

        with mock.patch.object(urllib.request.HTTPHandler, "http_open", http_open):
            fake_url = BASE + "/chat/completions"
            client = lemonade.LemonadeClient(log=io.StringIO())          # the default transport
            chat = client.chat(lemonade.QWEN, "system", "user")
            self.assertEqual((chat.text, chat.error), ("hello", None))
            self.assertEqual((seen["method"], seen["url"]), ("GET", BASE + "/stats"))      # the last call is the stats request
            self.assertEqual(lemonade.urllib_transport("POST", fake_url, {"a": 1}), {"choices": [{"message": {"content": "hello"}}]})
            self.assertEqual((seen["method"], json.loads(seen["data"]), seen["type"]), ("POST", {"a": 1}, "application/json"))

    def test_proxy_settings_are_never_used(self):
        _, seen = self.run_transport("GET", None)
        proxy_handlers = [h for h in seen["handlers"] if isinstance(h, urllib.request.ProxyHandler)]
        self.assertEqual(len(proxy_handlers), 1)
        self.assertEqual(proxy_handlers[0].proxies, {})


if __name__ == "__main__":
    unittest.main()
