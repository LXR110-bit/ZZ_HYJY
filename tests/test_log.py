import io
import re
import unittest
from contextlib import redirect_stdout

from services.log import log


class TestLog(unittest.TestCase):
    def test_prefixes_iso_timestamp(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            log("[gate] hello")
        out = buf.getvalue()
        self.assertRegex(out, r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[gate\] hello\n$")

    def test_preserves_message_verbatim(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            log("meeting=123 attend=False participants=11")
        self.assertIn("meeting=123 attend=False participants=11", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
