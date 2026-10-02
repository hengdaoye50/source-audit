"""Build an explicit local release archive without research files or caches."""
from pathlib import Path
import argparse,hashlib,json
from zipfile import ZipFile,ZIP_DEFLATED

def package(root,output):
    root=Path(root).resolve();output=Path(output).resolve()
    allowed_roots={'skills','tests','scripts','.agents','deepseek-harness'}
    allowed_top={'plugin.json','README.md','INSTALL.md','CHANGELOG.md','requirements.txt','.gitignore','LICENSE'}
    allowed_suffixes={'.py','.ps1','.json','.md','.txt','.yml','.yaml','.js','.mjs'}
    files=[]
    for path in sorted(root.rglob('*')):
        if not path.is_file():continue
        rel=path.relative_to(root)
        if any(part in {'__pycache__','.git','.venv','local-data','outputs'} for part in rel.parts):continue
        if len(rel.parts)==1:
            if rel.name not in allowed_top:continue
        elif rel.parts[0] not in allowed_roots:continue
        if path.suffix.lower() not in allowed_suffixes and rel.name not in {'LICENSE','.gitignore'}:continue
        if rel.name in {'fixture-validation.json'}:continue
        files.append((path,rel))
    output.parent.mkdir(parents=True,exist_ok=True)
    manifest=[]
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for path,rel in files:
            raw=path.read_bytes();archive.writestr('source-audit-plugin/'+rel.as_posix(),raw)
            manifest.append({'path':rel.as_posix(),'sha256':hashlib.sha256(raw).hexdigest()})
    result={'plugin_version':json.loads((root/'plugin.json').read_text(encoding='utf8'))['version'],
      'files':manifest,'archive':output.name,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
      'license_present':(root/'LICENSE').is_file(),'research_files_included':False}
    output.with_suffix('.manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=package(Path(__file__).resolve().parents[1],a.output)
    print(json.dumps({k:v for k,v in r.items() if k!='files'}|{'file_count':len(r['files'])},ensure_ascii=False))
