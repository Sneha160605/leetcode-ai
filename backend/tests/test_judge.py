import os
import unittest

from tests import _stubs  # noqa: F401
from shared import problems
from judge import judge, sandbox


class JudgeTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "Sandbox integration tests require Linux/POSIX")
    def test_reference_solutions_accepted(self):
        for lang in problems.LANGUAGES:
            for p in problems.PROBLEMS:
                with self.subTest(lang=lang, problem=p["id"]):
                    r = judge.judge(lang, p["reference"][lang], p, problems.all_tests(p))
                    self.assertEqual(r["verdict"], "ACCEPTED", r)

    def test_wrong_answer_hides_hidden_case(self):
        p = problems.get_problem("two-sum")
        bad = "def two_sum(nums, target):\n    return [0, 0]\n"
        r = judge.judge("python", bad, p, [{"args": [[1, 2], 3], "expected": [0, 1], "hidden": True}])
        self.assertEqual(r["verdict"], "WRONG_ANSWER")
        self.assertNotIn("expected", r["failure"])
        self.assertNotIn("input", r["failure"])

    @unittest.skipUnless(os.name == "posix", "Sandbox integration tests require Linux/POSIX")
    def test_infinite_loop_times_out(self):
        p = problems.get_problem("fibonacci")
        r = judge.judge("python", "def fib(n):\n    while True: pass\n", p, problems.all_tests(p)[:1])
        self.assertEqual(r["verdict"], "TIME_LIMIT_EXCEEDED")

    @unittest.skipUnless(os.name == "posix", "Sandbox integration tests require Linux/POSIX")
    def test_sandbox_blocks_os_and_network(self):
        for code in ("import os\ndef f():\n    os.system('echo hi')\n",
                     "import socket\ndef f():\n    socket.create_connection(('1.1.1.1', 80))\n",
                     "def f():\n    open('/etc/passwd','w')\n"):
            r = sandbox.run_case("python", code, "f", [])
            self.assertEqual(r["status"], "error", code)

    @unittest.skipUnless(os.name == "posix", "Sandbox integration tests require Linux/POSIX")
    def test_memory_bomb(self):
        r = sandbox.run_case("python", "def f():\n    return bytearray(4*1024**3)\n", "f", [])
        self.assertIn(r["status"], ("mle", "error"))

    @unittest.skipUnless(os.name == "posix", "Sandbox integration tests require Linux/POSIX")
    def test_node_has_no_process(self):
        r = sandbox.run_case("javascript", "function f(){ return process.env; }", "f", [])
        self.assertEqual(r["status"], "error")

    def test_output_comparison(self):
        self.assertTrue(judge.outputs_match(1.0, 1))
        self.assertTrue(judge.outputs_match([2, 1], [1, 2], "sorted"))
        self.assertFalse(judge.outputs_match(True, 1))


if __name__ == "__main__":
    unittest.main()
