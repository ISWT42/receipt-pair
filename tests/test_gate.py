"""The gate, driven in-process against the fake Lemonade. The command it guards is a real one: a Python one-liner that
writes a file when it runs, so "the command ran" and "the command did not run" are facts about the disk.
No network, no model."""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from receipt_pair import cli, gate, pair, rules

from .fakes import FakeLemonade, reply_json
from .test_cli import factory_for
from .test_pair import GEMMA, GOOD, MAIL_QUOTE, PUSH_QUOTE, QWEN, fake_pair, scripted

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"

# The three toy claims: with GOOD scripted for both models the pair says shown, contradicted and not shown.
SHOWN_CASE = ("push-ok.json", "I pushed the parser fix to acme/tools.")
CONTRADICTED_CASE = ("invoice-failed.json", "Sent the March invoice to Dana.")
NOT_SHOWN_CASE = ("dashboard-built-only.json", "The dashboard is deployed.")

# Writes the arguments it was given (after the file name) to that file. Proof that it ran, and with what.
WRITE_ARGUMENTS = "import json, sys; open(sys.argv[1], 'w').write(json.dumps(sys.argv[2:]))"


def marker_command(path, *arguments):
    return [sys.executable, "-c", WRITE_ARGUMENTS, str(path), *arguments]


def one_model_says(answer_for_b):
    """Model A as in GOOD, model B with its answer to the push claim replaced."""
    b = dict(GOOD)
    b["I pushed the parser fix"] = answer_for_b
    return fake_pair(GOOD, b)


class GateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.marker = self.dir / "ran.json"

    @property
    def ran(self):
        return self.marker.exists()

    def arguments_it_ran_with(self):
        return json.loads(self.marker.read_text(encoding="utf-8"))

    def gate(self, case=SHOWN_CASE, command=None, *, fake=None, options=()):
        log, claim = case
        argv = ["gate", "--claim", claim, "--log", str(EXAMPLES / log), *options, "--",
                *(command if command is not None else marker_command(self.marker))]
        out, err = io.StringIO(), io.StringIO()
        fake = fake or fake_pair()
        code = cli.main(argv, client_factory=factory_for(fake), stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue(), fake

    def usage_error(self, argv):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                cli.main(argv, client_factory=factory_for(fake_pair()), stdout=io.StringIO(), stderr=io.StringIO())
        return caught.exception.code, err.getvalue()


class TheCommandRunsOnlyWhenShown(GateCase):
    def test_shown_runs_the_command(self):
        code, out, err, fake = self.gate(SHOWN_CASE, marker_command(self.marker, "one", "two"))
        self.assertEqual(code, 0)
        self.assertTrue(self.ran)
        self.assertEqual(self.arguments_it_ran_with(), ["one", "two"])
        self.assertIn("Answer: SHOWN", out)
        self.assertEqual(out.count(PUSH_QUOTE), 2)                      # both models' quotes are on the screen
        self.assertIn("shown: the log shows it worked, so the command runs: ", out)
        self.assertEqual(fake.chats(), [QWEN, GEMMA])
        self.assertIn("asking " + QWEN, err)

    def test_contradicted_blocks_the_command(self):
        code, out, err, fake = self.gate(CONTRADICTED_CASE)
        self.assertEqual(code, 4)
        self.assertFalse(self.ran)
        self.assertIn("Answer: CONTRADICTED", out)
        self.assertEqual(out.count(MAIL_QUOTE), 2)
        self.assertEqual(out.rstrip().splitlines()[-1], "contradicted: the log shows it failed")
        self.assertNotIn("the command runs", out)
        self.assertEqual(fake.chats(), [QWEN, GEMMA])

    def test_not_shown_blocks_the_command(self):
        code, out, err, fake = self.gate(NOT_SHOWN_CASE)
        self.assertEqual(code, 3)
        self.assertFalse(self.ran)
        self.assertIn("Answer: NOT SHOWN", out)
        self.assertEqual(out.rstrip().splitlines()[-1], "not shown: no receipt, no action")

    def test_a_blocked_gate_ends_with_one_plain_line_after_the_answer_and_the_quotes(self):
        for case, line in ((CONTRADICTED_CASE, gate.PLAIN["contradicted"]), (NOT_SHOWN_CASE, gate.PLAIN["not shown"])):
            _, out, _, _ = self.gate(case)
            *report, blank, plain = out.rstrip("\n").split("\n")
            self.assertEqual((blank, plain), ("", line))
            self.assertTrue(report[0].startswith("Claim:  "))
            self.assertIn("Answer: ", "\n".join(report))

    def test_models_that_disagree_do_not_unlock_it_under_r2_or_r3(self):
        for rule in ("r2", "r3"):
            code, out, _, _ = self.gate(fake=one_model_says(reply_json("not_shown")), options=["--rule", rule])
            self.assertEqual(code, 3, rule)
            self.assertFalse(self.ran, rule)
            self.assertIn("The two models differ", out)

    def test_a_lone_shown_unlocks_it_only_under_r1_because_that_is_what_r1_says(self):
        code, _, _, _ = self.gate(fake=one_model_says(reply_json("not_shown")), options=["--rule", "r1"])
        self.assertEqual(code, 0)
        self.assertTrue(self.ran)

    def test_shown_against_contradicted_blocks(self):
        reply = reply_json("contradicted", "T1", "To github.com:acme/tools.git")
        code, out, _, _ = self.gate(fake=one_model_says(reply))
        self.assertEqual(code, 3)
        self.assertFalse(self.ran)

    def test_two_models_that_invent_a_quote_do_not_unlock_it(self):
        lying = {**GOOD, "I pushed the parser fix": reply_json("shown", "T1", "Everything up-to-date")}
        code, out, _, _ = self.gate(fake=fake_pair(lying, lying))
        self.assertEqual(code, 3)
        self.assertFalse(self.ran)
        self.assertIn("Refused: the model said \"shown\" citing T1, but the quote is not verbatim", out)

    def test_a_model_that_cites_a_failure_line_as_its_receipt_does_not_unlock_it(self):
        lying = {**GOOD, "I pushed the parser fix": reply_json("shown", "T1", "To github.com:acme/tools.git failed")}
        log = self.dir / "failed.json"
        log.write_text(json.dumps([{"cmd": "git push", "output": "To github.com:acme/tools.git failed"}]), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        argv = ["gate", "--claim", "I pushed the parser fix to acme/tools.", "--log", str(log), "--", *marker_command(self.marker)]
        code = cli.main(argv, client_factory=factory_for(fake_pair(lying, lying)), stdout=out, stderr=err)
        self.assertEqual(code, 3)
        self.assertFalse(self.ran)
        self.assertIn("shown citing a failure line", out.getvalue())


class FailingClosed(GateCase):
    def test_a_server_that_does_not_answer_blocks_the_command(self):
        fake = fake_pair()
        fake.fail["/chat/completions"] = 99
        code, out, err, _ = self.gate(fake=fake)
        self.assertEqual(code, 1)
        self.assertFalse(self.ran)
        self.assertIn("Answer: COULD NOT CHECK", out)
        self.assertEqual(out.rstrip().splitlines()[-1], "could not check: no receipt, no action")
        self.assertIn("did not answer for " + QWEN + ", " + GEMMA + " at http://localhost:13305/api/v1", err)
        self.assertIn("connection refused", err)

    def test_one_model_that_does_not_answer_blocks_it_even_when_the_other_says_shown_under_r1(self):
        def crashes(body):
            raise OSError("model B crashed")
        fake = FakeLemonade({QWEN: scripted(GOOD), GEMMA: crashes})
        code, out, err, _ = self.gate(fake=fake, options=["--rule", "r1"])
        self.assertEqual(code, 1)
        self.assertFalse(self.ran)
        self.assertIn("did not answer for " + GEMMA, err)
        self.assertNotIn(QWEN + " at", err)
        self.assertEqual(out.rstrip().splitlines()[-1], "could not check: no receipt, no action")

    def test_a_timeout_blocks_it_too(self):
        def too_slow(body):
            raise TimeoutError("timed out")
        fake = FakeLemonade({QWEN: too_slow, GEMMA: scripted(GOOD)})
        code, _, _, _ = self.gate(fake=fake)
        self.assertEqual(code, 1)
        self.assertFalse(self.ran)

    def test_a_missing_log_stops_before_any_model_is_asked(self):
        argv = ["gate", "--claim", "x", "--log", str(self.dir / "nope.json"), "--", *marker_command(self.marker)]
        out, err, fake = io.StringIO(), io.StringIO(), fake_pair()
        code = cli.main(argv, client_factory=factory_for(fake), stdout=out, stderr=err)
        self.assertEqual(code, 1)
        self.assertFalse(self.ran)
        self.assertEqual(fake.calls, [])
        self.assertIn("nope.json", err.getvalue())
        self.assertEqual(out.getvalue().strip(), "could not check: no receipt, no action")

    def test_a_remote_address_blocks_it_without_sending_the_log(self):
        code, out, err, fake = self.gate(options=["--base-url", "http://10.1.2.3:13305/api/v1"])
        self.assertEqual(code, 1)
        self.assertFalse(self.ran)
        self.assertEqual(fake.calls, [])
        self.assertIn("not on this machine", err)
        self.assertEqual(out.strip(), "could not check: no receipt, no action")

    def test_an_empty_claim_blocks_it(self):
        for claim in ("", "   "):
            code, out, err, fake = self.gate(("push-ok.json", claim))
            self.assertEqual(code, 1)
            self.assertFalse(self.ran)
            self.assertEqual(fake.calls, [])
            self.assertIn("the claim is empty", err)
            self.assertEqual(out.strip(), "could not check: no receipt, no action")

    def test_a_bug_in_the_check_blocks_it_and_says_so(self):
        with mock.patch.object(pair, "check_claim", side_effect=RuntimeError("boom")):
            code, out, err, _ = self.gate()
        self.assertEqual(code, 1)
        self.assertFalse(self.ran)
        self.assertIn("receipt_pair: RuntimeError: boom", err)
        self.assertEqual(out.strip(), "could not check: no receipt, no action")

    def test_a_bug_after_the_check_still_does_not_run_the_command(self):
        with mock.patch.object(gate, "judge", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.gate()
        self.assertFalse(self.ran)

    def test_a_bad_option_for_the_check_blocks_it(self):
        for options in (["--extra-a", "not json"], ["--max-turns", "0"]):
            code, out, err, fake = self.gate(options=options)
            self.assertEqual(code, 1, options)
            self.assertFalse(self.ran, options)
            self.assertEqual(fake.calls, [], options)
            self.assertTrue(out.strip().endswith("could not check: no receipt, no action"), options)


class DryRun(GateCase):
    def test_a_dry_run_asks_the_models_and_runs_nothing(self):
        with mock.patch("receipt_pair.gate.subprocess.run") as run:
            code, out, _, fake = self.gate(options=["--dry-run"])
        self.assertEqual(code, 0)
        run.assert_not_called()
        self.assertFalse(self.ran)
        self.assertEqual(fake.chats(), [QWEN, GEMMA])
        self.assertIn("Answer: SHOWN", out)
        last = out.rstrip().splitlines()[-1]
        prefix = "shown: the log shows it worked. Dry run, so nothing runs. It would run: "
        self.assertEqual(last, prefix + gate.describe(marker_command(self.marker)))      # the command, argument by argument

    def test_a_dry_run_that_would_be_blocked_says_so_and_exits_the_same_way(self):
        for case, status in ((CONTRADICTED_CASE, 4), (NOT_SHOWN_CASE, 3)):
            code, out, _, _ = self.gate(case, options=["--dry-run"])
            self.assertEqual(code, status)
            self.assertFalse(self.ran)
            self.assertNotIn("Dry run", out)

    def test_a_dry_run_with_no_server_still_blocks(self):
        fake = fake_pair()
        fake.fail["/chat/completions"] = 99
        code, _, _, _ = self.gate(fake=fake, options=["--dry-run"])
        self.assertEqual(code, 1)


class RunningTheCommand(GateCase):
    def test_the_commands_own_exit_status_is_the_gates(self):
        code, _, _, _ = self.gate(command=[sys.executable, "-c", "import sys; sys.exit(7)"])
        self.assertEqual(code, 7)

    def test_the_models_have_answered_before_the_command_starts(self):
        seen = []
        fake = fake_pair()

        def record(*args, **kwargs):
            seen.append(list(fake.chats()))
            return types.SimpleNamespace(returncode=0)

        with mock.patch("receipt_pair.gate.subprocess.run", side_effect=record):
            code, _, _, _ = self.gate(fake=fake)
        self.assertEqual(code, 0)
        self.assertEqual(seen, [[QWEN, GEMMA]])

    def test_the_command_is_started_once_as_a_list_and_without_a_shell(self):
        with mock.patch("receipt_pair.gate.subprocess.run", return_value=types.SimpleNamespace(returncode=0)) as run:
            self.gate(command=["git", "push", "origin", "main"])
        run.assert_called_once_with(["git", "push", "origin", "main"], shell=False, check=False)

    def test_a_blocked_gate_never_starts_anything(self):
        for case in (CONTRADICTED_CASE, NOT_SHOWN_CASE):
            with mock.patch("receipt_pair.gate.subprocess.run") as run:
                self.gate(case)
            run.assert_not_called()

    def test_flags_after_the_double_dash_belong_to_the_command(self):
        theirs = ["--rule", "r1", "--claim", "other", "--dry-run", "-h", "--"]
        code, out, _, _ = self.gate(command=marker_command(self.marker, *theirs))
        self.assertEqual(code, 0)
        self.assertEqual(self.arguments_it_ran_with(), theirs)
        self.assertIn('R2, "shown needs both"', out)            # the gate's own options were not touched

    def test_there_is_no_shell_so_shell_words_arrive_as_they_are(self):
        awkward = ["two words", "semi;colon", "and && and", "$HOME", "%PATH%", "*", "~", "back`tick", "it's",
                   'say "hi"', ">" + str(self.dir / "stolen.txt"), "| more", ""]
        code, _, _, _ = self.gate(command=marker_command(self.marker, *awkward))
        self.assertEqual(code, 0)
        self.assertEqual(self.arguments_it_ran_with(), awkward)
        self.assertFalse((self.dir / "stolen.txt").exists())

    def test_the_commands_output_comes_after_the_gates_even_when_the_output_is_a_pipe(self):
        """A pipe is block-buffered: without a flush before the command starts, the gate's report would arrive last."""
        child = "\n".join([
            "import sys",
            "from unittest import mock",
            "from receipt_pair import cli, pair",
            "def row(arm):",
            "    return {'arm': arm, 'model': 'm' + arm, 'id': 'x', 'answer': 'shown', 'code': 'verified', 'verdict': 'shown',",
            "            'turn': 'T1', 'quote': 'OK', 'reason': 'r', 'seconds': 1.0}",
            "decision = pair.decide(row('A'), row('B'), 'r2')",
            "decision['rows'] = {}",
            "log = sys.argv[1]",
            "with mock.patch.object(pair, 'check_claim', return_value=decision):",
            "    sys.exit(cli.main(['gate', '--claim', 'x', '--log', log, '--', sys.executable, '-c', \"print('CHILD OUTPUT')\"]))",
        ])
        result = subprocess.run([sys.executable, "-c", child, str(EXAMPLES / "push-ok.json")], cwd=str(ROOT),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("Answer: SHOWN", result.stdout)
        self.assertLess(result.stdout.index("shown: the log shows it worked, so the command runs"), result.stdout.index("CHILD OUTPUT"))

    def test_a_command_that_cannot_be_found_is_reported_after_the_check(self):
        code, out, err, fake = self.gate(command=["no-such-program-for-the-gate", "--flag"])
        self.assertEqual(code, 127)
        self.assertIn("the command was not found: no-such-program-for-the-gate", err)
        self.assertIn("no shell", err)
        self.assertEqual(fake.chats(), [QWEN, GEMMA])
        self.assertIn("Answer: SHOWN", out)

    def test_a_command_that_cannot_be_started_is_reported(self):
        # No real file here: if the gate ever handed a document to a shell, the shell would open it in a program.
        with mock.patch("receipt_pair.gate.subprocess.run", side_effect=PermissionError(13, "Permission denied")):
            code, out, err, _ = self.gate(command=["not-a-program"])
        self.assertEqual(code, 126)
        self.assertIn("the command could not be started: not-a-program (Permission denied)", err)
        self.assertIn("Answer: SHOWN", out)


class Judging(unittest.TestCase):
    """judge() on the decisions pair.decide makes, for every pair of answers under every rule."""

    def rows(self, a_answer, b_answer, a_code="verified", b_code="verified"):
        def row(arm, model, answer, code):
            quote = {"shown": PUSH_QUOTE, "contradicted": MAIL_QUOTE, "not shown": ""}[answer]
            return {"arm": arm, "model": model, "id": "x", "answer": answer, "code": code, "verdict": answer,
                    "turn": "T1" if quote else None, "quote": quote, "reason": "r", "seconds": 1.0}
        return row("A", QWEN, a_answer, a_code), row("B", GEMMA, b_answer, b_code)

    def test_it_runs_exactly_when_the_pair_says_shown(self):
        for a in rules.ANSWERS:
            for b in rules.ANSWERS:
                for rule in rules.RULES:
                    judgment = gate.judge(pair.decide(*self.rows(a, b), rule))
                    pair_says = rules.combine(a, b, rule)
                    self.assertEqual(judgment.run, pair_says == rules.SHOWN, (a, b, rule))
                    self.assertEqual(judgment.answer, pair_says, (a, b, rule))

    def test_under_r2_and_r3_shown_needs_both_models(self):
        for rule in ("r2", "r3"):
            for a in rules.ANSWERS:
                for b in rules.ANSWERS:
                    self.assertEqual(gate.judge(pair.decide(*self.rows(a, b), rule)).run, (a, b) == ("shown", "shown"), (a, b, rule))

    def test_the_exit_status_says_why_it_did_not_run(self):
        statuses = {"shown": 0, "not shown": 3, "contradicted": 4}
        for answer, status in statuses.items():
            judgment = gate.judge(pair.decide(*self.rows(answer, answer), "r2"))
            self.assertEqual(judgment.status, status, answer)

    def test_a_call_that_failed_blocks_under_every_rule(self):
        for code in pair.RETRY_CODES:
            for rule in rules.RULES:
                for failed in (0, 1):
                    codes = ["verified", "verified"]
                    codes[failed] = code
                    judgment = gate.judge(pair.decide(*self.rows("shown", "shown", *codes), rule))
                    self.assertFalse(judgment.run, (code, rule, failed))
                    self.assertEqual((judgment.answer, judgment.status), ("could not check", 1), (code, rule, failed))

    def test_shown_with_no_quote_is_not_a_receipt(self):
        models = {"A": {"code": "verified"}, "B": {"code": "verified"}}
        for quotes in ([], None, [{"arm": "A", "quote": ""}], [{"arm": "A", "quote": "   "}, {"arm": "B", "quote": "x"}]):
            judgment = gate.judge({"answer": "shown", "quotes": quotes, "models": models})
            self.assertEqual((judgment.run, judgment.answer, judgment.status), (False, "not shown", 3), quotes)

    def test_an_odd_decision_is_could_not_check(self):
        models = {"A": {"code": "verified"}, "B": {"code": "verified"}}
        for decision in ({}, {"answer": "maybe", "models": models}, {"answer": "shown", "quotes": [{"quote": "q"}], "models": {"A": {}}},
                         {"answer": "shown", "quotes": [{"quote": "q"}]}):
            judgment = gate.judge(decision)
            self.assertEqual((judgment.run, judgment.answer, judgment.status), (False, "could not check", 1), decision)


class PlainWords(unittest.TestCase):
    def test_describe_keeps_every_argument_whole(self):
        self.assertEqual(gate.describe(["git", "commit", "-m", "two words", ""]), '["git", "commit", "-m", "two words", ""]')
        self.assertEqual(gate.describe(["café"]), '["café"]')

    def test_the_four_plain_lines(self):
        command = ["git", "push"]
        shown = gate.Judgment("shown", True, 0)
        self.assertEqual(gate.plain_line(shown, command), 'shown: the log shows it worked, so the command runs: ["git", "push"]')
        self.assertEqual(gate.plain_line(shown, command, dry_run=True),
                         'shown: the log shows it worked. Dry run, so nothing runs. It would run: ["git", "push"]')
        self.assertEqual(gate.plain_line(gate.Judgment("not shown", False, 3), command), "not shown: no receipt, no action")
        self.assertEqual(gate.plain_line(gate.Judgment("contradicted", False, 4), command), "contradicted: the log shows it failed")
        self.assertEqual(gate.plain_line(gate.Judgment("could not check", False, 1), command), "could not check: no receipt, no action")


class RunCommand(unittest.TestCase):
    def runner(self, returncode=0, error=None):
        calls = []

        def run(*args, **kwargs):
            calls.append((args, kwargs))
            if error:
                raise error
            return types.SimpleNamespace(returncode=returncode)
        run.calls = calls
        return run

    def test_the_arguments_are_a_list_of_strings_with_no_shell(self):
        run = self.runner()
        self.assertEqual(gate.run_command(["git", "push", "origin", "main"], run), 0)
        self.assertEqual(run.calls, [((["git", "push", "origin", "main"],), {"shell": False, "check": False})])

    def test_a_stop_by_signal_is_128_plus_the_signal(self):
        self.assertEqual(gate.run_command(["x"], self.runner(returncode=-9)), 137)

    def test_other_statuses_pass_through(self):
        for status in (0, 1, 2, 3, 4, 255):
            self.assertEqual(gate.run_command(["x"], self.runner(returncode=status)), status)

    def test_not_found_and_not_startable(self):
        with self.assertRaises(gate.CommandNotStarted) as caught:
            gate.run_command(["x"], self.runner(error=FileNotFoundError(2, "No such file or directory")))
        self.assertEqual(caught.exception.status, 127)
        for error in (PermissionError(13, "Permission denied"), OSError(8, "Exec format error"), ValueError("embedded null byte")):
            with self.assertRaises(gate.CommandNotStarted) as caught:
                gate.run_command(["x"], self.runner(error=error))
            self.assertEqual(caught.exception.status, 126, repr(error))

    def test_the_real_subprocess_is_used_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "ran.json"
            self.assertEqual(gate.run_command(marker_command(marker, "a b")), 0)
            self.assertEqual(json.loads(marker.read_text(encoding="utf-8")), ["a b"])


class OnTheCommandLine(GateCase):
    def test_split_command_takes_everything_after_the_first_double_dash(self):
        self.assertEqual(cli.split_command(["gate", "--claim", "c", "--log", "l", "--", "git", "push", "--force", "--", "x"]),
                         (["gate", "--claim", "c", "--log", "l"], ["git", "push", "--force", "--", "x"]))

    def test_split_command_leaves_other_commands_and_a_missing_command_alone(self):
        for argv in (["gate", "--claim", "c", "--log", "l"], ["batch", "--", "items.jsonl"], ["check", "--claim", "--", "--log", "l"], []):
            self.assertEqual(cli.split_command(argv), (argv, None))

    def test_a_missing_command_is_a_usage_error_before_anything_is_asked(self):
        for argv in (["gate", "--claim", "x", "--log", "y"], ["gate", "--claim", "x", "--log", "y", "--"]):
            code, err = self.usage_error(argv)
            self.assertEqual(code, 2)
            self.assertIn("give the command to run after --", err)
            self.assertIn("receipt_pair gate", err)

    def test_the_claim_and_the_log_are_required(self):
        for argv in (["gate", "--log", "y", "--", "x"], ["gate", "--claim", "x", "--", "x"]):
            self.assertEqual(self.usage_error(argv)[0], 2)

    def test_the_options_of_check_are_there(self):
        args = cli.build_parser().parse_args(["gate", "--claim", "x", "--log", "y", "--rule", "R3", "--max-turns", "3",
                                              "--model-b", "Other-GGUF", "--timeout", "9", "--dry-run"])
        self.assertEqual((args.rule, args.max_turns, args.model_b, args.timeout, args.dry_run), ("r3", 3, "Other-GGUF", 9, True))
        defaults = cli.build_parser().parse_args(["gate", "--claim", "x", "--log", "y"])
        self.assertEqual((defaults.rule, defaults.dry_run, defaults.allow_remote), ("r2", False, False))

    def test_help_shows_where_the_command_goes_and_what_the_exit_statuses_mean(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as caught:
            cli.build_parser().parse_args(["gate", "--help"])
        self.assertEqual(caught.exception.code, 0)
        text = out.getvalue()
        self.assertIn("-- COMMAND [ARGS ...]", text)
        for fragment in ("--dry-run", "No receipt, no action", "not shown", "contradicted", "could not check", "127 or 126"):
            self.assertIn(fragment, text)

    def test_gate_is_in_the_top_level_help(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["--help"])
        self.assertIn("gate", out.getvalue())
        self.assertIn("-- git push origin main", out.getvalue())

    def test_the_real_entry_point_reads_its_arguments_from_the_command_line_and_fails_closed(self):
        """A fresh Python process: python -m receipt_pair gate ..., with a log that does not exist (so no model is asked)."""
        result = subprocess.run([sys.executable, "-m", "receipt_pair", "gate", "--claim", "x", "--log", str(self.dir / "nope.json"),
                                 "--", *marker_command(self.marker)], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(self.ran)
        self.assertIn("could not check: no receipt, no action", result.stdout)
        self.assertIn("nope.json", result.stderr)

    def test_the_real_entry_point_reports_a_missing_command(self):
        result = subprocess.run([sys.executable, "-m", "receipt_pair", "gate", "--claim", "x", "--log", "y"],
                                cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 2)
        self.assertIn("give the command to run after --", result.stderr)


if __name__ == "__main__":
    unittest.main()
