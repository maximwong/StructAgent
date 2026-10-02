"""Build and install a hash-verified Windows x64 Demo environment without a package index."""

import argparse
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LOCK = Path(__file__).with_name("offline-lock.json")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_members(archive):
    seen = set()
    for item in archive.infolist():
        path = PurePosixPath(item.filename)
        if (not item.filename or "\\" in item.filename or ":" in item.filename
                or path.is_absolute() or any(p in ("", ".", "..") for p in item.filename.rstrip("/").split("/"))
                or (item.external_attr >> 16) & 0o170000 == 0o120000
                or item.filename.casefold() in seen):
            raise ValueError("Unsafe or duplicate archive member.")
        seen.add(item.filename.casefold())
        yield item


def build(runtime_source, wheelhouse, bundle):
    runtime_source, wheelhouse, bundle = map(lambda p: Path(p).resolve(), (runtime_source, wheelhouse, bundle))
    if bundle.is_relative_to(runtime_source) or bundle.is_relative_to(wheelhouse):
        raise ValueError("Bundle destination must be outside its sources.")
    if bundle.exists():
        raise FileExistsError("Bundle destination must be new.")
    version = (ROOT / ".python-version").read_text().strip()
    check = subprocess.run([str(runtime_source / "python.exe"), "-I", "-c",
        "import platform,struct;print(platform.python_version()+'|'+str(struct.calcsize('P')*8))"],
        capture_output=True, check=True, text=True)
    if check.stdout.strip() != version + "|64" or platform.system() != "Windows":
        raise ValueError("Expected the pinned Windows x64 runtime.")
    pinned = {}
    for line in (ROOT / "requirements-demo.txt").read_text().splitlines():
        if line and not line.startswith("#"):
            name, package_version = line.split("==")
            pinned[re.sub(r"[-_.]+", "-", name).lower()] = package_version
    wheels = []
    for path in sorted(wheelhouse.glob("*.whl")):
        with zipfile.ZipFile(path) as archive:
            metadata_files = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
            if len(metadata_files) != 1:
                raise ValueError("Ambiguous wheel metadata.")
            metadata = BytesParser().parsebytes(archive.read(metadata_files[0]))
        name = re.sub(r"[-_.]+", "-", metadata["Name"]).lower()
        if name not in pinned or pinned.pop(name) != metadata["Version"]:
            raise ValueError("Wheel does not match the complete dependency pins.")
        wheels.append({"file": path.name, "name": name, "version": metadata["Version"], "sha256": digest(path)})
    if pinned:
        raise ValueError("Missing pinned wheels.")
    bundle.mkdir(parents=True)
    (bundle / "wheels").mkdir()
    for wheel in wheels:
        shutil.copyfile(wheelhouse / wheel["file"], bundle / "wheels" / wheel["file"])
    runtime = bundle / "runtime.zip"
    allowed = {"DLLs", "include", "Lib", "libs", "tcl", "LICENSE.txt", "python.exe", "python3.dll",
               "python312.dll", "pythonw.exe", "vcruntime140.dll", "vcruntime140_1.dll"}
    with zipfile.ZipFile(runtime, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(runtime_source.rglob("*")):
            relative = path.relative_to(runtime_source)
            if (relative.parts[0] not in allowed or "site-packages" in relative.parts
                    or "__pycache__" in relative.parts or path.suffix in (".pyc", ".pyo") or not path.is_file()):
                continue
            if path.is_symlink() or path.is_junction():
                raise ValueError("Runtime links are not supported.")
            info = zipfile.ZipInfo(relative.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    manifest = {"format": 1, "platform": "win_amd64", "python": version,
                "runtime": {"file": "runtime.zip", "sha256": digest(runtime)}, "wheels": wheels}
    if LOCK.exists() and manifest != json.loads(LOCK.read_text(encoding="utf-8")):
        raise ValueError("Bundle differs from the repository's reviewed artifact lock.")
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (bundle / "requirements.lock").write_text(requirements(manifest), encoding="utf-8")
    return manifest


def requirements(manifest):
    return "".join(f'{w["name"]}=={w["version"]} --hash=sha256:{w["sha256"]}\n' for w in manifest["wheels"])


def verify(bundle, lock=LOCK):
    bundle = Path(bundle).resolve()
    manifest = json.loads(Path(lock).read_text(encoding="utf-8"))
    if manifest != json.loads((bundle / "manifest.json").read_text(encoding="utf-8")):
        raise ValueError("Bundle manifest differs from the trusted repository lock.")
    for item in [manifest["runtime"], *manifest["wheels"]]:
        if Path(item["file"]).name != item["file"] or ":" in item["file"] or "\\" in item["file"]:
            raise ValueError("Invalid artifact filename.")
        path = bundle / ("wheels" if item in manifest["wheels"] else "") / item["file"]
        if path.is_symlink() or digest(path) != item["sha256"]:
            raise ValueError("Offline artifact hash mismatch.")
    if (bundle / "requirements.lock").read_text(encoding="utf-8") != requirements(manifest):
        raise ValueError("Offline requirements differ from the artifact lock.")
    with zipfile.ZipFile(bundle / manifest["runtime"]["file"]) as archive:
        list(safe_members(archive))
    return manifest


def install(bundle, destination, lock=LOCK):
    bundle, destination = Path(bundle).resolve(), Path(destination).resolve()
    if destination.exists():
        raise FileExistsError("Install destination must be new; existing environments are never overwritten.")
    manifest = verify(bundle, lock)
    if platform.system() != "Windows" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise ValueError("This bundle supports Windows x64 only.")
    runtime = destination / "runtime"
    runtime.mkdir(parents=True)
    with zipfile.ZipFile(bundle / manifest["runtime"]["file"]) as archive:
        archive.extractall(runtime, members=list(safe_members(archive)))
    runtime_python = runtime / "python.exe"
    subprocess.run([str(runtime_python), "-I", "-m", "venv", str(destination / "venv")], check=True, timeout=120)
    python = destination / "venv/Scripts/python.exe"
    subprocess.run([str(python), "-I", "-m", "pip", "--isolated", "--disable-pip-version-check", "install",
        "--no-index", "--only-binary=:all:", "--find-links", str(bundle / "wheels"), "--require-hashes",
        "-r", str(bundle / "requirements.lock")], check=True, timeout=180)
    subprocess.run([str(python), "-I", "-m", "pip", "--isolated", "check"], check=True, timeout=30)
    return python


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build")
    builder.add_argument("--runtime-source", type=Path, required=True)
    builder.add_argument("--wheelhouse", type=Path, required=True)
    builder.add_argument("--bundle", type=Path, required=True)
    installer = commands.add_parser("install")
    installer.add_argument("--bundle", type=Path, required=True)
    installer.add_argument("--destination", type=Path, required=True)
    checker = commands.add_parser("verify")
    checker.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        build(args.runtime_source, args.wheelhouse, args.bundle)
    elif args.command == "install":
        print(install(args.bundle, args.destination))
    else:
        verify(args.bundle)
        print("Offline bundle hashes verified.")


if __name__ == "__main__":
    main()
