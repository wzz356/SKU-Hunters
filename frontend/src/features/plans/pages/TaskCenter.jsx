/* ============================================================
 * SKU Hunters · TaskCenter（任务中心）
 * 使用 api/plans.js 的 listPlans，明确区分 loading / error / empty / success。
 * 真实接口失败不显示 demo 任务（demo 任务仅在后端真实返回时以 SourceTag 标注）。
 * 按 status 分「进行中 / 已归档」两组；唯一主 CTA 为「新建企划」。
 * 响应式：375 单列 / 768 两列 / 1440 三列。
 * ============================================================ */

import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Row, Col, Button, Divider, Empty, message } from 'antd';
import { PlusOutlined, ClockCircleOutlined, CheckCircleOutlined } from '@ant-design/icons';
import { listPlans, deletePlan } from '../../../api/plans';
import TaskCard from '../components/TaskCard';
import PageHeader from '../components/PageHeader';
import StateCard from '../../../shared/components/StateCard';

export default function TaskCenter() {
  const nav = useNavigate();
  const [plans, setPlans] = useState(null); // null = 尚未成功加载
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listPlans();
      setPlans(Array.isArray(data?.plans) ? data.plans : []);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const active = (plans || []).filter((t) => t.status !== 'archived');
  const archived = (plans || []).filter((t) => t.status === 'archived');

  // 删除任务：真实调后端 DELETE，成功后刷新列表（不做本地假删）
  const onDelete = async (task) => {
    try {
      await deletePlan(task.plan_id);
      message.success(`已删除「${task.theme || '未命名企划'}」`);
      load();
    } catch (e) {
      message.error(`删除失败：${e?.message || '请检查后端服务'}`);
    }
  };

  const newPlanCta = (
    <Button type="primary" icon={<PlusOutlined />} onClick={() => nav('/new')}>
      新建企划
    </Button>
  );

  // 加载中
  if (loading) {
    return (
      <div>
        <PageHeader title="新品企划任务" subtitle="企划约束由商品经理下达，AI 在约束内做有依据的创意" extra={newPlanCta} />
        <StateCard status="loading" />
      </div>
    );
  }

  // 加载失败：显式报错 + 重试（不显示 demo 任务）
  if (error) {
    return (
      <div>
        <PageHeader title="新品企划任务" extra={newPlanCta} />
        <StateCard status="error" onRetry={load} emptyText="任务列表加载失败" />
      </div>
    );
  }

  // 空列表：明确空态 + 保留新建 CTA
  if (!plans || plans.length === 0) {
    return (
      <div>
        <PageHeader title="新品企划任务" subtitle="企划约束由商品经理下达，AI 在约束内做有依据的创意" extra={newPlanCta} />
        <Empty description="暂无企划任务，点击右上角「新建企划」开始" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ margin: '48px 0' }} />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="新品企划任务"
        subtitle={`进行中 ${active.length} · 已归档 ${archived.length}`}
        extra={newPlanCta}
      />

      {/* 进行中 */}
      <Divider orientation="left" style={{ fontSize: 14, margin: '8px 0 16px' }}>
        <ClockCircleOutlined style={{ marginRight: 6 }} />
        进行中
      </Divider>
      {active.length === 0 ? (
        <Empty description="暂无进行中的企划任务" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ margin: '24px 0' }} />
      ) : (
        <Row gutter={[16, 16]}>
          {active.map((t) => (
            <Col xs={24} md={12} lg={8} key={t.plan_id}>
              <TaskCard task={t} onClick={() => nav(`/tasks/${t.plan_id}`)} onDelete={onDelete} />
            </Col>
          ))}
        </Row>
      )}

      {/* 已归档 */}
      {archived.length > 0 && (
        <>
          <Divider orientation="left" style={{ fontSize: 14, margin: '24px 0 16px' }}>
            <CheckCircleOutlined style={{ marginRight: 6 }} />
            已归档
          </Divider>
          <Row gutter={[16, 16]}>
            {archived.map((t) => (
              <Col xs={24} md={12} lg={8} key={t.plan_id}>
                <TaskCard task={t} onClick={() => nav(`/tasks/${t.plan_id}`)} onDelete={onDelete} />
              </Col>
            ))}
          </Row>
        </>
      )}
    </div>
  );
}
