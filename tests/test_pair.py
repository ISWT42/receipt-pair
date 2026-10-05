"""Building prompts, asking the models, deciding, and running a batch, against the fake Lemonade."""

import io
import tempfile
import unittest
from pathlib import Path

from receipt_pair import client as lemonade
from receipt_pair import files, pair, reader, rules

from .fakes import FakeLemonade, reply_json

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
QWEN, GEMMA = lemonade.QWEN.id, lemonade.GEMMA.id

PUSH_QUOTE = "4f1c2aa..9b3e771  fix-parser -> fix-parser"
MAIL_QUOTE = "smtplib.SMTPAuthenticationError: (535, 'Authentication failed')"


def toy_items():
    return files.load_items(EXAMPLES / "toy-items.jsonl")


def scripted(by_claim):
    """A model that answers by looking for a phrase in the request: {phrase: reply text}."""
    def reply(body):
        user = body["messages"][1]["content"]
        for phrase, text in by_claim.items():
            if phrase in user:
                return text
        raise AssertionError("no scripted reply for this request")
    return reply


GOOD = {"I pushed the parser fix": reply_json("shown", "T1", PUSH_QUOTE),
        "Sent the March invoice": reply_json("contradicted", "T1", MAIL_QUOTE),
        "The dashboard is deployed": reply_json("not_shown")}


def fake_pair(a=GOOD, b=GOOD):
    return FakeLemonade({QWEN: scripted(a), GEMMA: scripted(b)})


def make_client(fake):
    return lemonade.LemonadeClient(transport=fake, log=io.StringIO())


class Prompts(unittest.TestCase):
    def test_the_prompts_are_byte_identical_to_the_sealed_plumbing_run(self):
        """These request hashes were recorded by the real run on Lemonade (its toy-item check). Same bytes, same prompt."""
        golden = {"toy1": "ee66a523cfdb3b49fd7c169b365d75d94dcf6c4bce1e7dc5ea4582c52c7c2f02",
                  "toy2": "dae5a1e0b512ce7ae1644f1252aedd28e62d730eb388b253ff2e2bdad8572dc3",
                  "toy3": "649d56e12f3bc87cf954b2ffa1637850d1e198c27108e4cb1808a5648ddeb870"}
        for item in toy_items():
            _, request = pair.prepare(item["id"], item["claim"], item["turns"])
            self.assertEqual(request.sha256, golden[item["id"]], item["id"])

    def test_the_request_text(self):
        item = toy_items()[0]
        shown, request = pair.prepare(item["id"], item["claim"], item["turns"])
        self.assertEqual(request.system, reader.SYSTEM_PROMPT)
        self.assertIn('CLAIM: "I pushed the parser fix to acme/tools."', request.user)
        self.assertIn("Claimed operation: as stated in the claim", request.user)
        self.assertIn("[T1] step 1 of 1", request.user)
        self.assertIn("COMMAND:\ngit push origin fix-parser", request.user)
        self.assertIn("OUTPUT of T1:\nTo github.com:acme/tools.git", request.user)
        self.assertTrue(request.user.endswith("Answer with JSON only."))

    def test_a_short_log_is_shown_whole(self):
        turn = pair.build_turns("x", [{"cmd": "a", "output": "b\nc"}])[0]
        self.assertEqual((turn.label, turn.row_id, turn.age), ("T1", "x:1", "step 1 of 1"))
        self.assertEqual((turn.command, turn.command_full, turn.output, turn.output_pieces), ("a", "a", "b\nc", ("b\nc",)))
        self.assertEqual((turn.output_omitted, turn.command_omitted, turn.output_chars), (0, 0, 3))

    def test_only_the_last_turns_are_shown_and_positions_stay_true(self):
        log = [{"cmd": "c" + str(i), "output": "o" + str(i)} for i in range(1, 9)]
        shown = pair.build_turns("x", log, pair.Caps(max_turns=3))
        self.assertEqual([t.label for t in shown], ["T1", "T2", "T3"])
        self.assertEqual([t.command for t in shown], ["c6", "c7", "c8"])
        self.assertEqual([t.age for t in shown], ["step 6 of 8", "step 7 of 8", "step 8 of 8"])
        self.assertEqual([t.row_id for t in shown], ["x:6", "x:7", "x:8"])

    def test_a_long_command_is_cut_but_kept_whole_for_the_echo_check(self):
        command = "x" * 2000
        turn = pair.build_turns("x", [{"cmd": command, "output": "ok"}])[0]
        self.assertEqual(turn.command_full, command)
        self.assertLess(len(turn.command), len(command))
        self.assertGreater(turn.command_omitted, 0)

    def test_an_empty_log_is_refused(self):
        with self.assertRaises(ValueError):
            pair.build_turns("x", [])

    def test_a_missing_output_is_shown_as_such(self):
        _, request = pair.prepare("x", "Something ran.", [{"cmd": "make", "output": None}])
        self.assertIn("(no output recorded)", request.user)


class AskOneModel(unittest.TestCase):
    def ask(self, reply, log=None):
        fake = FakeLemonade({QWEN: reply})
        item = toy_items()[0]
        row = pair.ask(make_client(fake), lemonade.QWEN, "A", item["id"], item["claim"], log or item["turns"])
        return row, fake

    def test_a_verified_answer(self):
        row, fake = self.ask(reply_json("shown", "T1", PUSH_QUOTE, reason="The branch was updated."))
        self.assertEqual((row["arm"], row["model"], row["id"]), ("A", QWEN, "toy1"))
        self.assertEqual((row["answer"], row["code"], row["verdict"], row["turn"]), ("shown", "verified", "shown", "T1"))
        self.assertEqual(row["quote"], PUSH_QUOTE)
        self.assertEqual(row["reason"], "The branch was updated.")
        self.assertEqual(row["settings"], {"temperature": 0, "max_tokens": 400, "seed": 42})
        self.assertEqual(len(row["request_sha256"]), 64)
        self.assertEqual(row["reply"], reply_json("shown", "T1", PUSH_QUOTE, reason="The branch was updated."))
        self.assertEqual(row["stats"]["tokens_per_second"], 12.5)
        self.assertNotIn("error_detail", row)

    def test_the_row_has_every_field_the_scorer_and_the_sealed_files_use(self):
        row, _ = self.ask(reply_json("not_shown"))
        for key in ("arm", "model", "id", "answer", "code", "verdict", "quote", "seconds", "request_sha256", "reply_sha256", "reply", "stats"):
            self.assertIn(key, row)

    def test_an_invented_quote_is_not_shown(self):
        row, _ = self.ask(reply_json("shown", "T1", "Everything up-to-date"))
        self.assertEqual((row["answer"], row["code"], row["verdict"]), ("not shown", "unverified_quote", "shown"))

    def test_a_server_that_does_not_answer_is_recorded_as_such(self):
        fake = FakeLemonade({QWEN: reply_json("not_shown")})
        fake.fail["/chat/completions"] = 9
        item = toy_items()[0]
        row = pair.ask(make_client(fake), lemonade.QWEN, "A", item["id"], item["claim"], item["turns"])
        self.assertEqual((row["answer"], row["code"], row["reply"]), ("not shown", "backend_error", None))
        self.assertIn("connection refused", row["error_detail"])

    def test_an_unparseable_reply_is_not_shown(self):
        row, _ = self.ask("I think it worked!")
        self.assertEqual((row["answer"], row["code"]), ("not shown", "unparseable_reply"))


class Deciding(unittest.TestCase):
    def rows(self, a_answer, b_answer):
        def row(arm, model, answer):
            quote = {"shown": PUSH_QUOTE, "contradicted": MAIL_QUOTE, "not shown": ""}[answer]
            return {"arm": arm, "model": model, "id": "x", "answer": answer, "code": "verified", "verdict": answer,
                    "turn": "T1" if quote else None, "quote": quote, "reason": "r", "seconds": 1.0}
        return row("A", QWEN, a_answer), row("B", GEMMA, b_answer)

    def test_both_shown_lists_both_quotes(self):
        decision = pair.decide(*self.rows("shown", "shown"), "r2")
        self.assertEqual(decision["answer"], "shown")
        self.assertEqual([q["arm"] for q in decision["quotes"]], ["A", "B"])
        self.assertTrue(all(q["quote"] == PUSH_QUOTE for q in decision["quotes"]))

    def test_not_shown_has_no_quote(self):
        decision = pair.decide(*self.rows("shown", "contradicted"), "r2")
        self.assertEqual((decision["answer"], decision["quotes"]), ("not shown", []))

    def test_r2_lets_a_lone_contradicted_stand_with_its_quote(self):
        decision = pair.decide(*self.rows("not shown", "contradicted"), "r2")
        self.assertEqual(decision["answer"], "contradicted")
        self.assertEqual([q["arm"] for q in decision["quotes"]], ["B"])

    def test_r1_lets_a_lone_shown_stand_but_r2_does_not(self):
        rows = self.rows("shown", "not shown")
        self.assertEqual(pair.decide(*rows, "r1")["answer"], "shown")
        self.assertEqual(pair.decide(*rows, "r2")["answer"], "not shown")

    def test_every_shown_or_contradicted_answer_carries_a_quote(self):
        for a in rules.ANSWERS:
            for b in rules.ANSWERS:
                for rule in rules.RULES:
                    decision = pair.decide(*self.rows(a, b), rule)
                    if decision["answer"] != rules.NOT_SHOWN:
                        self.assertTrue(decision["quotes"], (a, b, rule))
                        self.assertTrue(all(q["quote"] for q in decision["quotes"]), (a, b, rule))

    def test_the_rule_is_recorded(self):
        self.assertEqual(pair.decide(*self.rows("shown", "shown"), "R3")["rule"], "r3")


class CheckOneClaim(unittest.TestCase):
    def test_the_toy_claims_end_to_end(self):
        expected = {"toy1": "shown", "toy2": "contradicted", "toy3": "not shown"}
        for item in toy_items():
            decision = pair.check_claim(item["claim"], item["turns"], client=make_client(fake_pair()))
            self.assertEqual(decision["answer"], expected[item["id"]], item["id"])
            self.assertEqual(decision["rule"], "r2")

    def test_one_model_at_a_time_in_order(self):
        fake = fake_pair()
        item = toy_items()[0]
        pair.check_claim(item["claim"], item["turns"], client=make_client(fake))
        self.assertEqual(fake.sequence(), [("chat", QWEN), ("unload", QWEN), ("chat", GEMMA)])

    def test_a_log_may_be_given_in_any_shape_the_loader_accepts(self):
        for log in ([{"command": "git push origin fix-parser", "output": toy_items()[0]["turns"][0]["output"]}],
                    {"turns": toy_items()[0]["turns"]}, toy_items()[0]["turns"][0]):
            decision = pair.check_claim(toy_items()[0]["claim"], log, client=make_client(fake_pair()))
            self.assertEqual(decision["answer"], "shown")
        with self.assertRaises(files.InputError):
            pair.check_claim("c", [], client=make_client(fake_pair()))

    def test_a_pair_needs_two_models(self):
        with self.assertRaises(ValueError):
            pair.check_claim("c", [{"cmd": "", "output": "o"}], client=make_client(fake_pair()), models=[lemonade.QWEN])

    def test_a_model_that_disagrees_keeps_shown_from_standing_under_r2(self):
        b = dict(GOOD)
        b["I pushed the parser fix"] = reply_json("not_shown")
        item = toy_items()[0]
        decision = pair.check_claim(item["claim"], item["turns"], client=make_client(fake_pair(GOOD, b)), rule="r2")
        self.assertEqual(decision["answer"], "not shown")
        decision = pair.check_claim(item["claim"], item["turns"], client=make_client(fake_pair(GOOD, b)), rule="r1")
        self.assertEqual(decision["answer"], "shown")

    def test_the_models_get_their_own_extras(self):
        fake = fake_pair()
        item = toy_items()[0]
        pair.check_claim(item["claim"], item["turns"], client=make_client(fake))
        bodies = {b["model"]: b for _, p, b in fake.calls if p == "/chat/completions"}
        self.assertNotIn("chat_template_kwargs", bodies[QWEN])
        self.assertEqual(bodies[GEMMA]["chat_template_kwargs"], {"enable_thinking": False})


class RunABatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "answers.jsonl"

    def run_batch(self, fake=None, items=None, **kwargs):
        fake = fake or fake_pair()
        events = []
        rows = pair.run_arms(make_client(fake), items or toy_items(), out_path=self.out, progress=events.append, **kwargs)
        return rows, fake, events

    def test_all_of_one_model_then_all_of_the_other(self):
        _, fake, events = self.run_batch()
        self.assertEqual(fake.sequence(), [("chat", QWEN)] * 3 + [("unload", QWEN)] + [("chat", GEMMA)] * 3)
        self.assertEqual([(e["arm"], e["number"], e["of"]) for e in events],
                         [("A", 1, 3), ("A", 2, 3), ("A", 3, 3), ("B", 1, 3), ("B", 2, 3), ("B", 3, 3)])

    def test_rows_are_written_as_they_arrive(self):
        rows, _, _ = self.run_batch()
        written = files.load_rows(self.out)
        self.assertEqual(len(written), 6)
        self.assertEqual({(r["arm"], r["id"]) for r in written}, set(rows))
        self.assertEqual([r["arm"] for r in written], ["A", "A", "A", "B", "B", "B"])

    def test_a_second_run_asks_nothing_again(self):
        self.run_batch()
        _, fake, events = self.run_batch()
        self.assertEqual(fake.chats(), [])
        self.assertEqual(events, [])
        self.assertEqual(len(files.load_rows(self.out)), 6)

    def test_a_changed_claim_is_asked_again(self):
        self.run_batch()
        items = toy_items()
        items[0]["claim"] = "I pushed the parser fix to acme/tools, as I said."
        _, fake, _ = self.run_batch(items=items)
        self.assertEqual(fake.chats(), [QWEN, GEMMA])

    def test_a_changed_model_is_asked_again(self):
        self.run_batch()
        fake = FakeLemonade({"Other-Model-GGUF": scripted(GOOD), GEMMA: scripted(GOOD)})
        _, fake, _ = self.run_batch(fake=fake, models=[lemonade.ModelSpec("Other-Model-GGUF"), lemonade.GEMMA])
        self.assertEqual(fake.chats(), ["Other-Model-GGUF"] * 3)

    def test_rows_where_lemonade_did_not_answer_are_asked_again(self):
        fake = fake_pair()
        fake.fail["/chat/completions"] = 2          # the first claim fails twice for model A: one row with no answer
        rows, _, _ = self.run_batch(fake=fake)
        self.assertEqual(rows[("A", "toy1")]["code"], "backend_error")
        _, fake2, _ = self.run_batch()
        self.assertEqual(fake2.chats(), [QWEN])
        rows = files.load_rows(self.out)
        later = pair.latest_rows(rows)
        self.assertEqual(later[("A", "toy1")]["code"], "verified")

    def test_stops_after_several_failures_in_a_row(self):
        fake = fake_pair()
        fake.fail["/chat/completions"] = 99
        with self.assertRaises(lemonade.BackendError) as caught:
            self.run_batch(fake=fake)
        self.assertIn("3 calls in a row", str(caught.exception))
        self.assertEqual(len(files.load_rows(self.out)), 3)

    def test_without_an_output_file_nothing_is_written(self):
        fake = fake_pair()
        rows = pair.run_arms(make_client(fake), toy_items())
        self.assertEqual(len(rows), 6)
        self.assertFalse(self.out.exists())

    def test_decisions_for_the_batch(self):
        rows, _, _ = self.run_batch()
        decisions = pair.decide_all(rows, toy_items(), "r2")
        self.assertEqual({k: v["answer"] for k, v in decisions.items()},
                         {"toy1": "shown", "toy2": "contradicted", "toy3": "not shown"})

    def test_an_item_one_model_has_not_answered_has_no_decision(self):
        rows, _, _ = self.run_batch()
        del rows[("B", "toy2")]
        self.assertNotIn("toy2", pair.decide_all(rows, toy_items(), "r2"))


if __name__ == "__main__":
    unittest.main()
