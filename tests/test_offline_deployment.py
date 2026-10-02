import json
from pathlib import Path
import re
import tempfile
import unittest
import zipfile

from deployment.offline import LOCK, digest, install, requirements, safe_members, verify


class OfflineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        with zipfile.ZipFile(self.bundle / "runtime.zip", "w") as archive:
            archive.writestr("python.exe", b"fixture, not executable")
        self.manifest = {"format": 1, "platform": "win_amd64", "python": "3.12.14", "wheels": [],
            "runtime": {"file": "runtime.zip", "sha256": digest(self.bundle / "runtime.zip")}}
        self.lock = self.root / "trusted-lock.json"
        self.lock.write_text(json.dumps(self.manifest))
        (self.bundle / "manifest.json").write_text(json.dumps(self.manifest))
        (self.bundle / "requirements.lock").write_text("")

    def test_artifacts_match_trusted_lock_and_corruption_is_detected(self):
        self.assertEqual(verify(self.bundle, self.lock), self.manifest)
        (self.bundle / "runtime.zip").write_bytes(b"wrong")
        with self.assertRaises(ValueError):
            verify(self.bundle, self.lock)

    def test_manifest_and_requirements_changes_cannot_disable_hashes(self):
        (self.bundle / "requirements.lock").write_text("unlocked-package")
        with self.assertRaises(ValueError):
            verify(self.bundle, self.lock)
        (self.bundle / "requirements.lock").write_text("")
        (self.bundle / "manifest.json").write_text("{}")
        with self.assertRaises(ValueError):
            verify(self.bundle, self.lock)

    def test_existing_environment_is_never_overwritten(self):
        target = self.root / "existing"
        target.mkdir()
        (target / "keep.txt").write_text("keep")
        with self.assertRaises(FileExistsError):
            install(self.bundle, target, self.lock)
        self.assertEqual((target / "keep.txt").read_text(), "keep")

    def test_zip_traversal_duplicate_and_symlink_rejected(self):
        for names in (("../escape",), ("C:/escape",), ("dir\\..\\escape",), ("FILE", "file")):
            with zipfile.ZipFile(self.root / "unsafe.zip", "w") as archive:
                for name in names:
                    member = zipfile.ZipInfo("placeholder")
                    member.filename = name  # Preserve malformed raw backslash names on Windows.
                    archive.writestr(member, b"x")
            with zipfile.ZipFile(self.root / "unsafe.zip") as archive, self.assertRaises(ValueError):
                list(safe_members(archive))
        with zipfile.ZipFile(self.root / "unsafe.zip", "w") as archive:
            link = zipfile.ZipInfo("link")
            link.external_attr = 0o120777 << 16
            archive.writestr(link, "../escape")
        with zipfile.ZipFile(self.root / "unsafe.zip") as archive, self.assertRaises(ValueError):
            list(safe_members(archive))

    def test_reviewed_lock_covers_all_pins_and_require_hashes(self):
        manifest = json.loads(LOCK.read_text())
        self.assertEqual(len(manifest["wheels"]), 11)
        self.assertEqual(requirements(manifest).count("--hash=sha256:"), 11)
        root = Path(__file__).resolve().parents[1]
        pinned = {re.sub(r"[-_.]+", "-", line.split("==")[0]).lower(): line.split("==")[1]
                  for line in (root / "requirements-demo.txt").read_text().splitlines() if line and not line.startswith("#")}
        self.assertEqual({w["name"]: w["version"] for w in manifest["wheels"]}, pinned)
        self.assertEqual((root / "requirements-demo.lock").read_text(), requirements(manifest))


if __name__ == "__main__":
    unittest.main()
