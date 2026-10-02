"""Validate the distributable contains the exact shared core, no user material."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_dsh', ROOT / 'scripts/build_deepseek_bundle.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class DeepSeekPackageTests(unittest.TestCase):
    def test_complete_bundle_and_shared_core(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'bundle.zip'
            result = builder.build(ROOT, output)
            with ZipFile(output) as archive:
                self.assertIsNone(archive.testzip())
                prefix = 'source-audit-deepseek/'
                package = json.loads(archive.read(prefix + 'package.json'))
                self.assertEqual(package['dsh']['bundle']['patch'], './cordis.patch.yml')
                self.assertEqual(package['exports']['.'], './index.js')
                self.assertNotIn('scripts', package)
                self.assertNotIn('dependencies', package)
                self.assertEqual(package['version'], result['version'])
                self.assertEqual(package['version'], json.loads((ROOT / 'plugin.json').read_text('utf8'))['version'])
                for resource in ('SKILL.md', 'schemas/ledger.schema.json',
                                 'scripts/read_manuscript.py', 'scripts/read_sources.py',
                                 'scripts/validate_ledger.py', 'scripts/export_report.py'):
                    relative = 'skills/source-audit/' + resource
                    self.assertEqual(archive.read(prefix + relative), (ROOT / relative).read_bytes())
                self.assertFalse(any(Path(n).suffix.lower() in {'.pdf', '.docx', '.png', '.jpg'}
                                     for n in archive.namelist()))
                self.assertEqual(len(archive.namelist()), len(result['files']))
                self.assertIn(prefix + 'LICENSE', archive.namelist())

    def test_exclude_private_material(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'deepseek-harness').mkdir()
            for name in ('package.json', 'index.js', 'cordis.patch.yml', 'README.md'):
                (root / 'deepseek-harness' / name).write_bytes((ROOT / 'deepseek-harness' / name).read_bytes())
            for name in ('requirements.txt', 'LICENSE'):
                (root / name).write_bytes((ROOT / name).read_bytes())
            core = root / 'skills/source-audit'
            (core / '__pycache__').mkdir(parents=True)
            (core / 'paper.pdf').write_text('private')
            (core / '__pycache__/private.py').write_text('private')
            result = builder.build(root, root / 'bundle.zip')
            self.assertFalse(any('private' in item['path'] or '.pdf' in item['path'] for item in result['files']))
