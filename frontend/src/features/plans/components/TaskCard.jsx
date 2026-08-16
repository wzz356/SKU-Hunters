/* ============================================================
 * SKU Hunters · TaskCard（任务卡片，纯展示/事件组件）
 * 数据由 TaskCenter 拉取后传入，不 import fixtures、不发请求。
 * 整块可点击（含键盘 Enter/Space）；右上角删除按钮 stopPropagation，不触发整卡跳转。
 * 状态用「文字标签」表达，不依赖左侧颜色条。
 * ============================================================ */

import { Button, Card, Popconfirm, Tag, Typography } from 'antd';
import { DeleteOutlined, LockOutlined } from '@ant-design/icons';

const { Paragraph } = Typography;

// 后端落盘状态 → 阶段展示（文字 + 颜色，颜色仅作辅助，状态含义由文字承载）
const STATUS_META = {
  brief_locked: { label: '企划约束', color: 'blue' },
  insights_ready: { label: '洞察驾驶舱', color: 'blue' },
  opportunities_ready: { label: '机会生成', color: 'blue' },
  plan_card_ready: { label: '新品企划卡', color: 'blue' },
  archived: { label: '已归档', color: 'default' },
};

/**
 * @param {object} task     任务摘要（plan_id / theme / category / audience / status / created_at / mode）
 * @param {Function} onClick 整卡点击
 * @param {Function} onDelete 删除回调（可选；Popconfirm 二次确认后触发，不冒泡整卡跳转）
 */
export default function TaskCard({ task, onClick, onDelete }) {
  const meta = STATUS_META[task.status] || STATUS_META.brief_locked;
  const isArchived = task.status === 'archived';
  const created = (task.created_at || '').slice(0, 10);

  return (
    <Card
      hoverable
      size="small"
      role="button"
      tabIndex={0}
      aria-label={`查看企划：${task.theme || '未命名企划'}`}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick();
        }
      }}
      style={{ cursor: 'pointer', height: '100%' }}
    >
      {/* 阶段 + 归档只读标记（文字表达状态，不依赖颜色）+ 删除 */}
      <div style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 4 }}>
        <Tag color={meta.color}>{meta.label}</Tag>
        {isArchived ? (
          <Tag icon={<LockOutlined />}>只读</Tag>
        ) : null}
        {onDelete ? (
          <Popconfirm
            title="删除该企划任务？"
            description="删除后不可恢复"
            okText="删除"
            okButtonProps={{ danger: true }}
            cancelText="取消"
            onConfirm={(e) => {
              e?.stopPropagation?.();
              onDelete(task);
            }}
            onCancel={(e) => e?.stopPropagation?.()}
          >
            <Button
              type="text"
              size="small"
              danger
              icon={<DeleteOutlined />}
              aria-label={`删除企划：${task.theme || '未命名企划'}`}
              style={{ marginLeft: 'auto' }}
              onClick={(e) => e.stopPropagation()}
            />
          </Popconfirm>
        ) : null}
      </div>

      {/* 主题：超长/英文自动换行，超两行截断并悬停显示完整标题 */}
      <Paragraph
        ellipsis={{ rows: 2, tooltip: task.theme || '未命名企划' }}
        style={{ fontWeight: 600, marginBottom: 8, minHeight: 40, wordBreak: 'break-word' }}
      >
        {task.theme || '未命名企划'}
      </Paragraph>

      {/* 品类 + 目标人群 */}
      <div style={{ fontSize: 13, color: 'var(--color-text-secondary)', marginBottom: 8, wordBreak: 'break-word' }}>
        {task.category || '未分类'}
        {task.audience ? ` · ${task.audience}` : ''}
      </div>

      {/* 创建时间（数据来源在任务详情页按洞察 dataSource 展示，列表摘要不含该信息） */}
      <div
        style={{
          fontSize: 12,
          color: 'var(--color-text-muted)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 8,
          flexWrap: 'wrap',
        }}
      >
        <span>{created || '—'}</span>
      </div>
    </Card>
  );
}
