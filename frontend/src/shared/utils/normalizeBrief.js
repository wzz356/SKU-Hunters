/* ============================================================
 * SKU Hunters · brief 归一化工具
 * 两个方向：
 *   ① fromForm(values, defaults)  表单值 → 后端 PlanBrief（snake_case）
 *   ② toCamelBrief(brief)         后端 brief（snake_case）→ 前端消费（camelCase + 默认值）
 * 纯函数：不 import fixtures、不发请求。
 * ============================================================ */

// 后端 brief 为 snake_case（PlanBrief schema 冻结），前端消费契约统一 camelCase。
const SNAKE_TO_CAMEL = {
  price_range: 'priceRange',
  cost_limit: 'costLimit',
  ip_strategy: 'ipStrategy',
  launch_window: 'launchWindow',
};

/** 后端 brief（snake_case）→ 前端消费（camelCase + 安全默认值） */
export function toCamelBrief(brief) {
  if (!brief) return null;
  const out = { ...brief };
  for (const [snake, camel] of Object.entries(SNAKE_TO_CAMEL)) {
    if (snake in out && !(camel in out)) out[camel] = out[snake];
  }
  out.priceRange = out.priceRange || [39, 99];
  out.costLimit = out.costLimit ?? 25;
  out.ipStrategy = out.ipStrategy || [];
  out.goals = out.goals || [];
  return out;
}

/** 表单值 → 后端 PlanBrief（snake_case） */
export function fromForm(values, defaults = {}) {
  return {
    theme: values.theme,
    category: values.category,
    market: values.market || defaults.market || '',
    audience: values.audience || '',
    price_range: [
      values.priceMin ?? defaults.priceRange?.[0] ?? 0,
      values.priceMax ?? defaults.priceRange?.[1] ?? 0,
    ],
    cost_limit: values.costLimit ?? defaults.costLimit ?? 0,
    ip_strategy: values.ipStrategy || [],
    launch_window: values.launchWindow || '',
    goals: values.goals || [],
  };
}

// 向后兼容别名（旧调用 `normalizeBrief` 指向 camel 方向）
export const normalizeBrief = toCamelBrief;
