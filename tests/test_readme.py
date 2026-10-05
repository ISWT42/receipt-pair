"""The README's numbers, rules and seals, checked against the files in this repo.

If a number in the README is wrong, or a sealed file was changed, one of these fails.
"""

import hashlib
import itertools
import json
import re
import unittest
from pathlib import Path

from receipt_pair import rules

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
RECEIPTS = ROOT / "receipts"

RUN1_SCORE = RECEIPTS / "run1" / "results" / "score-run.json"
RUN1_EXPLORE = RECEIPTS / "run1" / "results" / "explore-run1.json"
RUN2_SCORE = RECEIPTS / "run2" / "results" / "score-run2-local.json"
REPL_SCORE = RECEIPTS / "replication" / "results" / "score-replication.json"

# The fingerprints the seals recorded (and the README quotes).
SEALED = {
    RUN1_SCORE: "564bd53d66d39a6e84e2e18175fb775ff16f95cd3b79a7c54c03069e0d89ad27",
    RUN1_EXPLORE: "35734db2dabd57740f0e148b33d51e4ba64832f25223e15b5f198037b73870b5",
    RUN2_SCORE: "944afdd9cc9d1a4ad970df47544b391cccb7cc63c4abd0dfe86266272d8cdf23",
    REPL_SCORE: "4ab097d4bf1d34b312af5b2601c96177b1d5754c90994729d7582c20ddbe4e47",
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def section(title_start):
    """The README text from a heading that starts with title_start to the next heading of the same or higher level."""
    lines = README.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(title_start))
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("#") and len(lines[i]) - len(lines[i].lstrip("#")) <= level:
            end = i
            break
    return "\n".join(lines[start:end])


def tables(text):
    """Markdown tables in a text: a list of tables, each a list of rows, each a list of cell strings (header first)."""
    out, current = [], []
    for line in text.splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            current.append(cells)
        elif current:
            out.append(current)
            current = []
    if current:
        out.append(current)
    return out


def k_of_n(cell):
    match = re.fullmatch(r"(\d+) of (\d+)", cell)
    assert match, cell
    return int(match.group(1)), int(match.group(2))


def kn(entry):
    return entry["k"], entry["n"]


class SealedFilesAreIntact(unittest.TestCase):
    def test_the_score_files_are_the_sealed_bytes(self):
        for path, expected in SEALED.items():
            self.assertEqual(sha256(path), expected, path.name)

    def test_every_file_a_hash_list_names_that_is_here_matches(self):
        verified = set()
        for listing in RECEIPTS.rglob("*-SHA256.txt"):
            for line in listing.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                match = re.fullmatch(r"([0-9a-f]{64}) \*(.+)", line.strip())
                self.assertIsNotNone(match, (listing.name, line))
                target = (listing.parent / match.group(2)).resolve()
                if target.exists():
                    self.assertEqual(sha256(target), match.group(1), str(target))
                    verified.add(target.name)
        self.assertTrue({"score-run.json", "explore-run1.json", "score-run2-local.json", "score-replication.json"} <= verified, verified)

    def test_the_fingerprints_in_the_readme_are_in_the_hash_lists(self):
        lists = "\n".join(p.read_text(encoding="utf-8") for p in RECEIPTS.rglob("*-SHA256.txt"))
        quoted = re.findall(r"`([0-9a-f]{64})`", section("## Receipts"))
        self.assertGreaterEqual(len(quoted), 5)
        for digest in quoted:
            self.assertIn(digest, lists, digest)

    def test_the_stamp_files_come_in_sets(self):
        for listing in RECEIPTS.rglob("*-SHA256.txt"):
            for ext in (".tsq", ".tsr"):
                self.assertTrue(Path(str(listing) + ext).exists(), listing.name + ext)


class RulesTable(unittest.TestCase):
    def test_the_readme_table_is_what_the_code_does(self):
        text = section("## How it works")
        rule_table = next(t for t in tables(text) if t[0][:2] == ["Model A says", "Model B says"])
        rows = {(r[0], r[1]): tuple(r[2:5]) for r in rule_table[1:]}
        self.assertEqual(len(rows), 9)
        for a, b in itertools.product(rules.ANSWERS, repeat=2):
            self.assertEqual(rows[(a, b)], (rules.r1(a, b), rules.r2(a, b), rules.r3(a, b)), (a, b))


class Run2Numbers(unittest.TestCase):
    def setUp(self):
        self.sealed = json.loads(RUN2_SCORE.read_text(encoding="utf-8"))
        self.primary = self.sealed["sets"]["primary_201_300"]["run2-local"]
        self.fresh = self.sealed["sets"]["fresh_161_300"]["run2-local"]
        self.text = section("### Run 2")
        self.tables = tables(self.text)

    KEYS = {"Qwen3-4B alone": "A", "Gemma-4-E4B alone": "B", "R1": "pair_AB_R1", "R2": "pair_AB_R2", "R3": "pair_AB_R3"}

    def check_table(self, table, columns):
        rows = {r[0]: r[1:] for r in table[1:]}
        self.assertEqual(set(rows), set(self.KEYS))
        for label, cells in rows.items():
            for cell, measure in zip(cells, columns):
                self.assertEqual(k_of_n(cell), kn(self.primary[self.KEYS[label]][measure]), (label, measure))

    def test_the_results_tables(self):
        self.assertEqual(self.tables[0][0], ["Arm", "Right", "False \"shown\"", "True \"shown\" kept"])
        self.check_table(self.tables[0], ["right", "false_shown", "true_shown_kept"])
        self.assertEqual(self.tables[1][0], ["Arm", "Correct \"not shown\"", "False \"contradicted\"", "True \"contradicted\" kept"])
        self.check_table(self.tables[1], ["not_shown_right", "false_contradicted", "true_contradicted_kept"])

    def test_the_set_is_the_primary_one(self):
        truth = {"shown": 32, "contradicted": 34, "not shown": 34}
        self.assertIn("32 shown, 34 contradicted, 34 not shown", self.text)
        self.assertEqual(self.primary["A"]["right"]["n"], 100)
        self.assertEqual(self.primary["A"]["false_shown"]["n"], truth["contradicted"] + truth["not shown"])

    def test_the_prose_numbers(self):
        p, f = self.primary, self.fresh
        errors = p["pair_AB_errors"]
        self.assertEqual(errors["A_wrong"], errors["B_wrong"])
        self.assertIn("Each was wrong on %d of the 100 items, and both were wrong on the same %d of them." %
                      (errors["A_wrong"], errors["both_wrong"]), self.text)
        self.assertIn("(%d of %d, against %d and %d)" % (p["pair_AB_R1"]["false_shown"]["k"], p["pair_AB_R1"]["false_shown"]["n"],
                                                         p["A"]["false_shown"]["k"], p["B"]["false_shown"]["k"]), self.text)
        self.assertIn("cut false \"shown\" to %d of %d" % kn(p["pair_AB_R2"]["false_shown"]), self.text)
        self.assertEqual(kn(p["pair_AB_R2"]["false_shown"]), kn(p["pair_AB_R3"]["false_shown"]))
        self.assertIn("R2 keeps %d of %d where R1 keeps %d, so it gives up %d" % (
            p["pair_AB_R2"]["true_shown_kept"]["k"], p["pair_AB_R2"]["true_shown_kept"]["n"], p["pair_AB_R1"]["true_shown_kept"]["k"],
            p["pair_AB_R2_gives_up_true_shown_vs_R1"]), self.text)
        self.assertIn("from %d of %d (R1) to %d of %d" % (*kn(p["pair_AB_R1"]["false_contradicted"]), *kn(p["pair_AB_R3"]["false_contradicted"])), self.text)
        self.assertIn("%d fewer true \"contradicted\" answers (%d of %d against %d)" % (
            p["pair_AB_R1"]["true_contradicted_kept"]["k"] - p["pair_AB_R3"]["true_contradicted_kept"]["k"],
            p["pair_AB_R3"]["true_contradicted_kept"]["k"], p["pair_AB_R3"]["true_contradicted_kept"]["n"],
            p["pair_AB_R1"]["true_contradicted_kept"]["k"]), self.text)
        self.assertIn("false \"shown\" was %d of %d under R1 and %d of %d under both R2 and R3" % (
            *kn(f["pair_AB_R1"]["false_shown"]), *kn(f["pair_AB_R2"]["false_shown"])), self.text)
        self.assertEqual(f["pair_AB_R2"]["false_shown"], f["pair_AB_R3"]["false_shown"])

        def pct(interval):
            return "%.1f%% to %.1f%%" % (interval[0] * 100, interval[1] * 100)
        self.assertIn("R2's 95%% interval (Wilson) is %s and Qwen alone's is %s" % (
            pct(p["pair_AB_R2"]["false_shown"]["ci95"]), pct(p["A"]["false_shown"]["ci95"])), self.text)
        self.assertEqual((f["pair_AB_R1"]["false_shown"]["n"], p["pair_AB_R1"]["false_shown"]["n"]), (94, 68))

    def test_the_design_hash_in_the_score_file_is_the_one_in_the_seal(self):
        listing = (RECEIPTS / "run2" / "RUN2-DESIGN-SHA256.txt").read_text(encoding="utf-8")
        self.assertIn(self.sealed["design_sha256"], listing)
        bank = (RECEIPTS / "bank" / "completion-claims-001-300-SHA256.txt").read_text(encoding="utf-8")
        self.assertIn(self.sealed["bank_sha256"], bank)
        self.assertIn(self.sealed["bank_sha256"], README)


class Run1Numbers(unittest.TestCase):
    def setUp(self):
        self.score = json.loads(RUN1_SCORE.read_text(encoding="utf-8"))
        self.explore = json.loads(RUN1_EXPLORE.read_text(encoding="utf-8"))
        self.text = section("### Run 1")

    def per_truth(self, entry, label):
        return entry["per_truth"][label]["right"], entry["per_truth"][label]["n"]

    def test_the_table(self):
        table = tables(self.text)[0]
        self.assertEqual(table[0], ["Arm", "Right", "False \"shown\"", "True \"shown\" kept", "Correct \"not shown\""])
        rows = {r[0]: r[1:] for r in table[1:]}
        s = self.score
        not_shown_total = s["A"]["per_truth"]["contradicted"]["n"] + s["A"]["per_truth"]["not shown"]["n"]
        want = {}
        for label, key in (("Qwen3-4B alone", "A"), ("Gemma-4-E4B alone", "B"), ("R1 (sealed)", "pair_AB_two_models")):
            e = s[key]
            want[label] = [(e["right"], 160), (e["false_shown"], not_shown_total), self.per_truth(e, "shown"), self.per_truth(e, "not shown")]
        e = self.explore["rules"]["shown_needs_both AB"]
        shown_k, shown_n = map(int, e["per_truth"]["shown"].split("/"))
        ns_k, ns_n = map(int, e["per_truth"]["not shown"].split("/"))
        want["R2 (chosen afterwards)"] = [(e["right"], 160), (e["shown_when_contradicted"] + e["shown_when_not_shown"], not_shown_total),
                                          (shown_k, shown_n), (ns_k, ns_n)]
        self.assertEqual(set(rows), set(want))
        for label, cells in rows.items():
            self.assertEqual([k_of_n(c) for c in cells], want[label], label)

    def test_the_set(self):
        s = self.score["A"]["per_truth"]
        self.assertIn("%d shown, %d contradicted, %d not shown" % (s["shown"]["n"], s["contradicted"]["n"], s["not shown"]["n"]), self.text)

    def test_the_prose_numbers(self):
        s = self.score
        self.assertIn("both wrong on %d items, which is %d of Qwen's %d errors" % (
            s["errors_AB"]["both_wrong"], s["errors_AB"]["both_wrong"], s["errors_AB"]["A_wrong"]), self.text)
        self.assertIn("shared %d of its %d" % (s["errors_AC"]["both_wrong"], s["errors_AC"]["A_wrong"]), self.text)
        self.assertIn("(%d against Qwen's %d)" % (s["pair_AB_two_models"]["false_shown"], s["A"]["false_shown"]), self.text)
        self.assertIn("%d to %d of %d right for each model" % (
            s["B"]["per_truth"]["not shown"]["right"], s["A"]["per_truth"]["not shown"]["right"], s["A"]["per_truth"]["not shown"]["n"]), self.text)
        self.assertIn("Qwen %.1f s per claim" % s["seconds_per_call_median"]["A"], self.text)
        self.assertIn("Gemma %.1f s" % s["seconds_per_call_median"]["B"], self.text)
        self.assertIn("about %d tokens per second" % round(s["tokens_per_second_median"]["A"]), self.text)
        self.assertIn("about %.1f" % s["tokens_per_second_median"]["B"], self.text)


class ReplicationNumbers(unittest.TestCase):
    def test_the_limits_paragraph(self):
        r = json.loads(REPL_SCORE.read_text(encoding="utf-8"))
        text = section("## What I'm not claiming")
        self.assertIn("%d of %d and %d of %d of its \"sure\" answers were wrong" % (
            *kn(r["certainty"]["U-Q"]["wrong_when_sure"]), *kn(r["certainty"]["U-G"]["wrong_when_sure"])), text)
        self.assertIn("on 40 items", text)
        self.assertEqual(r["n"], 40)
        self.assertEqual(kn(r["reader"]["pair_R1"]["false_shown"]), kn(r["reader"]["pair_R3"]["false_shown"]))
        self.assertIn("false \"shown\" was %d of %d under R1 and %d of %d under R3" % (
            *kn(r["reader"]["pair_R1"]["false_shown"]), *kn(r["reader"]["pair_R3"]["false_shown"])), text)
        self.assertIn("Gemma alone was already at %d of %d" % kn(r["reader"]["G"]["false_shown"]), text)


def ots_status(path):
    """'block N' if the proof file names a Bitcoin block, else 'pending'. Read straight from the file's bytes."""
    data = path.read_bytes()
    marker = bytes.fromhex("0588960d73d71901")
    heights, at = [], 0
    while True:
        found = data.find(marker, at)
        if found < 0:
            break
        at = found + 1
        i = found + len(marker)

        def varuint():
            nonlocal i
            value = shift = 0
            while True:
                byte = data[i]
                i += 1
                value |= (byte & 0x7F) << shift
                shift += 7
                if not byte & 0x80:
                    return value
        varuint()               # length of the attestation payload
        heights.append(varuint())
    return "block %d" % min(heights) if heights else "pending"


class ReceiptsTable(unittest.TestCase):
    def rows(self):
        table = next(t for t in tables(section("## Receipts")) if t[0][0].startswith("Seal"))
        return table[1:]

    def test_every_seal_in_the_table_is_here_with_the_stamp_the_table_says(self):
        rows = self.rows()
        self.assertGreaterEqual(len(rows), 14)
        for path_cell, _, stamp_cell, proof_cell in rows:
            path = RECEIPTS / path_cell.strip("`")
            self.assertTrue(path.exists(), path)
            tsr = Path(str(path) + ".tsr").read_bytes()
            match = re.fullmatch(r"(\d+) Oct(?: 2026)?, (\d\d):(\d\d):(\d\d)", stamp_cell) or re.fullmatch(r"(\d+) Oct (\d\d):(\d\d):(\d\d)", stamp_cell)
            self.assertIsNotNone(match, stamp_cell)
            generalized = ("202610%02d%s%s%sZ" % (int(match.group(1)), match.group(2), match.group(3), match.group(4))).encode()
            self.assertIn(generalized, tsr, (path_cell, stamp_cell))
            ots = Path(str(path) + ".ots")
            self.assertEqual(proof_cell, ots_status(ots) if ots.exists() else "no proof file", path_cell)

    def test_every_hash_list_here_is_in_the_table(self):
        listed = {r[0].strip("`") for r in self.rows()}
        here = {str(p.relative_to(RECEIPTS)).replace("\\", "/") for p in RECEIPTS.rglob("*-SHA256.txt")}
        self.assertEqual(listed, here)


if __name__ == "__main__":
    unittest.main()
