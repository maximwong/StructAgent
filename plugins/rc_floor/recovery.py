"""Preserve the existing bounded recovery command behind the floor plugin."""

import json
from pathlib import Path
import subprocess
import sys

from tools.floor import cad_adapter


def recover(root):
    repository = Path(cad_adapter.__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, '-m', 'examples.cad_recovery', '--output-root', str(root)],
        cwd=repository, capture_output=True, timeout=40,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode != 0 or json.loads(result.stdout).get('success') is not True:
        raise ValueError('Recovery was not confirmed.')
