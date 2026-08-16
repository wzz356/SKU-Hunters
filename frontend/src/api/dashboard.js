/* ============================================================
 * SKU Hunters · 策展数据 API（dashboard）
 * 名创内部 / 流行元素板 / 数据看板三个独立页（策展数据，非 Agent 现搜）。
 * ============================================================ */

import { request } from './client';

/** 名创内部 Insight Base（策展数据独立页） */
export async function getInsightBase(topic = '小风扇') {
  return request(`/insight-base?topic=${encodeURIComponent(topic)}`);
}

/** 流行元素板 Trend Gallery */
export async function getTrendGallery(topic = '小风扇') {
  return request(`/trend-gallery?topic=${encodeURIComponent(topic)}`);
}

/** 数据看板（大盘） */
export async function getDataBoard() {
  return request('/data-board');
}

/** 名创内部 IP 资源库（12 个代表性 IP + 官方披露数据带 + 筛选维度） */
export async function getIpResource() {
  return request('/ip-resource');
}
