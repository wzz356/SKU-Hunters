/* ============================================================
 * SKU Hunters · AppShell（响应式应用外壳）
 * 桌面端（≥768px）：左侧固定侧栏（宽度 200，分组导航）。
 * 移动端（<768px）：侧栏完全隐藏，顶部汉堡按钮打开 Drawer。
 * Content 暖灰背景 + 内容 max-width 1200 居中，用 Outlet 渲染子路由。
 * ============================================================ */

import { useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Layout, Menu, Drawer, Button, Grid } from 'antd';
import {
  HomeOutlined,
  PlusOutlined,
  BarChartOutlined,
  ShopOutlined,
  BgColorsOutlined,
  MenuOutlined,
} from '@ant-design/icons';

const { Sider, Header, Content } = Layout;

const MENU_ITEMS = [
  {
    type: 'group',
    label: '企划流程',
    children: [
      { key: '/', icon: <HomeOutlined />, label: '任务中心' },
      { key: '/new', icon: <PlusOutlined />, label: '新建企划' },
    ],
  },
  {
    type: 'group',
    label: '洞察数据',
    children: [
      { key: '/dashboard', icon: <BarChartOutlined />, label: '数据看板' },
      { key: '/insight-base', icon: <ShopOutlined />, label: '名创内部' },
      { key: '/trend-gallery', icon: <BgColorsOutlined />, label: '流行元素板' },
    ],
  },
];

const BRAND = 'SKU Hunters';

function selectedKey(pathname) {
  if (pathname.startsWith('/tasks/')) return '/'; // 任务详情页选中「任务中心」
  if (pathname.startsWith('/new')) return '/new';
  return '/' + (pathname.split('/')[1] || '');
}

export default function AppShell() {
  const screens = Grid.useBreakpoint();
  const isDesktop = !!screens.md; // ≥768px
  const [drawerOpen, setDrawerOpen] = useState(false);
  const { pathname } = useLocation();
  const nav = useNavigate();

  const handleMenuClick = ({ key }) => {
    nav(key);
    setDrawerOpen(false);
  };

  const menu = (
    <Menu
      mode="inline"
      selectedKeys={[selectedKey(pathname)]}
      items={MENU_ITEMS}
      onClick={handleMenuClick}
    />
  );

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {/* 桌面侧栏（≥768px） */}
      {isDesktop && (
        <Sider width={200} style={{ background: 'var(--color-surface)' }}>
          <div
            style={{
              height: 56,
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '0 16px',
              borderBottom: '1px solid var(--color-border)',
              fontWeight: 700,
              fontSize: 15,
              color: 'var(--color-action-primary)',
            }}
          >
            <ShopOutlined style={{ fontSize: 18 }} />
            <span>SKU Hunters</span>
          </div>
          {menu}
        </Sider>
      )}

      <Layout>
        {/* 移动端顶栏 + 汉堡按钮（<768px） */}
        {!isDesktop && (
          <Header
            style={{
              background: 'var(--color-surface)',
              padding: '0 16px',
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              borderBottom: '1px solid var(--color-border)',
              position: 'sticky',
              top: 0,
              zIndex: 10,
            }}
          >
            <Button
              type="text"
              icon={<MenuOutlined />}
              aria-label="打开导航菜单"
              onClick={() => setDrawerOpen(true)}
            />
            <ShopOutlined style={{ fontSize: 16, color: 'var(--color-action-primary)' }} />
            <span style={{ fontWeight: 700, color: 'var(--color-action-primary)' }}>SKU Hunters</span>
          </Header>
        )}

        <Content style={{ padding: isDesktop ? 24 : 16, background: 'var(--color-bg)' }}>
          <div style={{ maxWidth: 1200, margin: '0 auto' }}>
            <Outlet />
          </div>
        </Content>
      </Layout>

      {/* 移动端抽屉导航 */}
      {!isDesktop && (
        <Drawer
          title={BRAND}
          placement="left"
          width={260}
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          styles={{ body: { padding: 0 } }}
        >
          {menu}
        </Drawer>
      )}
    </Layout>
  );
}
