/* ============================================================
 * SKU Hunters · NotFound（404 页）
 * 深层路由直接访问 / SPA fallback 时的兜底页面。
 * ============================================================ */

import { Button, Result } from 'antd';
import { useNavigate } from 'react-router-dom';

export default function NotFound() {
  const navigate = useNavigate();
  return (
    <Result
      status="404"
      title="页面不存在"
      subTitle="你访问的页面不存在或已被移动。"
      extra={
        <Button type="primary" onClick={() => navigate('/')}>
          返回任务中心
        </Button>
      }
    />
  );
}
