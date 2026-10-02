"""Repeat the approved floor Demo and retain independently checked acceptance evidence."""

import argparse
import hashlib
import json
from pathlib import Path
import time
from uuid import uuid4

from agent.controller import AgentController
from agent.parameter_parser import ParameterParser
from agent.state import AgentState
from config import load_settings
from core import ToolRegistry
from core.persistence import write_json
from tools.floor.language_profile import FloorDemoProfile
from tools.floor.design_adapter import canonical_hash
from tools.floor.plugin import register_floor_workflow
from llm import DeepSeekGateway

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class DemoAcceptance:
    """Floor-specific QA composition. The Agent Controller remains unchanged."""
    def __init__(self, output_root, gateway, *, cad_backend=None, evidence_kind="live"):
        if evidence_kind not in ("live", "simulated"):
            raise ValueError("Unknown evidence kind.")
        self.root = Path(output_root).resolve()
        self.gateway, self.backend, self.kind = gateway, cad_backend, evidence_kind
        self.spec = read_json(ROOT / "demos/floor_cases.json")
        self.baselines = read_json(ROOT / "demos/floor_baselines.json")
        self.state = AgentState(self.root / "agent")

    def controller(self, timeout=240):
        registry = ToolRegistry()
        workflow = register_floor_workflow(registry, self.root, cad_timeout=timeout, cad_backend=self.backend)
        parser = ParameterParser(registry, self.gateway, [FloorDemoProfile()])
        return AgentController(registry, parser, self.state, [workflow])

    def _check(self, result, case, hashes, identities, original_documents):
        if result["run_id"] in identities:
            raise ValueError("Workflow identity was reused.")
        identities.add(result["run_id"])
        persisted = self.state.get(result["run_id"])
        if persisted["status"] != result["status"] or persisted["steps"] != result["steps"]:
            raise ValueError("Persisted workflow differs from the returned state.")
        if "expected_status" in case:
            if (result["status"] != case["expected_status"] or result["success"] or result["artifacts"]
                    or len(result["tool_calls"]) != case["expected_calls"]
                    or (case.get("error") and case["error"] not in {e["code"] for e in result["errors"]})):
                raise ValueError("Failure probe did not stop at the expected boundary.")
            if result["status"] == "needs_input" and "live_load" not in result["parse_result"]["missing_fields"]:
                raise ValueError("Missing live load was not reported.")
            return {}, original_documents
        if (not result["success"] or result["steps"] != {"parse": "completed", "design": "completed", "cad": "completed"}
                or len(result["tool_calls"]) != 2 or persisted["persistence_state"] != "COMPLETED"):
            raise ValueError("Demo workflow did not complete.")
        parameters = result["parse_result"]["envelope"]["parameters"]
        if any(parameters.get(k) != v for k, v in case["parameters"].items()):
            raise ValueError("Parsed parameters differ from the declared Demo.")
        design, cad = [read_json(c["result_path"]) for c in result["tool_calls"]]
        baseline = self.baselines[case["id"]]
        if (design["metadata"]["legacy_result_sha256"] != baseline["design_sha256"]
                or canonical_hash(design["result"]["legacy_result"]) != baseline["design_sha256"]
                or cad["metadata"]["scene_sha256"] != baseline["scene_sha256"]):
            raise ValueError("Complete design or CAD scene differs from the frozen Demo baseline.")
        for identity in (design["metadata"]["design_result_ref"], cad["result"]["run_id"]):
            if identity in identities:
                raise ValueError("Design or CAD identity was reused.")
            identities.add(identity)
        artifacts = {a["type"]: Path(a["path"]).resolve() for a in result["artifacts"]}
        scene_path = Path(cad["metadata"]["run_directory"]) / "drawing_scene.json"
        if canonical_hash(read_json(scene_path)) != baseline["scene_sha256"]:
            raise ValueError("Saved scene differs from the frozen Demo baseline.")
        receipt = read_json(artifacts["verification"])
        if (receipt["run_id"] != cad["result"]["run_id"] or receipt.get("state") != "SUCCESS"
                or receipt.get("owned_document_closed") is not True or receipt.get("reopened") is not True
                or receipt.get("scene_verified") is not True or receipt["before"] != receipt["after"]
                or any(receipt.get(k) != baseline[k] for k in ("entities", "texts", "dimensions"))):
            raise ValueError("CAD save/reopen, entity counts, cleanup or system variables failed verification.")
        documents = receipt["original_documents"]
        if original_documents is not None and documents != original_documents:
            raise ValueError("Original CAD documents changed between Demo runs.")
        version = receipt.get("autocad_version")
        if self.kind == "live" and (not isinstance(version, str) or not version.strip() or "SIMULATED" in version.upper()):
            raise ValueError("Simulated receipts cannot qualify as desktop acceptance.")
        paths = ([Path(c["result_path"]).resolve() for c in result["tool_calls"]] + list(artifacts.values())
                 + [scene_path.resolve(), scene_path.with_name("floor_data.dat").resolve(),
                    self.root / "designs" / (design["metadata"]["design_result_ref"] + ".json")])
        for path in paths:
            if not path.is_relative_to(self.root) or path in hashes or path.stat().st_size <= 0:
                raise ValueError("Artifact is empty, shared, or outside the output root.")
            hashes[path] = file_hash(path)
        return {"design_sha256": baseline["design_sha256"], "scene_sha256": baseline["scene_sha256"],
                "entities": receipt["entities"], "texts": receipt["texts"], "dimensions": receipt["dimensions"],
                "dwg": str(artifacts["dwg"]), "dwg_sha256": hashes[artifacts["dwg"]],
                "save_reopen_verified": True}, documents

    def run(self, *, rounds=2, timeout_probe=False, progress=None):
        if type(rounds) is not int or not 1 <= rounds <= 3:
            raise ValueError("rounds must be an integer between 1 and 3.")
        suite_id = uuid4().hex
        directory = self.root / "acceptance" / suite_id
        summary = {"suite_id": suite_id, "evidence_kind": self.kind, "success": False,
                   "status": "running", "rounds": rounds, "runs": [], "previous_artifacts_unchanged": False}
        summary_path = directory / "summary.json"
        write_json(summary_path, summary, exclusive=True)
        plan = [(0, p, 240) for p in self.spec["probes"]]
        for number in range(1, rounds + 1):
            plan.extend((number, c, 240) for c in self.spec["cases"])
            if number == 1 and timeout_probe:
                plan.append((number, {"id": "cad_timeout", "text": self.spec["cases"][0]["text"],
                    "expected_status": "failed", "expected_calls": 2, "error": "cad_timeout"}, 10))
        hashes, identities, original_documents = {}, set(), None
        for number, case, timeout in plan:
            if progress:
                progress({"round": number, "case": case["id"], "status": "running"})
            started = time.monotonic()
            result = self.controller(timeout).run(case["text"], project_id=self.spec["project_id"], profile_name=self.spec["profile"])
            result_path = directory / (f'{len(summary["runs"]):02d}-{case["id"]}.json')
            write_json(result_path, result, exclusive=True)
            row = {"round": number, "case": case["id"], "run_id": result.get("run_id"), "status": result["status"],
                   "qualified": False, "elapsed_seconds": round(time.monotonic() - started, 3), "result_path": str(result_path),
                   "errors": result.get("errors", []), "parse_metadata": result.get("parse_result", {}).get("metadata", {})}
            try:
                detail, original_documents = self._check(result, case, hashes, identities, original_documents)
                if any(not path.is_file() or file_hash(path) != expected for path, expected in hashes.items()):
                    raise ValueError("An earlier published artifact changed.")
                row.update(qualified=True, **detail)
            except (ValueError, KeyError, OSError, TypeError) as exc:
                row["verification_error"] = str(exc) if isinstance(exc, ValueError) else "Incomplete acceptance evidence."
            summary["runs"].append(row)
            if progress:
                progress({"round": number, "case": case["id"], "status": result["status"], "qualified": row["qualified"]})
            summary["status"] = "running" if row["qualified"] else "failed"
            write_json(summary_path, summary)
            if not row["qualified"]:
                return summary
        summary.update(success=True, status="completed", previous_artifacts_unchanged=True,
                       original_documents=original_documents, checked_files=len(hashes))
        write_json(summary_path, summary)
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT / "data/projects/demo")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--timeout-probe", action="store_true", help="Inject a 10-second CAD limit after round 1; retain the failed attempt.")
    args = parser.parse_args()
    settings = load_settings()
    suite = DemoAcceptance(args.output_root, DeepSeekGateway(settings))
    result = suite.run(rounds=args.rounds, timeout_probe=args.timeout_probe,
                       progress=lambda data: print(json.dumps(data, ensure_ascii=True), flush=True))
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
