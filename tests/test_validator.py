import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/source-audit/scripts/validate_ledger.py'
spec = importlib.util.spec_from_file_location('audit_validator', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EvidenceValidationTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / 'tests/fixtures/valid-ledger.json').read_text(encoding='utf-8'))
        self.claim = self.data['claims'][0]
        self.evidence = self.claim['evidence'][0]
        self.source = self.data['sources'][0]

    def result(self):
        return module.validate(self.data)

    def rejects(self, code):
        r = self.result()
        self.assertFalse(r['valid'], r)
        self.assertTrue(any(e.startswith(code + ':') for e in r['errors']), r)

    def blocked(self, code):
        r = self.result()
        self.assertTrue(r['valid'], r)
        self.assertFalse(r['ready_for_report'], r)
        self.assertTrue(any(e.startswith(code + ':') for e in r['blockers']), r)

    def negative_claim(self):
        self.claim['status'] = 'not_found'
        self.claim['evidence'] = []
        self.claim['assessments'][0]['evidence_ids'] = []
        self.claim['assessments'][0]['support'] = 'unsupported'

    def policy_claim(self):
        self.claim['citation_role'] = 'policy'
        self.source['kind'] = 'policy_document'
        self.claim['policy_checks'] = {'claimed_level': 'formal', 'evidence_level': 'formal',
            'quotation_verified': None, 'dates_reviewed': True,
            'claims_originals_verified': True, 'version_note': '自制政策测试，不对应实际文件。'}

    def test_valid_ledger(self):
        self.assertTrue(self.result()['ready_for_report'])

    def test_cross_page_quote(self):
        data = json.loads((ROOT / 'tests/fixtures/cross-page-ledger.json').read_text(encoding='utf-8'))
        self.assertTrue(module.validate(data)['ready_for_report'])

    def test_missing_required_field(self):
        del self.evidence['section']
        self.assertFalse(self.result()['valid'])

    def test_unknown_field(self):
        self.claim['assumed_accuracy'] = 1
        self.assertFalse(self.result()['valid'])

    def test_unknown_status(self):
        self.claim['status'] = 'probably_ok'
        self.assertFalse(self.result()['valid'])

    def test_empty_reason(self):
        self.claim['reason'] = '   '
        self.assertFalse(self.result()['valid'])

    def test_duplicate_claim(self):
        self.data['claims'].append(copy.deepcopy(self.claim))
        self.rejects('DUPLICATE_ID')

    def test_duplicate_segment(self):
        self.source['pages'][1]['segments'][0]['id'] = 'body1'
        self.rejects('DUPLICATE_ID')

    def test_source_version_changed(self):
        self.evidence['source_sha256'] = '0' * 64
        self.rejects('EVIDENCE_VERSION_MISMATCH')

    def test_source_contents_changed(self):
        self.source['pages'][1]['segments'][0]['text'] += '新增字符。'
        self.rejects('SOURCE_DIGEST_MISMATCH')

    def test_nonexistent_quote(self):
        self.evidence['quote'] = '来源从未包含的原句。'
        self.rejects('QUOTE_MISMATCH')

    def test_negation_removed(self):
        self.evidence['quote'] = self.evidence['quote'].replace('未发现', '发现')
        self.rejects('QUOTE_MISMATCH')

    def test_whitespace_only_changes(self):
        self.evidence['quote'] = self.evidence['quote'].replace('，', '，\n  ')
        self.assertTrue(self.result()['ready_for_report'])

    def test_punctuation_change_not_normalized(self):
        self.evidence['quote'] = self.evidence['quote'].replace('，', ',')
        self.rejects('QUOTE_MISMATCH')

    def test_abstract_quote_rejected(self):
        abstract = self.source['pages'][0]['segments'][0]
        self.evidence.update(quote=abstract['text'], section='摘要',
            spans=[{'segment_id': 'abstract', 'start': 0, 'end': len(abstract['text'])}])
        self.rejects('NON_BODY_EVIDENCE')

    def test_bibliography_quote_rejected(self):
        self.source['pages'][0]['segments'][1]['region'] = 'bibliography'
        self.rejects('NON_BODY_EVIDENCE')

    def test_wrong_pdf_page(self):
        self.evidence['pdf_pages'] = [9]
        self.rejects('PDF_PAGE_MISMATCH')

    def test_wrong_print_page(self):
        self.evidence['print_pages'] = ['999']
        self.rejects('PRINT_PAGE_MISMATCH')

    def test_wrong_section(self):
        self.evidence['section'] = '一、引言'
        self.rejects('SECTION_MISMATCH')

    def test_invalid_offset(self):
        self.evidence['spans'][0]['end'] = 999
        self.rejects('SPAN_INVALID')

    def test_unverified_ocr(self):
        self.source['pages'][0]['segments'][1].update(extraction='ocr', review_status='unverified')
        self.blocked('SEGMENT_REVIEW_PENDING')

    def test_quote_completeness_pending(self):
        self.evidence['completeness_review'] = 'pending'
        self.blocked('EVIDENCE_REVIEW_PENDING')

    def test_claim_review_pending(self):
        self.claim['review_status'] = 'pending'
        self.blocked('CLAIM_REVIEW_PENDING')

    def test_stitched_quote_rejected(self):
        second = self.source['pages'][1]['segments'][0]['text']
        self.evidence['spans'][0]['end'] -= 2
        self.evidence['spans'].append({'segment_id': 'body2', 'start': 0, 'end': len(second)})
        self.evidence['quote'] = self.evidence['quote'][:-2] + second
        self.evidence['pdf_pages'] = [1, 2]
        self.evidence['print_pages'] = ['101', '102']
        self.rejects('NONCONTIGUOUS_QUOTE')

    def test_subclaim_not_assessed(self):
        self.claim['subclaims'].append({'id': 'C1.2', 'text': '同时增加就业。'})
        self.rejects('SUBCLAIM_COVERAGE')

    def test_direct_with_unsupported_subclaim(self):
        self.claim['assessments'][0]['support'] = 'unsupported'
        self.rejects('VERDICT_CONFLICT')

    def test_supported_with_geographic_mismatch(self):
        self.claim['assessments'][0]['boundaries']['geography_match'] = False
        self.rejects('SUPPORTED_BOUNDARY_UNRESOLVED')

    def test_partial_with_mismatch_is_allowed(self):
        self.claim['status'] = 'partial'
        self.claim['assessments'][0]['support'] = 'partial'
        self.claim['assessments'][0]['boundaries']['geography_match'] = False
        self.assertTrue(self.result()['ready_for_report'])

    def test_incomplete_search_not_found(self):
        self.negative_claim()
        self.claim['search']['status'] = 'incomplete'
        self.rejects('NOT_FOUND_UNJUSTIFIED')

    def test_partial_corpus_not_found(self):
        self.negative_claim()
        self.source['coverage'] = 'partial'
        self.rejects('NOT_FOUND_COVERAGE_INCOMPLETE')

    def test_unknown_regions_not_found(self):
        self.negative_claim()
        self.source['pages'][0]['segments'][1]['region'] = 'unknown'
        self.rejects('NOT_FOUND_COVERAGE_INCOMPLETE')

    def test_empty_page_not_found_is_not_complete(self):
        self.negative_claim()
        self.source['pages'][0]['segments'] = []
        self.rejects('NOT_FOUND_COVERAGE_INCOMPLETE')

    def test_valid_not_found(self):
        self.negative_claim()
        self.assertTrue(self.result()['ready_for_report'])

    def test_unable_is_distinct(self):
        self.negative_claim()
        self.claim['status'] = 'unable'
        self.claim['assessments'][0]['support'] = 'unknown'
        self.claim['search']['status'] = 'incomplete'
        r = self.result()
        self.assertTrue(r['ready_for_report'])
        self.assertTrue(any(x.startswith('UNABLE_TO_VERIFY:') for x in r['warnings']))

    def test_policy_without_metadata(self):
        self.claim['citation_role'] = 'policy'
        self.rejects('POLICY_CHECKS_MISSING')

    def test_interpretation_as_formal(self):
        self.policy_claim()
        self.source['kind'] = 'official_interpretation'
        self.claim['policy_checks']['evidence_level'] = 'interpretation'
        self.rejects('POLICY_LEVEL_MISMATCH')

    def test_secondary_cannot_certify_originals(self):
        self.policy_claim()
        self.source['kind'] = 'secondary_summary'
        self.claim['policy_checks'].update(claimed_level='secondary', evidence_level='secondary')
        self.rejects('SECONDARY_AS_ORIGINAL')

    def test_policy_date_review_pending(self):
        self.policy_claim()
        self.claim['policy_checks']['dates_reviewed'] = False
        self.blocked('POLICY_DATES_PENDING')

    def test_invalid_calendar_date(self):
        self.source['dates']['issued'] = '2024-02-30'
        self.rejects('DATE_INVALID')

    def test_verbatim_requires_continuous_target_text(self):
        self.claim.update(quotation_mode='verbatim', verbatim_text='数字服务改善办事效率且显著增加就业。')
        self.rejects('VERBATIM_NOT_CONTINUOUS')

    def test_explicit_and_suggested_counts_are_separate(self):
        other = copy.deepcopy(self.claim)
        other['id'] = 'C2'
        other['evidence'][0]['id'] = 'E2'
        other['assessments'][0]['evidence_ids'] = ['E2']
        other['citation_role'] = 'suggested'
        self.data['claims'].append(other)
        self.assertEqual(self.result()['counts_by_role'], {'explicit': {'direct': 1}, 'suggested': {'direct': 1}})

    def test_real_file_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            raw = b'local-source-test'
            Path(folder, 'source.pdf').write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            self.source['origin'].update(kind='local', locator='source.pdf')
            self.source['sha256'] = self.evidence['source_sha256'] = digest
            self.assertTrue(module.validate(self.data, folder)['ready_for_report'])
            Path(folder, 'source.pdf').write_bytes(b'changed')
            self.assertFalse(module.validate(self.data, folder)['valid'])

    def test_without_source_root_cannot_certify_real_file(self):
        self.source['origin'].update(kind='local', locator='source.pdf')
        self.blocked('SOURCE_FILE_UNVERIFIED')

    def test_path_cannot_escape_root(self):
        self.source['origin'].update(kind='local', locator='../private.pdf')
        with tempfile.TemporaryDirectory() as folder:
            r = module.validate(self.data, folder)
            self.assertFalse(r['valid'])
            self.assertTrue(any(x.startswith('SOURCE_PATH_OUTSIDE_ROOT:') for x in r['errors']))


if __name__ == '__main__':
    unittest.main()
