import os
import tempfile
import unittest
from pathlib import Path
from backend.app.services.compilation.toolchain import JavaToolchainDetector, JavaToolchainStatus
from backend.app.services.compilation.java_compiler import JavaCompiler
from backend.app.services.execution.java_runner import JavaRunner

class TestJavaToolchainDetection(unittest.TestCase):
    def test_detector_returns_structured_status(self):
        status = JavaToolchainDetector.detect(refresh=True)
        self.assertIsInstance(status, JavaToolchainStatus)
        self.assertIsInstance(status.available, bool)
        self.assertIsInstance(status.status_message, str)
        self.assertIsInstance(status.details, dict)
        self.assertIn("os", status.details)

    def test_missing_java_home_returns_graceful_status(self):
        # Point to a nonexistent directory
        fake_path = "C:\\Nonexistent\\Path\\To\\JavaJDK" if os.name == "nt" else "/nonexistent/java"
        compiler = JavaCompiler(java_home=fake_path)
        with tempfile.TemporaryDirectory() as tmpdir:
            pdir = Path(tmpdir)
            fake_file = pdir / "Test.java"
            fake_file.write_text("class Test {}", encoding="utf-8")
            res = compiler.compile(pdir, fake_file)
            self.assertFalse(res.success)
            self.assertEqual(res.error_type, "TOOLCHAIN_UNAVAILABLE")
            self.assertIn("Java", res.errors)

    def test_java_runner_graceful_missing_toolchain(self):
        fake_path = "C:\\Nonexistent\\Path\\To\\JavaJDK" if os.name == "nt" else "/nonexistent/java"
        runner = JavaRunner(java_home=fake_path)
        with tempfile.TemporaryDirectory() as tmpdir:
            pdir = Path(tmpdir)
            out = runner.execute(pdir, "TestApp", {"key": "value"})
            self.assertEqual(out["status"], "ERROR")
            self.assertEqual(out["error_type"], "TOOLCHAIN_UNAVAILABLE")

    def test_extract_java_version_parser(self):
        # Test the version extraction regex on sample strings
        samples = [
            ('openjdk version "17.0.2" 2022-01-18', "17.0.2", 17),
            ('java version "21.0.1" 2023-10-17', "21.0.1", 21),
            ('java version "1.8.0_292"', "1.8.0_292", 8),
        ]
        import re
        for text, exp_str, exp_major in samples:
            m = re.search(r'version\s*["\']([0-9._]+)["\']', text, re.IGNORECASE)
            self.assertIsNotNone(m)
            ver = m.group(1)
            self.assertEqual(ver, exp_str)
            major = int(ver.split(".")[1]) if ver.startswith("1.") else int(ver.split(".")[0])
            self.assertEqual(major, exp_major)

if __name__ == "__main__":
    unittest.main()
