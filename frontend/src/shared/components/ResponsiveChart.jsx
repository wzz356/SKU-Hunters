/* ============================================================
 * SKU Hunters · ResponsiveChart（ECharts 响应式封装）
 * 统一图表可访问性：aria-label + 可见文本摘要（红线：图表不能只有图形）。
 * ============================================================ */

import ReactECharts from 'echarts-for-react';

/**
 * @param {object} option      ECharts option
 * @param {number|string} height 图表高度（px）
 * @param {string} ariaLabel  无障碍标签（屏幕阅读器）
 * @param {string} summary    可见文本摘要（caption，替代可访问数据表）
 */
export default function ResponsiveChart({ option, height = 240, ariaLabel, summary }) {
  return (
    <figure style={{ margin: 0 }}>
      <div role="img" aria-label={ariaLabel || summary || '数据图表'}>
        <ReactECharts option={option} style={{ height }} notMerge lazyUpdate />
      </div>
      {summary && (
        <figcaption style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 4 }}>
          {summary}
        </figcaption>
      )}
    </figure>
  );
}
