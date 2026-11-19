import unittest
from pathlib import Path


class UpdateProfileWorkflowTest(unittest.TestCase):
    def test_blog_publication_dispatch_and_hourly_fallback_are_enabled(self):
        source = Path('.github/workflows/update-profile.yml').read_text(encoding='utf-8')
        self.assertIn('repository_dispatch:', source)
        self.assertIn('types: [blog-publication]', source)
        self.assertIn('cron: "17 * * * *"', source)
        self.assertIn('BLOG_FEED: https://blog.ox0.uk/rss/', source)

    def test_writing_and_knowledge_keeps_ek_outside_feed_managed_publications(self):
        source = Path('README.md').read_text(encoding='utf-8')
        self.assertIn('## Writing & Knowledge', source)
        self.assertIn('### Engineering Knowledge', source)
        self.assertIn('### Recent Publications', source)
        self.assertIn('https://github.com/luceat-lux-vestra/engineering-knowledge', source)
        self.assertIn('<!-- LATEST-WRITING:START -->', source)
        self.assertIn('<!-- LATEST-WRITING:END -->', source)
        ek_position = source.index('### Engineering Knowledge')
        publications_position = source.index('### Recent Publications')
        start = source.index('<!-- LATEST-WRITING:START -->')
        end = source.index('<!-- LATEST-WRITING:END -->')
        self.assertLess(ek_position, publications_position)
        self.assertLess(publications_position, start)
        self.assertLess(start, end)
        self.assertNotIn('engineering-knowledge', source[start:end])


if __name__ == '__main__':
    unittest.main()
