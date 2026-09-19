import base64
import json
import unittest
from unittest.mock import patch

import scripts.update_profile as update_profile


class PublicationsLocaleSelectionTest(unittest.TestCase):
    def test_article_locale_slugs_reads_canonical_article_manifests(self):
        manifest = {
            "variants": [
                {"locale": "ko-KR", "slug": "managed-post"},
                {"locale": "en", "slug": "managed-post-en"},
            ]
        }
        encoded = base64.b64encode(json.dumps(manifest).encode("utf-8")).decode("ascii")

        def fake_public_github_json(path, params=None):
            self.assertEqual(params, {"ref": "main"})
            if path.endswith("/contents/posts"):
                return [{"type": "dir", "name": "managed-post"}]
            if path.endswith("/contents/posts/managed-post/article.json"):
                return {"encoding": "base64", "content": encoded}
            self.fail(f"unexpected GitHub API path: {path}")

        with patch.object(update_profile, "public_github_json", side_effect=fake_public_github_json):
            self.assertEqual(
                update_profile.article_locale_slugs(),
                {"managed-post": "ko-KR", "managed-post-en": "en"},
            )

    def test_latest_writing_uses_managed_locale_not_title_language(self):
        rss = """<?xml version="1.0" encoding="UTF-8"?>
<rss><channel>
  <item>
    <title>ASCII title on the Korean managed projection</title>
    <link>https://blog.ox0.uk/managed-post/</link>
    <pubDate>Sat, 19 Sep 2026 07:00:00 +0000</pubDate>
  </item>
  <item>
    <title>English managed projection</title>
    <link>https://blog.ox0.uk/managed-post-en/</link>
    <pubDate>Sat, 19 Sep 2026 06:59:00 +0000</pubDate>
  </item>
  <item>
    <title>Legacy English post</title>
    <link>https://blog.ox0.uk/legacy-english/</link>
    <pubDate>Sat, 19 Sep 2026 06:58:00 +0000</pubDate>
  </item>
  <item>
    <title>레거시 한국어 글</title>
    <link>https://blog.ox0.uk/legacy-korean/</link>
    <pubDate>Sat, 19 Sep 2026 06:57:00 +0000</pubDate>
  </item>
</channel></rss>""".encode("utf-8")

        with (
            patch.object(
                update_profile,
                "article_locale_slugs",
                return_value={"managed-post": "ko-KR", "managed-post-en": "en"},
            ),
            patch.object(update_profile, "request_bytes", return_value=rss),
        ):
            lines = update_profile.latest_writing()

        self.assertEqual(
            lines,
            [
                "- [English managed projection](https://blog.ox0.uk/managed-post-en/) — 2026-09-19",
                "- [Legacy English post](https://blog.ox0.uk/legacy-english/) — 2026-09-19",
            ],
        )
        self.assertNotIn("managed-post/", "\n".join(lines))
        self.assertNotIn("레거시", "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
