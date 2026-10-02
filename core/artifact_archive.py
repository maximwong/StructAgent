"""Opt-in, verified archives of terminal workflow artifacts. Never resumes engineering tools."""

import hashlib
import json
from pathlib import Path
import re
import zipfile

from .persistence import write_json
from .project_state import ProjectStateStore


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class ArtifactArchive:
    def __init__(self, project_root):
        self.root = Path(project_root).resolve()
        if not (self.root / "agent/state.sqlite3").is_file():
            raise ValueError("Existing workflow state is required.")
        self.state = ProjectStateStore(self.root / "agent/state.sqlite3")
        self.archives = self.root / "archives"

    def _path(self, relative):
        if (not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative
                or relative.startswith("/") or any(p in ("", ".", "..") for p in relative.split("/"))):
            raise ValueError("Invalid project-relative artifact path.")
        path = self.root / relative
        if not path.resolve().is_relative_to(self.root) or any(p.is_symlink() or p.is_junction()
                for p in (path, *path.parents) if p != self.root and p.is_relative_to(self.root)):
            raise ValueError("Artifact paths must stay inside the project without links.")
        return path

    def _terminal(self, run_id):
        if not isinstance(run_id, str) or re.fullmatch(r"[0-9a-f]{32}", run_id) is None:
            raise ValueError("Invalid run identity.")
        record = self.state.get(run_id)
        if (record["tool"] != "engineering_agent" or record["state"] not in ("COMPLETED", "FAILED", "INTERRUPTED")
                or record["metadata"].get("external_started")):
            raise ValueError("Running or unresolved external sessions cannot be archived.")
        return record

    def _files(self, run_id):
        record = self._terminal(run_id)
        directories = [self._path("agent/" + run_id)]
        for call in record["metadata"]["tool_calls"]:
            result_path = self._path("agent/" + run_id + "/" + call["step"] + ".json")
            if Path(call["result_path"]).resolve() != result_path:
                raise ValueError("Result ownership differs from the workflow.")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            metadata = result.get("metadata", {})
            if not metadata.get("run_directory"):
                continue
            candidate = Path(metadata["run_directory"])
            directory = candidate.resolve()  # Windows may report the same directory using an 8.3 alias.
            relative = directory.relative_to(self.root).as_posix()
            for ancestor in (candidate, *candidate.parents):
                if ancestor.resolve() == self.root:
                    break
                if ancestor.is_symlink() or ancestor.is_junction():
                    raise ValueError("Artifact paths must not use links.")
            directory = self._path(relative)
            tool_run = metadata.get("run_id")
            if directory.name != tool_run or not re.fullmatch(r"[0-9a-f]{32}", tool_run or ""):
                raise ValueError("Tool directory ownership is missing.")
            store_path = directory.parent / "state.sqlite3"
            if not store_path.is_file():
                raise ValueError("Tool state is missing; retain the diagnostics.")
            tool_record = ProjectStateStore(store_path).get(tool_run)
            if (tool_record["project_id"] != record["project_id"] or tool_record["tool"] != call["tool"]
                    or tool_record["state"] not in ("COMPLETED", "FAILED", "INTERRUPTED")
                    or Path(tool_record["metadata"].get("run_directory", "")).resolve() != directory):
                raise ValueError("Tool state is unresolved or has another owner.")
            if metadata.get("external_started") or tool_record["metadata"].get("external_started"):
                closed = False
                for artifact in result.get("artifacts", []):
                    if artifact.get("type") == "verification":
                        receipt = self._path(Path(artifact["path"]).relative_to(self.root).as_posix())
                        data = json.loads(receipt.read_text(encoding="utf-8-sig"))
                        closed |= data.get("run_id") == tool_run and data.get("owned_document_closed") is True
                if not closed:
                    raise ValueError("External session closure is not verified; retain the diagnostics.")
            directories.append(directory)
        files = {}
        for directory in directories:
            if directory.exists():
                for path in directory.rglob("*"):
                    relative = path.relative_to(self.root).as_posix()
                    checked = self._path(relative)
                    if checked.is_file():
                        if path.name.startswith(".env") or path.suffix in (".sqlite3", ".pem", ".key"):
                            raise ValueError("Unexpected configuration inside artifact directory.")
                        files[relative] = checked
        return record, files

    def inventory(self):
        rows = []
        for record in self.state.list_runs():
            row = {"run_id": record["run_id"], "state": record["state"], "eligible": False, "bytes": 0}
            index = self.archives / (record["run_id"] + ".json")
            if index.is_file():
                row["archive"] = str(index.with_suffix(".zip"))
            else:
                try:
                    _, files = self._files(record["run_id"])
                    row.update(eligible=True, bytes=sum(p.stat().st_size for p in files.values()), files=len(files))
                except (ValueError, KeyError, OSError, TypeError):
                    row["reason"] = "Keep running, unresolved, or unverified artifacts."
            rows.append(row)
        return rows

    def verify(self, run_id):
        self._terminal(run_id)
        index = json.loads(self._path("archives/" + run_id + ".json").read_text(encoding="utf-8"))
        archive_path = self._path("archives/" + run_id + ".zip")
        if index["run_id"] != run_id or digest(archive_path) != index["sha256"]:
            raise ValueError("Archive identity or checksum mismatch.")
        with zipfile.ZipFile(archive_path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            entries = manifest["files"]
            expected = {"manifest.json", *("files/" + e["path"] for e in entries)}
            if (manifest["run_id"] != run_id or len(entries) != len(expected) - 1
                    or set(archive.namelist()) != expected or len(archive.namelist()) != len(expected)):
                raise ValueError("Archive members differ from the manifest.")
            for entry in entries:
                self._path(entry["path"])
                data = archive.read("files/" + entry["path"])
                if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                    raise ValueError("Archive member checksum mismatch.")
        return manifest

    def archive(self, run_id, *, compact=False):
        record, files = self._files(run_id)
        if not files:
            raise ValueError("No artifacts to archive.")
        self.archives.mkdir(exist_ok=True)
        archive_path = self._path("archives/" + run_id + ".zip")
        manifest = {"format": 1, "run_id": run_id, "project_id": record["project_id"], "state": record["state"],
                    "files": [{"path": r, "bytes": p.stat().st_size, "sha256": digest(p)} for r, p in sorted(files.items())]}
        # Exclusive creation avoids replacement of a prior archive. A failed write is retained for diagnosis.
        with archive_path.open("xb") as stream, zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            for relative, path in sorted(files.items()):
                archive.write(path, "files/" + relative)
        write_json(archive_path.with_suffix(".json"), {"run_id": run_id, "sha256": digest(archive_path)}, exclusive=True)
        self.verify(run_id)
        if compact:
            self._terminal(run_id)
            # Validate ALL source files before removing any; immutable design references and databases are outside this set.
            for entry in manifest["files"]:
                if digest(self._path(entry["path"])) != entry["sha256"]:
                    raise ValueError("Source changed during archiving; no source files were removed.")
            for entry in manifest["files"]:
                self._path(entry["path"]).unlink()
        return {"run_id": run_id, "archive": str(archive_path), "files": len(files), "compacted": compact}

    def restore(self, run_id):
        manifest = self.verify(run_id)
        # Preflight every destination before writing anything. Existing different files are preserved.
        for entry in manifest["files"]:
            path = self._path(entry["path"])
            if path.exists() and (not path.is_file() or digest(path) != entry["sha256"]):
                raise FileExistsError("Restore would replace different existing data.")
        with zipfile.ZipFile(self._path("archives/" + run_id + ".zip")) as archive:
            for entry in manifest["files"]:
                path = self._path(entry["path"])
                if not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("xb") as stream:
                        stream.write(archive.read("files/" + entry["path"]))
        return {"run_id": run_id, "restored": True, "files": len(manifest["files"])}
