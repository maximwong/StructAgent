"""Side-by-side before/after comparison images for the detailing improvements.

OLD is the preserved previous package (2026-09-23_SlabMomentDiagram), NEW is the
current examples directory. Each image pairs the pages around the same section
heading in both versions, so the added narratives and capacity tables can be
reviewed without opening both documents.
"""
import pypdfium2 as pdf
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OLD = ROOT / 'examples_旧版_SlabMomentDiagram'
NEW = ROOT / 'examples'
OUT = ROOT / '对比图'
OUT.mkdir(exist_ok=True)
FONT = ImageFont.truetype(str(Path('C:/Windows/Fonts/simhei.ttf')), 28)

SECTIONS = [
    ('板正截面承载力计算', '4 板正截面承载力计算'),
    ('次梁内力计算', '3 次梁的内力计算'),
    ('次梁配筋计算', '4 次梁的配筋计算'),
    ('主梁计算简图', '2 主梁的计算简图'),
    ('主梁截面强度计算', '4 截面强度计算'),
    ('主梁钢筋构造要求', '8 钢筋的构造要求'),
]


def find_page(doc, anchor):
    # exact heading line match, so TOC entries (with dot leaders/page numbers)
    # never shadow the real section page
    for i in range(len(doc)):
        if any(ln.strip() == anchor
               for ln in doc[i].get_textpage().get_text_range().splitlines()):
            return i + 1
    raise ValueError('未找到小节：' + anchor)


def pages(path, start, count=2, scale=1.3):
    doc = pdf.PdfDocument(str(path))
    return [doc[min(i, len(doc) - 1)].render(scale=scale).to_pil().convert('RGB')
            for i in range(start - 1, start - 1 + count)]


def compose(case, label, old_start, new_start):
    olds = pages(OLD / case / '设计说明书.pdf', old_start)
    news = pages(NEW / case / '设计说明书.pdf', new_start)
    imgs = [(f'修改前 p{old_start}', *olds), (f'修改后 p{new_start}', *news)]
    W = sum(sum(im.width for im in ims) for _, *ims in imgs)
    H = 46 + max(max(im.height for im in ims) for _, *ims in imgs)
    canvas = Image.new('RGB', (W, H), 'white')
    d = ImageDraw.Draw(canvas)
    x = 0
    for heading, *ims in imgs:
        w = sum(im.width for im in ims)
        d.rectangle((x, 0, x + w, 40), fill=(230, 230, 230))
        d.text((x + 20, 8), heading, font=FONT, fill='black')
        for im in ims:
            canvas.paste(im, (x, 46))
            x += im.width
        x += 8
        d.line([(x - 4, 0), (x - 4, H)], fill=(120, 120, 120), width=3)
    out = OUT / f'{case}_{label}_前后对比.png'
    canvas.save(out)
    print(out.name, canvas.size)


for case in ['sample1', 'changed']:
    for label, anchor in SECTIONS:
        old_doc = pdf.PdfDocument(str(OLD / case / '设计说明书.pdf'))
        new_doc = pdf.PdfDocument(str(NEW / case / '设计说明书.pdf'))
        compose(case, label, find_page(old_doc, anchor), find_page(new_doc, anchor))
        old_doc.close()
        new_doc.close()
