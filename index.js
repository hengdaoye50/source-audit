import { registerSkill } from './deepseek-harness/index.js';
export const name = 'source-audit';
export const inject = ['skills'];
export function apply(ctx) {
  registerSkill(ctx, new URL('./skills/source-audit/', import.meta.url));
}
