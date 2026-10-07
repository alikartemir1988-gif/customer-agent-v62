import contextlib
import io
import json
import unittest
import urllib.error
from unittest.mock import Mock, patch

from scripts import verify_majd_release as verifier


EXPECTED = "a" * 40
OLD_COMMIT = "b" * 40
HEALTH_URL = "https://example.test/health"


class MajdLiveCheckTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.clock = patch.object(verifier.time, "monotonic", side_effect=lambda: self.now).start()
        self.sleep = patch.object(verifier.time, "sleep", side_effect=self.advance_time).start()
        self.urlopen = patch.object(verifier.urllib.request, "urlopen").start()
        self.output = io.StringIO()
        self.addCleanup(patch.stopall)
        output_context = contextlib.redirect_stdout(self.output)
        output_context.__enter__()
        self.addCleanup(output_context.__exit__, None, None, None)

    def advance_time(self, seconds):
        self.now += seconds

    def response(self, payload):
        response = Mock()
        response.__enter__ = Mock(return_value=io.StringIO(json.dumps(payload)))
        response.__exit__ = Mock(return_value=False)
        return response

    def wait(self, **kwargs):
        return verifier.wait_for_release(HEALTH_URL, EXPECTED, **kwargs)

    def test_accepts_only_healthy_exact_commit(self):
        self.urlopen.return_value = self.response({"status": "ok", "commit": EXPECTED})
        self.assertEqual(self.wait()["commit"], EXPECTED)
        self.sleep.assert_not_called()
        self.assertIn(f"Verified live Majd commit {EXPECTED}", self.output.getvalue())

    def test_waits_for_new_release_instead_of_accepting_old_commit(self):
        self.urlopen.side_effect = [
            self.response({"status": "ok", "commit": OLD_COMMIT}),
            self.response({"status": "ok", "commit": EXPECTED}),
        ]
        self.wait()
        self.sleep.assert_called_once_with(10)
        self.assertEqual(self.urlopen.call_count, 2)

    def test_retries_unhealthy_response_even_when_commit_matches(self):
        self.urlopen.side_effect = [
            self.response({"status": "error", "commit": EXPECTED}),
            self.response({"status": "ok", "commit": EXPECTED}),
        ]
        self.wait()
        self.assertEqual(self.urlopen.call_count, 2)

    def test_retries_transient_http_and_network_failures(self):
        self.urlopen.side_effect = [
            urllib.error.HTTPError(HEALTH_URL, 503, "deploying", {}, None),
            urllib.error.URLError("starting"),
            TimeoutError("timeout"),
            self.response({"status": "ok", "commit": EXPECTED}),
        ]
        self.wait()
        self.assertEqual(self.urlopen.call_count, 4)
        self.assertEqual(self.now, 30)

    def test_retries_malformed_or_incomplete_health_json(self):
        malformed = self.response({})
        malformed.__enter__.return_value = io.StringIO("<html>Starting</html>")
        self.urlopen.side_effect = [
            malformed, self.response([]), self.response(None), self.response({"status": "ok"}),
            self.response({"status": "ok", "commit": EXPECTED}),
        ]
        self.wait()
        self.assertEqual(self.urlopen.call_count, 5)

    def test_old_release_fails_at_deadline_with_expected_and_observed_commits(self):
        self.urlopen.side_effect = lambda *args, **kwargs: self.response({
            "status": "ok", "commit": OLD_COMMIT,
        })
        with self.assertRaises(TimeoutError) as error:
            self.wait(wait_seconds=25)
        self.assertEqual(self.now, 25)
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [10, 10, 5])
        self.assertEqual([call.kwargs["timeout"] for call in self.urlopen.call_args_list], [20, 15, 5])
        self.assertIn(EXPECTED, str(error.exception))
        self.assertIn(OLD_COMMIT, str(error.exception))

    def test_network_failure_uses_same_deadline_and_does_not_sleep_after_expiry(self):
        def failure(*args, **kwargs):
            self.advance_time(kwargs["timeout"])
            raise TimeoutError("timed out")
        self.urlopen.side_effect = failure
        with self.assertRaises(TimeoutError):
            self.wait(wait_seconds=5)
        self.assertEqual(self.now, 5)
        self.sleep.assert_not_called()
        self.urlopen.assert_called_once_with(HEALTH_URL, timeout=5)

    def test_empty_or_abbreviated_expected_commit_fails_before_any_request(self):
        for commit in ("", EXPECTED[:7], "invalid" * 6):
            with self.subTest(commit=commit), self.assertRaises(ValueError):
                verifier.wait_for_release(HEALTH_URL, commit)
        self.urlopen.assert_not_called()

    def test_nonpositive_or_nonfinite_timings_fail_before_any_request(self):
        for name in ("wait_seconds", "poll_interval", "request_timeout"):
            for value in (0, -1, float("inf"), float("nan")):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    self.wait(**{name: value})
        self.urlopen.assert_not_called()

    def test_cli_returns_failure_when_release_never_arrives(self):
        self.urlopen.side_effect = lambda *args, **kwargs: self.response({"status": "ok"})
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            result = verifier.main([
                "--health-url", HEALTH_URL, "--expected-commit", EXPECTED, "--wait-seconds", "5",
            ])
        self.assertEqual(result, 1)
        self.assertIn(EXPECTED, errors.getvalue())


if __name__ == "__main__":
    unittest.main()
