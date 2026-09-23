"""Offline regression checks for the separately deployed private MCP bridge.

Run using that service's virtualenv Python; no credentials or network are used.
"""

import sys
import unittest
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1] / "agent-workspace/.agent-runtime/services/baishi-aa-mcp"
sys.path.insert(0, str(SERVICE))
from server import BestrieClient


class ResponseTests(unittest.TestCase):
    def test_success_with_missing_or_null_error(self):
        for envelope in ({}, {"error": None}):
            for result, expected in (
                ({"content": [{"type": "text", "text": "[]"}]}, []),
                ({"structuredContent": {"count": 0}}, {"count": 0}),
            ):
                with self.subTest(envelope=envelope, result=result):
                    self.assertEqual(
                        BestrieClient._extract_result({**envelope, "result": result}), expected
                    )

    def test_real_errors_remain_errors(self):
        for response in (
            {"error": {"code": -32603, "message": "synthetic failure"}},
            {"error": {}},
            {"error": None, "result": {"isError": True}},
        ):
            with self.subTest(response=response), self.assertRaises(RuntimeError):
                BestrieClient._extract_result(response)


if __name__ == "__main__":
    unittest.main()
