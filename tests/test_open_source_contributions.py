import re
import unittest
from unittest.mock import patch

from scripts import update_profile as subject

USER = subject.USER


def issue(repo, number, *, pr=False, updated="2026-10-20T00:00:00Z"):
    result = {
        "repository_url": f"https://api.github.com/repos/{repo}",
        "number": number,
        "title": f"Work {number}",
        "html_url": f"https://github.com/{repo}/{'pull' if pr else 'issues'}/{number}",
        "updated_at": updated,
    }
    if pr:
        result["pull_request"] = {"url": f"https://api.github.com/repos/{repo}/pulls/{number}"}
    return result


def comment(date, *, user=USER):
    return {"user": {"login": user}, "created_at": date}


def review(date, *, user=USER, state="APPROVED"):
    return {"user": {"login": user}, "submitted_at": date, "state": state}


def mock_api(*, authored_issues=(), authored_prs=(), commented_issues=(), commented_prs=(),
             reviewed_prs=(), details=None, fail_query=None, incomplete_query=None):
    details = details or {}
    recorded = []

    def github(path, params=None):
        recorded.append((path, params))
        if path == "/search/issues":
            query = params["q"]
            if fail_query and fail_query in query:
                raise OSError("GitHub unavailable")
            if query.startswith(f"author:{USER}"):
                items = authored_prs if "is:pr" in query else authored_issues
            elif query.startswith(f"commenter:{USER}"):
                items = commented_prs if "is:pr" in query else commented_issues
            elif query.startswith(f"reviewed-by:{USER}"):
                items = reviewed_prs
            else:
                raise AssertionError(query)
            return {
                "items": list(items)[:params["per_page"]],
                "incomplete_results": bool(incomplete_query and incomplete_query in query),
            }
        match = re.fullmatch(r"/repos/([^/]+/[^/]+)/(issues|pulls)/(\d+)/(comments|reviews)", path)
        if match:
            repo, family, number, endpoint = match.groups()
            records = details.get((repo, int(number), family, endpoint), [])
            start = (params["page"] - 1) * params["per_page"]
            return records[start:start + params["per_page"]]
        raise AssertionError(f"unexpected call: {path}")

    return github, recorded


class CollaborationSearchTest(unittest.TestCase):
    def test_existing_pr_has_verified_comment_and_review_without_duplicate(self):
        repo = "zed-industries/extensions"
        item = issue(repo, 6875, pr=True, updated="2026-10-15T10:24:31Z")
        api, calls = mock_api(
            authored_prs=[item], commented_prs=[item], reviewed_prs=[item],
            details={
                (repo, 6875, "issues", "comments"): [
                    comment("2026-10-15T10:24:31Z"), comment("2026-10-27T01:00:00Z", user="another")
                ],
                (repo, 6875, "pulls", "reviews"): [review("2026-09-17T12:14:29Z")],
                (repo, 6875, "pulls", "comments"): [],
            },
        )
        with patch.object(subject, "github_json", side_effect=api):
            lines = subject.external_contributions()
        self.assertEqual(len(lines), 1)
        self.assertIn("zed-industries/extensions#6875", lines[0])
        self.assertIn("**PR · Commented · Reviewed**", lines[0])
        self.assertIn("— 2026-10-15", lines[0])
        self.assertNotIn(" · commented, reviewed —", lines[0])
        self.assertNotIn("2026-10-27", lines[0])
        self.assertTrue(any("reviewed-by:" in args["q"] for p, args in calls if p == "/search/issues"))

    def test_comment_on_someone_elses_issue_survives_event_history_expiry(self):
        item = issue("external/project", 51, updated="2026-10-26T00:00:00Z")
        api, _ = mock_api(
            commented_issues=[item],
            details={("external/project", 51, "issues", "comments"): [
                comment("2026-10-02T08:30:00Z"), comment("2026-10-26T00:00:00Z", user="other")
            ]},
        )
        with patch.object(subject, "github_json", side_effect=api):
            lines = subject.external_contributions()
        self.assertEqual(len(lines), 1)
        self.assertIn("external/project#51", lines[0])
        self.assertIn("**Commented on Issue**", lines[0])
        self.assertIn("— 2026-10-02", lines[0])

    def test_review_activity_only_pr_is_included(self):
        item = issue("external/project", 77, pr=True, updated="2026-10-28T00:00:00Z")
        api, _ = mock_api(
            reviewed_prs=[item],
            details={
                ("external/project", 77, "pulls", "reviews"): [
                    review("2026-10-10T13:00:00Z", state="COMMENTED"),
                    review("2026-10-26T14:00:00Z", user="other"),
                    review("", state="PENDING"),
                ],
                ("external/project", 77, "pulls", "comments"): [
                    comment("2026-10-11T00:00:00Z")
                ],
            },
        )
        with patch.object(subject, "github_json", side_effect=api):
            lines = subject.external_contributions()
        self.assertEqual(len(lines), 1)
        self.assertIn("**Reviewed PR · Review Comment**", lines[0])
        self.assertIn("— 2026-10-11", lines[0])

    def test_plain_authored_items_have_simple_leading_type(self):
        for kind, expected in (("Issue", "Issue"), ("PR", "PR")):
            with self.subTest(kind=kind):
                self.assertEqual(
                    subject._contribution_activity_label(
                        {"kind": kind, "notes": set()}, authored=True
                    ),
                    expected,
                )

    def test_authored_issue_with_comment_has_visible_leading_activity(self):
        label = subject._contribution_activity_label(
            {"kind": "Issue", "notes": {"commented"}}, authored=True
        )
        self.assertEqual(label, "Issue · Commented")

    def test_collaboration_only_pr_comment_and_review_labels(self):
        cases = [
            ({"commented"}, "Commented on PR"),
            ({"reviewed"}, "Reviewed PR"),
            ({"review comment"}, "Review Comment on PR"),
            ({"commented", "reviewed"}, "Commented on PR · Reviewed"),
            ({"reviewed", "review comment"}, "Reviewed PR · Review Comment"),
        ]
        for notes, expected in cases:
            with self.subTest(notes=notes):
                self.assertEqual(
                    subject._contribution_activity_label(
                        {"kind": "PR", "notes": notes}, authored=False
                    ),
                    expected,
                )

    def test_authored_issue_activity_is_not_relabelled_as_collaboration_only(self):
        item = issue("JetBrains/jcef", 47)
        api, _ = mock_api(
            authored_issues=[item], commented_issues=[item],
            details={("JetBrains/jcef", 47, "issues", "comments"): [
                comment("2026-10-22T00:00:00Z")
            ]},
        )
        with patch.object(subject, "github_json", side_effect=api):
            lines = subject.external_contributions()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("- **Issue · Commented** · "))
        self.assertIn("](https://github.com/JetBrains/jcef/issues/47)", lines[0])

    def test_thread_last_updated_by_other_user_is_not_falsely_credited(self):
        item = issue("external/maintained", 8, updated="2026-10-27T00:00:00Z")
        api, _ = mock_api(commented_issues=[item], details={
            ("external/maintained", 8, "issues", "comments"): [
                comment("2026-08-05T10:00:00Z"), comment("2026-10-27T00:00:00Z", user="another")
            ]})
        with patch.object(subject, "github_json", side_effect=api):
            self.assertIn("2026-08-05", subject.external_contributions()[0])

    def test_search_match_without_own_comment_is_not_displayed(self):
        item = issue("external/project", 8)
        api, _ = mock_api(commented_issues=[item], details={
            ("external/project", 8, "issues", "comments"): [
                comment("2026-10-25T00:00:00Z", user="other")
            ]})
        with patch.object(subject, "github_json", side_effect=api):
            self.assertEqual(subject.external_contributions(), [
                "_No recent public contributions to external repositories found._"
            ])

    def test_private_repo_noise_and_owned_repos_are_filtered(self):
        api, calls = mock_api(
            commented_issues=[
                issue(f"{USER}/private", 9),
                issue("other/public", 10),
            ],
            details={("other/public", 10, "issues", "comments"): [
                comment("2026-10-25T00:00:00Z", user="other")
            ]},
        )
        with patch.object(subject, "github_json", side_effect=api):
            lines = subject.external_contributions()
        self.assertEqual(len(lines), 1)
        self.assertIn("No recent", lines[0])
        self.assertFalse(any(f"/repos/{USER}/" in p for p, _ in calls))

    def test_multiple_authored_threads_in_same_repo_are_preserved(self):
        api, _ = mock_api(authored_issues=[
            issue("zed-industries/zed", 61349, updated="2026-10-26T00:00:00Z"),
            issue("zed-industries/zed", 61865, updated="2026-09-11T00:00:00Z"),
        ])
        with patch.object(subject, "github_json", side_effect=api):
            lines = subject.external_contributions()
        self.assertEqual(len(lines), 2)
        self.assertIn("#61349", lines[0])
        self.assertIn("#61865", lines[1])

    def test_four_authored_plus_two_collaboration_threads(self):
        authored = [
            issue("owned-contributions/external", number,
                  updated=f"2026-10-{number:02d}T00:00:00Z") for number in range(21, 26)
        ]
        recent = [issue("other/project", number, updated="2026-10-27T00:00:00Z")
                  for number in (1, 2, 3)]
        details = {("other/project", number, "issues", "comments"):
                   [comment("2026-10-27T00:00:00Z")] for number in (1, 2, 3)}
        api, _ = mock_api(authored_issues=authored, commented_issues=recent, details=details)
        with patch.object(subject, "github_json", side_effect=api):
            lines = subject.external_contributions()
        self.assertEqual(len(lines), 6)
        self.assertEqual(sum("owned-contributions/external" in x for x in lines), 4)
        self.assertEqual(sum("other/project" in x for x in lines), 2)

    def test_authored_issue_and_pr_failures_are_fatal(self):
        api, _ = mock_api(fail_query=f"author:{USER}")
        with patch.object(subject, "github_json", side_effect=api):
            with self.assertRaises(OSError):
                subject.external_contributions()

    def test_collaboration_search_failure_is_fatal_to_preserve_last_good(self):
        api, _ = mock_api(authored_issues=[issue("JetBrains/jcef", 47)],
                          fail_query=f"commenter:{USER}")
        with patch.object(subject, "github_json", side_effect=api):
            with self.assertRaises(OSError):
                subject.external_contributions()

    def test_incomplete_collaboration_search_is_fatal(self):
        api, _ = mock_api(incomplete_query=f"reviewed-by:{USER}")
        with patch.object(subject, "github_json", side_effect=api):
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                subject.external_contributions()

    def test_review_pending_or_wrong_user_cannot_be_claimed(self):
        repo = "other/reviews"
        item = issue(repo, 3, pr=True)
        api, _ = mock_api(reviewed_prs=[item], details={
            (repo, 3, "pulls", "reviews"): [
                review("2026-10-21T00:00:00Z", state="PENDING"),
                review("2026-10-22T00:00:00Z", user="other"),
            ],
        })
        with patch.object(subject, "github_json", side_effect=api):
            self.assertEqual(subject.external_contributions(), [
                "_No recent public contributions to external repositories found._"
            ])

    def test_comment_scan_paginates_and_verifies_correct_user(self):
        repo = "other/project"
        item = issue(repo, 7)
        many = [comment("2026-10-01T00:00:00Z", user="other") for _ in range(100)]
        many.append(comment("2026-10-20T00:00:00Z"))
        api, calls = mock_api(commented_issues=[item], details={
            (repo, 7, "issues", "comments"): many,
        })
        with patch.object(subject, "github_json", side_effect=api):
            lines = subject.external_contributions()
        self.assertIn("2026-10-20", lines[0])
        self.assertEqual([params["page"] for path, params in calls if path.endswith("/comments")], [1, 2])

    def test_truncated_comment_history_aborts_instead_of_claiming_partial(self):
        repo = "other/project"
        item = issue(repo, 7)
        api, _ = mock_api(commented_issues=[item], details={
            (repo, 7, "issues", "comments"): [
                comment("2026-10-01T00:00:00Z", user="other")
                for _ in range(300)
            ],
        })
        with patch.object(subject, "github_json", side_effect=api):
            with self.assertRaisesRegex(RuntimeError, "could not verify collaboration"):
                subject.external_contributions()

    def test_only_scan_eight_search_candidates_per_source(self):
        items = [issue("other/repo", n) for n in range(1, 12)]
        details = {
            ("other/repo", n, "issues", "comments"): [comment("2026-10-20T00:00:00Z")]
            for n in range(1, 12)
        }
        api, calls = mock_api(commented_issues=items, details=details)
        with patch.object(subject, "github_json", side_effect=api):
            subject.external_contributions()
        self.assertEqual(
            len([path for path, _ in calls if path.endswith("/issues/9/comments")]),
            0,
        )
        self.assertEqual(
            len([path for path, _ in calls if "/issues/" in path and path.endswith("/comments")]),
            8,
        )


if __name__ == "__main__":
    unittest.main()
