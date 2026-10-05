"""The command line, driven in-process against the fake Lemonade. No network, no model."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from receipt_pair import __version__, cli
from receipt_pair import client as lemonade

from .fakes import FakeLemonade, reply_json
from .test_pair import GOOD, GEMMA, QWEN, fake_pair, scripted

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
PUSH = ["--claim", "I pushed the parser fix to acme/tools.", "--log", str(EXAMPLES / "push-ok.json")]


def factory_for(fake):
    def make(**kwargs):
        return lemonade.LemonadeClient(transport=fake, **kwargs)
    return make


class CliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def run_cli(self, argv, fake=None):
        out, err = io.StringIO(), io.StringIO()
        fake = fake or fake_pair()
        code = cli.main(argv, client_factory=factory_for(fake), stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue(), fake

    def exits(self, argv):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                cli.build_parser().parse_args(argv)
        return caught.exception.code, err.getvalue()


class Arguments(CliCase):
    def test_defaults(self):
        args = cli.build_parser().parse_args(["check", "--claim", "x", "--log", "y"])
        self.assertEqual((args.rule, args.model_a, args.model_b), ("r2", "Qwen3-4B-Instruct-2507-GGUF", "Gemma-4-E4B-it-GGUF"))
        self.assertEqual(args.base_url, "http://localhost:13305/api/v1")
        self.assertEqual((args.max_turns, args.allow_remote, args.timeout, args.json), (6, False, 600, False))

    def test_the_rule_may_be_given_in_either_case(self):
        args = cli.build_parser().parse_args(["check", "--claim", "x", "--log", "y", "--rule", "R3"])
        self.assertEqual(args.rule, "r3")

    def test_an_unknown_rule_is_a_usage_error(self):
        code, err = self.exits(["check", "--claim", "x", "--log", "y", "--rule", "majority"])
        self.assertEqual(code, 2)
        self.assertIn("unknown rule", err)

    def test_a_claim_and_a_log_are_required(self):
        self.assertEqual(self.exits(["check", "--claim", "x"])[0], 2)
        self.assertEqual(self.exits(["check", "--log", "y"])[0], 2)

    def test_batch_needs_items_and_score_needs_two_files(self):
        self.assertEqual(self.exits(["batch"])[0], 2)
        self.assertEqual(self.exits(["score", "answers.jsonl"])[0], 2)

    def test_a_command_is_required(self):
        self.assertEqual(self.exits([])[0], 2)

    def test_version(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as caught:
            cli.build_parser().parse_args(["--version"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn(__version__, out.getvalue())

    def test_help_for_every_command_works(self):
        for argv in (["--help"], ["check", "--help"], ["batch", "--help"], ["score", "--help"], ["verify", "--help"]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as caught:
                cli.build_parser().parse_args(argv)
            self.assertEqual(caught.exception.code, 0, argv)
            self.assertIn("usage", out.getvalue())

    def test_model_extras_default_to_the_sealed_ones_for_the_default_models_only(self):
        args = cli.build_parser().parse_args(["check", "--claim", "x", "--log", "y"])
        a, b = cli.model_specs(args)
        self.assertEqual((a.extra, b.extra), ({}, {"chat_template_kwargs": {"enable_thinking": False}}))
        args = cli.build_parser().parse_args(["check", "--claim", "x", "--log", "y", "--model-b", "Other-GGUF"])
        self.assertEqual(cli.model_specs(args)[1].extra, {})
        args = cli.build_parser().parse_args(["check", "--claim", "x", "--log", "y", "--model-b", "Other-GGUF",
                                              "--extra-b", '{"top_k": 1}'])
        self.assertEqual(cli.model_specs(args)[1].extra, {"top_k": 1})

    def test_bad_extras_are_reported(self):
        for extra in ("not json", "[1]"):
            code, out, err, _ = self.run_cli(["check", *PUSH, "--extra-a", extra])
            self.assertEqual(code, 1)
            self.assertIn("--extra-a", err)

    def test_a_remote_address_is_refused_unless_allowed(self):
        code, out, err, fake = self.run_cli(["check", *PUSH, "--base-url", "http://10.1.2.3:13305/api/v1"])
        self.assertEqual(code, 1)
        self.assertIn("not on this machine", err)
        self.assertEqual(fake.calls, [])

    def test_max_turns_must_be_positive(self):
        code, _, err, _ = self.run_cli(["check", *PUSH, "--max-turns", "0"])
        self.assertEqual(code, 1)
        self.assertIn("--max-turns", err)


class Check(CliCase):
    def test_a_claim_that_both_models_find_shown(self):
        code, out, err, fake = self.run_cli(["check", *PUSH])
        self.assertEqual(code, 0)
        self.assertIn("Answer: SHOWN", out)
        self.assertIn('R2, "shown needs both"', out)
        self.assertIn("Qwen3-4B-Instruct-2507-GGUF (A): shown", out)
        self.assertIn("Gemma-4-E4B-it-GGUF (B): shown", out)
        self.assertIn("4f1c2aa..9b3e771  fix-parser -> fix-parser", out)
        self.assertIn("character for character", out)
        self.assertIn("asking Qwen3-4B-Instruct-2507-GGUF", err)
        self.assertIn("asking Gemma-4-E4B-it-GGUF", err)
        self.assertEqual(fake.chats(), [QWEN, GEMMA])

    def test_the_other_toy_claims(self):
        cases = {"invoice-failed.json": ("Sent the March invoice to Dana.", "Answer: CONTRADICTED"),
                 "dashboard-built-only.json": ("The dashboard is deployed.", "Answer: NOT SHOWN")}
        for name, (claim, expected) in cases.items():
            code, out, _, _ = self.run_cli(["check", "--claim", claim, "--log", str(EXAMPLES / name)])
            self.assertEqual(code, 0, name)
            self.assertIn(expected, out, name)

    def test_json_output(self):
        code, out, _, _ = self.run_cli(["check", *PUSH, "--json"])
        result = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual((result["answer"], result["rule"], result["claim"]), ("shown", "r2", "I pushed the parser fix to acme/tools."))
        self.assertEqual([q["arm"] for q in result["quotes"]], ["A", "B"])
        self.assertNotIn("rows", result)
        self.assertEqual(result["models"]["A"]["code"], "verified")

    def test_save_keeps_both_raw_replies(self):
        target = self.dir / "receipt.json"
        code, _, _, _ = self.run_cli(["check", *PUSH, "--save", str(target)])
        saved = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(saved["answer"], "shown")
        self.assertEqual(set(saved["rows"]), {"A", "B"})
        self.assertIn("reply", saved["rows"]["A"])
        self.assertEqual(len(saved["rows"]["A"]["request_sha256"]), 64)

    def test_a_refused_quote_is_explained(self):
        lying = dict(GOOD)
        lying["I pushed the parser fix"] = reply_json("shown", "T1", "Everything up-to-date")
        fake = FakeLemonade({QWEN: scripted(lying), GEMMA: scripted(GOOD)})
        code, out, _, _ = self.run_cli(["check", *PUSH], fake=fake)
        self.assertEqual(code, 0)
        self.assertIn("Answer: NOT SHOWN", out)
        self.assertIn("The two models differ", out)
        self.assertIn("Refused: the model said \"shown\" citing T1, but the quote is not verbatim", out)
        self.assertIn("Everything up-to-date", out)

    def test_the_rule_changes_the_answer(self):
        half = dict(GOOD)
        half["I pushed the parser fix"] = reply_json("not_shown")
        fake = lambda: FakeLemonade({QWEN: scripted(GOOD), GEMMA: scripted(half)})   # noqa: E731
        self.assertIn("Answer: SHOWN", self.run_cli(["check", *PUSH, "--rule", "r1"], fake=fake())[1])
        self.assertIn("Answer: NOT SHOWN", self.run_cli(["check", *PUSH, "--rule", "r2"], fake=fake())[1])
        self.assertIn("Answer: NOT SHOWN", self.run_cli(["check", *PUSH, "--rule", "r3"], fake=fake())[1])

    def test_a_server_that_is_down_is_an_error_not_an_answer(self):
        fake = fake_pair()
        fake.fail["/chat/completions"] = 99
        code, out, err, _ = self.run_cli(["check", *PUSH], fake=fake)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("did not answer at http://localhost:13305/api/v1", err)
        self.assertIn("connection refused", err)

    def test_a_missing_log_is_an_error(self):
        code, out, err, fake = self.run_cli(["check", "--claim", "x", "--log", str(self.dir / "nope.json")])
        self.assertEqual(code, 1)
        self.assertIn("nope.json", err)
        self.assertEqual(fake.calls, [])

    def test_a_long_log_is_cut_to_the_last_turns_and_says_so(self):
        log = self.dir / "long.json"
        log.write_text(json.dumps([{"cmd": "step " + str(i), "output": "out " + str(i)} for i in range(1, 11)]), encoding="utf-8")
        fake = FakeLemonade({QWEN: reply_json("not_shown"), GEMMA: reply_json("not_shown")})
        code, _, err, fake = self.run_cli(["check", "--claim", "All steps ran.", "--log", str(log), "--max-turns", "4"], fake=fake)
        self.assertEqual(code, 0)
        self.assertIn("10 turns; the models see the last 4", err)
        user = next(b for _, p, b in fake.calls if p == "/chat/completions")["messages"][1]["content"]
        self.assertIn("[T1] step 7 of 10", user)
        self.assertNotIn("step 6 of 10", user)


class Batch(CliCase):
    def test_the_toy_items(self):
        answers = self.dir / "answers.jsonl"
        code, out, err, fake = self.run_cli(["batch", str(EXAMPLES / "toy-items.jsonl"), "--out", str(answers)])
        self.assertEqual(code, 0)
        for fragment in ("toy1", "toy2", "toy3", "3 items: 1 shown, 1 contradicted, 1 not shown", str(answers), "score"):
            self.assertIn(fragment, out)
        self.assertIn("[A Qwen3-4B-I 1/3] toy1: shown (verified,", err)
        self.assertEqual(len(answers.read_text(encoding="utf-8").splitlines()), 6)
        self.assertEqual(fake.chats(), [QWEN] * 3 + [GEMMA] * 3)

    def test_limit(self):
        answers = self.dir / "answers.jsonl"
        code, out, _, fake = self.run_cli(["batch", str(EXAMPLES / "toy-items.jsonl"), "--out", str(answers), "--limit", "1"])
        self.assertEqual(code, 0)
        self.assertEqual(fake.chats(), [QWEN, GEMMA])
        self.assertNotIn("toy2", out)

    def test_json_lines(self):
        code, out, _, _ = self.run_cli(["batch", str(EXAMPLES / "toy-items.jsonl"), "--out", str(self.dir / "a.jsonl"), "--json"])
        lines = [json.loads(line) for line in out.splitlines()]
        self.assertEqual([(d["id"], d["answer"]) for d in lines], [("toy1", "shown"), ("toy2", "contradicted"), ("toy3", "not shown")])
        self.assertEqual(lines[0]["quotes"][0]["quote"], "4f1c2aa..9b3e771  fix-parser -> fix-parser")

    def test_a_second_run_resumes_without_asking_again(self):
        argv = ["batch", str(EXAMPLES / "toy-items.jsonl"), "--out", str(self.dir / "a.jsonl")]
        self.run_cli(argv)
        code, out, _, fake = self.run_cli(argv)
        self.assertEqual(code, 0)
        self.assertEqual(fake.chats(), [])
        self.assertIn("3 items", out)

    def test_batch_then_score(self):
        answers = str(self.dir / "a.jsonl")
        items = str(EXAMPLES / "toy-items.jsonl")
        self.run_cli(["batch", items, "--out", answers])
        code, out, _, _ = self.run_cli(["score", answers, items])
        self.assertEqual(code, 0)
        self.assertIn("Scored 3 items: 1 shown, 1 contradicted, 1 not shown.", out)
        self.assertIn("3 of 3", out)

    def test_a_bad_items_file_is_an_error(self):
        bad = self.dir / "bad.jsonl"
        bad.write_text('{"id": "a"}\n', encoding="utf-8")
        code, _, err, fake = self.run_cli(["batch", str(bad), "--out", str(self.dir / "a.jsonl")])
        self.assertEqual(code, 1)
        self.assertIn("line 1", err)
        self.assertEqual(fake.calls, [])

    def test_a_dead_server_stops_the_batch_after_three_failures(self):
        fake = fake_pair()
        fake.fail["/chat/completions"] = 99
        code, _, err, _ = self.run_cli(["batch", str(EXAMPLES / "toy-items.jsonl"), "--out", str(self.dir / "a.jsonl")], fake=fake)
        self.assertEqual(code, 1)
        self.assertIn("3 calls in a row", err)


class Score(CliCase):
    def write_answers(self, rows):
        path = self.dir / "answers.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return str(path)

    def test_the_report_and_the_json(self):
        rows = [{"arm": arm, "id": i, "answer": a, "model": m}
                for arm, m in (("A", "ModelA"), ("B", "ModelB"))
                for i, a in (("toy1", "shown"), ("toy2", "contradicted"), ("toy3", "shown"))]
        answers = self.write_answers(rows)
        items = str(EXAMPLES / "toy-items.jsonl")
        code, out, _, _ = self.run_cli(["score", answers, items])
        self.assertEqual(code, 0)
        self.assertIn("ModelA alone (A)", out)
        self.assertIn("2 of 3", out)
        self.assertIn("False \"shown\"", out)
        code, out, _, _ = self.run_cli(["score", answers, items, "--json"])
        result = json.loads(out)
        self.assertEqual(result["arms"]["A"]["right"]["k"], 2)
        self.assertEqual(result["arms"]["A"]["false_shown"], {"k": 1, "n": 2, "ci95": result["arms"]["A"]["false_shown"]["ci95"]})
        self.assertEqual(result["pairs"]["R2"]["false_shown"]["k"], 1)

    def test_items_without_truth_cannot_be_scored(self):
        items = self.dir / "items.jsonl"
        items.write_text(json.dumps({"id": "a", "claim": "c", "turns": [{"cmd": "x", "output": "y"}]}) + "\n", encoding="utf-8")
        answers = self.write_answers([{"arm": "A", "id": "a", "answer": "shown"}, {"arm": "B", "id": "a", "answer": "shown"}])
        code, _, err, _ = self.run_cli(["score", answers, str(items)])
        self.assertEqual(code, 1)
        self.assertIn("truth", err)

    def test_a_missing_arm_is_an_error(self):
        answers = self.write_answers([{"arm": "A", "id": "toy1", "answer": "shown"}])
        code, _, err, _ = self.run_cli(["score", answers, str(EXAMPLES / "toy-items.jsonl")])
        self.assertEqual(code, 1)
        self.assertIn("'B'", err)

    def test_arms_must_be_two_names(self):
        answers = self.write_answers([{"arm": "A", "id": "toy1", "answer": "shown"}])
        code, _, err, _ = self.run_cli(["score", answers, str(EXAMPLES / "toy-items.jsonl"), "--arms", "A"])
        self.assertEqual(code, 1)
        self.assertIn("--arms", err)


class Verify(CliCase):
    def verify(self, reply, *extra):
        return self.run_cli(["verify", "--log", str(EXAMPLES / "push-ok.json"), "--reply", str(EXAMPLES / reply), *extra])

    def test_a_good_reply_is_verified(self):
        code, out, _, fake = self.verify("reply-good.json")
        self.assertEqual(code, 0)
        self.assertIn("Answer: SHOWN  (verified)", out)
        self.assertEqual(fake.calls, [])          # no server is involved

    def test_an_invented_quote_is_refused(self):
        code, out, _, _ = self.verify("reply-invented-quote.json")
        self.assertIn("Answer: NOT SHOWN  (unverified_quote)", out)
        self.assertIn("Everything up-to-date", out)

    def test_a_quote_from_the_command_is_refused(self):
        self.assertIn("(quote_from_command)", self.verify("reply-quote-from-command.json")[1])

    def test_json(self):
        result = json.loads(self.verify("reply-invented-quote.json", "--json")[1])
        self.assertEqual((result["answer"], result["code"], result["verdict"]), ("not shown", "unverified_quote", "shown"))

    def test_the_reply_may_come_from_standard_input(self):
        text = (EXAMPLES / "reply-good.json").read_text(encoding="utf-8")
        with mock.patch.object(sys, "stdin", io.StringIO(text)):
            code, out, _, _ = self.run_cli(["verify", "--log", str(EXAMPLES / "push-ok.json"), "--reply", "-"])
        self.assertIn("Answer: SHOWN", out)

    def test_a_missing_reply_file_is_an_error(self):
        code, _, err, _ = self.run_cli(["verify", "--log", str(EXAMPLES / "push-ok.json"), "--reply", str(self.dir / "nope.json")])
        self.assertEqual(code, 1)
        self.assertIn("nope.json", err)


if __name__ == "__main__":
    unittest.main()
