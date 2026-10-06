"""The gate's documentation: every command it shows is one the parsers accept, and the numbers and words it uses hold."""

import importlib.util
import json
import re
import shlex
import unittest
from pathlib import Path

from receipt_pair import cli, gate

from .test_readme import README, RUN2_SCORE, section

ROOT = Path(__file__).resolve().parent.parent
DOCS = {"README.md": README,
        "DEMO-GATE.md": (ROOT / "DEMO-GATE.md").read_text(encoding="utf-8"),
        "examples/gate-demo/README.md": (ROOT / "examples" / "gate-demo" / "README.md").read_text(encoding="utf-8")}

_spec = importlib.util.spec_from_file_location("gate_demo", ROOT / "examples" / "gate-demo" / "demo.py")
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)


def commands(text, needle):
    """Every line inside a fenced code block that is a command containing needle, as a list of words (shell-style quoting)."""
    found, in_fence = [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
        elif in_fence and needle in line and line.strip().startswith("python "):
            found.append(shlex.split(line.strip()))
    return found


class EveryCommandShownIsOneTheParserTakes(unittest.TestCase):
    def test_gate_commands(self):
        total = 0
        for name, text in DOCS.items():
            for words in commands(text, "receipt_pair gate"):
                total += 1
                self.assertEqual(words[:3], ["python", "-m", "receipt_pair"], (name, words))
                argv, command = cli.split_command(words[3:])
                self.assertTrue(command, (name, words))                         # something to run after --
                args = cli.build_parser().parse_args(argv)
                self.assertEqual(args.command, "gate", (name, words))
                self.assertTrue(args.claim and args.log, (name, words))
        self.assertGreaterEqual(total, 2)                                        # the README and the demo's README

    def test_the_gate_command_in_the_docs_is_the_one_the_demo_runs(self):
        shown = "python -m receipt_pair " + demo.show_command(demo.gate_words(demo.DEFAULT_BASE_URL))
        for name in ("README.md", "examples/gate-demo/README.md"):
            self.assertIn(shown, DOCS[name], name)

    def test_demo_commands(self):
        parser = demo.build_parser()
        seen = set()
        for name, text in DOCS.items():
            for words in commands(text, "examples/gate-demo/demo.py"):
                self.assertEqual(words[:2], ["python", "examples/gate-demo/demo.py"], (name, words))
                seen.add(parser.parse_args(words[2:]).step)
        self.assertEqual(seen, {"setup", "take1", "take2", "clean"})

    def test_the_recording_script_pastes_the_commands_in_the_order_it_uses_them(self):
        order = [words[2] for words in commands(DOCS["DEMO-GATE.md"], "examples/gate-demo/demo.py")]
        self.assertEqual(order[:4], ["setup", "take1", "take2", "clean"])        # the list of four
        self.assertEqual(order[4:], ["setup", "take1", "take2", "clean"])        # and again, in the sections


class TheNumbersTheGateDocsQuote(unittest.TestCase):
    """The README and the recording script quote run 2's R2 row: check it against the sealed score file."""

    def setUp(self):
        sealed = json.loads(RUN2_SCORE.read_text(encoding="utf-8"))
        primary = sealed["sets"]["primary_201_300"]["run2-local"]
        self.r1, self.r2 = primary["pair_AB_R1"], primary["pair_AB_R2"]

    def test_the_readme_section(self):
        text = section("## Gate an action on a receipt")
        false_shown, kept = self.r2["false_shown"], self.r2["true_shown_kept"]
        self.assertIn("passed %d of the %d claims the log doesn't back, and kept %d of the %d true" % (
            false_shown["k"], false_shown["n"], kept["k"], kept["n"]), text)
        r1 = self.r1["false_shown"]
        self.assertEqual(r1["n"], false_shown["n"])
        self.assertIn("R1 is looser (it passed %d of those %d)" % (r1["k"], r1["n"]), text)

    def test_the_recording_script(self):
        text = DOCS["DEMO-GATE.md"]
        false_shown, kept = self.r2["false_shown"], self.r2["true_shown_kept"]
        self.assertIn("passed %d of %d claims the log doesn't back, and kept %d of %d true ones" % (
            false_shown["k"], false_shown["n"], kept["k"], kept["n"]), text)
        self.assertIn("%d of %d (false \"shown\", rule R2) and %d of %d (true \"shown\" kept, rule R2)" % (
            false_shown["k"], false_shown["n"], kept["k"], kept["n"]), text)
        self.assertIn("100 invented logs", text)


class WhatTheGateDocsSay(unittest.TestCase):
    def test_the_readme_table_of_outcomes_matches_the_code(self):
        text = section("## Gate an action on a receipt")
        for line in (gate.PLAIN["not shown"], gate.PLAIN["contradicted"], gate.PLAIN["could not check"]):
            self.assertIn("`" + line + "`", text)
        self.assertIn("`shown: the log shows it worked, so the command runs: git`", text)
        rows = {}
        for row in text.splitlines():
            cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
            if row.startswith("| ") and len(cells) == 4:
                rows[cells[0]] = cells[3]
        self.assertEqual((rows["not shown"], rows["contradicted"]), (str(gate.EXIT_NOT_SHOWN), str(gate.EXIT_CONTRADICTED)))
        self.assertEqual(rows["Lemonade did not answer, or the log can't be read"], str(gate.EXIT_COULD_NOT_CHECK))

    def test_the_demo_readme_lists_what_is_scripted_and_what_is_live(self):
        readme = DOCS["examples/gate-demo/README.md"]
        for fragment in ("The agent's message", "The bug and its one-line fix", "The order of the steps", "The test run",
                         "The log, which the demo script writes", "Both model checks", "The gate's decision", "The git push"):
            self.assertIn(fragment, readme)
        self.assertIn("There is no real agent in the demo", readme)

    def test_the_recording_script_and_the_demo_pages_avoid_two_words(self):
        pages = {"DEMO-GATE.md": DOCS["DEMO-GATE.md"], "examples/gate-demo/README.md": DOCS["examples/gate-demo/README.md"],
                 "the README's gate section": section("## Gate an action on a receipt")}
        for name, text in pages.items():
            for word in ("first", "novel"):
                self.assertIsNone(re.search(r"\b" + word + r"\b", text, re.I), (name, word))

    def test_the_recording_script_is_about_three_minutes_of_voice(self):
        spoken = re.findall(r"\*\*Say[^\n]*\n((?:>.*\n?)+)", DOCS["DEMO-GATE.md"])
        words = sum(len(re.sub(r"^>\s?", "", block, flags=re.M).split()) for block in spoken)
        self.assertEqual(len(spoken), 7)
        self.assertTrue(300 <= words <= 400, words)                              # about 2:30 at a calm pace

    def test_the_recording_script_names_the_two_takes_and_the_exact_result_lines(self):
        text = DOCS["DEMO-GATE.md"]
        for fragment in ("Take 1", "Take 2", "contradicted: the log shows it failed",
                         "shown: the log shows it worked, so the command runs", "Gate exit status: 4", "Gate exit status: 0"):
            self.assertIn(fragment, text)


if __name__ == "__main__":
    unittest.main()
