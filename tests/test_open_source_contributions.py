import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from scripts import update_profile as subject

USER = subject.USER


def issue(repo: str, number: int, kind: str = "issue", date: str = "2026-10-20T10:00:00Z"):
    return {
        "repository_url": f"https://api.github.com/repos/{repo}",
        "number": number,
        "title": f"Work {number}",
        "html_url": f"https://github.com/{repo}/{'pull' if kind == 'pr' else 'issues'}/{number}",
        "updated_at": date,
    }


def event(repo: str, number: int, event_type: str, date: str, *, action: str = "created"):
    is_pr = event_type.startswith("PullRequest")
    details = {
        "user": {"login": USER},
        "html_url": f"https://github.com/{repo}/issues/{number}#issuecomment-100",
        "state": "approved",
    }
    target = {
        "number": number,
        "title": f"Work {number}",
        "html_url": f"https://github.com/{repo}/{'pull' if is_pr else 'issues'}/{number}",
        "user": {"login": USER},
    }
    payload = {"action": action}
    if event_type == "IssueCommentEvent":
        payload.update(issue=target, comment=details)
    elif event_type == "PullRequestReviewEvent":
        payload.update(pull_request=target, review=details)
    elif event_type == "PullRequestReviewCommentEvent":
        payload.update(pull_request=target, comment=details)
    elif event_type == "IssuesEvent":
        payload.update(issue=target)
    elif event_type == "PullRequestEvent":
        payload.update(pull_request=target)
    return {
        "type": event_type,
        "repo": {"name": repo},
        "actor": {"login": USER},
        "created_at": date,
        "payload": payload,
    }


def fake_github(search_prs=None, search_issues=None, events=None, *, event_error=None):
    search_prs = search_prs if search_prs is not None else []
    search_issues = search_issues if search_issues is not None else []
    events = events if events is not None else []

    def respond(path, params=None):
        if path == "/search/issues":
            items = search_prs if "is:pr" in params["q"] else search_issues
            return {"items": items, "incomplete_results": False}
        if path == f"/users/{USER}/events/public":
            if event_error is not None:
                raise event_error
            return events if params["page"] == 1 else []
        raise AssertionError(f"unexpected endpoint: {path}")

    return respond


class ExternalContributionTest(unittest.TestCase):
    def test_authored_issue_remains_canonical_and_comment_is_collapsed(self):
        repo = "JetBrains/jcef"
        authored = issue(repo, 47)
        activity = event(repo, 47, "IssueCommentEvent", "2026-10-25T09:00:00Z")
        with patch.object(subject, "github_json", side_effect=fake_github(search_issues=[authored], events=[activity])):
            lines = subject.external_contributions()
        self.assertEqual(len(lines), 1)
        self.assertIn("JetBrains/jcef#47", lines[0])
        self.assertIn("](https://github.com/JetBrains/jcef/issues/47)", lines[0])
        self.assertIn("· commented — 2026-10-25", lines[0])
        self.assertNotIn("#issuecomment-", lines[0])

    def test_distinct_contributions_in_one_repo_are_not_dropped(self):
        repo = "JetBrains/jcef"
        with patch.object(subject, "github_json", side_effect=fake_github(
            search_issues=[issue(repo, 47), issue(repo, 48)],
            search_prs=[issue(repo, 49, "pr")],
        )):
            lines = subject.external_contributions()
        self.assertEqual(len(lines), 3)
        for number in (47, 48, 49):
            self.assertEqual(sum(f"#{number}:" in line for line in lines), 1)

    def test_review_and_review_comment_are_one_pr(self):
        repo = "open/project"
        events = [
            event(repo, 12, "PullRequestReviewEvent", "2026-10-21T12:00:00Z", action="submitted"),
            event(repo, 12, "PullRequestReviewCommentEvent", "2026-10-22T12:00:00Z"),
        ]
        with patch.object(subject, "github_json", side_effect=fake_github(events=events)):
            lines = subject.external_contributions()
        self.assertEqual(len(lines), 1)
        self.assertIn("**PR**", lines[0])
        self.assertIn("#12:", lines[0])
        self.assertIn("review comment, reviewed", lines[0])
        self.assertIn("2026-10-22", lines[0])

    def test_comments_on_someone_elses_issue_are_included(self):
        repo = "other/repo"
        activity = event(repo, 33, "IssueCommentEvent", "2026-10-26T08:00:00Z")
        activity["payload"]["issue"]["user"]["login"] = "another-author"
        with patch.object(subject, "github_json", side_effect=fake_github(events=[activity])):
            lines = subject.external_contributions()
        self.assertEqual(len(lines), 1)
        self.assertIn("other/repo#33", lines[0])
        self.assertIn("commented", lines[0])

    def test_noise_other_actor_and_owned_repo_are_filtered(self):
        activities = [
            event("external/proj", 1, "PushEvent", "2026-10-25T00:00:00Z"),
            event(f"{USER}/owned", 2, "IssueCommentEvent", "2026-10-25T00:00:00Z"),
            event("external/proj", 3, "IssueCommentEvent", "2026-10-25T00:00:00Z"),
        ]
        activities[2]["actor"]["login"] = "someone-else"
        with patch.object(subject, "github_json", side_effect=fake_github(events=activities)):
            self.assertEqual(subject.external_contributions(), ["_No recent public contributions to external repositories found._"])

    def test_authored_baseline_preserved_over_newer_activity(self):
        authored = [issue("first/repo", n, date=f"2026-10-{n:02d}T00:00:00Z") for n in (21, 22, 23, 24, 25)]
        activities = [event("other/repo", n, "IssueCommentEvent", "2026-10-27T00:00:00Z") for n in (1, 2, 3)]
        with patch.object(subject, "github_json", side_effect=fake_github(search_issues=authored, events=activities)):
            lines = subject.external_contributions()
        self.assertEqual(len(lines), 6)
        self.assertEqual(sum("first/repo" in line for line in lines), 4)
        self.assertEqual(sum("other/repo" in line for line in lines), 2)
        self.assertFalse(any("first/repo#21" in line for line in lines))

    def test_optional_event_failure_preserves_search_baseline_with_warning(self):
        stderr = io.StringIO()
        with (
            patch.object(subject, "github_json", side_effect=fake_github(search_issues=[issue("JetBrains/jcef", 47)], event_error=OSError("timeout"))),
            redirect_stderr(stderr),
        ):
            lines = subject.external_contributions()
        self.assertEqual(len(lines), 1)
        self.assertIn("JetBrains/jcef#47", lines[0])
        self.assertIn("could not enrich contributions", stderr.getvalue())

    def test_search_failure_remains_fatal(self):
        with patch.object(subject, "github_json", side_effect=OSError("search unavailable")):
            with self.assertRaises(OSError):
                subject.external_contributions()

    def test_incomplete_search_is_rejected(self):
        with patch.object(subject, "github_json", return_value={"items": [], "incomplete_results": True}):
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                subject.external_contributions()

    def test_opened_event_requires_original_author(self):
        activity = event("another/repo", 19, "IssuesEvent", "2026-10-20T00:00:00Z", action="opened")
        activity["payload"]["issue"]["user"]["login"] = "someone-else"
        self.assertIsNone(subject._external_event_item(activity))
        activity["payload"]["issue"]["user"]["login"] = USER
        self.assertEqual(subject._external_event_item(activity)["kind"], "Issue")

    def test_non_public_unverifiable_review_is_ignored(self):
        activity = event("open/repo", 29, "PullRequestReviewEvent", "2026-10-22T00:00:00Z", action="submitted")
        activity["payload"]["review"]["state"] = "pending"
        self.assertIsNone(subject._external_event_item(activity))
        activity["payload"]["review"] = {}
        self.assertIsNone(subject._external_event_item(activity))

    def test_event_pagination_stops_after_partial_page(self):
        calls = []
        def read(path, params):
            calls.append(params["page"])
            return [object()] * 100 if params["page"] < 3 else [object()] * 5
        with patch.object(subject, "github_json", side_effect=read):
            events = subject._recent_external_events()
        self.assertEqual(calls, [1, 2, 3])
        self.assertEqual(len(events), 205)


if __name__ == "__main__":
    unittest.main()
