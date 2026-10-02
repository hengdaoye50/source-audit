"""Read DOCX main text, tables, footnotes and endnotes without OCR or guessed pages.

Uses OOXML, includes inserted text and excludes deleted text. Retains revision
warnings: this reading convention is not acceptance of revisions in the file.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
NS = {'w': W[1:-1]}


def paragraph_text(element):
    chunks, references = [], []
    def visit(node):
        if node.tag in (W+'del', W+'moveFrom', W+'txbxContent', W+'drawing', W+'pict'):
            return
        if node.tag == W+'t':
            chunks.append(node.text or '')
        elif node.tag == W+'tab':
            chunks.append('\t')
        elif node.tag in (W+'br', W+'cr'):
            chunks.append('\n')
        elif node.tag in (W+'footnoteReference', W+'endnoteReference'):
            references.append({'kind': 'footnote' if node.tag == W+'footnoteReference' else 'endnote',
                               'id': node.get(W+'id'), 'offset': sum(map(len, chunks))})
        else:
            for child in node:
                visit(child)
    visit(element)
    return ''.join(chunks), references


def citation_candidates(text):
    patterns = [('author_year', r'[（(][^()（）\n]{0,70}?\b(?:19|20)\d{2}[a-z]?[^()（）\n]{0,20}[）)]'),
                ('numbered', r'[\[［]\d+(?:\s*[-–—,，、]\s*\d+)*[\]］]')]
    found = []
    for kind, expression in patterns:
        for match in re.finditer(expression, text):
            found.append({'kind': kind, 'marker': match.group(0), 'start': match.start(),
                          'end': match.end(), 'candidate_only': True})
    return sorted(found, key=lambda item: item['start'])


def bibliography_entry(text):
    """Conservative hint for an untitled bibliography: require a run, not one line."""
    chinese = re.match(r'^[\u3400-\u9fff、，\s]{2,45}[，,]\s*(?:19|20)\d{2}[a-z]?\s*[，,]', text)
    english = re.match(r'^[A-Za-z][A-Za-z .,&\x27’\-]{2,110},\s*(?:19|20)\d{2}[a-z]?\s*,', text)
    return bool((chinese and '《' in text) or english)


def read_docx(path, source_root):
    path, base = Path(path).resolve(), Path(source_root).resolve()
    if not path.is_relative_to(base):
        raise ValueError('Manuscript must stay inside source_root')
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    with ZipFile(path) as archive:
        if sum(info.file_size for info in archive.infolist()) > 100 * 1024 * 1024:
            raise ValueError('Uncompressed DOCX too large for this reader')
        root = ET.fromstring(archive.read('word/document.xml'))
        styles = {}
        if 'word/styles.xml' in archive.namelist():
            for style in ET.fromstring(archive.read('word/styles.xml')).findall('w:style', NS):
                outline = style.find('w:pPr/w:outlineLvl', NS)
                name = style.find('w:name', NS)
                level = int(outline.get(W+'val'))+1 if outline is not None else None
                if level is None and name is not None:
                    match = re.search(r'(?:heading|标题)\s*(\d)', name.get(W+'val', ''), re.I)
                    if match:
                        level = int(match.group(1))
                styles[style.get(W+'styleId')] = level
        blocks, citations, notes = [], [], []
        headings, paragraph_number, table_number, region = {}, 0, 0, 'body'

        def append_paragraph(element, locator, bid, in_main=True):
            nonlocal region
            text, references = paragraph_text(element)
            if not text.strip():
                return
            style = element.find('w:pPr/w:pStyle', NS)
            sid = style.get(W+'val') if style is not None else None
            level = styles.get(sid)
            if in_main and level:
                for key in list(headings):
                    if key >= level:
                        del headings[key]
                headings[level] = text.strip()
            if in_main and re.fullmatch(r'参考文献|References|Bibliography', text.strip(), re.I):
                region = 'bibliography'
            elif in_main and level and region == 'bibliography':
                region = 'body'
            section = ' / '.join(headings[k] for k in sorted(headings)) or '未定位章节'
            block = {'id': bid, 'text': text, 'section': section, 'region': region if in_main else locator['kind'],
                     'location': locator, 'note_references': references, 'review_status': 'unverified'}
            blocks.append(block)
            if block['region'] != 'bibliography':
                for item in citation_candidates(text):
                    citations.append({'block_id': bid, **item})
            for reference in references:
                citations.append({'block_id': bid, 'kind': reference['kind']+'_reference',
                    'marker': reference['id'], 'start': reference['offset'], 'end': reference['offset'],
                    'note_id': reference['id'], 'candidate_only': True})

        def walk_body(container):
            nonlocal paragraph_number, table_number
            for child in container:
                if child.tag == W+'p':
                    paragraph_number += 1
                    append_paragraph(child, {'kind': 'paragraph', 'paragraph_index': paragraph_number},
                                     f'P{paragraph_number:06d}')
                elif child.tag == W+'tbl':
                    table_number += 1
                    ti = table_number
                    for ri, row in enumerate(child.findall('w:tr', NS), 1):
                        for ci, cell in enumerate(row.findall('w:tc', NS), 1):
                            for pi, p in enumerate(cell.findall('w:p', NS), 1):
                                append_paragraph(p, {'kind': 'table_cell', 'table_index': ti,
                                    'row_index': ri, 'cell_index': ci, 'paragraph_index': pi},
                                    f'T{ti}.R{ri}.C{ci}.P{pi}', False)
                elif child.tag not in (W+'del', W+'moveFrom', W+'sectPr'):
                    walk_body(child)
        body = root.find('w:body', NS)
        if body is None:
            raise ValueError('DOCX has no document body')
        walk_body(body)
        # Require at least three adjacent bibliography-like paragraphs.
        plain = [b for b in blocks if b['location']['kind'] == 'paragraph']
        bibliography_start = None
        for i in range(max(0, len(plain)-2)):
            if all(bibliography_entry(b['text']) for b in plain[i:i+3]):
                bibliography_start = plain[i]['id']
                break
        if bibliography_start:
            started = False
            for block in blocks:
                if block['id'] == bibliography_start:
                    started = True
                if started:
                    block['region'] = 'bibliography'
                    block['section'] = '未设标题的参考文献清单（候选）'
            citations = [c for c in citations if next(b for b in blocks if b['id']==c['block_id'])['region'] != 'bibliography']
        anchors = {}
        for block in blocks:
            for reference in block['note_references']:
                anchors.setdefault((reference['kind'], reference['id']), []).append({
                    'block_id': block['id'], 'offset': reference['offset'], 'section': block['section']})
        for kind in ('footnote', 'endnote'):
            member = f'word/{kind}s.xml'
            if member not in archive.namelist():
                continue
            for note in ET.fromstring(archive.read(member)).findall('w:'+kind, NS):
                note_id = note.get(W+'id')
                if note.get(W+'type') in ('separator', 'continuationSeparator') or int(note_id) < 0:
                    continue
                note_blocks = []
                for pi, p in enumerate(note.findall('w:p', NS), 1):
                    bid = f'{kind.upper()}{note_id}.P{pi}'
                    append_paragraph(p, {'kind': kind, 'note_id': note_id, 'paragraph_index': pi}, bid, False)
                    note_blocks.append(bid)
                note_anchors = anchors.get((kind, note_id), [])
                for block in blocks:
                    if block['id'] in note_blocks:
                        block['section'] = note_anchors[0]['section'] if note_anchors else '未关联正文位置'
                notes.append({'kind': kind, 'id': note_id, 'blocks': note_blocks, 'anchors': note_anchors})
        warnings = []
        revisions = sum(1 for node in root.iter() if node.tag in (W+'ins', W+'del', W+'moveFrom', W+'moveTo'))
        if revisions:
            warnings.append('存在修订痕迹：候选文字包含新增、排除删除；未修改或接受原文件修订。')
        nested_tables = len(root.findall('.//w:tc/w:tbl', NS))
        if nested_tables:
            warnings.append('存在嵌套表格，当前版本需人工补读其内容。')
        if any(node.tag in (W+'drawing', W+'pict') for node in root.iter()):
            warnings.append('存在图片或绘图，其中文字未提取；仅在确有核准需要时另行识别。')
        known_notes = {(n['kind'], n['id']) for n in notes}
        for b in blocks:
            for reference in b['note_references']:
                if (reference['kind'], reference['id']) not in known_notes:
                    warnings.append('未读取到关联注释：'+str(reference))
        return {'format_version': '0.2', 'manuscript': {'format': 'docx', 'sha256': digest,
                'locator': path.relative_to(base).as_posix(), 'title': path.stem},
                'blocks': blocks, 'citation_candidates': citations, 'notes': notes,
                'diagnostics': {'ocr_used': False, 'page_numbers_inferred': False,
                    'revision_elements': revisions, 'warnings': warnings,
                    'locator_note': '段落序号包含空段落；表格列号是XML单元格位置，合并单元格不推测视觉列号；注释编号为OOXML ID。'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.input.suffix.lower() != '.docx':
        parser.error('This reader accepts .docx; legacy .doc must be converted first')
    result = read_docx(args.input, args.source_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'blocks': len(result['blocks']), 'citation_candidates': len(result['citation_candidates']),
                      'notes': len(result['notes']), **result['diagnostics']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
