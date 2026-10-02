import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export const name = 'source-audit';
export const inject = ['skills'];

// Resources are copied from the shared core by build_deepseek_bundle.py.
export function apply(ctx) {
  registerSkill(ctx, new URL('./skills/source-audit/', import.meta.url));
}

export function registerSkill(ctx, baseUrl) {
  const base = fileURLToPath(baseUrl);
  const path = fileURLToPath(new URL('SKILL.md', baseUrl));
  const raw = readFileSync(path, 'utf8').replace(/^\uFEFF/, '');
  const frontmatter = /^---\r?\n([\s\S]*?)\r?\n---\r?\n/.exec(raw);
  if (!frontmatter || !/^name: source-audit\s*$/m.test(frontmatter[1])) {
    throw new Error('Missing or incompatible source-audit SKILL.md; build the complete bundle first.');
  }
  const description = /^description: (.+)$/m.exec(frontmatter[1])?.[1]?.trim();
  if (!description) throw new Error('source-audit requires a skill description.');
  const content = raw.slice(frontmatter[0].length) + '\n\n' +
    '## DeepSeek Harness 执行约定\n\n' +
    '使用当前宿主提供的文件读取、终端和原页查看能力，资源相对本 Skill 基目录。' +
    '先确认可用的 Python 3.10+ 解释器与依赖，不假定 Codex 的运行时或工具存在。' +
    'Windows OCR 按需使用；其他系统缺少 OCR 时标记无法核准，不编造转写。' +
    '没有 Word 渲染能力时保留导出文件，明确标记页面验收未完成，不宣称报告已正式验收。' +
    '文件提取在本地执行；供当前模型阅读的片段受宿主模型服务配置约束，不承诺完全离线。\n';
  // register owns a Cordis effect and returns its disposer; bind it to this plugin lifecycle.
  ctx.effect(() => ctx.skills.register({
    name, description, source: 'runtime', path,
    resourceBase: { kind: 'directory', path: base },
    invocation: { modelInvocable: true, userInvocable: true },
    content,
  }));
}
