import itertools
import unittest

from receipt_pair import rules
from receipt_pair.rules import CONTRADICTED, NOT_SHOWN, SHOWN

S, C, N = SHOWN, CONTRADICTED, NOT_SHOWN

# (A says, B says): (R1, R2, R3). Written out by hand from the three definitions in the README.
EXPECTED = {
    (S, S): (S, S, S),
    (S, C): (N, N, N),
    (S, N): (S, N, N),
    (C, S): (N, N, N),
    (C, C): (C, C, C),
    (C, N): (C, C, N),
    (N, S): (S, N, N),
    (N, C): (C, C, N),
    (N, N): (N, N, N),
}


class PairRules(unittest.TestCase):
    def test_every_combination_under_every_rule(self):
        for (a, b), (want1, want2, want3) in EXPECTED.items():
            with self.subTest(a=a, b=b):
                self.assertEqual(rules.r1(a, b), want1)
                self.assertEqual(rules.r2(a, b), want2)
                self.assertEqual(rules.r3(a, b), want3)

    def test_the_table_covers_all_nine_combinations(self):
        self.assertEqual(set(EXPECTED), set(itertools.product(rules.ANSWERS, repeat=2)))

    def test_a_pair_never_invents_an_answer(self):
        for a, b in itertools.product(rules.ANSWERS, repeat=2):
            for key in rules.RULES:
                result = rules.combine(a, b, key)
                self.assertIn(result, (a, b, NOT_SHOWN), (a, b, key))

    def test_the_order_of_the_models_does_not_matter(self):
        for a, b in itertools.product(rules.ANSWERS, repeat=2):
            for key in rules.RULES:
                self.assertEqual(rules.combine(a, b, key), rules.combine(b, a, key), (a, b, key))

    def test_shown_needs_both_under_r2_and_r3(self):
        for a, b in itertools.product(rules.ANSWERS, repeat=2):
            for key in ("r2", "r3"):
                self.assertEqual(rules.combine(a, b, key) == SHOWN, a == b == SHOWN, (a, b, key))

    def test_r3_says_contradicted_only_when_both_do(self):
        for a, b in itertools.product(rules.ANSWERS, repeat=2):
            self.assertEqual(rules.r3(a, b) == CONTRADICTED, a == b == CONTRADICTED)

    def test_r1_is_the_only_rule_that_lets_one_model_carry_a_shown(self):
        self.assertEqual(rules.r1(SHOWN, NOT_SHOWN), SHOWN)
        self.assertEqual(rules.r2(SHOWN, NOT_SHOWN), NOT_SHOWN)
        self.assertEqual(rules.r3(SHOWN, NOT_SHOWN), NOT_SHOWN)

    def test_the_default_is_r2(self):
        self.assertEqual(rules.DEFAULT_RULE, "r2")
        self.assertEqual(rules.combine(SHOWN, NOT_SHOWN), NOT_SHOWN)
        self.assertEqual(rules.combine(CONTRADICTED, NOT_SHOWN), CONTRADICTED)

    def test_rule_names_are_forgiving_about_case_and_spaces(self):
        self.assertEqual(rules.rule_key("R2"), "r2")
        self.assertEqual(rules.rule_key(" r3 "), "r3")
        self.assertEqual(rules.combine(SHOWN, SHOWN, "R1"), SHOWN)

    def test_an_unknown_rule_is_refused(self):
        with self.assertRaises(ValueError):
            rules.rule_key("r4")
        with self.assertRaises(ValueError):
            rules.combine(SHOWN, SHOWN, "majority")

    def test_an_unknown_answer_is_refused(self):
        for rule in (rules.r1, rules.r2, rules.r3):
            with self.assertRaises(ValueError):
                rule("shown", "maybe")
            with self.assertRaises(ValueError):
                rule("not_shown", "shown")

    def test_normalize_answer(self):
        for text in ("not_shown", "Not-Shown", " NOT  SHOWN ", "not shown"):
            self.assertEqual(rules.normalize_answer(text), NOT_SHOWN)
        self.assertEqual(rules.normalize_answer("SHOWN"), SHOWN)
        with self.assertRaises(ValueError):
            rules.normalize_answer("maybe")


if __name__ == "__main__":
    unittest.main()
