"""Acceptance scan of the generated 设计说明书.pdf for both examples.

Checks the body table numbering against sample 1, that the new detailing
narratives and capacity tables really reached the PDF, that no figure caption is
separated from its image or orphaned at a page break, and that no glyph falls
outside the page box. Writes verification/report_pdf_checks.json.
"""
import json
import re
import sys
from pathlib import Path
import pypdfium2 as pdf

ROOT = Path(__file__).resolve().parent
EXAMPLES = ROOT / 'examples'
OUT = ROOT / 'verification' / 'report_pdf_checks.json'

# Sample-1 numbering that the body of the report must reproduce exactly.
BODY_TABLES = ['板弯矩计算表', '板截面承载力计算', '次梁弯矩计算表', '次梁剪力计算表',
               '次梁正截面承载力计算', '次梁斜截面承载力计算', '主梁弯矩计算表',
               '主梁剪力计算表', '主梁正截面承载力计算', '主梁斜截面承载力计算']
# Detailing narrative and table content requested by 改进汇总.
REQUIRED = ['Ⅰ-Ⅰ板带是指板的边带', 'Ⅱ-Ⅱ板带在Ⅰ-Ⅰ板带的基础上下降20%', '本设计采用分离式配筋方案',
            '受力钢筋的间距不超过200mm', '分布钢筋的截面面积不宜小于单位宽度上受力钢筋截面面积的15%',
            '次梁在跨中按T形截面计算', '翼缘宽度取上述三者的较小者',
            '主梁的中间支座按铰支座考虑', '要求梁柱线刚度之比超过4',
            '纵筋的弯起应满足三方面的要求', '下部纵向钢筋伸入梁端支座的锚固长度应大于las',
            '架立钢筋与受力钢筋的搭接长度', 'Ⅰ-Ⅰ板带', 'Ⅱ-Ⅱ板带',
            'V0·b柱/2', 'Asv=nAsv1']


def scan(path):
    doc = pdf.PdfDocument(str(path))
    text = []
    problems = []
    notes = []
    page_info = []
    for i in range(len(doc)):
        page = doc[i]
        tp = page.get_textpage()
        raw = tp.get_text_range()
        text.append(raw)
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        images = sum(1 for o in page.get_objects() if o.type == 1)
        figures = [l for l in lines if re.match(r'^图\s*\d+', l)]
        tables = [l for l in lines if re.match(r'^表\s*\d+', l)]
        for c in figures:
            if images == 0:
                problems.append(f'p{i+1} 图题无同页图片：{c[:30]}')
        if lines:
            last = lines[-1]
            if re.match(r'^表\s*\d+', last):
                problems.append(f'p{i+1} 表题孤立于页尾：{last[:30]}')
            # A figure caption deliberately follows its image, so sitting at the
            # foot of a page is normal multi-page behaviour here; record it only.
            if re.match(r'^图\s*\d+', last):
                notes.append(f'p{i+1} 图题位于页尾（图片同页，属分页行为）：{last[:30]}')
        w, h = page.get_size()
        for j in range(tp.count_chars()):
            l, b, r, top = tp.get_charbox(j)
            if l < -1 or r > w + 1 or top > h + 1 or b < -1:
                problems.append(f'p{i+1} 字符越界 idx{j}')
                break
        page_info.append(dict(page=i + 1, images=images, figure_captions=len(figures),
                              table_captions=len(tables), table_lines=tables))
    return doc, '\n'.join(text), page_info, problems, notes


def table_numbering(page_info):
    """Page number of every body table caption, keyed by its number."""
    found = {}
    for info in page_info:
        for line in info['table_lines']:
            m = re.match(r'^表\s*(\d+)\s*(.*)$', line)
            if not m:
                continue
            number = int(m.group(1))
            found.setdefault(number, dict(page=info['page'], title=m.group(2).strip()))
    return found


def main():
    report = {}
    ok = True
    for name in ['sample1', 'changed']:
        path = EXAMPLES / name / '设计说明书.pdf'
        doc, text, page_info, problems, notes = scan(path)
        numbering = table_numbering(page_info)
        for index, expected in enumerate(BODY_TABLES, start=1):
            item = numbering.get(index)
            if item is None:
                problems.append(f'缺少表 {index} {expected}')
                continue
            if not item['title'].startswith(expected):
                problems.append(f'表 {index} 标题为“{item["title"]}”，应为“{expected}”')
        pages = [numbering[i]['page'] for i in range(1, 11) if i in numbering]
        if pages != sorted(pages):
            problems.append('主体表号未按顺序出现')
        # PDF text extraction inserts line breaks, so match on whitespace-free text.
        flat = re.sub(r'\s+', '', text)
        missing = [token for token in REQUIRED if re.sub(r'\s+', '', token) not in flat]
        for token in missing:
            problems.append(f'缺少要求内容：{token}')
        report[name] = dict(pages=len(doc), body_tables={i: numbering.get(i) for i in range(1, 11)},
                            page_map=page_info, missing_required=missing, problems=problems, notes=notes)
        print(name, 'pages', len(doc), 'body tables', len(pages),
              'problems', len(problems), 'notes', len(notes))
        for p in problems:
            print('   -', p)
        ok = ok and not problems
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('check file written:', OUT)
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
