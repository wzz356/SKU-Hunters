/* ============================================================
 * SKU Hunters · 洞察/机会只读 API（insights）
 * 只读接口（刷新恢复用），不推进业务状态。
 * ============================================================ */

import { request } from './client';

/** 五看洞察（camelCase 契约，只读） */
export async function getInsights(planId) {
  return request(`/plans/${planId}/insights`);
}

/** 机会生成（3 张方向卡 + processLog，只读） */
export async function getOpportunities(planId) {
  return request(`/plans/${planId}/opportunities`);
}
