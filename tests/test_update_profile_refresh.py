import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from scripts import update_profile


README = """# Profile

<!-- LATEST-WRITING:START -->
- old writing
<!-- LATEST-WRITING:END -->

<!-- OSS-CONTRIBUTIONS:START -->
- old contribution
<!-- OSS-CONTRIBUTIONS:END -->
"""


class ProfileRefreshTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.readme_path = Path(directory.name) / "README.md"
        self.readme_path.write_text(README, encoding="utf-8")

    def test_success_updates_sections_without_obsolete_activity_markers(self):
        self.assertNotIn("activity", update_profile.SECTIONS)
        with (
            patch.object(update_profile, "README_PATH", self.readme_path),
            patch.object(update_profile, "latest_writing", return_value=["- new writing"]),
            patch.object(update_profile, "external_contributions", return_value=["- new contribution"]),
            patch.object(update_profile, "generate_github_assets") as assets,
        ):
            self.assertEqual(update_profile.main(), 0)
        assets.assert_called_once_with()
        actual = self.readme_path.read_text(encoding="utf-8")
        self.assertIn("- new writing", actual)
        self.assertIn("- new contribution", actual)
        self.assertNotIn("old writing", actual)

    def test_upstream_failure_is_not_green_and_preserves_readme(self):
        stderr = io.StringIO()
        with (
            patch.object(update_profile, "README_PATH", self.readme_path),
            patch.object(update_profile, "latest_writing", return_value=["- new writing"]),
            patch.object(update_profile, "external_contributions", side_effect=OSError("GitHub unavailable")),
            patch.object(update_profile, "generate_github_assets") as assets,
            redirect_stderr(stderr),
        ):
            self.assertEqual(update_profile.main(), 1)
        assets.assert_not_called()
        self.assertEqual(self.readme_path.read_text(encoding="utf-8"), README)
        self.assertIn("could not update contrib", stderr.getvalue())

    def test_asset_failure_is_not_green_and_preserves_readme(self):
        stderr = io.StringIO()
        with (
            patch.object(update_profile, "README_PATH", self.readme_path),
            patch.object(update_profile, "latest_writing", return_value=["- new writing"]),
            patch.object(update_profile, "external_contributions", return_value=["- new contribution"]),
            patch.object(update_profile, "generate_github_assets", side_effect=RuntimeError("GraphQL unavailable")),
            redirect_stderr(stderr),
        ):
            self.assertEqual(update_profile.main(), 1)
        self.assertEqual(self.readme_path.read_text(encoding="utf-8"), README)
        self.assertIn("could not refresh GitHub metric assets", stderr.getvalue())

    def test_missing_section_markers_fail_instead_of_silently_skipping(self):
        malformed = README.replace("<!-- OSS-CONTRIBUTIONS:END -->", "")
        self.readme_path.write_text(malformed, encoding="utf-8")
        stderr = io.StringIO()
        with (
            patch.object(update_profile, "README_PATH", self.readme_path),
            patch.object(update_profile, "latest_writing", return_value=["- new writing"]),
            patch.object(update_profile, "external_contributions", return_value=["- new contribution"]),
            patch.object(update_profile, "generate_github_assets") as assets,
            redirect_stderr(stderr),
        ):
            self.assertEqual(update_profile.main(), 1)
        assets.assert_not_called()
        self.assertEqual(self.readme_path.read_text(encoding="utf-8"), malformed)
        self.assertIn("README markers missing for contrib", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
