import subprocess
import tempfile
import unittest
from pathlib import Path


class BenchmarkGeminiImageMockTests(unittest.TestCase):
    def test_mock_benchmark_generates_markdown_report(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "benchmark_gemini_image.py"
        image = root / "tests" / "pizza.jpg"

        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "mock_report.md"
            cmd = [
                "python3",
                str(script),
                "--mock",
                "--image",
                str(image),
                "--gender",
                "mulher",
                "--hair-color",
                "castanho",
                "--runs",
                "3",
                "--sleep-between",
                "0",
                "--report-out",
                str(report),
            ]
            proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            self.assertTrue(report.exists(), "report file should be generated")
            content = report.read_text(encoding="utf-8")
            self.assertIn("modo: `mock`", content)
            self.assertIn("tentativas executadas: **3**", content)
            self.assertIn("sucessos: **3**", content)


if __name__ == "__main__":
    unittest.main()

