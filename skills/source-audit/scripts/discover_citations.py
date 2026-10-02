"""Link footnote groups and author-year markers to bibliography/source candidates.

No inference here is a support verdict. Ambiguous files remain visible.
"""
import argparse
import json
from pathlib import Path
import re

def normalized(text):
    return ''.join(c.lower() for c in text if c.isalnum())

def note_references(text):
    out = []
    for m in re.finditer(r'([^；;\n]{1,100}?)[:：]\s*《([^》]+)》([^；;\n]*)', text):
        authors = re.split(r'参见|讨论，|应用，', m.group(1))[-1].strip()
        tail = m.group(3)
        year = re.search(r'(?:19|20)\d{2}', tail)
        out.append({'authors':authors,'year':year.group(0) if year else None,'title':m.group(2)})
    for m in re.finditer(r'"([^"]+)"', text):
        before = re.split(r'[；;]', text[:m.start()])[-1]
        after = text[m.end():].split('；')[0].split(';')[0]
        year = re.search(r'(?:19|20)\d{2}', after)
        out.append({'authors':before.strip(' ,，'),'year':year.group(0) if year else None,'title':m.group(1)})
    return out

def author_year(marker):
    parts = re.split(r'[;；]', marker.strip('（）()'))
    authors, out = '', []
    for part in parts:
        year = re.search(r'(?:19|20)\d{2}[a-z]?', part)
        if not year:
            continue
        prefix = part[:year.start()].strip(' ,，、')
        if prefix:
            authors = prefix
        out.append({'authors':authors,'year':year.group(0),'title':None})
    return out

def bibliography(manuscript):
    result = []
    for b in manuscript['blocks']:
        if b['region'] != 'bibliography':
            continue
        text = b['text']
        year = re.search(r'(?:19|20)\d{2}[a-z]?',text)
        title = re.search(r'《([^》]+)》|"([^"]+)"',text)
        if not year:
            continue
        result.append({'authors':text[:year.start()].strip(' ,，'), 'year':year.group(0),
                       'title':next((g for g in title.groups() if g),None) if title else text[year.end():].strip(' ,，'),
                       'block_id':b['id']})
    return result

def file_matches(reference, files):
    title = normalized(reference.get('title') or '')
    authors = re.split(r'[、，,]|\band\b|\bet al\b',reference['authors'])[0].replace('等','').strip()
    author = normalized(authors)
    found=[]
    for entry in files:
        name=normalized(entry['title'])
        score=0
        if title and (title in name or name in title):score=1.0
        elif author and author in name:
            score=.8 if reference.get('year') and reference['year'] in entry['title'] else .6
        if score:found.append({**entry,'match_score':score,'candidate_only':True})
    return sorted(found,key=lambda x:(-x['match_score'],x['relative_path']))

def discover(manuscript, files):
    blocks={b['id']:b for b in manuscript['blocks']}
    notes={(n['kind'],n['id']):n for n in manuscript['notes']}
    bib=bibliography(manuscript)
    groups=[]
    for marker in manuscript['citation_candidates']:
        block=blocks[marker['block_id']]
        if marker['kind'] in ('footnote_reference','endnote_reference'):
            kind=marker['kind'].removesuffix('_reference')
            note=notes.get((kind,marker['note_id']))
            text='\n'.join(blocks[n]['text'] for n in note['blocks'] if n in blocks) if note else ''
            refs=note_references(text)
        elif marker['kind']=='author_year':
            refs=author_year(marker['marker']);text=marker['marker']
            for reference in refs:
                for item in bib:
                    if item['year']==reference['year'] and normalized(reference['authors'].replace('等','')) in normalized(item['authors']):
                        reference['title']=item['title'];break
        else:
            refs=[];text=marker['marker']
        for reference in refs:reference['source_candidates']=file_matches(reference,files)
        groups.append({'id':f'G{len(groups)+1:03d}','block_id':block['id'], 'section':block['section'],
            'anchor_start':marker['start'],'anchor_end':marker['end'],'marker_kind':marker['kind'],
            'reference_text':text,'target_context':block['text'],'references':refs,
            'status':'candidate_group_not_semantic_verdict'})
    return {'groups':groups,'bibliography':bib,'reference_occurrences':sum(len(g['references']) for g in groups),
        'unmatched':[{'group_id':g['id'],**r} for g in groups for r in g['references'] if not r['source_candidates']]}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manuscript',type=Path)
    parser.add_argument('--references',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    files=[{'relative_path':p.relative_to(args.references).as_posix(),'title':p.stem,'format':p.suffix.lstrip('.').lower()}
           for p in args.references.rglob('*') if p.suffix.lower() in ('.pdf','.docx')]
    result=discover(json.loads(args.manuscript.read_text(encoding='utf-8')),files)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'groups':len(result['groups']),'references':result['reference_occurrences'],
                      'unmatched':len(result['unmatched'])},ensure_ascii=False))

if __name__=='__main__':main()
