/* ============================================================
 * SKU Hunters · StateCard（统一状态封装）
 * 单一 status 枚举（非多布尔），避免 loading/error/empty 冲突态。
 *   status: 'idle' | 'loading' | 'success' | 'empty' | 'error'
 * ============================================================ */

import { Alert, Button, Empty, Spin } from 'antd';

/**
 * @param {string} status    五态之一
 * @param {Function} onRetry error 态重试回调
 * @param {string} emptyText empty 态提示文案
 * @param {ReactNode} children success 态渲染的数据内容
 */
export default function StateCard({ status, onRetry, emptyText = '暂无数据', children }) {
  switch (status) {
    case 'loading':
      return (
        <div style={{ textAlign: 'center', padding: 48 }} role="status" aria-busy="true">
          <Spin />
        </div>
      );
    case 'error':
      return (
        <Alert
          type="error"
          role="alert"
          showIcon
          message="加载失败"
          action={
            onRetry ? (
              <Button size="small" onClick={onRetry}>
                重试
              </Button>
            ) : undefined
          }
        />
      );
    case 'empty':
      return <Empty description={emptyText} image={Empty.PRESENTED_IMAGE_SIMPLE} />;
    case 'success':
      return children;
    case 'idle':
    default:
      return <div style={{ padding: 48, textAlign: 'center', color: 'var(--color-text-muted)' }}>—</div>;
  }
}
