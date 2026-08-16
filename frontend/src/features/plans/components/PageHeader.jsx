/* ============================================================
 * SKU Hunters · PageHeader（页面头部）
 * 标题 + 可选副标题 + 右侧操作区（主 CTA）。
 * 可选 onBack：标题左侧渲染「← 返回」按钮（任务详情 / 新建等子页用）。
 * 窄屏（375）下操作区自动换行，避免挤压标题。
 * ============================================================ */

import { Button } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';

export default function PageHeader({ title, subtitle, extra, onBack }) {
  return (
    <div
      style={{
        marginBottom: 20,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        gap: 16,
        flexWrap: 'wrap',
      }}
    >
      <div style={{ minWidth: 0, display: 'flex', alignItems: 'flex-start', gap: 8 }}>
        {onBack ? (
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            aria-label="返回上一页"
            onClick={onBack}
            style={{ marginTop: 2 }}
          />
        ) : null}
        <div style={{ minWidth: 0 }}>
          <h2 style={{ margin: 0, wordBreak: 'break-word' }}>{title}</h2>
          {subtitle ? (
            <p style={{ margin: '4px 0 0', color: 'var(--color-text-secondary)', fontSize: 13 }}>{subtitle}</p>
          ) : null}
        </div>
      </div>
      {extra ? <div style={{ flexShrink: 0 }}>{extra}</div> : null}
    </div>
  );
}
