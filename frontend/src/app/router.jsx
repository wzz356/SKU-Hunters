/* ============================================================
 * SKU Hunters · router（data router 路由表 + 路由级分包）
 * 所有页面走 React.lazy 分包，每个路由有语义明确的 Suspense fallback。
 * ECharts 只随用到图表的 chunk（DataBoard / InsightCockpit）加载，
 * 不进入入口 chunk。
 * ============================================================ */

import { lazy, Suspense } from 'react';
import { createBrowserRouter } from 'react-router-dom';
import { Spin } from 'antd';
import AppShell from './AppShell';

const TaskCenter = lazy(() => import('../features/plans/pages/TaskCenter'));
const NewPlan = lazy(() => import('../features/plans/pages/NewPlan'));
const TaskFlow = lazy(() => import('../features/plans/pages/TaskFlow'));
const DataBoard = lazy(() => import('../features/dashboard/DataBoard'));
const InsightBase = lazy(() => import('../features/dashboard/InsightBase'));
const TrendGallery = lazy(() => import('../features/dashboard/TrendGallery'));
const NotFound = lazy(() => import('../shared/components/NotFound'));

function PageLoading() {
  return (
    <div style={{ textAlign: 'center', padding: 48 }} role="status" aria-busy="true">
      <Spin />
      <div style={{ marginTop: 8, color: 'var(--color-text-muted)' }}>正在加载页面…</div>
    </div>
  );
}

// 每个 lazy 页面包一层语义 Suspense
function lazyElement(Component) {
  return (
    <Suspense fallback={<PageLoading />}>
      <Component />
    </Suspense>
  );
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: lazyElement(TaskCenter) },
      { path: 'new', element: lazyElement(NewPlan) },
      { path: 'tasks/:id', element: lazyElement(TaskFlow) },
      { path: 'dashboard', element: lazyElement(DataBoard) },
      { path: 'insight-base', element: lazyElement(InsightBase) },
      { path: 'trend-gallery', element: lazyElement(TrendGallery) },
      { path: '*', element: lazyElement(NotFound) },
    ],
  },
]);
