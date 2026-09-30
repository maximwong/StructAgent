"""Regenerate DELIVERY_MANIFEST.json with sha256 of every package file."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
files={}
for p in sorted(ROOT.rglob('*')):
    if not p.is_file():continue
    rel=p.relative_to(ROOT).as_posix()
    if rel=='DELIVERY_MANIFEST.json' or rel.startswith('generated/') or '__pycache__' in rel:continue
    data=p.read_bytes()
    files[rel]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
out={'version':json.loads((ROOT/'VERSION.json').read_text(encoding='utf-8'))['version'],'files':files}
(ROOT/'DELIVERY_MANIFEST.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print('manifest files:',len(files))
