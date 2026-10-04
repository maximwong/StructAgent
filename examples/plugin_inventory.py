"""List installed local plugin capabilities without API, calculation or CAD execution."""

import argparse
import json
import sys
from pathlib import Path
from core.plugin_base import PluginContext
from core.plugin_loader import load_plugins


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugins', type=Path, default=root/'plugins')
    args = parser.parse_args()
    catalog = load_plugins(args.plugins, PluginContext(root/'data/projects'))
    sys.stdout.buffer.write((json.dumps(catalog.describe(), ensure_ascii=False, indent=2)+'\n').encode('utf-8'))


if __name__ == '__main__':
    main()
