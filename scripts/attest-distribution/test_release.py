import base64
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

import release


class SourceReleaseTests(unittest.TestCase):
    def test_altered_npm_archive_fails(self):
        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / "package.tgz"
            file.write_bytes(b"changed")
            sri = "sha512-" + base64.b64encode(hashlib.sha512(b"original").digest()).decode()
            with self.assertRaisesRegex(ValueError, "digest"):
                release.verify_sri(file, sri)

    def test_source_archive_repeats_after_mtime_changes(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "source"
            folder.mkdir()
            (folder / "test").write_text("foo")
            first, second = Path(d) / "one.tgz", Path(d) / "two.tgz"
            release.archive(folder, first)
            os.utime(folder / "test", (313125112, 313125112))
            release.archive(folder, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_extracts_actual_uploaded_module_including_trailing_newline(self):
        raw = b'--bound\r\nContent-Disposition: form-data; name="index.js"; filename="index.js"\r\nContent-Type: application/javascript+module\r\n\r\none\n\r\n--bound--\r\n'
        self.assertEqual(release.uploaded_js(raw), b"one\n")

    def test_rejects_traversal(self):
        with self.assertRaisesRegex(ValueError, "path"):
            release.member_path("project/../oops")

if __name__ == "__main__":
    unittest.main()
