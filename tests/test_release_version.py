"""Keep the documented release aligned without importing the application."""

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReleaseVersionTests(unittest.TestCase):
    def test_readme_heading_matches_app_version(self):
        module = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        assignments = [
            node for node in module.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "APP_VERSION"
                    for target in node.targets)
        ]
        self.assertEqual(len(assignments), 1, "app.py must define one APP_VERSION")
        app_version = ast.literal_eval(assignments[0].value)
        heading = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(
            heading, f"# Customer Agent V{app_version}",
            "Update the README release heading when APP_VERSION changes",
        )


if __name__ == "__main__":
    unittest.main()
