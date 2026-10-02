"""Inventory, archive or restore local terminal workflow artifacts; never calls API/CAD."""

import argparse
import json
from pathlib import Path

from core.artifact_archive import ArtifactArchive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path(__file__).resolve().parents[1] / "data/projects")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--archive", metavar="RUN_ID")
    action.add_argument("--restore", metavar="RUN_ID")
    parser.add_argument("--compact", action="store_true", help="Only with --archive: remove verified archived source artifacts.")
    args = parser.parse_args()
    if args.compact and not args.archive:
        parser.error("--compact requires --archive")
    archive = ArtifactArchive(args.output_root)
    result = archive.archive(args.archive, compact=args.compact) if args.archive else archive.restore(args.restore) if args.restore else archive.inventory()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
