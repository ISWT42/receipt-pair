"""Replaying saved answers: no model, no network."""

import io
import json
import tempfile
import unittest
from pathlib import Path

from receipt_pair import cli, pair, replay

from .test_pair import EXAMPLES, fake_pair, make_client, toy_items


def saved_rows(fake=None):
    return list(pair.run_arms(make_client(fake or fake_pair()), toy_items()).values())


class Replay(unittest.TestCase):
    def test_a_fresh_run_replays_without_differences(self):
        result = replay.replay(saved_rows(), toy_items())
        self.assertEqual(result["differences"], [])
        self.assertEqual(result["counts"], {"rows": 6, "requests_checked": 6, "requests_equal": 6, "replies_checked": 6,
                                           "replies_equal": 6, "outcomes_checked": 6, "outcomes_equal": 6})

    def test_an_edited_reply_is_caught(self):
        rows = saved_rows()
        rows[0]["reply"] = rows[0]["reply"].replace("shown", "contradicted")
        result = replay.replay(rows, toy_items())
        self.assertIn("the saved reply has a different hash", [d["what"] for d in result["differences"]])

    def test_an_answer_that_does_not_follow_from_its_reply_is_caught(self):
        rows = saved_rows()
        rows[0]["answer"] = "contradicted"
        result = replay.replay(rows, toy_items())
        self.assertEqual([d["what"] for d in result["differences"]], ["the quote check on the saved reply gives a different answer"])
        self.assertEqual((result["differences"][0]["arm"], result["differences"][0]["id"]), (rows[0]["arm"], rows[0]["id"]))

    def test_a_quote_that_was_not_in_the_log_cannot_be_smuggled_back_in(self):
        rows = saved_rows()
        rows[0]["quote"] = "a line the log never had"
        self.assertEqual(len(replay.replay(rows, toy_items())["differences"]), 1)

    def test_a_different_claim_means_a_different_request(self):
        items = toy_items()
        items[0]["claim"] = "I pushed something else."
        result = replay.replay(saved_rows(), items)
        self.assertEqual({d["what"] for d in result["differences"]}, {"the rebuilt request has a different hash"})
        self.assertEqual(len(result["differences"]), 2)           # both models' rows for that item

    def test_an_id_that_is_not_in_the_items_is_reported(self):
        result = replay.replay(saved_rows(), toy_items()[1:])
        self.assertEqual(result["counts"]["no_item"], 2)

    def test_only_the_chosen_arms(self):
        result = replay.replay(saved_rows(), toy_items(), arms=["B"])
        self.assertEqual(result["counts"]["rows"], 3)

    def test_a_row_with_no_reply_must_be_not_shown(self):
        fake = fake_pair()
        fake.fail["/chat/completions"] = 2
        rows = saved_rows(fake)
        dead = next(r for r in rows if r["reply"] is None)
        self.assertEqual(replay.replay(rows, toy_items())["counts"]["no_reply"], 1)
        self.assertEqual(replay.replay(rows, toy_items())["differences"], [])
        dead["answer"] = "shown"
        self.assertEqual(len(replay.replay(rows, toy_items())["differences"]), 1)

    def test_rows_without_hashes_are_still_rederived(self):
        rows = saved_rows()
        for row in rows:
            del row["request_sha256"], row["reply_sha256"]
        result = replay.replay(rows, toy_items())
        self.assertEqual(result["differences"], [])
        self.assertNotIn("requests_checked", result["counts"])
        self.assertEqual(result["counts"]["outcomes_equal"], 6)

    def test_the_report(self):
        text = replay.format_replay(replay.replay(saved_rows(), toy_items()), None, 3)
        for fragment in ("Replayed 6 saved answers against 3 items.", "request hashes equal:  6 of 6", "reply hashes equal:    6 of 6",
                         "answers re-derived:    6 of 6", "No differences."):
            self.assertIn(fragment, text)
        bad = saved_rows()
        bad[0]["answer"] = "contradicted"
        self.assertIn("1 differences:", replay.format_replay(replay.replay(bad, toy_items()), None, 3))


class ReplayCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, rows):
        path = self.dir / "answers.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return str(path)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(["replay", *argv], stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def test_a_clean_file_exits_zero(self):
        code, out, _ = self.run_cli(self.write(saved_rows()), str(EXAMPLES / "toy-items.jsonl"))
        self.assertEqual(code, 0)
        self.assertIn("No differences.", out)

    def test_a_tampered_file_exits_one_and_names_the_row(self):
        rows = saved_rows()
        rows[3]["answer"] = "contradicted"
        code, out, _ = self.run_cli(self.write(rows), str(EXAMPLES / "toy-items.jsonl"))
        self.assertEqual(code, 1)
        self.assertIn("arm " + rows[3]["arm"] + ", id " + rows[3]["id"], out)

    def test_json_and_arms(self):
        code, out, _ = self.run_cli(self.write(saved_rows()), str(EXAMPLES / "toy-items.jsonl"), "--arms", "A", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["counts"]["rows"], 3)

    def test_a_missing_file_is_an_error(self):
        code, _, err = self.run_cli(str(self.dir / "nope.jsonl"), str(EXAMPLES / "toy-items.jsonl"))
        self.assertEqual(code, 1)
        self.assertIn("nope.jsonl", err)


if __name__ == "__main__":
    unittest.main()
