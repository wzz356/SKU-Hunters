/* ============================================================
 * SKU Hunters · usePlanWorkspace（状态编排核心 hook）
 * 集中管理 TaskFlow 的全部状态与副作用，页面组件薄壳化。
 *
 * 状态所有权：单一 hook 持有，页面组件只读。
 * 红线：展示组件只读 props + 触发事件回调，不 import fixtures、不发请求。
 * 数据纪律：全部数据来自后端真实链路（采集数据 / LLM 生成），
 *          失败只报错，无任何本地 mock 回退。
 * ============================================================ */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  archivePlan,
  generateInsights,
  generateOpportunities,
  generatePlanCard,
  getPlan,
  reviewPlan,
  revisePlan,
} from '../../../api/plans';
import { getInsights, getOpportunities } from '../../../api/insights';
import { toCamelBrief } from '../../../shared/utils/normalizeBrief';

// 后端落盘状态 → 流程 step 索引
const STATUS_STEP = { brief_locked: 0, insights_ready: 1, opportunities_ready: 2, plan_card_ready: 3 };

export default function usePlanWorkspace(planId) {
  // ── 数据状态 ───────────────────────────────────────────
  const [plan, setPlan] = useState(null);
  const [insights, setInsights] = useState(null);
  const [opportunities, setOpportunities] = useState(null);
  const [opportunitiesLog, setOpportunitiesLog] = useState([]);
  const [reviseLogs, setReviseLogs] = useState([]);
  const [reviewLogs, setReviewLogs] = useState([]);

  // ── UI 状态 ───────────────────────────────────────────
  const [loading, setLoading] = useState(true);       // 初始加载中
  const [pendingAction, setPendingAction] = useState(null); // 当前原子动作名
  const [error, setError] = useState(null);           // 最近一次结构化错误

  // 数据来源标识：取自后端洞察的 dataSource（crawled 真实采集 / llm LLM 生成），洞察未生成前不展示
  const source = insights?.dataSource || null;
  const status = plan?.status || 'brief_locked';
  const selectedOpportunity = plan?.selected_opportunity || null;
  const planCard = plan?.plan_card || null;
  const productProposal = plan?.product_proposal || null;
  const brief = toCamelBrief(plan?.brief || null);

  // ── 内部：加载任务详情 + 按落盘状态恢复已生成数据 ──────
  const loadPlan = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const p = await getPlan(planId);
      setPlan(p);
      // 按落盘状态恢复已生成产物（只读接口）
      if (p?.status === 'insights_ready' || p?.status === 'opportunities_ready' || p?.status === 'plan_card_ready' || p?.status === 'archived') {
        try { setInsights(await getInsights(planId)); } catch { /* 只读恢复失败不阻断 */ }
      }
      if (p?.status === 'opportunities_ready' || p?.status === 'plan_card_ready' || p?.status === 'archived') {
        try {
          const data = await getOpportunities(planId);
          setOpportunities(data.opportunities || []);
          setOpportunitiesLog(data.processLog || []);
        } catch { /* 只读恢复失败不阻断 */ }
      }
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, [planId]);

  useEffect(() => { loadPlan(); }, [loadPlan]);

  // ── 原子动作：生成洞察 ────────────────────────────────
  const runGenerateInsights = useCallback(async () => {
    setPendingAction('insights');
    setError(null);
    try {
      const data = await generateInsights(planId);
      setInsights(data.insights);
      setPlan((p) => (p ? { ...p, status: data.status } : p));
      return data.insights;
    } catch (e) {
      setError(e);
      throw e;
    } finally {
      setPendingAction(null);
    }
  }, [planId]);

  // ── 原子动作：生成机会 ────────────────────────────────
  const runGenerateOpportunities = useCallback(async () => {
    setPendingAction('opportunities');
    setError(null);
    try {
      const data = await generateOpportunities(planId);
      setOpportunities(data.opportunities || []);
      setOpportunitiesLog(data.processLog || []);
      setPlan((p) => (p ? { ...p, status: data.status } : p));
      return data.opportunities;
    } catch (e) {
      setError(e);
      throw e;
    } finally {
      setPendingAction(null);
    }
  }, [planId]);

  // ── 原子动作：生成企划卡 ──────────────────────────────
  const runGeneratePlanCard = useCallback(async (opportunityId) => {
    setPendingAction('plan-card');
    setError(null);
    try {
      const data = await generatePlanCard(opportunityId, planId);
      setPlan((p) => (p ? { ...p, status: data.status, plan_card: data.plan_card, product_proposal: data.product_proposal, selected_opportunity: opportunityId } : p));
      return data.plan_card;
    } catch (e) {
      setError(e);
      throw e;
    } finally {
      setPendingAction(null);
    }
  }, [planId]);

  // ── 改稿沟通 ──────────────────────────────────────────
  const runRevise = useCallback(async (message) => {
    setPendingAction('revise');
    setError(null);
    try {
      const data = await revisePlan(message, planId);
      setReviseLogs((logs) => [...logs, { message, reply: data.reply, timestamp: data.timestamp }]);
      return data;
    } catch (e) {
      setError(e);
      throw e;
    } finally {
      setPendingAction(null);
    }
  }, [planId]);

  // ── 复盘追问（只读，归档后）────────────────────────
  const runReview = useCallback(async (question) => {
    setPendingAction('review');
    setError(null);
    try {
      const data = await reviewPlan(question, planId);
      setReviewLogs((logs) => [...logs, { question, answer: data.answer }]);
      return data;
    } catch (e) {
      setError(e);
      throw e;
    } finally {
      setPendingAction(null);
    }
  }, [planId]);

  // ── 归档 ──────────────────────────────────────────────
  const runArchive = useCallback(async () => {
    setPendingAction('archive');
    setError(null);
    try {
      const data = await archivePlan(planId);
      setPlan((p) => (p ? { ...p, status: data.status, archived_at: data.archived_at } : p));
      return data;
    } catch (e) {
      setError(e);
      throw e;
    } finally {
      setPendingAction(null);
    }
  }, [planId]);

  const actions = useMemo(() => ({
    generateInsights: runGenerateInsights,
    generateOpportunities: runGenerateOpportunities,
    generatePlanCard: runGeneratePlanCard,
    revise: runRevise,
    review: runReview,
    archive: runArchive,
    reload: loadPlan,
  }), [runGenerateInsights, runGenerateOpportunities, runGeneratePlanCard, runRevise, runReview, runArchive, loadPlan]);

  return {
    plan,
    insights,
    opportunities,
    opportunitiesLog,
    reviseLogs,
    reviewLogs,
    status,
    source,
    brief,
    selectedOpportunity,
    planCard,
    productProposal,
    // UI
    loading,
    pendingAction,
    error,
    actions,
  };
}
