"""Regression test for evaluation-truth isolation in the product Dataset API."""

from __future__ import annotations

import unittest
from pathlib import Path

from api.dataset_server import create_app


class DatasetApiTruthIsolationTest(unittest.TestCase):
    def test_evaluation_truth_routes_are_not_registered(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app = create_app(root)

        routes = {rule.rule for rule in app.url_map.iter_rules()}
        self.assertFalse(any("evaluation" in route or "truth" in route for route in routes))

        response = app.test_client().get("/evaluation/truth/cnc")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
