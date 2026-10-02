"""Read PDF text locally, cache by file digest, and optionally OCR weak pages.

Extracted regions and headings are candidates, never automatically reviewed.
Requires pdfplumber; Windows OCR additionally requires pypdfium2 and zh-Hans OCR.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

READER_VERSION = '0.2.5'
HEAD = re.compile(r'^(?:[一二三四五六七八九十]+[、．.]|[（(][一二三四五六七八九十]+[）)]|\d+(?:\.\d+)*[.、\s]|(?:Introduction|Conclusion|Discussion|Results|Methods)\b)', re.I)


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def text_quality(text, minimum=40):
    clean = re.sub(r'\s+', '', text)
    if len(clean) < minimum:
        return False, 'too_little_text'
    if '\ufffd' in clean or '(cid:' in clean or re.search(r'/C\d+', clean):
        return False, 'replacement_or_cid_characters'
    if '\x00' in clean:
        return False, 'null_characters'
    if len(re.findall(r'([A-Za-z])\1{3,}', clean)) >= 3:
        return False, 'duplicated_glyph_runs'
    if sum(c.isalnum() for c in clean) / len(clean) < 0.45:
        return False, 'low_readable_character_ratio'
    return True, 'text_layer_candidate'


def extract_layout(page):
    """Find a persistent central gutter; preserve full-width opening material."""
    chars = [c for c in page.chars if c.get('text', '').strip()]
    if not chars:
        return '', {'layout': 'no_text', 'gutter': None}
    gutter = None
    # A wide table may occupy the upper half of an otherwise two-column page.
    for lower, upper in ((.65, .95), (.35, .90)):
        sample = [c for c in chars if page.height * lower < c['top'] < page.height * upper]
        if len(sample) <= 150:
            continue
        scores = [(x, sum(c['x0'] < x < c['x1'] for c in sample))
                  for x in range(int(page.width * .45), int(page.width * .56))]
        low = min(v for _, v in scores)
        runs = []
        for x, value in scores:
            if value <= low + 1:
                if runs and x == runs[-1][-1] + 1:
                    runs[-1].append(x)
                else:
                    runs.append([x])
        best = max(runs, key=len)
        mid = (best[0] + best[-1]) / 2
        left = sum(c['x1'] <= mid for c in sample)
        right = sum(c['x0'] >= mid for c in sample)
        if len(best) >= 5 and low <= 2 and min(left, right) >= len(sample) * .20:
            gutter = mid
            break
    if gutter is None:
        return page.extract_text(x_tolerance=2, y_tolerance=3) or '', {'layout': 'single_or_uncertain', 'gutter': None}

    rows = {}
    for c in chars:
        key = round(c['top'] / 3) * 3
        rows.setdefault(key, []).append(c)
    paired = [y for y, row in rows.items()
              if any(c['x1'] < gutter - 2 for c in row)
              and any(c['x0'] > gutter + 2 for c in row)
              and not any(c['x0'] < gutter < c['x1'] for c in row)]
    if len(paired) < 5:
        return page.extract_text(x_tolerance=2, y_tolerance=3) or '', {'layout': 'single_or_uncertain', 'gutter': None}
    top = max(page.bbox[1], min(paired) - 2)
    bottom = min(page.bbox[3], max(paired) + 16)
    x0, y0, x1, y1 = page.bbox
    boxes = []
    if top > y0:
        boxes.append((x0, y0, x1, top))
    boxes += [(x0, top, gutter, bottom), (gutter, top, x1, bottom)]
    if bottom < y1:
        boxes.append((x0, bottom, x1, y1))
    chunks = [page.crop(box).extract_text(x_tolerance=2, y_tolerance=3) or '' for box in boxes]
    return '\n'.join(chunks), {'layout': 'two_column_candidate', 'gutter': round(gutter, 2)}


def page_flow(page):
    """Preserve ancillary text separately, with unverified layout heuristics.

    Header/footer and small bottom notes must not interrupt main-text continuation.
    Nothing is discarded; diagnostics retain ancillary text for page review.
    """
    chars = [c for c in page.chars if c.get('text', '').strip()]
    if not chars:
        return page, None, ''
    sizes = Counter(round(c.get('size', 0), 1) for c in chars
                    if page.height * .08 < c['top'] < page.height * .90)
    typical = sizes.most_common(1)[0][0] if sizes else 0
    rows = {}
    for c in chars:
        rows.setdefault(round(c['top'] / 3) * 3, []).append(c)
    removed, print_page = set(), None
    note_rows = {y for y, row in rows.items()
                 if y > page.height * .72 and typical
                 and max(c.get('size', 0) for c in row) <= typical * .88
                 and len(''.join(c['text'] for c in row).strip()) > 12}
    for y, row in rows.items():
        line = ''.join(c['text'] for c in sorted(row, key=lambda c: c['x0'])).strip()
        numeric = re.fullmatch(r'[·.\-—\s]*(\d{1,4})[·.\-—\s]*', line)
        if y > page.height * .88 and numeric:
            print_page = numeric.group(1)
            removed.update(id(c) for c in row)
        elif y < page.height * .08:
            removed.update(id(c) for c in row)
        elif y in note_rows or (len(line) <= 12 and any(abs(y - ny) <= 4 for ny in note_rows)):
            removed.update(id(c) for c in row)
    if not removed:
        return page, print_page, ''
    main = page.filter(lambda obj: obj.get('object_type') != 'char' or id(obj) not in removed)
    notes = page.filter(lambda obj: obj.get('object_type') == 'char' and id(obj) in removed)
    return main, print_page, notes.extract_text(x_tolerance=2, y_tolerance=3) or ''


def classify_line(line, state):
    compact = re.sub(r'\s+', '', line)
    if re.match(r'^(?:【|\[)?(?:摘要|内容提要|Abstract)(?:】|\])?(?:[:：\s]|(?=[\u3400-\u9fff])|$)', line, re.I):
        return 'abstract', '摘要'
    if re.match(r'^(参考文献|References|Bibliography)[:：\s]?$', compact, re.I):
        return 'bibliography', '参考文献'
    if HEAD.match(line) and len(compact) < 85:
        return 'body', line
    if re.match(r'^(?:【|\[)?(?:关键词|关键字|Keywords)(?:】|\])?[:：\s]?', line, re.I):
        return 'other', '关键词'
    region, section = state
    if region == 'other' and section == '关键词':
        return 'unknown', '未定位章节'
    return state


def segment_text(text, pdf_page, state=('unknown', '未定位章节'), extraction='text_layer'):
    segments, buffered = [], []
    current = state
    def flush():
        if buffered:
            segments.append({'id': f'p{pdf_page}.s{len(segments)+1}', 'region': current[0],
                'section': current[1], 'text': '\n'.join(buffered),
                'extraction': extraction, 'review_status': 'unverified'})
            buffered.clear()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        new = classify_line(line, current)
        if new != current:
            flush()
            current = new
        buffered.append(line)
    flush()
    return segments, current


def windows_ocr(pdf_path, page_index, language='zh-Hans-CN'):
    if os.name != 'nt':
        raise RuntimeError('Windows OCR is unavailable on this platform')
    import pypdfium2 as pdfium
    helper = Path(__file__).with_name('windows_ocr.ps1')
    shell = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    with tempfile.TemporaryDirectory(prefix='source-audit-ocr-') as folder:
        image_path, output = Path(folder) / 'page.png', Path(folder) / 'ocr.json'
        doc = pdfium.PdfDocument(str(pdf_path))
        page = doc[page_index]
        bitmap = None
        try:
            scale = min(2.6, 2600 / max(page.get_size()))
            bitmap = page.render(scale=scale)
            bitmap.to_pil().save(image_path)
        finally:
            if bitmap is not None:
                bitmap.close()
            page.close()
            doc.close()
        cp = subprocess.run([str(shell), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(helper),
                             '-ImageFile', str(image_path), '-OutputJson', str(output), '-LanguageTag', language],
                            capture_output=True, timeout=60)
        if cp.returncode or not output.is_file():
            detail = cp.stderr.decode('utf-8', errors='replace')[-1000:]
            raise RuntimeError('Windows OCR failed: ' + detail)
        return json.loads(output.read_text(encoding='utf-8-sig'))


def read_pdf(path, source_root, cache_dir, ocr='none', page_numbers=None, ocr_language='zh-Hans-CN'):
    import pdfplumber
    path, base = Path(path).resolve(), Path(source_root).resolve()
    if not path.is_relative_to(base):
        raise ValueError('Source must stay inside source_root')
    sha = digest_file(path)
    key = hashlib.sha256(json.dumps([READER_VERSION, sha, ocr, page_numbers, ocr_language], sort_keys=True).encode()).hexdigest()
    cache = Path(cache_dir) / (key + '.json')
    relative = path.relative_to(base).as_posix()
    source_id = 'S-' + hashlib.sha256(relative.encode('utf-8')).hexdigest()[:16]
    if cache.is_file():
        try:
            saved = json.loads(cache.read_text(encoding='utf-8'))
            if saved['source']['sha256'] == sha and saved['diagnostics']['reader_version'] == READER_VERSION:
                # Relocation must not preserve somebody else's original path or title.
                saved['source']['origin']['locator'] = relative
                saved['source']['id'] = source_id
                saved['source']['title'] = path.stem
                saved['diagnostics']['cache_hit'] = True
                return saved
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            pass  # A broken cache is recoverable from the original source.

    pages, diagnostics, state = [], [], ('unknown', '未定位章节')
    with pdfplumber.open(path) as document:
        total = len(document.pages)
        selected = set(page_numbers or range(1, total + 1))
        if any(p < 1 or p > total for p in selected):
            raise ValueError('Requested page outside PDF')
        for number, page in enumerate(document.pages, 1):
            if number not in selected:
                continue
            try:
                flow_page, printed, ancillary = page_flow(page)
                text, layout = extract_layout(flow_page)
                good, reason = text_quality(text)
                method, issue, ocr_info = 'text_layer', None, None
                fallback_used = False
                if not good and reason in ('replacement_or_cid_characters', 'null_characters', 'duplicated_glyph_runs'):
                    from pypdf import PdfReader
                    alternate = PdfReader(path).pages[number-1].extract_text() or ''
                    alternate_good, _ = text_quality(alternate)
                    if alternate_good:
                        text, good, reason = alternate, True, 'alternate_text_layer_candidate'
                        layout = {'layout': 'alternate_text_reading_order_unverified', 'gutter': None}
                        fallback_used = True
                if not good and ocr == 'windows':
                    try:
                        ocr_info = windows_ocr(path, number - 1, ocr_language)
                        text = ocr_info['text'] if isinstance(ocr_info, dict) else ocr_info
                        method = 'ocr'
                        good, reason = text_quality(text)
                        layout = {'layout': 'ocr_reading_order_unverified', 'gutter': None}
                    except (OSError, RuntimeError, subprocess.TimeoutExpired, ImportError) as error:
                        issue = str(error)
                # Keep even weak text as unverified candidates; never mark success.
                segments, state = segment_text(text, number, state, method)
                pages.append({'pdf_page': number, 'print_page': printed, 'segments': segments})
                diagnostics.append({'pdf_page': number, 'quality_ok': good, 'quality_reason': reason,
                    'extraction': method, 'characters': len(text), **layout, 'issue': issue,
                    'ancillary_text': ancillary, 'layout_review_status': 'unverified',
                    'alternate_text_layer_used': fallback_used,
                    'ocr_language_actual': ocr_info.get('actual_language') if isinstance(ocr_info, dict) else None})
            except Exception as error:
                pages.append({'pdf_page': number, 'print_page': None, 'segments': []})
                diagnostics.append({'pdf_page': number, 'quality_ok': False,
                    'quality_reason': 'extraction_failed', 'extraction': 'text_layer',
                    'characters': 0, 'layout': 'unknown', 'gutter': None, 'issue': str(error)})
    read_count = sum(p['quality_ok'] for p in diagnostics)
    coverage = 'full' if len(selected) == total and read_count == total else ('partial' if read_count else 'unreadable')
    source = {'id': source_id, 'title': path.stem, 'kind': 'academic_article', 'sha256': sha,
        'coverage': coverage, 'origin': {'kind': 'local', 'locator': relative, 'snapshot_path': None},
        'dates': {k: None for k in ('issued', 'published', 'effective', 'accessed')}, 'pages': pages}
    saved = {'source': source, 'diagnostics': {'reader_version': READER_VERSION,
        'total_pages': total, 'selected_pages': sorted(selected), 'cache_hit': False, 'pages': diagnostics}}
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_suffix('.tmp')
    temporary.write_text(json.dumps(saved, ensure_ascii=False), encoding='utf-8')
    temporary.replace(cache)
    return saved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache-dir', type=Path, required=True)
    parser.add_argument('--ocr', choices=['none', 'windows'], default='none')
    parser.add_argument('--ocr-language', default='zh-Hans-CN')
    parser.add_argument('--pages', help='Comma-separated one-based pages; single PDF only')
    args = parser.parse_args()
    if args.pages and args.input.is_dir():
        parser.error('--pages requires a single PDF')
    files = sorted(args.input.glob('*.pdf')) if args.input.is_dir() else [args.input]
    if not files:
        parser.error('No PDFs found')
    sources, details, failures = [], [], []
    selection = [int(x) for x in args.pages.split(',')] if args.pages else None
    for file in files:
        try:
            result = read_pdf(file, args.source_root, args.cache_dir, args.ocr, selection, args.ocr_language)
            sources.append(result['source'])
            details.append({'source_id': result['source']['id'], **result['diagnostics']})
            print(json.dumps({'file': file.name, 'coverage': result['source']['coverage'],
                  'pages': len(result['source']['pages']), 'cache_hit': result['diagnostics']['cache_hit']}, ensure_ascii=False), flush=True)
        except Exception as error:
            failures.append({'file': file.name, 'error': str(error)})
            print(json.dumps(failures[-1], ensure_ascii=False), flush=True)
    output = {'format_version': '0.2', 'sources': sources, 'ingestion': details, 'failures': failures}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    weak_pages = sum(not page['quality_ok'] for detail in details for page in detail['pages'])
    return 2 if failures or weak_pages else 0


if __name__ == '__main__':
    raise SystemExit(main())
