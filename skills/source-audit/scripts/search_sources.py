"""Local lexical candidate retrieval and exact quote-span location; not verdicts."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re


def normalized_map(text):
    indices = [i for i, c in enumerate(text) if not c.isspace()]
    return ''.join(text[i] for i in indices), indices


def terms(text):
    lowered = text.lower()
    words = re.findall(r'[a-z0-9]+', lowered)
    chinese = re.findall(r'[\u3400-\u9fff]+', lowered)
    for chunk in chinese:
        words.extend(chunk[i:i+2] for i in range(max(1, len(chunk)-1)))
    return Counter(words)


def search(corpus, queries, limit=8):
    query_terms = terms(' '.join(queries))
    results = []
    for source in corpus['sources']:
        for page in source['pages']:
            segments = page['segments']
            for i, seg in enumerate(segments):
                if seg['region'] not in ('body', 'unknown'):
                    continue
                vocabulary = terms(seg['text'])
                overlap = set(query_terms) & set(vocabulary)
                score = sum(query_terms[t] * min(vocabulary[t], 3) for t in overlap)
                score = score / max(1, len(vocabulary) ** .3)
                if score <= 0:
                    continue
                results.append({'source_id': source['id'], 'title': source['title'],
                    'source_sha256': source['sha256'], 'pdf_page': page['pdf_page'],
                    'print_page': page['print_page'], 'segment_id': seg['id'], 'section': seg['section'],
                    'region': seg['region'], 'review_status': seg['review_status'],
                    'score': round(score, 4), 'matched_terms': sorted(overlap),
                    'text': seg['text'], 'candidate_only': True})
    return sorted(results, key=lambda x: (-x['score'], x['source_id'], x['pdf_page'], x['segment_id']))[:limit]


def locate_quote(source, quote, allow_unreviewed=True):
    """Return contiguous body spans; whitespace alone may differ.

    Unknown regions are excluded. Location does not certify complete meaning.
    """
    target, _ = normalized_map(quote)
    if not target:
        return []
    flattened = [(page, seg) for page in source['pages'] for seg in page['segments']]
    groups, current = [], []
    for page, seg in flattened:
        eligible = seg['region'] == 'body' and (allow_unreviewed or seg['review_status'] == 'verified')
        contiguous = (not current or (current[-1][1]['section'] == seg['section'] and
                                     page['pdf_page'] - current[-1][0]['pdf_page'] in (0, 1)))
        if not eligible or not contiguous:
            if current:
                groups.append(current)
            current = []
        if eligible:
            current.append((page, seg))
    if current:
        groups.append(current)
    matches = []
    for group in groups:
        joined, mapping = '', []
        for page, seg in group:
            normalized, offsets = normalized_map(seg['text'])
            joined += normalized
            mapping.extend((page, seg, x) for x in offsets)
        start = joined.find(target)
        while start >= 0:
            selected = mapping[start:start+len(target)]
            spans, pages, printed, verified = [], [], [], True
            for page, seg, offset in selected:
                if not spans or spans[-1]['segment_id'] != seg['id']:
                    spans.append({'segment_id': seg['id'], 'start': offset, 'end': offset+1})
                else:
                    spans[-1]['end'] = offset+1
                if page['pdf_page'] not in pages:
                    pages.append(page['pdf_page'])
                if page['print_page'] not in printed:
                    printed.append(page['print_page'])
                verified = verified and seg['review_status'] == 'verified'
            # Whitespace at inter-segment boundaries belongs to the contiguous span.
            if len(spans) > 1:
                by_id = {seg['id']: seg for _, seg in group}
                for item in spans[:-1]:
                    item['end'] = len(by_id[item['segment_id']]['text'])
                for item in spans[1:]:
                    item['start'] = 0
            matches.append({'source_id': source['id'], 'source_sha256': source['sha256'],
                'quote': quote, 'section': selected[0][1]['section'], 'pdf_pages': pages,
                'print_pages': printed, 'spans': spans, 'segments_reviewed': verified,
                'completeness_review': 'pending', 'context_review': 'pending'})
            start = joined.find(target, start+1)
    return matches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('corpus', type=Path)
    parser.add_argument('--query', action='append', required=True)
    parser.add_argument('--limit', type=int, default=8)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit must be positive')
    result = {'retrieval': 'lexical_candidates_not_semantic_verdicts',
              'queries': args.query, 'results': search(json.loads(args.corpus.read_text(encoding='utf-8')), args.query, args.limit)}
    data = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(data + '\n', encoding='utf-8')
    else:
        print(data)


if __name__ == '__main__':
    main()
