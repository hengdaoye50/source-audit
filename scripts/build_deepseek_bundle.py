"""Build a standalone DSH bundle from the shared, allowlisted audit core."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def build(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    adapter = root / 'deepseek-harness'
    files = [(adapter / name, name) for name in
             ('package.json', 'index.js', 'cordis.patch.yml', 'README.md')]
    files += [(root / name, name) for name in ('requirements.txt', 'LICENSE')]
    core = root / 'skills' / 'source-audit'
    for path in sorted(core.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix in {
                '.md', '.json', '.py', '.ps1'}:
            files.append((path, path.relative_to(root).as_posix()))
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = []
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for path, relative in files:
            data = path.read_bytes()
            archive.writestr('source-audit-deepseek/' + relative, data)
            manifest.append({'path': relative, 'sha256': hashlib.sha256(data).hexdigest()})
    result = {'platform': 'deepseek-harness',
              'version': json.loads((adapter / 'package.json').read_text(encoding='utf8'))['version'],
              'files': manifest, 'archive': output.name,
              'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
              'research_files_included': False}
    output.with_suffix('.manifest.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build(Path(__file__).resolve().parents[1], args.output)
    print(json.dumps({k: v for k, v in result.items() if k != 'files'} |
                     {'file_count': len(result['files'])}, ensure_ascii=False))
