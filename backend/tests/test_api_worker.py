import json
import unittest
from unittest import mock

from tests import _stubs
from api import handler as api
from judge import worker
from shared import ai, problems

TWO_SUM = problems.get_problem("two-sum")["reference"]["python"]


def event(method, path, body=None, user="u1", groups="", qs=None):
    return {"httpMethod": method, "path": path, "body": json.dumps(body) if body is not None else None,
            "queryStringParameters": qs,
            "requestContext": {"authorizer": {"claims": {"sub": user, "email": f"{user}@x.io", "cognito:groups": groups}}}}


def call(*a, **k):
    r = api.handler(event(*a, **k))
    return r["statusCode"], json.loads(r["body"])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.store = _stubs.FakeStore()
        self.queue = []
        api.deps._store = self.store
        api.deps.enqueue = lambda lang, body: self.queue.append((lang, body))

    def test_requires_auth(self):
        r = api.handler({"httpMethod": "GET", "path": "/problems", "requestContext": {}})
        self.assertEqual(r["statusCode"], 401)

    def test_problem_detail_never_leaks_answers(self):
        status, body = call("GET", "/problems/two-sum")
        self.assertEqual(status, 200)
        text = json.dumps(body)
        self.assertNotIn("reference", text)
        self.assertNotIn("hints", text)
        self.assertLessEqual(len(body["examples"]), 3)

    def test_submit_enqueues_to_language_queue(self):
        status, body = call("POST", "/submissions", {"problemId": "two-sum", "language": "javascript", "code": "x"})
        self.assertEqual(status, 202)
        self.assertEqual(self.queue[0][0], "javascript")
        self.assertEqual(self.store.subs[body["id"]]["status"], "QUEUED")

    def test_submit_validation(self):
        self.assertEqual(call("POST", "/submissions", {"problemId": "nope", "language": "python", "code": "x"})[0], 404)
        self.assertEqual(call("POST", "/submissions", {"problemId": "two-sum", "language": "cobol", "code": "x"})[0], 400)
        self.assertEqual(call("POST", "/submissions", {"problemId": "two-sum", "language": "python", "code": "x" * 30000})[0], 413)

    def test_enqueue_failure_marks_failed(self):
        def boom(*_):
            raise RuntimeError("sqs down")
        api.deps.enqueue = boom
        status, _ = call("POST", "/submissions", {"problemId": "two-sum", "language": "python", "code": "x"})
        self.assertEqual(status, 503)
        self.assertEqual(next(iter(self.store.subs.values()))["status"], "FAILED")

    def test_cannot_read_others_submission(self):
        _, body = call("POST", "/submissions", {"problemId": "two-sum", "language": "python", "code": "x"})
        self.assertEqual(call("GET", f"/submissions/{body['id']}", user="u2")[0], 404)
        self.assertEqual(call("GET", f"/submissions/{body['id']}")[0], 200)

    def test_hints_escalate_progressively(self):
        with mock.patch.object(ai, "invoke", side_effect=RuntimeError):
            levels = [call("POST", "/hints", {"problemId": "two-sum", "code": ""})[1]["level"] for _ in range(6)]
        self.assertEqual(levels, [1, 2, 3, 4, 4, 4])

    def test_gentests_admin_only(self):
        self.assertEqual(call("POST", "/problems/two-sum/gentests")[0], 403)
        self.assertEqual(call("POST", "/problems/two-sum/gentests", groups="admins")[0], 202)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.store = _stubs.FakeStore()
        self.store.create_submission({"id": "s1", "user": "u1", "userName": "u1", "problemId": "two-sum",
                                      "language": "python", "code": TWO_SUM, "status": "QUEUED", "createdAt": "t"})
        self.review = {"time_complexity": "O(n)", "space_complexity": "O(n)", "is_optimal": True}

    def test_accepted_scores_once_and_reviews(self):
        with mock.patch.object(ai, "review_code", return_value=self.review), mock.patch.object(worker, "emit_metrics"):
            worker.process_message(self.store, {"type": "judge", "submissionId": "s1"})
            worker.process_message(self.store, {"type": "judge", "submissionId": "s1"})  # redelivery
        s = self.store.subs["s1"]
        self.assertEqual((s["status"], s["verdict"]), ("DONE", "ACCEPTED"))
        self.assertEqual(s["review"], self.review)
        self.assertEqual(self.store.scores["u1"], 10)

    def test_review_failure_does_not_block_verdict(self):
        with mock.patch.object(ai, "review_code", side_effect=RuntimeError), mock.patch.object(worker, "emit_metrics"):
            worker.process_message(self.store, {"type": "judge", "submissionId": "s1"})
        self.assertEqual(self.store.subs["s1"]["verdict"], "ACCEPTED")
        self.assertTrue(self.store.subs["s1"]["reviewError"])

    def test_gentests_keeps_only_reference_verified(self):
        with mock.patch.object(ai, "suggest_test_inputs", return_value=[[[3, 3], 6], [[1], "bad"]]):
            worker.process_message(self.store, {"type": "gentests", "problemId": "two-sum"})
        self.assertEqual(self.store.extra["two-sum"][0]["expected"], [0, 1])

    def test_unknown_job_raises(self):
        with self.assertRaises(ValueError):
            worker.process_message(self.store, {"type": "??"})


if __name__ == "__main__":
    unittest.main()
