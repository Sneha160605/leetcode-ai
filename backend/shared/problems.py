"""Bundled problem set. Tests are JSON-able: {"args": [...], "expected": ..., "hidden": bool}.

The python reference solution is used (a) by unit tests to prove the judge works,
(b) by the AI hint leak-guard, and (c) to compute expected outputs for LLM-generated edge cases.
"""
from __future__ import annotations

import copy

_BIG_N = 100_000

PROBLEMS: list[dict] = [
    {
        "id": "two-sum",
        "title": "Two Sum",
        "difficulty": "easy",
        "tags": ["array", "hash-table"],
        "statement": (
            "Given an array of integers `nums` and an integer `target`, return the indices of the two "
            "numbers that add up to `target`, as a list sorted ascending. Exactly one valid pair exists.\n\n"
            "Constraints: 2 <= len(nums) <= 100000, -10^9 <= nums[i] <= 10^9."
        ),
        "function": {"python": "two_sum", "javascript": "twoSum"},
        "arity": 2,
        "compare": "sorted",
        "optimal": {"time": "O(n)", "space": "O(n)"},
        "starter": {
            "python": "def two_sum(nums, target):\n    # return the two indices as a sorted list\n    pass\n",
            "javascript": "function twoSum(nums, target) {\n  // return the two indices as a sorted array\n}\n",
        },
        "hints": [
            "Before coding: what is the simplest approach that checks every pair, and how many pairs is that for n = 100,000?",
            "For each number, the partner you need is fixed. What would let you ask 'have I already seen that partner?' instantly?",
            "Think of a lookup structure keyed by value that remembers where each value was seen, filled while you scan once.",
            "Plan in words: walk the array once; for each element compute the missing partner, check your lookup, answer if found, otherwise record the current element and move on.",
        ],
        "reference": {
            "python": (
                "def two_sum(nums, target):\n"
                "    seen = {}\n"
                "    for i, n in enumerate(nums):\n"
                "        if target - n in seen:\n"
                "            return sorted([seen[target - n], i])\n"
                "        seen[n] = i\n"
                "    return []\n"
            ),
            "javascript": (
                "function twoSum(nums, target) {\n"
                "  const seen = new Map();\n"
                "  for (let i = 0; i < nums.length; i++) {\n"
                "    const need = target - nums[i];\n"
                "    if (seen.has(need)) return [seen.get(need), i].sort((a, b) => a - b);\n"
                "    seen.set(nums[i], i);\n"
                "  }\n"
                "  return [];\n"
                "}\n"
            ),
        },
        "tests": [
            {"args": [[2, 7, 11, 15], 9], "expected": [0, 1]},
            {"args": [[3, 2, 4], 6], "expected": [1, 2]},
            {"args": [[3, 3], 6], "expected": [0, 1]},
            {"args": [[-1, -2, -3, -4, -5], -8], "expected": [2, 4], "hidden": True},
            {"args": [[0, 4, 3, 0], 0], "expected": [0, 3], "hidden": True},
            {"args": [list(range(_BIG_N)), 2 * _BIG_N - 3], "expected": [_BIG_N - 2, _BIG_N - 1], "hidden": True},
        ],
    },
    {
        "id": "valid-parentheses",
        "title": "Valid Parentheses",
        "difficulty": "easy",
        "tags": ["stack", "string"],
        "statement": (
            "Given a string `s` containing only `()[]{}`, return true if the brackets are closed by the same "
            "type and in the correct order. The empty string is valid.\n\nConstraints: 0 <= len(s) <= 100000."
        ),
        "function": {"python": "is_valid", "javascript": "isValid"},
        "arity": 1,
        "compare": "exact",
        "optimal": {"time": "O(n)", "space": "O(n)"},
        "starter": {
            "python": "def is_valid(s):\n    pass\n",
            "javascript": "function isValid(s) {\n}\n",
        },
        "hints": [
            "What does it mean for the most recently opened bracket to be 'still waiting'? What must happen when you see a closer?",
            "The bracket that must close first is always the one opened last. Which everyday structure behaves that way?",
            "Use a last-in-first-out structure. Think about what to do on an opener, on a closer, and what must be true when the string ends.",
            "Plan in words: scan left to right; push openers; for a closer, fail if nothing is waiting or the waiting opener has a different type, else discard it; at the end nothing may remain.",
        ],
        "reference": {
            "python": (
                "def is_valid(s):\n"
                "    pairs = {')': '(', ']': '[', '}': '{'}\n"
                "    stack = []\n"
                "    for ch in s:\n"
                "        if ch in pairs:\n"
                "            if not stack or stack.pop() != pairs[ch]:\n"
                "                return False\n"
                "        else:\n"
                "            stack.append(ch)\n"
                "    return not stack\n"
            ),
            "javascript": (
                "function isValid(s) {\n"
                "  const pairs = { ')': '(', ']': '[', '}': '{' };\n"
                "  const stack = [];\n"
                "  for (const ch of s) {\n"
                "    if (ch in pairs) {\n"
                "      if (stack.pop() !== pairs[ch]) return false;\n"
                "    } else stack.push(ch);\n"
                "  }\n"
                "  return stack.length === 0;\n"
                "}\n"
            ),
        },
        "tests": [
            {"args": ["()"], "expected": True},
            {"args": ["()[]{}"], "expected": True},
            {"args": ["(]"], "expected": False},
            {"args": ["([)]"], "expected": False, "hidden": True},
            {"args": ["{[]}"], "expected": True, "hidden": True},
            {"args": [""], "expected": True, "hidden": True},
            {"args": ["((("], "expected": False, "hidden": True},
            {"args": ["(" * 50_000 + ")" * 50_000], "expected": True, "hidden": True},
        ],
    },
    {
        "id": "fibonacci",
        "title": "Fibonacci Number",
        "difficulty": "easy",
        "tags": ["dynamic-programming", "recursion"],
        "statement": "Return the n-th Fibonacci number with F(0)=0, F(1)=1.\n\nConstraints: 0 <= n <= 70.",
        "function": {"python": "fib", "javascript": "fib"},
        "arity": 1,
        "compare": "exact",
        "optimal": {"time": "O(n)", "space": "O(1)"},
        "starter": {
            "python": "def fib(n):\n    pass\n",
            "javascript": "function fib(n) {\n}\n",
        },
        "hints": [
            "Write the plain recursive definition. How many times is fib(3) recomputed when you ask for fib(40)?",
            "The same sub-answers are requested again and again. What could you do so each one is computed only once?",
            "Either remember answers you have already computed, or build upward from the smallest cases. How many previous values do you really need at any moment?",
            "Plan in words: start from the two base values; repeat n times replacing the pair with (second, sum of both); report the first value of the pair.",
        ],
        "reference": {
            "python": (
                "def fib(n):\n"
                "    a, b = 0, 1\n"
                "    for _ in range(n):\n"
                "        a, b = b, a + b\n"
                "    return a\n"
            ),
            "javascript": (
                "function fib(n) {\n"
                "  let a = 0, b = 1;\n"
                "  for (let i = 0; i < n; i++) [a, b] = [b, a + b];\n"
                "  return a;\n"
                "}\n"
            ),
        },
        "tests": [
            {"args": [0], "expected": 0},
            {"args": [1], "expected": 1},
            {"args": [10], "expected": 55},
            {"args": [30], "expected": 832040, "hidden": True},
            {"args": [70], "expected": 190392490709135, "hidden": True},
        ],
    },
    {
        "id": "merge-intervals",
        "title": "Merge Intervals",
        "difficulty": "medium",
        "tags": ["array", "sorting"],
        "statement": (
            "Given a list of `intervals` where intervals[i] = [start, end], merge all overlapping intervals "
            "(touching intervals like [1,4] and [4,5] overlap) and return the result sorted by start.\n\n"
            "Constraints: 0 <= len(intervals) <= 20000."
        ),
        "function": {"python": "merge", "javascript": "merge"},
        "arity": 1,
        "compare": "exact",
        "optimal": {"time": "O(n log n)", "space": "O(n)"},
        "starter": {
            "python": "def merge(intervals):\n    pass\n",
            "javascript": "function merge(intervals) {\n}\n",
        },
        "hints": [
            "Take two intervals in any order. What condition tells you they overlap? Does input order make that hard to check across many intervals?",
            "If intervals were arranged so that neighbours are the only candidates for overlap, how many comparisons would you need?",
            "Order by start. Then keep a 'current' interval and decide, for the next one, whether to extend or to finalise the current one.",
            "Plan in words: sort by start; begin with the first as current; for each next, if its start is within current's end, stretch the end to the larger of the two; else emit current and restart from the next; emit the last.",
        ],
        "reference": {
            "python": (
                "def merge(intervals):\n"
                "    out = []\n"
                "    for s, e in sorted(intervals):\n"
                "        if out and s <= out[-1][1]:\n"
                "            out[-1][1] = max(out[-1][1], e)\n"
                "        else:\n"
                "            out.append([s, e])\n"
                "    return out\n"
            ),
            "javascript": (
                "function merge(intervals) {\n"
                "  const out = [];\n"
                "  for (const [s, e] of [...intervals].sort((a, b) => a[0] - b[0] || a[1] - b[1])) {\n"
                "    if (out.length && s <= out[out.length - 1][1]) out[out.length - 1][1] = Math.max(out[out.length - 1][1], e);\n"
                "    else out.push([s, e]);\n"
                "  }\n"
                "  return out;\n"
                "}\n"
            ),
        },
        "tests": [
            {"args": [[[1, 3], [2, 6], [8, 10], [15, 18]]], "expected": [[1, 6], [8, 10], [15, 18]]},
            {"args": [[[1, 4], [4, 5]]], "expected": [[1, 5]]},
            {"args": [[]], "expected": []},
            {"args": [[[1, 4], [0, 4]]], "expected": [[0, 4]], "hidden": True},
            {"args": [[[1, 4], [2, 3]]], "expected": [[1, 4]], "hidden": True},
            {"args": [[[i * 2, i * 2 + 1] for i in range(20_000)]], "expected": [[i * 2, i * 2 + 1] for i in range(20_000)], "hidden": True},
        ],
    },
]

_BY_ID = {p["id"]: p for p in PROBLEMS}
DIFFICULTY_POINTS = {"easy": 10, "medium": 25, "hard": 50}
LANGUAGES = ("python", "javascript")


def get_problem(problem_id: str) -> dict | None:
    return _BY_ID.get(problem_id)


def points(problem: dict) -> int:
    return DIFFICULTY_POINTS.get(problem["difficulty"], 10)


def public_summary(p: dict) -> dict:
    return {"id": p["id"], "title": p["title"], "difficulty": p["difficulty"], "tags": p["tags"], "points": points(p)}


def public_detail(p: dict) -> dict:
    """Everything the UI needs; never reference solutions, hint text or hidden tests."""
    d = public_summary(p)
    d["statement"] = p["statement"]
    d["starter"] = p["starter"]
    d["examples"] = [
        {"args": t["args"], "expected": t["expected"]} for t in p["tests"] if not t.get("hidden")
    ][:3]
    return d


def all_tests(problem: dict, extra: list[dict] | None = None) -> list[dict]:
    tests = copy.deepcopy(problem["tests"])
    for t in extra or []:
        tests.append({"args": t["args"], "expected": t["expected"], "hidden": True, "generated": True})
    return tests
