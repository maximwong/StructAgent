import sys
from pathlib import Path
import pypdfium2 as pdf
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent
name = sys.argv[1]
pages = [int(x) for x in sys.argv[2:]]
doc = pdf.PdfDocument(str(ROOT / 'examples' / name / '设计说明书.pdf'))
out = ROOT / '_tmp' / 'pages'
out.mkdir(parents=True, exist_ok=True)
for p in pages:
    img = doc[p - 1].render(scale=1.35).to_pil().convert('RGB')
    path = out / f'{name}_p{p}.png'
    img.save(path)
    print(path, img.size)
