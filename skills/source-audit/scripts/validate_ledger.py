"""Dependency-free validation for the bundled ledger schema and evidence links.

This is not a general JSON Schema implementation or a semantic evaluator.
Offsets are Python Unicode character offsets, zero-based, end-exclusive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

SCHEMA_PATH = Path(__file__).resolve().parents[1] / 'schemas' / 'ledger.schema.json'


def normalize(text):
    # Preserve punctuation, negation, numbers and words.
    return re.sub(r'\s+', '', text)


def schema_errors(value, schema, root, path='$'):
    """Implement only the keywords used by our versioned bundled schema."""
    if '$ref' in schema:
        ref = schema['$ref']
        node = root
        for key in ref.removeprefix('#/').split('/'):
            node = node[key]
        return schema_errors(value, node, root, path)
    errors = []
    kinds = schema.get('type', [])
    kinds = [kinds] if isinstance(kinds, str) else kinds
    matches = {
        'object': isinstance(value, dict), 'array': isinstance(value, list),
        'string': isinstance(value, str), 'integer': isinstance(value, int) and not isinstance(value, bool),
        'boolean': isinstance(value, bool), 'null': value is None,
    }
    if kinds and not any(matches.get(k, False) for k in kinds):
        return [f'{path}: expected {kinds}']
    if 'enum' in schema and value not in schema['enum']:
        errors.append(f'{path}: invalid enum value')
    if isinstance(value, dict):
        for key in schema.get('required', []):
            if key not in value:
                errors.append(f'{path}.{key}: required')
        props = schema.get('properties', {})
        for key, item in value.items():
            if key in props:
                errors += schema_errors(item, props[key], root, f'{path}.{key}')
            elif schema.get('additionalProperties') is False:
                errors.append(f'{path}.{key}: unexpected field')
    elif isinstance(value, list):
        if len(value) < schema.get('minItems', 0):
            errors.append(f'{path}: too few items')
        if schema.get('uniqueItems') and len({json.dumps(x, sort_keys=True) for x in value}) != len(value):
            errors.append(f'{path}: duplicate items')
        for i, item in enumerate(value):
            errors += schema_errors(item, schema.get('items', {}), root, f'{path}[{i}]')
    elif isinstance(value, str):
        if len(value) < schema.get('minLength', 0):
            errors.append(f'{path}: empty text')
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            errors.append(f'{path}: pattern mismatch')
    elif isinstance(value, int) and not isinstance(value, bool):
        if value < schema.get('minimum', value):
            errors.append(f'{path}: below minimum')
    return errors


def validate(ledger, source_root=None, manuscript=None, manuscript_root=None, image_root=None):
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
    errors = schema_errors(ledger, schema, schema)
    blockers = []
    warnings = []
    checked_files = 0
    if errors:
        return {'valid': False, 'ready_for_report': False, 'errors': errors,
                'blockers': [], 'warnings': [], 'files_checked': 0}

    def fail(code, detail):
        errors.append(f'{code}: {detail}')

    def block(code, detail):
        blockers.append(f'{code}: {detail}')

    def index(items, label):
        out = {}
        for item in items:
            if item['id'] in out:
                fail('DUPLICATE_ID', f'{label}/{item["id"]}')
            out[item['id']] = item
        return out

    sources = index(ledger['sources'], 'sources')
    index(ledger['claims'], 'claims')
    segment_maps = {}
    for sid, source in sources.items():
        segments = []
        pages_seen = set()
        last_page = 0
        for page in source['pages']:
            pn = page['pdf_page']
            if pn in pages_seen or pn <= last_page:
                fail('PAGE_ORDER', sid)
            pages_seen.add(pn)
            last_page = pn
            segments.extend((seg, pn, page['print_page']) for seg in page['segments'])
        smap = {}
        for position, (seg, pn, printed) in enumerate(segments):
            if seg['id'] in smap:
                fail('DUPLICATE_ID', f'{sid}/{seg["id"]}')
            smap[seg['id']] = (seg, pn, printed, position)
        segment_maps[sid] = smap
        for key, date in source['dates'].items():
            if date:
                import datetime
                try:
                    datetime.date.fromisoformat(date)
                except ValueError:
                    fail('DATE_INVALID', f'{sid}/{key}')

    used_ids = set()
    for claim in ledger['claims']:
        used_ids.update(claim['attributed_source_ids'])
        used_ids.update(claim['search']['source_ids'])
        used_ids.update(e['source_id'] for e in claim['evidence'])
    for sid in used_ids:
        if sid not in sources:
            fail('SOURCE_UNKNOWN', sid)
            continue
        source = sources[sid]
        origin = source['origin']
        if origin['kind'] == 'synthetic':
            # Synthetic fixtures have a documented deterministic text digest.
            raw = '\n'.join(seg['text'] for page in source['pages'] for seg in page['segments']).encode('utf-8')
        elif source_root is None:
            block('SOURCE_FILE_UNVERIFIED', sid)
            continue
        else:
            relative = origin['snapshot_path'] if origin['kind'] == 'web' else origin['locator']
            if not relative:
                block('SOURCE_SNAPSHOT_MISSING', sid)
                continue
            base = Path(source_root).resolve()
            # Reject either platform's absolute paths even when run elsewhere.
            if Path(relative).is_absolute() or re.match(r'^[A-Za-z]:|^\\\\', relative):
                fail('SOURCE_PATH_OUTSIDE_ROOT', sid)
                continue
            path = (base / relative).resolve()
            if not path.is_relative_to(base):
                fail('SOURCE_PATH_OUTSIDE_ROOT', sid)
                continue
            if not path.is_file():
                block('SOURCE_FILE_MISSING', sid)
                continue
            raw = path.read_bytes()
            checked_files += 1
        if hashlib.sha256(raw).hexdigest() != source['sha256']:
            fail('SOURCE_DIGEST_MISMATCH', sid)

    all_evidence_ids = set()
    for claim in ledger['claims']:
        cid = claim['id']
        status = claim['status']
        target = claim['target']
        docx = target.get('docx_location')
        if manuscript and manuscript.get('manuscript', {}).get('format') == 'docx' and not docx:
            fail('DOCX_LOCATION_MISSING', cid)
        if docx:
            if target['pdf_page'] is not None or target['print_page'] is not None:
                fail('DOCX_PAGE_INFERRED', cid)
            if manuscript is None or manuscript_root is None:
                block('MANUSCRIPT_UNVERIFIED', cid)
            else:
                meta = manuscript.get('manuscript', {})
                base = Path(manuscript_root).resolve()
                locator = meta.get('locator', '')
                original = (base / locator).resolve()
                if not locator or Path(locator).is_absolute() or re.match(r'^[A-Za-z]:|^\\\\', locator) or not original.is_relative_to(base):
                    fail('MANUSCRIPT_PATH_OUTSIDE_ROOT', cid)
                elif not original.is_file():
                    block('MANUSCRIPT_FILE_MISSING', cid)
                elif hashlib.sha256(original.read_bytes()).hexdigest() != docx['manuscript_sha256']:
                    fail('MANUSCRIPT_DIGEST_MISMATCH', cid)
                if meta.get('format') != 'docx' or meta.get('sha256') != docx['manuscript_sha256']:
                    fail('MANUSCRIPT_VERSION_MISMATCH', cid)
                blocks = {b['id']: b for b in manuscript.get('blocks', [])}
                main_block = blocks.get(docx['block_id'])
                if main_block is None:
                    fail('MANUSCRIPT_BLOCK_UNKNOWN', cid)
                else:
                    if docx['location'] != main_block['location'] or target['section'] != main_block['section']:
                        fail('MANUSCRIPT_LOCATION_MISMATCH', cid)
                    if normalize(target['text']) not in normalize(main_block['text']):
                        fail('MANUSCRIPT_TEXT_MISMATCH', cid)
                    if main_block['review_status'] != 'verified':
                        block('MANUSCRIPT_BLOCK_REVIEW_PENDING', cid)
        if claim['review_status'] != 'reviewed':
            block('CLAIM_REVIEW_PENDING', cid)
        subclaims = index(claim['subclaims'], cid)
        evidence = index(claim['evidence'], cid)
        for eid in evidence:
            if eid in all_evidence_ids:
                fail('DUPLICATE_ID', eid)
            all_evidence_ids.add(eid)
        for eid, ev in evidence.items():
            sid = ev['source_id']
            source = sources.get(sid)
            if source is None:
                continue
            if ev['source_sha256'] != source['sha256']:
                fail('EVIDENCE_VERSION_MISMATCH', eid)
            if sid not in claim['attributed_source_ids']:
                fail('EVIDENCE_ATTRIBUTION_MISMATCH', eid)
            if ev['completeness_review'] != 'verified' or ev['context_review'] != 'verified':
                block('EVIDENCE_REVIEW_PENDING', eid)
            if ev.get('docx_location'):
                if ev['pdf_pages'] or ev['print_pages'] or ev['spans']:
                    fail('WORD_SOURCE_PAGE_INFERRED', eid)
                if source_root is None:
                    block('WORD_SOURCE_UNVERIFIED', eid)
                else:
                    from read_manuscript import read_docx
                    base=Path(source_root).resolve()
                    path=(base/source['origin']['locator']).resolve()
                    if not path.is_relative_to(base) or not path.is_file() or path.suffix.lower()!='.docx':
                        fail('WORD_SOURCE_UNAVAILABLE', eid)
                    else:
                        block_data=next((b for b in read_docx(path,base)['blocks'] if b['id']==ev['docx_location']['block_id']),None)
                        if not block_data or block_data['text']!=ev['quote'] or block_data['location']!=ev['docx_location']['location']:
                            fail('WORD_SOURCE_LOCATION_MISMATCH', eid)
                        elif block_data['section']!=ev['section']:
                            fail('SECTION_MISMATCH', eid)
                        elif block_data['region'] in ('abstract','bibliography'):
                            fail('NON_BODY_EVIDENCE', eid)
                continue
            if not ev['spans'] or not ev['pdf_pages']:
                fail('PDF_BINDING_MISSING', eid)
            pieces = []
            touched = []
            smap = segment_maps[sid]
            for span in ev['spans']:
                found = smap.get(span['segment_id'])
                if found is None:
                    fail('SEGMENT_UNKNOWN', eid)
                    continue
                seg, pn, printed, pos = found
                if not (0 <= span['start'] < span['end'] <= len(seg['text'])):
                    fail('SPAN_INVALID', eid)
                    continue
                if seg['region'] != 'body':
                    fail('NON_BODY_EVIDENCE', eid)
                if seg['review_status'] != 'verified':
                    block('SEGMENT_REVIEW_PENDING', eid)
                if seg.get('verification_image'):
                    if image_root is None:
                        block('TRANSCRIPTION_IMAGE_UNVERIFIED', eid)
                    else:
                        base=Path(image_root).resolve()
                        path=(base/seg['verification_image']).resolve()
                        if not path.is_relative_to(base) or not path.is_file():
                            fail('TRANSCRIPTION_IMAGE_UNAVAILABLE', eid)
                if seg['section'] != ev['section']:
                    fail('SECTION_MISMATCH', eid)
                pieces.append(seg['text'][span['start']:span['end']])
                touched.append((pn, printed, pos, span, len(seg['text'])))
            for left, right in zip(touched, touched[1:]):
                if (right[2] != left[2] + 1 or left[3]['end'] != left[4] or right[3]['start'] != 0
                        or right[0] - left[0] not in (0, 1)):
                    fail('NONCONTIGUOUS_QUOTE', eid)
            if touched:
                if ev['pdf_pages'] != sorted({x[0] for x in touched}):
                    fail('PDF_PAGE_MISMATCH', eid)
                if ev['print_pages'] != list(dict.fromkeys(x[1] for x in touched)):
                    fail('PRINT_PAGE_MISMATCH', eid)
            if normalize(ev['quote']) != normalize(''.join(pieces)):
                fail('QUOTE_MISMATCH', eid)

        assessments = claim['assessments']
        aids = [a['subclaim_id'] for a in assessments]
        if len(set(aids)) != len(aids) or set(aids) != set(subclaims):
            fail('SUBCLAIM_COVERAGE', cid)
        referenced_evidence = set()
        for assessment in assessments:
            eids = assessment['evidence_ids']
            referenced_evidence.update(eids)
            if not set(eids).issubset(evidence):
                fail('ASSESSMENT_EVIDENCE_UNKNOWN', cid)
            if assessment['support'] in ('supported', 'partial') and not eids:
                fail('SUPPORT_WITHOUT_EVIDENCE', cid)
            if assessment['support'] == 'supported' and any(v is not True for v in assessment['boundaries'].values()):
                fail('SUPPORTED_BOUNDARY_UNRESOLVED', cid)
        if set(evidence) - referenced_evidence:
            fail('ORPHAN_EVIDENCE', cid)
        supports = [a['support'] for a in assessments]
        if status == 'direct' and not all(s == 'supported' for s in supports):
            fail('VERDICT_CONFLICT', cid)
        if status == 'partial' and (not any(s in ('supported', 'partial') for s in supports)
                                    or all(s == 'supported' for s in supports)):
            fail('VERDICT_CONFLICT', cid)
        if status == 'insufficient' and (not evidence or any(s in ('supported', 'partial') for s in supports)):
            fail('VERDICT_CONFLICT', cid)
        if status == 'not_found':
            search = claim['search']
            if (evidence or search['status'] != 'complete' or not search['queries']
                    or 'body' not in search['regions']
                    or not set(claim['attributed_source_ids']).issubset(search['source_ids'])
                    or any(s != 'unsupported' for s in supports)):
                fail('NOT_FOUND_UNJUSTIFIED', cid)
            for sid in claim['attributed_source_ids']:
                source = sources.get(sid)
                if source and (source['coverage'] != 'full' or not source['pages']
                               or any(not p['segments'] for p in source['pages'])
                               or not any(seg['region'] == 'body' for p in source['pages'] for seg in p['segments'])
                               or any(seg['review_status'] != 'verified'
                                      for p in source['pages'] for seg in p['segments'] if seg['region'] == 'body')
                               or any(seg['region'] == 'unknown' for p in source['pages'] for seg in p['segments'])):
                    fail('NOT_FOUND_COVERAGE_INCOMPLETE', cid)
        if status == 'unable':
            warnings.append(f'UNABLE_TO_VERIFY: {cid}')
        if status in ('direct', 'partial') and not evidence:
            fail('VERDICT_WITHOUT_EVIDENCE', cid)
        if claim['quotation_mode'] == 'verbatim':
            literal = claim['verbatim_text']
            if not literal:
                fail('VERBATIM_TEXT_MISSING', cid)
            elif status == 'direct' and not any(normalize(literal) in normalize(e['quote']) for e in evidence.values()):
                fail('VERBATIM_NOT_CONTINUOUS', cid)
        if claim['citation_role'] == 'policy':
            checks = claim['policy_checks']
            if checks is None:
                fail('POLICY_CHECKS_MISSING', cid)
                continue
            level = {'policy_document': 'formal', 'official_interpretation': 'interpretation',
                     'secondary_summary': 'secondary', 'academic_article': 'secondary', 'other': 'secondary'}
            for ev in evidence.values():
                source = sources.get(ev['source_id'])
                if source and checks['evidence_level'] != level[source['kind']]:
                    fail('POLICY_LEVEL_METADATA_CONFLICT', cid)
            if status == 'direct' and checks['claimed_level'] != checks['evidence_level']:
                fail('POLICY_LEVEL_MISMATCH', cid)
            if not checks['dates_reviewed']:
                block('POLICY_DATES_PENDING', cid)
            if status == 'direct' and claim['quotation_mode'] == 'verbatim' and checks['quotation_verified'] is not True:
                fail('POLICY_VERBATIM_UNVERIFIED', cid)
            if checks['claims_originals_verified'] and checks['evidence_level'] == 'secondary':
                fail('SECONDARY_AS_ORIGINAL', cid)
        elif claim['policy_checks'] is not None:
            fail('POLICY_CHECKS_UNEXPECTED', cid)

    counts = {}
    for claim in ledger['claims']:
        role = claim['citation_role']
        counts.setdefault(role, {})
        counts[role][claim['status']] = counts[role].get(claim['status'], 0) + 1
    return {'valid': not errors, 'ready_for_report': not errors and not blockers,
            'errors': errors, 'blockers': blockers, 'warnings': warnings,
            'files_checked': checked_files, 'counts_by_role': counts,
            'scope': 'structural/provenance checks; semantic judgment is not independently verified'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ledger', type=Path)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--manuscript', type=Path, help='DOCX reader output JSON')
    parser.add_argument('--manuscript-root', type=Path, help='Directory containing original DOCX')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--image-root', type=Path)
    args = parser.parse_args()
    try:
        manuscript = json.loads(args.manuscript.read_text(encoding='utf-8')) if args.manuscript else None
        result = validate(json.loads(args.ledger.read_text(encoding='utf-8')), args.source_root,
                          manuscript, args.manuscript_root, args.image_root)
    except (OSError, json.JSONDecodeError) as error:
        result = {'valid': False, 'ready_for_report': False, 'errors': [str(error)]}
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + '\n', encoding='utf-8')
    print(text)
    return 0 if result['ready_for_report'] else 2


if __name__ == '__main__':
    sys.exit(main())
