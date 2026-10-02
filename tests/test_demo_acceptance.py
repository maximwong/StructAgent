"""Acceptance harness contracts use recorded parsing and explicitly simulated CAD only."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from examples.demo_acceptance import DemoAcceptance, ROOT, read_json
from llm import GatewayError
from tests.semantic_fixtures import floor_proposal
from tools.floor.cad_adapter import FloorCADError


class RecordedGateway:
    def __init__(self):
        self.calls = []
        self.failure = False

    def complete(self, messages):
        text = messages[-1]["content"]
        self.calls.append(text)
        if self.failure:
            raise GatewayError("api_timeout", "Simulated timeout", {"model": "SIMULATED"})
        spec = read_json(ROOT / "demos/floor_cases.json")
        values = {c["text"]: c["parameters"] for c in spec["cases"]}
        values[spec["probes"][2]["text"]] = {**spec["cases"][0]["parameters"], "span_x": 7200}
        if text == spec["probes"][0]["text"]:
            parameters = {**spec["cases"][0]["parameters"], "live_load": None}
            proposal = floor_proposal(parameters)
        elif text == spec["probes"][1]["text"]:
            proposal = floor_proposal({**spec["cases"][0]["parameters"], "concrete": "C50"}, concrete="C50", load="2kN/m²")
        else:
            parameters = values[text]
            pair = "7.2m×6m" if text == spec["probes"][2]["text"] else ("5.4m×6m" if parameters["span_x"] == 5400 else "6m×6m")
            load = "2kN/m²" if text == spec["probes"][2]["text"] else ("3.0kN/m²" if parameters["live_load"] == 3 else "2.0kN/m²")
            proposal = floor_proposal(parameters, pair=pair, concrete=parameters["concrete"], load=load)
        return proposal, {"model": "SIMULATED"}


class SimulatedCAD:
    def __init__(self):
        self.calls = []
        self.corrupt_previous = False
        self.closed = True
        self.unknown_recovery = False

    def execute(self, directory, run_id, timeout):
        self.calls.append(directory)
        if timeout == 10:
            code = "cad_recovery_required" if self.unknown_recovery else "cad_timeout"
            raise FloorCADError(code, "Simulated CAD fault; no desktop was touched.")
        scene = read_json(directory / "drawing_scene.json")
        rows = [row for group in scene["groups"].values() for row in group]
        receipt = {"state": "SUCCESS", "run_id": run_id, "entities": len(rows),
                   "texts": sum(r[0] == "TEXT" for r in rows), "dimensions": sum(r[0] == "DIM" for r in rows),
                   "reopened": True, "scene_verified": True, "owned_document_closed": self.closed,
                   "before": {"CMDECHO": 1}, "after": {"CMDECHO": 1}, "autocad_version": "SIMULATED",
                   "original_documents": ["SIMULATED_USER_DOCUMENT"]}
        (directory / "floor.dwg").write_bytes(("SIMULATED DRAWING " + run_id).encode())
        (directory / "cad_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        if self.corrupt_previous and len(self.calls) > 1:
            (self.calls[0] / "floor.dwg").write_bytes(b"Modified test fixture")
        return receipt


class DemoTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="demo_acceptance_")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "中文 工程"
        self.gateway = RecordedGateway()
        self.backend = SimulatedCAD()
        self.suite = DemoAcceptance(self.root, self.gateway, cad_backend=self.backend, evidence_kind="simulated")

    def test_two_rounds_and_fault_boundary_preserve_artifacts_and_distinct_runs(self):
        result = self.suite.run(rounds=2, timeout_probe=True)
        self.assertTrue(result["success"], result)
        self.assertEqual([r["case"] for r in result["runs"]],
            ["missing_load", "unsupported_material", "design_rejection", "A", "B", "C", "cad_timeout", "A", "B", "C"])
        self.assertEqual(len({r["run_id"] for r in result["runs"]}), 10)
        self.assertEqual(len(self.gateway.calls), 10)
        self.assertEqual(len(self.backend.calls), 7)
        self.assertEqual(result["checked_files"], 48)
        self.assertTrue(result["previous_artifacts_unchanged"])
        self.assertEqual(result["evidence_kind"], "simulated")
        self.assertTrue(all(r["qualified"] for r in result["runs"]))
        self.assertTrue(all(self.suite.state.get(r["run_id"])["persistence_state"] != "RUNNING" for r in result["runs"]))

    def test_unexpected_api_error_stops_without_automatic_retry_or_cad(self):
        self.gateway.failure = True
        result = self.suite.run()
        self.assertFalse(result["success"])
        self.assertEqual(len(result["runs"]), 1)
        self.assertEqual(len(self.gateway.calls), 1)
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(result["runs"][-1]["errors"][0]["code"], "api_timeout")

    def test_mutated_previous_dwg_is_detected_and_stops_suite(self):
        self.backend.corrupt_previous = True
        result = self.suite.run(rounds=1)
        self.assertFalse(result["success"])
        self.assertEqual(len(result["runs"]), 5)
        self.assertIn("earlier published artifact", result["runs"][-1]["verification_error"])

    def test_success_receipt_with_unclosed_document_does_not_qualify(self):
        self.backend.closed = False
        result = self.suite.run(rounds=1)
        self.assertFalse(result["success"])
        self.assertEqual(len(result["runs"]), 4)

    def test_simulated_receipts_cannot_be_reported_as_live(self):
        self.suite.kind = "live"
        result = self.suite.run(rounds=1)
        self.assertFalse(result["success"])
        self.assertIn("Simulated", result["runs"][-1]["verification_error"])

    def test_pending_recovery_stops_before_second_round(self):
        self.backend.unknown_recovery = True
        result = self.suite.run(rounds=2, timeout_probe=True)
        self.assertFalse(result["success"])
        self.assertEqual(result["runs"][-1]["status"], "recovery_required")
        self.assertEqual(len(result["runs"]), 7)

    def test_invalid_round_budget_is_rejected(self):
        for value in (True, 0, 4, 1.5):
            with self.assertRaises(ValueError):
                self.suite.run(rounds=value)


if __name__ == "__main__":
    unittest.main()
