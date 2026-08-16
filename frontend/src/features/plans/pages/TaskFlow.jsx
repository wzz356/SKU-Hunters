/* ============================================================
 * SKU Hunters · TaskFlow（4 步流程编排，薄壳）
 * 状态编排收敛在 usePlanWorkspace；本页只做 step 切换 + 渲染。
 * 四个 step 均已迁到新架构：
 *   0 企划约束 → 1 洞察驾驶舱（features/insights/InsightCockpit）
 *   2 机会生成（features/opportunities/OpportunityCards）
 *   3 新品企划卡（features/plan-card/PlanCard）
 * 访问控制：按 plan.status 计算 maxAccessibleStep，越权跳步无效；
 * 归档（archived）后全流程只读，改稿沟通切换为「复盘追问」。
 * ============================================================ */

import { lazy, Suspense, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Steps, Card, Descriptions, Tag, Button, message, Spin } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';

// 洞察驾驶舱含 ECharts，属实测重模块，按已批准方案做流程内二级懒加载
const InsightCockpit = lazy(() => import('../../insights/InsightCockpit'));
import OpportunityCards from '../../opportunities/OpportunityCards';
import PlanCard from '../../plan-card/PlanCard';
import StateCard from '../../../shared/components/StateCard';
import SourceTag from '../../../shared/components/SourceTag';
import usePlanWorkspace from '../hooks/usePlanWorkspace';

const STEPS = ['企划约束', '洞察驾驶舱', '机会生成', '新品企划卡'];

const STATUS_STEP = { brief_locked: 0, insights_ready: 1, opportunities_ready: 2, plan_card_ready: 3, archived: 3 };

export default function TaskFlow() {
  const nav = useNavigate();
  const { id } = useParams();
  const ws = usePlanWorkspace(id);

  const [step, setStep] = useState(0);
  const [selectedOpp, setSelectedOpp] = useState(null);
  const [archiving, setArchiving] = useState(false);

  // 按落盘状态恢复 step（含已选方向 / 已生成企划卡）
  useEffect(() => {
    if (!ws.plan) return;
    if (ws.plan.selected_opportunity || ws.plan.plan_card) {
      setSelectedOpp(ws.plan.selected_opportunity || null);
      setStep(3);
      return;
    }
    const s = STATUS_STEP[ws.plan.status];
    if (s !== undefined) setStep(s);
  }, [ws.plan?.plan_id, ws.plan?.status, ws.plan?.selected_opportunity]); // eslint-disable-line react-hooks/exhaustive-deps

  const isArchived = ws.status === 'archived';
  // 最大可访问 step：未解锁步骤不可跳转（archived 只读，仍可回看 0-3）
  const maxAccessibleStep = STATUS_STEP[ws.status] ?? 0;
  const handleStepChange = (next) => { if (next <= maxAccessibleStep) setStep(next); };

  // ── 原子动作：确认约束 → 生成洞察 ──────────────────────
  const onGenerateInsights = async () => {
    try {
      await ws.actions.generateInsights();
      setStep(1);
    } catch (e) {
      message.error(`洞察生成失败：${e?.message || '请检查后端服务'}`);
    }
  };

  // ── 原子动作：洞察完成 → 生成机会 ──────────────────────
  const onGenerateOpportunities = async () => {
    try {
      await ws.actions.generateOpportunities();
      setStep(2);
    } catch (e) {
      message.error(`机会生成失败：${e?.message || '请检查后端服务'}`);
    }
  };

  // ── 原子动作：选定方向 → 生成企划卡 ────────────────────
  const onGeneratePlanCard = async () => {
    if (!selectedOpp) return;
    try {
      await ws.actions.generatePlanCard(selectedOpp);
      setStep(3);
    } catch (e) {
      message.error(`企划卡生成失败：${e?.message || '请检查后端服务'}`);
    }
  };

  // ── 归档 ──────────────────────────────────────────────
  const onArchive = async () => {
    setArchiving(true);
    try {
      await ws.actions.archive();
      message.success('已归档：企划案进入历史库，可随时复盘追问');
      nav('/');
    } catch (e) {
      message.error(`归档失败：${e?.message}`);
    } finally {
      setArchiving(false);
    }
  };

  // 初始加载
  if (ws.loading) {
    return <StateCard status="loading" />;
  }
  // 加载失败（无本地 mock 回退，只报错 + 重试）
  if (ws.error && !ws.plan) {
    return <StateCard status="error" onRetry={ws.actions.reload} />;
  }

  const brief = ws.brief;

  // 洞察块状态 → StateCard 五态
  const insightState = ws.insights
    ? 'success'
    : (ws.pendingAction === 'insights' ? 'loading' : (ws.error ? 'error' : 'idle'));

  const oppState = ws.opportunities
    ? 'success'
    : (ws.pendingAction === 'opportunities' ? 'loading' : (ws.error ? 'error' : 'idle'));

  const planCardState = ws.planCard
    ? 'success'
    : (ws.pendingAction === 'plan-card' ? 'loading' : (ws.error ? 'error' : 'idle'));

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
        <Button
          type="text"
          icon={<ArrowLeftOutlined />}
          aria-label="返回任务中心"
          onClick={() => nav('/')}
        />
        <h2 style={{ margin: 0 }}>{brief?.theme || '未命名企划'} · {brief?.category || ''}</h2>
        <SourceTag runSource={ws.source} />
      </div>

      <Steps
        current={step}
        onChange={handleStepChange}
        items={STEPS.map((s) => ({ title: s }))}
        style={{ marginBottom: 24, maxWidth: 720 }}
      />

      {step === 0 && brief && (
        <Card title="企划约束（由商品经理下达）" style={{ maxWidth: 720 }}>
          <Descriptions column={{ xs: 1, md: 2 }} size="small">
            <Descriptions.Item label="企划主题">{brief.theme}</Descriptions.Item>
            <Descriptions.Item label="品类">{brief.category}</Descriptions.Item>
            <Descriptions.Item label="目标市场">{brief.market}</Descriptions.Item>
            <Descriptions.Item label="目标人群">{brief.audience}</Descriptions.Item>
            <Descriptions.Item label="价格带">{brief.priceRange[0]}-{brief.priceRange[1]} 元</Descriptions.Item>
            <Descriptions.Item label="成本上限">≤ {brief.costLimit} 元</Descriptions.Item>
            <Descriptions.Item label="IP 策略">{(brief.ipStrategy || []).map((ip) => <Tag key={ip} color="red">{ip}</Tag>)}</Descriptions.Item>
            <Descriptions.Item label="上新窗口">{brief.launchWindow || '—'}</Descriptions.Item>
            <Descriptions.Item label="商业目标" span={2}>{(brief.goals || []).map((g) => <Tag key={g}>{g}</Tag>)}</Descriptions.Item>
          </Descriptions>
          <Button
            type="primary"
            style={{ marginTop: 16 }}
            disabled={isArchived}
            loading={ws.pendingAction === 'insights'}
            onClick={onGenerateInsights}
          >
            确认约束，开始洞察分析
          </Button>
        </Card>
      )}

      {step === 1 && (
        <div>
          <StateCard status={insightState} onRetry={onGenerateInsights} emptyText="暂无洞察数据">
            <Suspense
              fallback={
                <div style={{ textAlign: 'center', padding: 48 }} role="status" aria-busy="true">
                  <Spin />
                  <div style={{ marginTop: 8, color: 'var(--color-text-muted)' }}>正在加载洞察模块…</div>
                </div>
              }
            >
              {ws.insights && <InsightCockpit insights={ws.insights} category={brief?.category} />}
            </Suspense>
          </StateCard>
          <Button
            type="primary"
            style={{ marginTop: 16 }}
            disabled={!ws.insights || isArchived}
            loading={ws.pendingAction === 'opportunities'}
            onClick={onGenerateOpportunities}
          >
            洞察完成，生成机会方向
          </Button>
        </div>
      )}

      {step === 2 && (
        <div>
          <StateCard status={oppState} onRetry={onGenerateOpportunities} emptyText="暂无机会方向">
            {ws.opportunities && (
              <OpportunityCards
                opportunities={ws.opportunities}
                selected={selectedOpp}
                onSelect={isArchived ? () => {} : setSelectedOpp}
                processLog={ws.opportunitiesLog}
              />
            )}
          </StateCard>
          <Button
            type="primary"
            style={{ marginTop: 16 }}
            disabled={!selectedOpp || isArchived}
            loading={ws.pendingAction === 'plan-card'}
            onClick={onGeneratePlanCard}
          >
            进入企划生成（概念设计 + 商品策略）
          </Button>
        </div>
      )}

      {step === 3 && (
        <div>
          <PlanCard
            card={ws.planCard}
            proposal={ws.productProposal}
            opportunity={ws.opportunities?.find((o) => o.id === selectedOpp)}
            brief={brief}
            status={planCardState}
            isArchived={isArchived}
            onGenerate={ws.actions.generatePlanCard}
            onRevise={ws.actions.revise}
            onReview={ws.actions.review}
          />
          <div style={{ marginTop: 16, display: 'flex', gap: 8, alignItems: 'center' }}>
            {isArchived ? (
              <>
                <Tag>已归档 · 只读复盘，不可再改稿</Tag>
                <Button onClick={() => nav('/')}>返回任务中心</Button>
              </>
            ) : (
              <>
                <Button onClick={() => setStep(2)}>返回换方向</Button>
                <Button type="primary" loading={archiving} onClick={onArchive}>归档企划案</Button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
