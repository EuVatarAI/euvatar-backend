import subprocess
import tempfile
import unittest
from pathlib import Path


class MockLoadGeminiImageFlowTests(unittest.TestCase):
    def test_generates_markdown_for_100_and_200_users(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "mock_load_gemini_image_flow.py"
        image = root / "tests" / "pizza.jpg"

        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "load_mock_report.md"
            cmd = [
                "python3",
                str(script),
                "--image",
                str(image),
                "--users",
                "100",
                "200",
                "--base-latency-ms",
                "1",
                "--usd-per-image",
                "0.04",
                "--report-out",
                str(report),
            ]
            proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            self.assertTrue(report.exists())

            content = report.read_text(encoding="utf-8")
            self.assertIn("Cenario: 100 pessoas", content)
            self.assertIn("Cenario: 200 pessoas", content)
            self.assertIn("mulher:", content)
            self.assertIn("homem:", content)
            self.assertIn("modo: `mock`", content)


if __name__ == "__main__":
    unittest.main()

