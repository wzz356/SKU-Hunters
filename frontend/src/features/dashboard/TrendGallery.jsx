/* ============================================================
 * SKU Hunters · TrendGallery（流行元素板）
 * 使用 api/dashboard.js 的 getTrendGallery，接口失败不回退 fixture。
 * 配色 / 花纹 / 形态 / 表情化四个区块。
 * 色块 hex 非法时安全占位；色块同时显示色名、色值、来源（不依赖颜色）。
 * 响应式：375 单列，宽屏配色区 / 元素区响应式排列。
 * ============================================================ */

import { useEffect, useState } from 'react';
import { Card, Row, Col, Tag, Empty } from 'antd';
import { getTrendGallery } from '../../api/dashboard';
import StateCard from '../../shared/components/StateCard';
import PageHeader from '../plans/components/PageHeader';

// hex 校验：合法 #RGB / #RRGGBB 才使用，否则安全占位
function safeHex(hex) {
  return /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(hex || '') ? hex : 'var(--gray-200)';
}

export default function TrendGallery() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await getTrendGallery();
      setData(d || {});
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (loading) {
    return (
      <div>
        <PageHeader title="流行元素板 · Trend Gallery" />
        <StateCard status="loading" />
      </div>
    );
  }
  if (error) {
    return (
      <div>
        <PageHeader title="流行元素板 · Trend Gallery" />
        <StateCard status="error" onRetry={load} emptyText="Trend Gallery 加载失败" />
      </div>
    );
  }

  const colors = data.colors || [];
  const patterns = data.patterns || [];
  const shapes = data.shapes || [];
  const expressions = data.expressions || [];

  return (
    <div>
      <PageHeader
        title="流行元素板 · Trend Gallery"
        subtitle="跨品类采集（服装 / 食品 / 美妆 / 潮玩），企划生成时由创意设计模块调用融合"
      />

      {/* 配色趋势 */}
      <Card title="配色趋势" size="small" style={{ marginBottom: 16 }}>
        {colors.length === 0 ? (
          <Empty description="暂无配色数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Row gutter={[12, 12]}>
            {colors.map((c) => (
              <Col xs={12} sm={8} md={6} lg={4} key={c.name}>
                <div style={{ border: '1px solid var(--color-border)', borderRadius: 8, overflow: 'hidden', height: '100%' }}>
                  <div style={{ height: 48, background: safeHex(c.hex) }} aria-hidden="true" />
                  <div style={{ padding: 8 }}>
                    <div style={{ fontWeight: 600, fontSize: 13, wordBreak: 'break-word' }}>{c.name}</div>
                    <div style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>{c.hex}</div>
                    <div style={{ fontSize: 11, color: 'var(--color-text-muted)', wordBreak: 'break-word' }}>{c.source}</div>
                  </div>
                </div>
              </Col>
            ))}
          </Row>
        )}
      </Card>

      {/* 花纹 / 形态 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="花纹图案" size="small">
            {patterns.length === 0 ? (
              <Empty description="暂无花纹数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              patterns.map((p) => (
                <Card key={p.name} size="small" style={{ marginBottom: 8 }}>
                  <b style={{ wordBreak: 'break-word' }}>{p.name}</b>
                  <Tag style={{ marginLeft: 8 }}>{p.source}</Tag>
                  <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 4, wordBreak: 'break-word' }}>{p.note}</div>
                </Card>
              ))
            )}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="形态结构" size="small">
            {shapes.length === 0 ? (
              <Empty description="暂无形态数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              shapes.map((s) => (
                <Card key={s.name} size="small" style={{ marginBottom: 8 }}>
                  <b style={{ wordBreak: 'break-word' }}>{s.name}</b>
                  <Tag style={{ marginLeft: 8 }}>{s.source}</Tag>
                  <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 4, wordBreak: 'break-word' }}>{s.note}</div>
                </Card>
              ))
            )}
          </Card>
        </Col>
      </Row>

      {/* 表情化趋势 */}
      <Card title="表情化趋势（IP 情绪语言）" size="small" style={{ marginTop: 16 }}>
        {expressions.length === 0 ? (
          <Empty description="暂无表情化数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Row gutter={[16, 16]}>
            {expressions.map((e) => (
              <Col xs={24} sm={12} lg={8} key={e.name}>
                <Card size="small" style={{ textAlign: 'center', height: '100%' }}>
                  <div style={{ fontSize: 36, letterSpacing: 2 }}>{e.emoji}</div>
                  <b style={{ wordBreak: 'break-word' }}>{e.name}</b>
                  <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', wordBreak: 'break-word' }}>{e.note}</div>
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Card>

      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 16 }}>
        数据来源：跨品类社媒采集样本
      </p>
    </div>
  );
}
