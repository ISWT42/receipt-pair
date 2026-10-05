"""Scoring: counts, denominators, intervals, and the three pair rules on a small set worked out by hand."""

import unittest

from receipt_pair import score

S, C, N = "shown", "contradicted", "not shown"

# Ten items. truth, then what A said, then what B said.
TABLE = [
    # id  truth  A  B
    ("1", S, S, S),
    ("2", S, S, N),
    ("3", S, N, S),
    ("4", C, C, C),
    ("5", C, C, N),
    ("6", C, S, C),
    ("7", N, S, S),
    ("8", N, N, N),
    ("9", N, S, N),
    ("10", N, C, N),
]
ITEMS = [{"id": i, "truth": t} for i, t, _, _ in TABLE]
ROWS = ([{"arm": "A", "id": i, "answer": a, "model": "ModelA"} for i, _, a, _ in TABLE]
        + [{"arm": "B", "id": i, "answer": b, "model": "ModelB"} for i, _, _, b in TABLE])


def k_n(entry):
    return (entry["k"], entry["n"])


class Wilson(unittest.TestCase):
    def test_values_the_sealed_run_reported(self):
        # From the sealed run 2 score file (these are the intervals printed there).
        self.assertEqual(score.wilson(66, 100), [0.563, 0.745])
        self.assertEqual(score.wilson(6, 68), [0.041, 0.179])
        self.assertEqual(score.wilson(2, 68), [0.008, 0.101])
        self.assertEqual(score.wilson(26, 32), [0.647, 0.911])
        self.assertEqual(score.wilson(21, 34), [0.45, 0.761])

    def test_no_items_no_interval(self):
        self.assertIsNone(score.wilson(0, 0))

    def test_all_or_nothing(self):
        low, high = score.wilson(0, 10)
        self.assertEqual(low, 0.0)
        self.assertGreater(high, 0.2)
        low, high = score.wilson(10, 10)
        self.assertEqual(high, 1.0)


class Measures(unittest.TestCase):
    """Every number below was counted by hand from TABLE."""

    def setUp(self):
        self.result = score.score(ROWS, ITEMS)

    def test_the_truth_counts(self):
        self.assertEqual(self.result["items"], 10)
        self.assertEqual(self.result["truth"], {S: 3, C: 3, N: 4})

    def test_model_a_alone(self):
        a = self.result["arms"]["A"]
        self.assertEqual(a["model"], "ModelA")
        self.assertEqual(k_n(a["right"]), (5, 10))                  # items 1, 2, 4, 5, 8
        self.assertEqual(k_n(a["false_shown"]), (3, 7))             # items 6, 7, 9: shown, truth not shown
        self.assertEqual(k_n(a["true_shown_kept"]), (2, 3))         # items 1, 2
        self.assertEqual(k_n(a["not_shown_right"]), (1, 4))         # item 8
        self.assertEqual(k_n(a["false_contradicted"]), (1, 7))      # item 10
        self.assertEqual(k_n(a["true_contradicted_kept"]), (2, 3))  # items 4, 5
        self.assertEqual(a["answers"], {S: 5, N: 2, C: 3})

    def test_model_b_alone(self):
        b = self.result["arms"]["B"]
        self.assertEqual(k_n(b["right"]), (7, 10))                  # items 1, 3, 4, 6, 8, 9, 10
        self.assertEqual(k_n(b["false_shown"]), (1, 7))             # item 7
        self.assertEqual(k_n(b["true_shown_kept"]), (2, 3))         # items 1, 3
        self.assertEqual(k_n(b["not_shown_right"]), (3, 4))         # items 8, 9, 10
        self.assertEqual(k_n(b["false_contradicted"]), (0, 7))
        self.assertEqual(k_n(b["true_contradicted_kept"]), (2, 3))  # items 4, 6

    def test_r1_pair(self):
        # R1 gives S, S, S, C, C, N, S, N, S, C for items 1 to 10.
        r1 = self.result["pairs"]["R1"]
        self.assertEqual(k_n(r1["right"]), (6, 10))                 # items 1, 2, 3, 4, 5, 8
        self.assertEqual(k_n(r1["false_shown"]), (2, 7))            # items 7, 9
        self.assertEqual(k_n(r1["true_shown_kept"]), (3, 3))
        self.assertEqual(k_n(r1["not_shown_right"]), (1, 4))        # item 8
        self.assertEqual(k_n(r1["false_contradicted"]), (1, 7))     # item 10
        self.assertEqual(k_n(r1["true_contradicted_kept"]), (2, 3))  # items 4, 5

    def test_r2_pair(self):
        # R2 gives S, N, N, C, C, N, S, N, N, C.
        r2 = self.result["pairs"]["R2"]
        self.assertEqual(k_n(r2["right"]), (5, 10))                 # items 1, 4, 5, 8, 9
        self.assertEqual(k_n(r2["false_shown"]), (1, 7))            # item 7, where both said shown
        self.assertEqual(k_n(r2["true_shown_kept"]), (1, 3))        # item 1
        self.assertEqual(k_n(r2["not_shown_right"]), (2, 4))        # items 8, 9
        self.assertEqual(k_n(r2["false_contradicted"]), (1, 7))     # item 10
        self.assertEqual(k_n(r2["true_contradicted_kept"]), (2, 3))  # items 4, 5

    def test_r3_pair(self):
        # R3 gives S, N, N, C, N, N, S, N, N, N.
        r3 = self.result["pairs"]["R3"]
        self.assertEqual(k_n(r3["right"]), (5, 10))                 # items 1, 4, 8, 9, 10
        self.assertEqual(k_n(r3["false_shown"]), (1, 7))            # item 7
        self.assertEqual(k_n(r3["true_shown_kept"]), (1, 3))        # item 1
        self.assertEqual(k_n(r3["not_shown_right"]), (3, 4))        # items 8, 9, 10
        self.assertEqual(k_n(r3["false_contradicted"]), (0, 7))
        self.assertEqual(k_n(r3["true_contradicted_kept"]), (1, 3))  # item 4

    def test_shared_errors(self):
        # A is wrong on 3, 6, 7, 9, 10 and B on 2, 5, 7: they share item 7.
        self.assertEqual(self.result["errors"], {"A_wrong": 5, "B_wrong": 3, "both_wrong": 1, "both_wrong_of_smaller": "1 of 3",
                                                 "smaller_wrong": 3})

    def test_true_shown_given_up_against_r1(self):
        # R1 keeps shown on items 1, 2, 3; R2 and R3 keep only item 1.
        self.assertEqual(self.result["true_shown_given_up_r2_vs_r1"], 2)
        self.assertEqual(self.result["true_shown_given_up_r3_vs_r1"], 2)

    def test_every_measure_has_an_interval(self):
        self.assertEqual(self.result["arms"]["A"]["right"]["ci95"], score.wilson(5, 10))

    def test_the_measures_agree_with_a_plain_recount_on_random_data(self):
        import random
        rng = random.Random(7)
        labels = (S, C, N)
        ids = [str(i) for i in range(200)]
        truth = {i: rng.choice(labels) for i in ids}
        ans = {i: rng.choice(labels) for i in ids}
        got = score.measures(ans, truth, ids)
        not_s = [i for i in ids if truth[i] != S]
        only_s = [i for i in ids if truth[i] == S]
        only_n = [i for i in ids if truth[i] == N]
        not_c = [i for i in ids if truth[i] != C]
        only_c = [i for i in ids if truth[i] == C]
        self.assertEqual(k_n(got["right"]), (len([i for i in ids if ans[i] == truth[i]]), 200))
        self.assertEqual(k_n(got["false_shown"]), (len([i for i in not_s if ans[i] == S]), len(not_s)))
        self.assertEqual(k_n(got["true_shown_kept"]), (len([i for i in only_s if ans[i] == S]), len(only_s)))
        self.assertEqual(k_n(got["not_shown_right"]), (len([i for i in only_n if ans[i] == N]), len(only_n)))
        self.assertEqual(k_n(got["false_contradicted"]), (len([i for i in not_c if ans[i] == C]), len(not_c)))
        self.assertEqual(k_n(got["true_contradicted_kept"]), (len([i for i in only_c if ans[i] == C]), len(only_c)))


class Edges(unittest.TestCase):
    def test_not_shown_may_be_spelled_either_way(self):
        items = [{"id": "1", "truth": "not_shown"}]
        rows = [{"arm": "A", "id": "1", "answer": "not shown"}, {"arm": "B", "id": "1", "answer": "not shown"}]
        self.assertEqual(k_n(score.score(rows, items)["arms"]["A"]["right"]), (1, 1))

    def test_ids_not_in_the_items_are_left_out_and_counted(self):
        rows = ROWS + [{"arm": "A", "id": "99", "answer": S}, {"arm": "B", "id": "99", "answer": S}]
        result = score.score(rows, ITEMS)
        self.assertEqual(result["ignored_ids"], 1)
        self.assertEqual(result["items"], 10)

    def test_an_item_one_model_skipped_shrinks_that_arms_denominator(self):
        rows = [r for r in ROWS if not (r["arm"] == "B" and r["id"] == "10")]
        result = score.score(rows, ITEMS)
        self.assertEqual(result["arms"]["A"]["right"]["n"], 10)
        self.assertEqual(result["arms"]["B"]["right"]["n"], 9)
        self.assertEqual(result["pairs"]["R2"]["right"]["n"], 9)

    def test_the_last_row_for_an_item_counts(self):
        rows = ROWS + [{"arm": "A", "id": "1", "answer": N}]      # A was right on item 1; the later row says "not shown"
        self.assertEqual(k_n(score.score(rows, ITEMS)["arms"]["A"]["right"]), (4, 10))

    def test_items_without_truth_are_left_out(self):
        items = ITEMS + [{"id": "11"}]
        self.assertEqual(score.score(ROWS, items)["items"], 10)

    def test_no_truth_at_all_is_an_error(self):
        with self.assertRaises(ValueError):
            score.score(ROWS, [{"id": "1"}])

    def test_a_missing_arm_is_an_error_that_names_the_arms_present(self):
        with self.assertRaises(ValueError) as caught:
            score.score(ROWS, ITEMS, arms=("A", "Z"))
        self.assertIn("'Z'", str(caught.exception))
        self.assertIn("A, B", str(caught.exception))

    def test_two_arms_only(self):
        with self.assertRaises(ValueError):
            score.score(ROWS, ITEMS, arms=("A", "B", "C"))

    def test_an_unknown_answer_is_refused(self):
        with self.assertRaises(ValueError):
            score.score([{"arm": "A", "id": "1", "answer": "maybe"}, {"arm": "B", "id": "1", "answer": S}], [{"id": "1", "truth": S}])


class Report(unittest.TestCase):
    def test_counts_come_first_each_with_its_denominator(self):
        text = score.format_report(score.score(ROWS, ITEMS))
        for fragment in ("Scored 10 items: 3 shown, 3 contradicted, 4 not shown.", "6 of 10", "3 of 7", "2 of 3",
                         "ModelA alone (A)", "ModelB alone (B)", "R1", "R2 (default)", "R3",
                         "Wrong on the same items: 1 of the smaller model's 3 errors."):
            self.assertIn(fragment, text)


if __name__ == "__main__":
    unittest.main()
