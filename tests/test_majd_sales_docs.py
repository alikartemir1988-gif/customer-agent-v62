import ast
import re
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MajdSalesDocsTests(unittest.TestCase):
    def test_sales_offer_uses_only_the_bots_public_price(self):
        # Read the constant without importing the service or running startup hooks.
        module = ast.parse((ROOT / "majd_sales_bot.py").read_text(encoding="utf-8"))
        public_price = next(
            ast.literal_eval(node.value)
            for node in module.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "PUBLIC_PRICE_USD"
                    for target in node.targets)
        )
        offer = (ROOT / "SALES.md").read_text(encoding="utf-8")
        amounts = re.findall(
            r"(?:\bUSD\s*|\$\s*)(\d[\d,]*(?:\.\d+)?)"
            r"|(\d[\d,]*(?:\.\d+)?)\s*(?:USD\b|dollars?\b|دولار)",
            offer, re.IGNORECASE,
        )
        self.assertTrue(amounts, "SALES.md must state the public USD price")
        documented_prices = {Decimal((before or after).replace(",", ""))
                             for before, after in amounts}
        self.assertEqual(
            documented_prices, {Decimal(str(public_price).replace(",", ""))},
            "Every public price in SALES.md must match Majd's PUBLIC_PRICE_USD",
        )


if __name__ == "__main__":
    unittest.main()
