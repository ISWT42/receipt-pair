"""The gate demo (examples/gate-demo/demo.py), end to end: a real throwaway project, a real test run, a real git push to
a local bare repository. Only the two models are the in-memory fake, and the gate runs in this process instead of
its own. No network, no model, nothing outside a temporary folder."""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from receipt_pair import cli
from receipt_pair import client as lemonade

from .fakes import FakeLemonade, reply_json
from .test_cli import factory_for

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("gate_demo", ROOT / "examples" / "gate-demo" / "demo.py")
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)

QWEN, GEMMA = lemonade.QWEN.id, lemonade.GEMMA.id
LEMONADE_IS_UP = lambda url: {"status": "ok", "model_loaded": None}      # noqa: E731
REAL_RUN = subprocess.run


def models_that_quote_the_deciding_line(body):
    """What a careful model would say about a unittest log: the failing line, or the OK line."""
    user = body["messages"][1]["content"]
    if "FAILED (failures=2)" in user:
        return reply_json("contradicted", "T1", "FAILED (failures=2)", reason="The test run failed.")
    return reply_json("shown", "T1", "OK", reason="The tests passed.")


@contextlib.contextmanager
def chdir(path):
    before = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(before)


class Session:
    """One run of the demo with a fake Lemonade, remembering what each gate run did."""

    def __init__(self, base, replies=None):
        self.base = str(base)
        self.out = io.StringIO()
        self.fake = FakeLemonade(replies or {QWEN: models_that_quote_the_deciding_line, GEMMA: models_that_quote_the_deciding_line})
        self.gates = []

    def gate_runner(self, words, cwd, env):
        """The gate, as the demo would start it, but in this process and against the fake. The command it runs (git push)
        is real; its output is captured here instead of going to the test run's output."""
        out, err, pushed = io.StringIO(), io.StringIO(), []

        def capturing(command, **kwargs):
            result = REAL_RUN(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                              errors="replace", **kwargs)
            pushed.append(result.stdout)
            return result

        log_before = json.loads((Path(cwd) / demo.LOG).read_text(encoding="utf-8"))
        with mock.patch.dict(os.environ, env, clear=True), chdir(cwd), mock.patch("receipt_pair.gate.subprocess.run", capturing):
            status = cli.main(list(words), client_factory=factory_for(self.fake), stdout=out, stderr=err)
        folder = Path(cwd).parent
        self.gates.append({"words": list(words), "status": status, "stdout": out.getvalue(), "stderr": err.getvalue(),
                           "push_output": "".join(pushed), "log_when_called": log_before,
                           "server_after": demo.server_has(folder), "chats_so_far": list(self.fake.chats())})
        return status

    def run(self, *argv, health=LEMONADE_IS_UP):
        return demo.main([*argv, "--dir", self.base], out=self.out, gate_runner=self.gate_runner, health=health)

    @property
    def folder(self):
        return demo.folder_for(self.base)

    @property
    def project(self):
        return self.folder / "project"


def git_output(folder, cwd, *args):
    return demo.git(folder, cwd, *args).stdout.strip()


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class TheTwoTakes(unittest.TestCase):
    """setup, then Take 1, then Take 2, run once for all the tests in this class."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.session = Session(cls.tmp.name)
        cls.exit_status = cls.session.run("all", "--no-pause")
        cls.take1, cls.take2 = cls.session.gates

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_demo_itself_finishes_cleanly(self):
        self.assertEqual(self.exit_status, 0)

    def test_the_folder_is_made_in_the_folder_it_was_given_and_is_marked_as_the_demos(self):
        self.assertEqual(self.session.folder, Path(self.tmp.name) / "receipt-pair-gate-demo")
        self.assertTrue((self.session.folder / demo.MARKER).exists())
        self.assertTrue((self.session.folder / "server.git").is_dir())

    def test_both_gate_runs_are_the_command_on_the_screen(self):
        expected = ["gate", "--claim", "The tests pass, ready to push.", "--log", "test-run.log", "--", "git", "push", "origin", "main"]
        self.assertEqual([g["words"] for g in self.session.gates], [expected, expected])
        self.assertIn('> python -m receipt_pair gate --claim "The tests pass, ready to push." --log test-run.log -- git push origin main',
                      self.session.out.getvalue())

    def test_take_1_the_bug_makes_the_tests_fail_and_the_gate_blocks_the_push(self):
        self.assertEqual(self.take1["status"], 4)
        self.assertIn("Answer: CONTRADICTED", self.take1["stdout"])
        self.assertEqual(self.take1["stdout"].count("FAILED (failures=2)"), 2)             # both models quote the failing line
        self.assertEqual(self.take1["stdout"].rstrip().splitlines()[-1], "contradicted: the log shows it failed")
        self.assertNotIn("the command runs", self.take1["stdout"])
        self.assertEqual(self.take1["push_output"], "")                                    # git was never started
        self.assertTrue(self.take1["server_after"].startswith("nothing"))

    def test_take_2_the_tests_really_pass_and_the_gate_lets_the_push_through(self):
        self.assertEqual(self.take2["status"], 0)
        self.assertIn("Answer: SHOWN", self.take2["stdout"])
        self.assertEqual(self.take2["stdout"].count("quote from T1:\n    OK"), 2)         # both models quote the OK line
        self.assertIn('shown: the log shows it worked, so the command runs: ["git", "push", "origin", "main"]', self.take2["stdout"])
        self.assertIn("main -> main", self.take2["push_output"])
        self.assertTrue(self.take2["server_after"].endswith("Include tax in the cart total"), self.take2["server_after"])

    def test_the_server_got_exactly_the_fixed_commit_and_nothing_else_was_pushed(self):
        folder = self.session.folder
        project_head = git_output(folder, self.session.project, "rev-parse", "main")
        self.assertEqual(git_output(folder, folder / "server.git", "rev-parse", "main"), project_head)
        self.assertEqual(git_output(folder, folder / "server.git", "for-each-ref", "--format=%(refname)"), "refs/heads/main")
        self.assertEqual(git_output(folder, self.session.project, "log", "--format=%s").splitlines(),
                         ["Include tax in the cart total", "Add the cart total"])

    def test_the_log_was_written_by_the_script_from_the_real_test_run_before_the_gate_was_asked(self):
        for take, verdict in ((self.take1, "FAILED (failures=2)"), (self.take2, "\n\nOK")):
            turns = take["log_when_called"]
            self.assertEqual(len(turns), 1)
            self.assertEqual(turns[0]["cmd"], "python -m unittest -v")
            # "tests", as the claim says. A log that says "Ran 1 test" made Qwen3 call a passing run contradicted (see TEST_CART).
            self.assertIn("Ran 2 tests in", turns[0]["output"])
            self.assertTrue(turns[0]["output"].endswith(verdict), turns[0]["output"])
        for line in ("AssertionError: 15.0 != 16.5", "AssertionError: 10.0 != 12.0"):             # both tests fail with the bug
            self.assertIn(line, self.take1["log_when_called"][0]["output"])
        for name in ("test_tax_is_added", "test_tax_on_one_item"):                                 # and both pass without it
            self.assertIn(name + " (test_cart.CartTests." + name + ") ... ok", self.take2["log_when_called"][0]["output"])

    def test_the_models_were_asked_for_every_gate_run_and_both_answered_before_the_push(self):
        self.assertEqual(self.take1["chats_so_far"], [QWEN, GEMMA])
        self.assertEqual(self.take2["chats_so_far"], [QWEN, GEMMA, QWEN, GEMMA])

    def test_the_screen_says_what_is_scripted_and_what_is_live(self):
        text = self.session.out.getvalue()
        self.assertEqual(text.count('scripted: the agent says: "The tests pass, ready to push."'), 2)
        self.assertIn("live: my script runs the tests and writes the log. The agent never touches it.", text)
        self.assertIn("live: the server has: nothing. The push never reached it.", text)
        self.assertIn("Scripted: the agent's message, the bug and its fix, the order of the steps.", text)
        self.assertIn("Live: the test run, the log, both model checks, the gate's decision, the push.", text)

    def test_the_exit_statuses_are_explained(self):
        text = self.session.out.getvalue()
        self.assertIn("Gate exit status: 4 (contradicted, so the push did not run).", text)
        self.assertIn("Gate exit status: 0 (the gate let the push run).", text)

    def test_nothing_the_demo_ran_could_reach_the_users_git_settings(self):
        env = demo.environment(self.session.folder)
        self.assertEqual(Path(env["GIT_CONFIG_GLOBAL"]), self.session.folder / "gitconfig")
        self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(git_output(self.session.folder, self.session.project, "log", "-1", "--format=%an <%ae>"),
                         "Gate Demo <gate-demo@example.invalid>")

    def test_clean_removes_the_folder_it_made(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        session = Session(other.name)
        self.assertEqual(session.run("setup"), 0)
        self.assertTrue(session.folder.exists())
        self.assertEqual(session.run("clean"), 0)
        self.assertFalse(session.folder.exists())


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class WhenALiveModelDisagrees(unittest.TestCase):
    """The demo is live: a model can block the good claim in Take 2. The screen must say so, not pretend."""

    def test_take_2_blocked_by_a_model_is_reported_as_blocked_and_the_server_stays_empty(self):
        def gemma_unsure(body):
            user = body["messages"][1]["content"]
            return reply_json("not_shown") if "\n\nOK" in user else models_that_quote_the_deciding_line(body)

        with tempfile.TemporaryDirectory() as tmp:
            session = Session(tmp, {QWEN: models_that_quote_the_deciding_line, GEMMA: gemma_unsure})
            self.assertEqual(session.run("all", "--no-pause"), 0)
            take2 = session.gates[1]
            self.assertEqual(take2["status"], 3)
            self.assertIn("Gate exit status: 3 (not shown, so the push did not run).", session.out.getvalue())
            self.assertTrue(take2["server_after"].startswith("nothing"))
            self.assertEqual(take2["push_output"], "")


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class TheUsersGitEnvironmentStaysOut(unittest.TestCase):
    def test_git_variables_in_the_environment_do_not_get_in(self):
        """Run from inside a git hook, or by someone with GIT_DIR or GIT_AUTHOR_NAME set, the demo must still build its own repos."""
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as elsewhere:
            hostile = {"GIT_DIR": str(Path(elsewhere) / "not-a-repo"), "GIT_WORK_TREE": elsewhere,
                       "GIT_AUTHOR_NAME": "Someone Else", "GIT_COMMITTER_NAME": "Someone Else"}
            with mock.patch.dict(os.environ, hostile):
                session = Session(tmp)
                self.assertEqual(session.run("setup"), 0)
                names = git_output(session.folder, session.project, "log", "-1", "--format=%an|%cn")
            self.assertEqual(names, "Gate Demo|Gate Demo")
            self.assertEqual(list(Path(elsewhere).iterdir()), [])       # nothing was written where GIT_DIR pointed


class SafetyWithoutGit(unittest.TestCase):
    """The checks that need no git: what the demo refuses to touch, and what it says when something is missing."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.session = Session(self.tmp.name)

    def run_quietly(self, *argv, **kwargs):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = self.session.run(*argv, **kwargs)
        return code, err.getvalue()

    def fake_setup(self):
        """A folder that looks like the demo's, without running git."""
        self.session.project.mkdir(parents=True)
        (self.session.folder / demo.MARKER).write_text(demo.MARKER_TEXT, encoding="utf-8")
        (self.session.project / "cart.py").write_text(demo.CART_BUGGY, encoding="utf-8")

    def test_the_default_folder_is_in_the_system_temp_folder(self):
        self.assertEqual(demo.folder_for(None), Path(tempfile.gettempdir()) / "receipt-pair-gate-demo")

    def test_a_folder_the_demo_did_not_make_is_never_touched(self):
        self.session.folder.mkdir()
        (self.session.folder / "precious.txt").write_text("mine", encoding="utf-8")
        for step in ("setup", "clean", "all"):
            code, err = self.run_quietly(step, "--no-pause")
            self.assertEqual(code, 1, step)
            self.assertIn("Not touching it", err)
            self.assertEqual((self.session.folder / "precious.txt").read_text(encoding="utf-8"), "mine")
        self.assertEqual(self.session.gates, [])

    def test_clean_when_there_is_nothing_to_clean(self):
        self.assertEqual(self.session.run("clean"), 0)
        self.assertIn("Nothing to remove", self.session.out.getvalue())

    def test_the_takes_need_setup_first(self):
        for step in ("take1", "take2"):
            code, err = self.run_quietly(step)
            self.assertEqual(code, 1, step)
            self.assertIn("python examples/gate-demo/demo.py setup", err)
        self.assertEqual(self.session.gates, [])

    def test_lemonade_not_answering_stops_the_take_before_anything_runs(self):
        self.fake_setup()
        code, err = self.run_quietly("take1", health=lambda url: None)
        self.assertEqual(code, 1)
        self.assertIn("Lemonade is not answering at http://localhost:13305/api/v1", err)
        self.assertIn(QWEN, err)
        self.assertEqual(self.session.gates, [])
        self.assertFalse((self.session.project / demo.LOG).exists())

    def test_take_1_refuses_to_run_on_a_folder_whose_bug_is_already_fixed(self):
        self.fake_setup()
        (self.session.project / "cart.py").write_text(demo.CART_FIXED, encoding="utf-8")
        code, err = self.run_quietly("take1")
        self.assertEqual(code, 1)
        self.assertIn("already fixed", err)

    def test_a_remote_lemonade_address_is_refused_as_everywhere_else(self):
        self.fake_setup()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = demo.main(["take1", "--dir", self.tmp.name, "--base-url", "http://10.0.0.5:13305/api/v1"], out=io.StringIO())
        self.assertEqual(code, 1)
        self.assertIn("not on this machine", err.getvalue())

    def test_the_pause_happens_only_in_all_and_never_with_no_pause(self):
        prompts = []
        with mock.patch.object(demo.Demo, "setup"), mock.patch.object(demo.Demo, "take1"), mock.patch.object(demo.Demo, "take2"):
            demo.main(["all", "--dir", self.tmp.name], out=io.StringIO(), pause=prompts.append)
            self.assertEqual(len(prompts), 2)
            self.assertIn("Take 1", prompts[0])
            self.assertIn("Take 2", prompts[1])
            demo.main(["all", "--dir", self.tmp.name, "--no-pause"], out=io.StringIO(), pause=prompts.append)
            demo.main(["take1", "--dir", self.tmp.name], out=io.StringIO(), pause=prompts.append)
            self.assertEqual(len(prompts), 2)

    def test_the_steps_the_parser_accepts(self):
        parser = demo.build_parser()
        self.assertEqual(parser.parse_args([]).step, "all")
        for step in ("all", "setup", "take1", "take2", "clean"):
            self.assertEqual(parser.parse_args([step]).step, step)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["take3"])

    def test_the_project_text_is_what_the_screen_says_it_is(self):
        self.assertIn("round(sum(prices), 2)", demo.CART_BUGGY)
        self.assertIn("round(sum(prices) * (1 + tax), 2)", demo.CART_FIXED)
        self.assertEqual(demo.CART_FIXED.count("\n"), demo.CART_BUGGY.count("\n"))      # a one-line fix
        self.assertEqual(demo.TEST_CART.count("def test_"), 2)                          # two tests: the claim says "tests"
        self.assertEqual(demo.CLAIM, "The tests pass, ready to push.")

    def test_the_project_text_avoids_the_words_the_reader_treats_as_failure_markers(self):
        from receipt_pair import reader
        for text in (demo.CART_BUGGY, demo.CART_FIXED, demo.TEST_CART):
            self.assertEqual(reader.failure_markers(text), [], text)


if __name__ == "__main__":
    unittest.main()
