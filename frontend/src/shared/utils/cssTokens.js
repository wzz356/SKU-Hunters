/* ============================================================
 * SKU Hunters · CSS token 读取工具
 * ECharts 走 Canvas 渲染，不识别 CSS 变量 var(--xxx)，
 * 直接传入会退化为默认灰色。此工具通过 getComputedStyle
 * 读取 documentElement 上计算后的真实颜色值，供 Canvas 绘图使用。
 *
 * 约定：feature 文件不得重新写入 hex 字面量，统一经由本函数取色。
 * ============================================================ */

const cache = {};

/**
 * 读取 :root 上定义的 CSS 变量计算值。
 * @param {string} name     变量名（如 '--chart-series-accent'）
 * @param {string} fallback 变量缺失/SSR 环境时的兜底值
 * @returns {string} 计算后的颜色值（如 '#E60012'）
 */
export function readCssVar(name, fallback = '') {
  if (cache[name] !== undefined) return cache[name];

  let value = fallback;
  if (typeof window !== 'undefined' && typeof document !== 'undefined') {
    try {
      const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      if (v) value = v;
    } catch {
      // 忽略读取异常，回退到 fallback
    }
  }
  cache[name] = value;
  return value;
}

/** 清空缓存（测试/主题热切换时用） */
export function clearCssVarCache() {
  Object.keys(cache).forEach((k) => delete cache[k]);
}
