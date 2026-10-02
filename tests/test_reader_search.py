import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/source-audit/scripts'

def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

reader = load('read_sources')
retrieval = load('search_sources')
validator = load('validate_ledger')

class FakePage:
    width, height, bbox = 600, 800, (0, 0, 600, 800)
    chars = [{'text': '甲', 'top': 120, 'x0': 10, 'x1': 20, 'size': 11, 'object_type': 'char'}]
    def extract_text(self, **kwargs):
        return '一、研究结果\n' + '本样本中数字服务改善办事效率，但未发现显著增加就业。' * 4

class FakePdf:
    pages = [FakePage()]
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass

class GeometryPage:
    width, height, bbox = 600, 800, (0, 0, 600, 800)
    def __init__(self, chars):
        self.chars = chars
    def filter(self, predicate):
        return GeometryPage([c for c in self.chars if predicate(c)])
    def crop(self, box):
        return self.filter(lambda c: box[0] <= c['x0'] < box[2] and box[1] <= c['top'] < box[3])
    def extract_text(self, **kwargs):
        rows = {}
        for c in self.chars:
            rows.setdefault(c['top'], []).append(c)
        return '\n'.join(''.join(c['text'] for c in sorted(row, key=lambda c: c['x0']))
                         for _, row in sorted(rows.items()))

def geometry_line(text, x, y, size=12, step=9):
    return [{'text': c, 'top': y, 'x0': x+i*step, 'x1': x+i*step+step-1,
             'size': size, 'object_type': 'char'} for i, c in enumerate(text)]

class ReaderSearchTests(unittest.TestCase):
    def setUp(self):
        self.ledger = json.loads((ROOT / 'tests/fixtures/cross-page-ledger.json').read_text(encoding='utf-8'))
        self.source = self.ledger['sources'][0]

    def test_text_quality_empty(self):
        self.assertFalse(reader.text_quality('')[0])

    def test_text_quality_cid(self):
        self.assertFalse(reader.text_quality('甲' * 60 + '(cid:99)')[0])

    def test_text_quality_readable(self):
        self.assertTrue(reader.text_quality('本样本研究数字服务。' * 8)[0])

    def test_segmentation_does_not_verify(self):
        text = '摘要：效率提高。\n关键词：数字\n一、研究结果\n未发现就业增加。\n参考文献\n作者某某。'
        segments, state = reader.segment_text(text, 1)
        self.assertEqual([x['region'] for x in segments], ['abstract', 'other', 'body', 'bibliography'])
        self.assertTrue(all(x['review_status'] == 'unverified' for x in segments))

    def test_unknown_stays_unknown(self):
        segments, _ = reader.segment_text('没有章节标题的任意文字。', 1)
        self.assertEqual(segments[0]['region'], 'unknown')

    def test_bracketed_abstract_and_keywords(self):
        segments, _ = reader.segment_text('【摘要】正文效率改善。\n【关键词】数字服务\n一、研究结果\n结果仍有限。', 1)
        self.assertEqual([s['region'] for s in segments], ['abstract', 'other', 'body'])

    def test_ancillary_preserved_separately(self):
        chars = geometry_line('期刊页眉', 40, 30)
        chars += geometry_line('正文研究结果与样本限定' * 3, 40, 200)
        chars += geometry_line('基金及作者注释需要在辅助文字中保留', 40, 640, size=9)
        chars += geometry_line('·123·', 270, 760, size=10)
        main, printed, notes = reader.page_flow(GeometryPage(chars))
        self.assertEqual(printed, '123')
        self.assertNotIn('基金', main.extract_text())
        self.assertIn('基金及作者注释', notes)
        self.assertIn('期刊页眉', notes)

    def test_inline_small_reference_not_removed(self):
        chars = geometry_line('正文研究结果与样本限定' * 3, 40, 600)
        chars += geometry_line('[6]', 280, 597, size=8)
        main, _, notes = reader.page_flow(GeometryPage(chars))
        self.assertIn('[6]', main.extract_text())
        self.assertNotIn('[6]', notes)

    def test_table_above_two_columns(self):
        chars = geometry_line('表格数据' * 15, 20, 350)
        for i in range(8):
            chars += geometry_line('左栏' + str(i) + '甲' * 17, 40, 600+i*18)
            chars += geometry_line('右栏' + str(i) + '乙' * 17, 340, 600+i*18)
        text, diagnostics = reader.extract_layout(GeometryPage(chars))
        self.assertEqual(diagnostics['layout'], 'two_column_candidate')
        self.assertLess(text.index('左栏7'), text.index('右栏0'))
        self.assertIn('表格数据', text)

    def test_cached_source_not_reparsed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.pdf'
            path.write_bytes(b'first-source')
            with patch('pdfplumber.open', return_value=FakePdf()) as opening:
                first = reader.read_pdf(path, folder, Path(folder) / 'cache')
                second = reader.read_pdf(path, folder, Path(folder) / 'cache')
                self.assertEqual(opening.call_count, 1)
            self.assertFalse(first['diagnostics']['cache_hit'])
            self.assertTrue(second['diagnostics']['cache_hit'])
            self.assertEqual(first['source']['coverage'], 'full')
            self.assertEqual(validator.schema_errors(first['source'],
                {'$ref': '#/$defs/source'}, json.loads(validator.SCHEMA_PATH.read_text(encoding='utf-8'))), [])

    def test_changed_file_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.pdf'
            path.write_bytes(b'first-source')
            with patch('pdfplumber.open', return_value=FakePdf()) as opening:
                one = reader.read_pdf(path, folder, Path(folder) / 'cache')
                path.write_bytes(b'second-source')
                two = reader.read_pdf(path, folder, Path(folder) / 'cache')
                self.assertEqual(opening.call_count, 2)
            self.assertNotEqual(one['source']['sha256'], two['source']['sha256'])

    def test_corrupt_cache_is_rebuilt(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.pdf'
            path.write_bytes(b'first-source')
            cache = Path(folder) / 'cache'
            with patch('pdfplumber.open', return_value=FakePdf()) as opening:
                reader.read_pdf(path, folder, cache)
                next(cache.glob('*.json')).write_text('broken-json', encoding='utf-8')
                recovered = reader.read_pdf(path, folder, cache)
            self.assertEqual(opening.call_count, 2)
            self.assertFalse(recovered['diagnostics']['cache_hit'])

    def test_reader_rejects_outside_root(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                reader.read_pdf(Path(folder).parent / 'outside.pdf', folder, Path(folder) / 'cache')

    def test_invalid_selected_page(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.pdf'
            path.write_bytes(b'test')
            with patch('pdfplumber.open', return_value=FakePdf()):
                with self.assertRaises(ValueError):
                    reader.read_pdf(path, folder, Path(folder) / 'cache', page_numbers=[9])

    def test_good_text_layer_does_not_use_ocr(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.pdf'
            path.write_bytes(b'test')
            with patch('pdfplumber.open', return_value=FakePdf()), patch.object(reader, 'windows_ocr') as ocr:
                result = reader.read_pdf(path, folder, Path(folder) / 'cache', ocr='windows')
            self.assertEqual(ocr.call_count, 0)
            self.assertEqual(result['source']['coverage'], 'full')

    def test_empty_page_is_unreadable_not_success(self):
        document = FakePdf()
        document.pages = [FakePage()]
        document.pages[0].chars = []
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.pdf'
            path.write_bytes(b'test')
            with patch('pdfplumber.open', return_value=document):
                result = reader.read_pdf(path, folder, Path(folder) / 'cache')
            self.assertEqual(result['source']['coverage'], 'unreadable')
            schema = json.loads(validator.SCHEMA_PATH.read_text(encoding='utf-8'))
            self.assertEqual(validator.schema_errors(result['source'], {'$ref':'#/$defs/source'}, schema), [])

    def test_retrieval_excludes_abstract(self):
        self.source['pages'][0]['segments'][0]['text'] = '独特测试词量子芯片。'
        self.assertEqual(retrieval.search({'sources': [self.source]}, ['量子芯片']), [])

    def test_retrieval_returns_candidates(self):
        rows = retrieval.search({'sources': [self.source]}, ['就业', '数字服务'])
        self.assertTrue(rows)
        self.assertTrue(all(x['candidate_only'] for x in rows))

    def test_cross_page_location_validates(self):
        original = self.ledger['claims'][0]['evidence'][0]
        matches = retrieval.locate_quote(self.source, original['quote'])
        self.assertEqual(len(matches), 1)
        match = matches[0]
        match.pop('segments_reviewed')
        match.update(id='E1', completeness_review='verified', context_review='verified')
        self.ledger['claims'][0]['evidence'] = [match]
        self.assertTrue(validator.validate(self.ledger)['ready_for_report'])

    def test_negation_change_not_located(self):
        quote = self.ledger['claims'][0]['evidence'][0]['quote'].replace('未发现', '发现')
        self.assertEqual(retrieval.locate_quote(self.source, quote), [])

    def test_unknown_not_exact_body_evidence(self):
        self.source['pages'][0]['segments'][1]['region'] = 'unknown'
        self.assertEqual(retrieval.locate_quote(self.source,
            self.source['pages'][0]['segments'][1]['text']), [])

    def test_pending_review_propagates(self):
        self.source['pages'][0]['segments'][1]['review_status'] = 'unverified'
        match = retrieval.locate_quote(self.source, self.source['pages'][0]['segments'][1]['text'])[0]
        self.assertFalse(match['segments_reviewed'])
        self.assertEqual(match['context_review'], 'pending')

    def test_missing_middle_not_joined(self):
        first = self.source['pages'][0]['segments'][1]['text']
        second = self.source['pages'][1]['segments'][0]['text']
        self.source['pages'][0]['segments'].append({'id': 'gap', 'region': 'other', 'section': '注释',
            'text': '不能省略的中间文字。', 'extraction': 'text_layer', 'review_status': 'verified'})
        self.assertEqual(retrieval.locate_quote(self.source, first+second), [])

if __name__ == '__main__':
    unittest.main()
