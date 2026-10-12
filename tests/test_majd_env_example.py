import ast
import re
import unittest
from pathlib import Path


class MajdEnvExampleTests(unittest.TestCase):
    def test_env_example_documents_majd_configuration(self):
        root = Path(__file__).resolve().parents[1]
        source = ast.parse((root / "majd_sales_bot.py").read_text(encoding="utf-8"))
        # Read the real configuration names instead of maintaining a second list.
        env_names = {
            node.args[0].value
            for node in ast.walk(source)
            if isinstance(node, ast.Call)
            and ast.unparse(node.func) == "os.environ.get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        }
        # Render supplies release metadata; operators do not configure it.
        env_names.discard("RENDER_GIT_COMMIT")
        self.assertTrue(env_names, "No Majd environment configuration was found")
        example = (root / ".env.example").read_text(encoding="utf-8")
        documented_names = set(re.findall(r"(?m)^([A-Z][A-Z0-9_]*)\s*=", example))
        missing_names = sorted(env_names - documented_names)
        self.assertEqual(
            missing_names, [],
            f"Undocumented Majd environment variables: {', '.join(missing_names)}",
        )


if __name__ == "__main__":
    unittest.main()
