from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "update_selected_work.py"
SPEC = importlib.util.spec_from_file_location("update_selected_work", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sample_readme() -> str:
    return (
        "before\n"
        f"{MODULE.START_MARKER}\n"
        "<table>\n"
        "<tr>\n"
        "<td>\n\n"
        "<!-- repo-id:100 -->\n"
        "### [Project A](https://github.com/luceat-lux-vestra/Project-A-old)\n\n"
        "Description A.\n\n"
        "</td>\n"
        "<td>\n\n"
        "<!-- repo-id:200 -->\n"
        "### [Project B](https://github.com/luceat-lux-vestra/Project-B)\n\n"
        "Description B.\n\n"
        "</td>\n"
        "</tr>\n"
        "</table>\n"
        f"{MODULE.END_MARKER}\n"
        "after\n"
    )


class SelectedWorkTests(unittest.TestCase):
    def test_update_tracks_rename_without_touching_selected_work_content(self) -> None:
        original = sample_readme()
        urls = {
            100: "https://github.com/luceat-lux-vestra/Project-A",
            200: "https://github.com/luceat-lux-vestra/Project-B",
        }
        updated = MODULE.update_selected_work(original, urls.__getitem__)

        expected = original.replace(
            "https://github.com/luceat-lux-vestra/Project-A-old",
            "https://github.com/luceat-lux-vestra/Project-A",
        )
        self.assertEqual(updated, expected)
        self.assertIn("Description A.", updated)
        self.assertIn("Description B.", updated)

    def test_update_supports_inline_logo_in_heading(self) -> None:
        original = (
            "before\n"
            f"{MODULE.START_MARKER}\n"
            "<!-- repo-id:100 -->\n"
            "### <a href=\"https://github.com/luceat-lux-vestra/Project-A-old\">"
            "<img src=\"logo.svg\" width=\"24\" height=\"24\" alt=\"Project A logo\" /></a> "
            "[Project A](https://github.com/luceat-lux-vestra/Project-A-old)\n"
            f"{MODULE.END_MARKER}\n"
            "after\n"
        )

        updated = MODULE.update_selected_work(
            original,
            lambda _: "https://github.com/luceat-lux-vestra/Project-A",
        )

        self.assertIn(
            "[Project A](https://github.com/luceat-lux-vestra/Project-A)",
            updated,
        )
        self.assertIn(
            "<a href=\"https://github.com/luceat-lux-vestra/Project-A-old\">",
            updated,
        )
        self.assertIn("<img src=\"logo.svg\"", updated)

    def test_collect_repo_ids_rejects_unannotated_selected_heading(self) -> None:
        block = (
            "<!-- repo-id:100 -->\n"
            "### [Project A](https://github.com/luceat-lux-vestra/Project-A)\n"
            "### [Project B](https://github.com/luceat-lux-vestra/Project-B)\n"
        )
        with self.assertRaises(RuntimeError):
            MODULE.collect_repo_ids(block)

    def test_collect_repo_ids_rejects_duplicate_ids(self) -> None:
        block = (
            "<!-- repo-id:100 -->\n"
            "### [Project A](https://github.com/luceat-lux-vestra/Project-A)\n"
            "<!-- repo-id:100 -->\n"
            "### [Project B](https://github.com/luceat-lux-vestra/Project-B)\n"
        )
        with self.assertRaises(RuntimeError):
            MODULE.collect_repo_ids(block)

    def test_resolve_repo_url_rejects_owner_change(self) -> None:
        transferred = {
            "owner": {"login": "someone-else"},
            "private": False,
            "html_url": "https://github.com/someone-else/Project-A",
        }
        with mock.patch.object(MODULE, "request_repo", return_value=transferred):
            with self.assertRaises(RuntimeError):
                MODULE.resolve_repo_url(100)

    def test_resolve_repo_url_rejects_private_repository(self) -> None:
        private = {
            "owner": {"login": "luceat-lux-vestra"},
            "private": True,
            "html_url": "https://github.com/luceat-lux-vestra/Project-A",
        }
        with mock.patch.object(MODULE, "request_repo", return_value=private):
            with self.assertRaises(RuntimeError):
                MODULE.resolve_repo_url(100)

    def test_main_preserves_last_known_good_on_retryable_api_failure(self) -> None:
        original = sample_readme()
        with tempfile.TemporaryDirectory() as tmp:
            readme = Path(tmp) / "README.md"
            readme.write_text(original, encoding="utf-8")
            with (
                mock.patch.object(MODULE, "README_PATH", readme),
                mock.patch.object(MODULE, "STRICT_UPSTREAM", False),
                mock.patch.object(
                    MODULE,
                    "resolve_repo_url",
                    side_effect=MODULE.TemporaryGitHubError("temporary failure"),
                ),
            ):
                self.assertEqual(MODULE.main(), 0)
            self.assertEqual(readme.read_text(encoding="utf-8"), original)

    def test_main_propagates_retryable_api_failure_in_strict_mode(self) -> None:
        original = sample_readme()
        with tempfile.TemporaryDirectory() as tmp:
            readme = Path(tmp) / "README.md"
            readme.write_text(original, encoding="utf-8")
            with (
                mock.patch.object(MODULE, "README_PATH", readme),
                mock.patch.object(MODULE, "STRICT_UPSTREAM", True),
                mock.patch.object(
                    MODULE,
                    "resolve_repo_url",
                    side_effect=MODULE.TemporaryGitHubError("temporary failure"),
                ),
            ):
                with self.assertRaises(MODULE.TemporaryGitHubError):
                    MODULE.main()
            self.assertEqual(readme.read_text(encoding="utf-8"), original)

    def test_missing_markers_fail_instead_of_silently_succeeding(self) -> None:
        with self.assertRaises(RuntimeError):
            MODULE.update_selected_work("no markers here", lambda _: "unused")


if __name__ == "__main__":
    unittest.main()
