"""Reading logs, items and answer files."""

import json
import tempfile
import unittest
from pathlib import Path

from receipt_pair.files import InputError, load_items, load_rows, read_log

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
TURN = {"cmd": "make build", "output": "Build complete"}


class Logs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def test_a_json_list_of_turns(self):
        self.assertEqual(read_log(self.write("a.json", json.dumps([TURN, TURN]))), [TURN, TURN])

    def test_an_object_with_a_turns_list(self):
        self.assertEqual(read_log(self.write("a.json", json.dumps({"turns": [TURN]}))), [TURN])

    def test_one_turn_object(self):
        self.assertEqual(read_log(self.write("a.json", json.dumps(TURN))), [TURN])

    def test_command_is_accepted_for_cmd(self):
        log = read_log(self.write("a.json", json.dumps([{"command": "ls", "output": "x"}])))
        self.assertEqual(log, [{"cmd": "ls", "output": "x"}])

    def test_json_lines(self):
        text = json.dumps(TURN) + "\n" + json.dumps({"cmd": "ls", "output": "x"}) + "\n"
        self.assertEqual(len(read_log(self.write("a.jsonl", text))), 2)

    def test_plain_text_is_one_turn_with_no_command(self):
        log = read_log(self.write("a.log", "line one\nline two\n"))
        self.assertEqual(log, [{"cmd": "", "output": "line one\nline two\n"}])

    def test_a_json_string_is_output_text(self):
        self.assertEqual(read_log(self.write("a.json", json.dumps("just text"))), [{"cmd": "", "output": "just text"}])

    def test_a_number_is_plain_text(self):
        self.assertEqual(read_log(self.write("a.log", "404"))[0]["output"], "404")

    def test_structured_output_is_kept_as_json_text(self):
        log = read_log(self.write("a.json", json.dumps([{"cmd": "curl x", "output": {"status": 200}}])))
        self.assertEqual(json.loads(log[0]["output"]), {"status": 200})

    def test_a_missing_command_or_output_is_empty_text(self):
        log = read_log(self.write("a.json", json.dumps([{"cmd": "make"}, {"output": "done"}])))
        self.assertEqual(log, [{"cmd": "make", "output": ""}, {"cmd": "", "output": "done"}])

    def test_an_empty_file_is_refused(self):
        with self.assertRaises(InputError):
            read_log(self.write("a.log", "  \n"))

    def test_an_empty_list_is_refused(self):
        with self.assertRaises(InputError):
            read_log(self.write("a.json", "[]"))

    def test_a_turn_without_cmd_or_output_is_refused(self):
        with self.assertRaises(InputError) as caught:
            read_log(self.write("a.json", json.dumps([{"note": "x"}])))
        self.assertIn("turn 1", str(caught.exception))

    def test_a_missing_file_says_so(self):
        with self.assertRaises(InputError) as caught:
            read_log(self.dir / "nope.json")
        self.assertIn("nope.json", str(caught.exception))

    def test_utf8_survives(self):
        self.assertEqual(read_log(self.write("a.json", json.dumps([{"cmd": "x", "output": "café"}], ensure_ascii=False)))[0]["output"],
                         "café")

    def test_the_example_logs_load(self):
        for name in ("push-ok.json", "invoice-failed.json", "dashboard-built-only.json", "log-report-retry.json"):
            self.assertTrue(read_log(EXAMPLES / name), name)


class Items(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "items.jsonl"

    def load(self, *lines):
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return load_items(self.path)

    def item(self, **over):
        base = {"id": "a", "claim": "It built.", "turns": [TURN]}
        base.update(over)
        return json.dumps(base)

    def test_a_good_item(self):
        items = self.load(self.item(truth="not_shown"))
        self.assertEqual(items, [{"id": "a", "claim": "It built.", "turns": [TURN], "truth": "not shown"}])

    def test_truth_is_optional(self):
        self.assertNotIn("truth", self.load(self.item())[0])

    def test_blank_lines_are_skipped_and_ids_may_be_numbers(self):
        items = self.load(self.item(id=7), "", self.item(id=8))
        self.assertEqual([i["id"] for i in items], ["7", "8"])

    def test_errors_name_the_line(self):
        cases = {
            "not json": "line 1",
            json.dumps([1]): "JSON object",
            json.dumps({"id": "a", "claim": "c"}): "missing \"turns\"",
            json.dumps({"id": "a", "turns": [TURN]}): "missing \"claim\"",
            json.dumps({"claim": "c", "turns": [TURN]}): "missing \"id\"",
            self.item(claim="  "): "claim",
            self.item(truth="maybe"): "answer must be one of",
            self.item(turns=[]): "non-empty list of turns",
        }
        for line, fragment in cases.items():
            with self.subTest(line=line):
                with self.assertRaises(InputError) as caught:
                    self.load(line)
                self.assertIn(fragment, str(caught.exception))
                self.assertIn("line 1", str(caught.exception))

    def test_a_repeated_id_is_refused(self):
        with self.assertRaises(InputError) as caught:
            self.load(self.item(), self.item())
        self.assertIn("twice", str(caught.exception))

    def test_an_empty_file_is_refused(self):
        self.path.write_text("\n\n", encoding="utf-8")
        with self.assertRaises(InputError):
            load_items(self.path)

    def test_the_example_item_files_load_with_truth(self):
        toy = load_items(EXAMPLES / "toy-items.jsonl")
        more = load_items(EXAMPLES / "more-items.jsonl")
        self.assertEqual([i["truth"] for i in toy], ["shown", "contradicted", "not shown"])
        self.assertEqual(len(more), 5)
        self.assertTrue(all("truth" in i for i in more))


class Rows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "answers.jsonl"

    def test_rows_load(self):
        self.path.write_text(json.dumps({"arm": "A", "id": 1, "answer": "shown"}) + "\n", encoding="utf-8")
        self.assertEqual(load_rows(self.path), [{"arm": "A", "id": "1", "answer": "shown"}])

    def test_a_last_line_cut_off_by_an_interrupted_run_is_skipped(self):
        self.path.write_text(json.dumps({"arm": "A", "id": "1", "answer": "shown"}) + "\n" + '{"arm": "A", "id": "2", "ans', encoding="utf-8")
        self.assertEqual(len(load_rows(self.path)), 1)

    def test_a_broken_line_in_the_middle_is_an_error(self):
        self.path.write_text("{broken\n" + json.dumps({"arm": "A", "id": "1", "answer": "shown"}) + "\n", encoding="utf-8")
        with self.assertRaises(InputError):
            load_rows(self.path)

    def test_a_row_needs_arm_id_and_answer(self):
        self.path.write_text(json.dumps({"arm": "A", "id": "1"}) + "\n", encoding="utf-8")
        with self.assertRaises(InputError):
            load_rows(self.path)


if __name__ == "__main__":
    unittest.main()
