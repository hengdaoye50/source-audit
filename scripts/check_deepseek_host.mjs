// Uses an installed Harness's real Cordis and Skill registry; no API/model calls.
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { parseArgs } from 'node:util';

const { values } = parseArgs({ options: {
  'host-root': { type: 'string' }, bundle: { type: 'string' },
} });
if (!values['host-root'] || !values.bundle) {
  throw new Error('Usage: node check_deepseek_host.mjs --host-root <dsh package> --bundle <complete bundle>');
}
const host = resolve(values['host-root']);
const bundle = resolve(values.bundle);
const requireHost = createRequire(join(host, 'package.json'));
const importHost = (name) => import(pathToFileURL(requireHost.resolve(name)).href);
const { Context } = await importHost('@deepseek-ai/cordis');
const { default: SkillRegistry, renderSkillContent } = await importHost('@deepseek-ai/dsh-skill');
const plugin = await import(pathToFileURL(join(bundle, 'index.js')).href);
const ctx = new Context();
let registry, mounted;
const checks = [];
try {
  registry = ctx.plugin(SkillRegistry, {});
  await registry;
  assert.ok(ctx.skills);
  mounted = ctx.plugin(plugin, {});
  await mounted;
  const catalog = await ctx.skills.list();
  assert.equal(catalog.filter(s => s.name === 'source-audit').length, 1);
  checks.push('real-registry-catalog');
  const skill = await ctx.skills.get('source-audit');
  assert.ok(skill.content.includes('DeepSeek Harness 执行约定'));
  assert.ok(!skill.content.startsWith('---'));
  assert.deepEqual(skill.invocation, { modelInvocable: true, userInvocable: true });
  checks.push('load-and-invocation-policy');
  assert.equal(skill.resourceBase.kind, 'directory');
  assert.equal(resolve(skill.path), join(bundle, 'skills/source-audit/SKILL.md'));
  for (const resource of ['scripts/read_manuscript.py', 'scripts/read_sources.py',
    'scripts/validate_ledger.py', 'scripts/export_report.py',
    'references/evidence-format.md', 'schemas/ledger.schema.json']) {
    assert.ok(existsSync(join(skill.resourceBase.path, resource)), resource);
  }
  checks.push('packaged-core-resources');
  assert.ok(renderSkillContent(skill).includes('source-audit'));
  checks.push('host-model-facing-render');
  await mounted.dispose();
  assert.equal(await ctx.skills.get('source-audit'), undefined);
  checks.push('plugin-disposal');
  mounted = ctx.plugin(plugin, {});
  await mounted;
  assert.ok(await ctx.skills.get('source-audit'));
  checks.push('remount');
  const version = JSON.parse(readFileSync(join(host, 'package.json'), 'utf8')).version;
  console.log(JSON.stringify({ harness_version: version, checks, passed: checks.length,
    profile_modified: false, model_called: false, full_profile_install_tested: false }, null, 2));
} finally {
  if (mounted) await mounted.dispose();
  if (registry) await registry.dispose();
}
