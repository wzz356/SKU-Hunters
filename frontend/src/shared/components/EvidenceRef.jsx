/* ============================================================
 * SKU Hunters · EvidenceRef（证据角标 + 来源 Popover）
 * 灰色圆形上标 [n]，hover/Tab 聚焦弹出来源详情。
 * 契约（8 字段）：
 *   id, type, title, domain, url, retrievedAt, version, reviewedAt
 * ============================================================ */

import { Popover, Typography } from 'antd';

const TYPE_LABEL = {
  local_kb: '名创内部知识库',
  warehouse: '电商数据仓库',
  rule: '规则推导',
  external: '外部社媒/趋势',
};

/**
 * @param {object} evidence 证据对象（8 字段契约）
 * @param {string|number} index 角标序号（如 1、2、3）
 */
export default function EvidenceRef({ evidence, index }) {
  if (!evidence) return null;

  const content = (
    <div style={{ maxWidth: 320 }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{evidence.title || '证据来源'}</div>
      {evidence.domain && (
        <div style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>
          来源域：{evidence.domain}
          {evidence.type && TYPE_LABEL[evidence.type] ? `（${TYPE_LABEL[evidence.type]}）` : ''}
        </div>
      )}
      {evidence.retrievedAt && (
        <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
          抓取时间：{evidence.retrievedAt}
        </div>
      )}
      {evidence.version && (
        <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>数据版本：{evidence.version}</div>
      )}
      {evidence.reviewedAt && (
        <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
          人工复核：{evidence.reviewedAt}
        </div>
      )}
      {evidence.url && (
        <Typography.Link href={evidence.url} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>
          查看原文
        </Typography.Link>
      )}
    </div>
  );

  return (
    <Popover content={content} title={null} trigger="hover focus">
      <button
        type="button"
        className="evidence-ref"
        aria-label={`证据 ${index ?? ''}：${evidence.title || ''}`}
      >
        [{index ?? '·'}]
      </button>
    </Popover>
  );
}
