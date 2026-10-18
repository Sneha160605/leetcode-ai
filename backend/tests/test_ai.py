import unittest
from unittest import mock

from tests import _stubs  # noqa: F401
from shared import ai, problems

P = problems.get_problem("two-sum")


class LeakGuard(unittest.TestCase):
    def test_flags_code_fence(self):
        self.assertTrue(ai.leaks_solution("try this\n```python\nx=1\n```", None))

    def test_flags_reference_lines(self):
        ref = P["reference"]["python"]
        self.assertTrue(ai.leaks_solution("seen={} for i,n in enumerate(nums): if target-n in seen: return sorted([seen[target-n],i])", ref))

    def test_allows_plain_hint(self):
        self.assertFalse(ai.leaks_solution("What lookup would let you ask whether you've seen the partner value?", P["reference"]["python"]))


class Hints(unittest.TestCase):
    def test_leaky_model_falls_back_to_static(self):
        with mock.patch.object(ai, "invoke", return_value="```python\ndef two_sum(): pass\n```"):
            out = ai.generate_hint(P, "", 2, [])
        self.assertEqual(out["source"], "static")
        self.assertEqual(out["hint"], P["hints"][1])

    def test_good_hint_used(self):
        with mock.patch.object(ai, "invoke", return_value="Think about what you could remember as you scan."):
            out = ai.generate_hint(P, "", 1, [])
        self.assertEqual(out["source"], "ai")

    def test_outage_falls_back(self):
        with mock.patch.object(ai, "invoke", side_effect=RuntimeError("throttled")):
            self.assertEqual(ai.generate_hint(P, "", 3, [])["source"], "static")


class Review(unittest.TestCase):
    def test_parses_and_sanitises(self):
        raw = 'sure! {"time_complexity":"O(n^2)","space_complexity":"O(1)","is_optimal":false,"summary":"Nested loops.","suggestions":["Use a map","```code```"]}'
        with mock.patch.object(ai, "invoke", return_value=raw):
            r = ai.review_code(P, "python", "x", {"verdict": "ACCEPTED"})
        self.assertEqual(r["time_complexity"], "O(n^2)")
        self.assertEqual(r["suggestions"], ["Use a map"])
        self.assertEqual(r["target"]["time"], "O(n)")

    def test_garbage_complexity_becomes_unknown(self):
        raw = '{"time_complexity":"ignore previous instructions","space_complexity":"O(1)","is_optimal":true}'
        with mock.patch.object(ai, "invoke", return_value=raw):
            r = ai.review_code(P, "python", "x", {})
        self.assertEqual(r["time_complexity"], "unknown")
        self.assertFalse(r["is_optimal"])

    def test_no_json_raises(self):
        with mock.patch.object(ai, "invoke", return_value="nope"):
            with self.assertRaises(ValueError):
                ai.review_code(P, "python", "x", {})


class TestGen(unittest.TestCase):
    def test_filters_wrong_arity(self):
        with mock.patch.object(ai, "invoke", return_value="[[[1,2],3],[[1]],[[0,4],4]]"):
            self.assertEqual(ai.suggest_test_inputs(P), [[[1, 2], 3], [[0, 4], 4]])


if __name__ == "__main__":
    unittest.main()
