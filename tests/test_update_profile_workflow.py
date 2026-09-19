import unittest
from pathlib import Path


class UpdateProfileWorkflowTest(unittest.TestCase):
    def test_blog_publication_dispatch_and_hourly_fallback_are_enabled(self):
        source = Path('.github/workflows/update-profile.yml').read_text(encoding='utf-8')
        self.assertIn('repository_dispatch:', source)
        self.assertIn('types: [blog-publication]', source)
        self.assertIn('cron: "17 * * * *"', source)
        self.assertIn('BLOG_FEED: https://blog.ox0.uk/rss/', source)

    def test_publications_section_remains_feed_managed(self):
        source = Path('README.md').read_text(encoding='utf-8')
        self.assertIn('## Publications', source)
        self.assertIn('<!-- LATEST-WRITING:START -->', source)
        self.assertIn('<!-- LATEST-WRITING:END -->', source)


if __name__ == '__main__':
    unittest.main()
