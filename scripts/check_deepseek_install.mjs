// Tests installed GitHub package metadata and composition in a workspace-only profile.
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { parseArgs } from 'node:util';

const { values } = parseArgs({ options: {
  'host-root': { type: 'string' }, home: { type: 'string' }, profile: { type: 'string' },
} });
if (!values['host-root'] || !values.home || !values.profile) {
  throw new Error('Required: --host-root <installed dsh> --home <isolated test home> --profile <test name>');
}
const host = resolve(values['host-root']);
const home = resolve(values.home);
const profileDir = join(home, 'profiles', values.profile);
const hostRequire = createRequire(join(host, 'package.json'));
const importHost = name => import(pathToFileURL(hostRequire.resolve(name)).href);
const { loadProfile, composeEntries, readProfileManifest, resolveBundleDir } =
  await importHost('@deepseek-ai/dsh-app-boot');
const anchor = join(host, 'package.json');
const dir = resolveBundleDir('dsh', '@local/dsh-source-audit', anchor, profileDir);
const manifest = readProfileManifest('dsh', dir);
assert.ok(manifest.dsh?.bundle?.patch, 'Installed package must declare dsh.bundle.patch');
assert.ok(existsSync(join(dir, manifest.dsh.bundle.patch)));
const profile = loadProfile('dsh', values.profile, anchor, home);
assert.equal(profile.layers.length, 1);
const rows = composeEntries([...profile.layers.map(layer => layer.patches), profile.patches]);
assert.equal(rows.length, 1);
assert.equal(rows[0].name, manifest.name);
const profileRequire = createRequire(join(profileDir, 'package.json'));
const entry = profileRequire.resolve(manifest.name);
const plugin = await import(pathToFileURL(entry).href);
const { Context } = await importHost('@deepseek-ai/cordis');
const { default: SkillRegistry } = await importHost('@deepseek-ai/dsh-skill');
const ctx = new Context();
const registry = ctx.plugin(SkillRegistry, {});
await registry;
const mounted = ctx.plugin(plugin, rows[0].config ?? {});
try {
  await mounted;
  const skill = await ctx.skills.get('source-audit');
  assert.ok(skill?.content.includes('DeepSeek Harness 执行约定'));
  for (const name of ['read_manuscript.py', 'read_sources.py', 'validate_ledger.py', 'export_report.py']) {
    assert.ok(existsSync(join(skill.resourceBase.path, 'scripts', name)));
  }
  console.log(JSON.stringify({ installed_package: manifest.name,
    installed_version: JSON.parse(readFileSync(join(dir, 'package.json'), 'utf8')).version,
    github_spec: JSON.parse(readFileSync(join(profileDir, 'package.json'), 'utf8')).dependencies[manifest.name],
    bundle_recognized: true, patch_composed: true, package_export_loaded: true,
    skill_loaded: true, core_resources_present: true,
    model_called: false, existing_user_profile_modified: false }, null, 2));
} finally {
  await mounted.dispose();
  await registry.dispose();
}
