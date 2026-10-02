import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/source-audit/scripts/read_manuscript.py'
spec = importlib.util.spec_from_file_location('read_manuscript', SCRIPT)
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
v_spec = importlib.util.spec_from_file_location('manuscript_validator', SCRIPT.with_name('validate_ledger.py'))
validator = importlib.util.module_from_spec(v_spec)
v_spec.loader.exec_module(validator)

def make_package(path):
    ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    document = f'''<w:document xmlns:w="{ns}"><w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>一 研究评述</w:t></w:r></w:p>
    <w:p><w:r><w:t>数字服务改善办事效率（甲，2024）。</w:t></w:r><w:r><w:footnoteReference w:id="2"/></w:r></w:p>
    <w:p><w:del><w:r><w:delText>应被排除的旧文字。</w:delText></w:r></w:del><w:ins><w:r><w:t>新增文字[1—3]。</w:t></w:r></w:ins></w:p>
    <w:tbl><w:tr><w:tc><w:p><w:r><w:t>表格引用（乙，2023）</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
    <w:p><w:r><w:t>参考文献</w:t></w:r></w:p>
    <w:p><w:r><w:t>书目（甲，2024）</w:t></w:r></w:p>
    </w:body></w:document>'''
    styles = f'''<w:styles xmlns:w="{ns}"><w:style w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style></w:styles>'''
    notes = f'''<w:footnotes xmlns:w="{ns}"><w:footnote w:type="separator" w:id="-1"/><w:footnote w:id="2"><w:p><w:r><w:t>政策脚注（部门，2024）。</w:t></w:r></w:p></w:footnote></w:footnotes>'''
    with ZipFile(path, 'w') as archive:
        archive.writestr('word/document.xml', document)
        archive.writestr('word/styles.xml', styles)
        archive.writestr('word/footnotes.xml', notes)

class ManuscriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'synthetic-package.zip'
        make_package(self.path)
        self.result = reader.read_docx(self.path, self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_word_does_not_use_ocr_or_infer_pages(self):
        self.assertFalse(self.result['diagnostics']['ocr_used'])
        self.assertFalse(self.result['diagnostics']['page_numbers_inferred'])

    def test_stable_paragraph_locator(self):
        block = next(x for x in self.result['blocks'] if x['id'] == 'P000002')
        self.assertEqual(block['location']['paragraph_index'], 2)
        self.assertEqual(block['section'], '一 研究评述')

    def test_table_cell_locator(self):
        block = next(x for x in self.result['blocks'] if x['id'] == 'T1.R1.C1.P1')
        self.assertEqual(block['location']['table_index'], 1)
        self.assertIn('乙', block['text'])

    def test_footnote_link_preserves_offset_without_fake_marker(self):
        block = next(x for x in self.result['blocks'] if x['id'] == 'P000002')
        self.assertEqual(block['note_references'][0]['id'], '2')
        self.assertEqual(block['note_references'][0]['offset'], len(block['text']))
        self.assertNotIn('脚注', block['text'])
        self.assertTrue(any(x['location'].get('note_id') == '2' for x in self.result['blocks']))

    def test_revision_convention_and_warning(self):
        all_text = ''.join(b['text'] for b in self.result['blocks'])
        self.assertIn('新增文字', all_text)
        self.assertNotIn('应被排除', all_text)
        self.assertTrue(self.result['diagnostics']['warnings'])

    def test_bibliography_not_counted_as_body_citation(self):
        self.assertEqual(len(self.result['citation_candidates']), 5)
        self.assertFalse(any(c['block_id'] == 'P000005' for c in self.result['citation_candidates']))

    def test_note_candidate_citation_is_included(self):
        self.assertTrue(any(x['block_id'] == 'FOOTNOTE2.P1' for x in self.result['citation_candidates']))

    def test_file_outside_root_rejected(self):
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaises(ValueError):
                reader.read_docx(self.path, other)

    def manuscript_ledger(self):
        data = json.loads((ROOT / 'tests/fixtures/valid-ledger.json').read_text(encoding='utf-8'))
        block = next(x for x in self.result['blocks'] if x['id'] == 'P000002')
        block['review_status'] = 'verified'
        data['claims'][0]['target'] = {'text': block['text'], 'pdf_page': None, 'print_page': None,
            'section': block['section'], 'docx_location': {'manuscript_sha256': self.result['manuscript']['sha256'],
            'block_id': block['id'], 'location': block['location']}}
        return data

    def test_word_target_validates_against_original(self):
        data = self.manuscript_ledger()
        self.assertTrue(validator.validate(data, manuscript=self.result,
            manuscript_root=self.temp.name)['ready_for_report'])

    def test_word_target_requires_original(self):
        result = validator.validate(self.manuscript_ledger())
        self.assertFalse(result['ready_for_report'])
        self.assertTrue(any(x.startswith('MANUSCRIPT_UNVERIFIED:') for x in result['blockers']))

    def test_word_target_requires_locator_when_context_is_supplied(self):
        data = self.manuscript_ledger()
        del data['claims'][0]['target']['docx_location']
        result = validator.validate(data, manuscript=self.result, manuscript_root=self.temp.name)
        self.assertTrue(any(x.startswith('DOCX_LOCATION_MISSING:') for x in result['errors']))

    def test_word_target_rejects_guessed_page(self):
        data = self.manuscript_ledger()
        data['claims'][0]['target']['pdf_page'] = 3
        self.assertTrue(any(x.startswith('DOCX_PAGE_INFERRED:') for x in validator.validate(data)['errors']))

    def test_word_target_change_detected(self):
        data = self.manuscript_ledger()
        self.path.write_bytes(b'changed-docx')
        result = validator.validate(data, manuscript=self.result, manuscript_root=self.temp.name)
        self.assertTrue(any(x.startswith('MANUSCRIPT_DIGEST_MISMATCH:') for x in result['errors']))

    def test_word_target_text_must_exist(self):
        data = self.manuscript_ledger()
        data['claims'][0]['target']['text'] = '主稿中没有的表述。'
        result = validator.validate(data, manuscript=self.result, manuscript_root=self.temp.name)
        self.assertTrue(any(x.startswith('MANUSCRIPT_TEXT_MISMATCH:') for x in result['errors']))

    def test_word_target_unreviewed_is_blocked(self):
        data = self.manuscript_ledger()
        next(b for b in self.result['blocks'] if b['id'] == 'P000002')['review_status'] = 'unverified'
        result = validator.validate(data, manuscript=self.result, manuscript_root=self.temp.name)
        self.assertTrue(any(x.startswith('MANUSCRIPT_BLOCK_REVIEW_PENDING:') for x in result['blockers']))

if __name__ == '__main__':
    unittest.main()
