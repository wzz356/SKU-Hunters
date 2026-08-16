/* ============================================================
 * SKU Hunters · TrendGallery（流行元素板）
 * 使用 api/dashboard.js 的 getTrendGallery，接口失败不回退 fixture。
 * 配色 / 花纹 / 形态 / 表情化四个区块。
 *
 * 2026-08-16 攻坚会 P1：文字占比过高、色块占比过小 →
 *   配色改大色块展示；花纹/形态为每个元素配矢量示意图（SVG motif，
 *   按元素名映射，未知名称用通用纹样兜底，图上标注"矢量示意"不冒充实拍）。
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

// ── 矢量示意图（按元素名映射；非实拍图，图上标注"矢量示意"）────────
// 统一视觉语言：浅底 + 品牌红系线条，大块面优先
const MOTIF_BG = '#FDF6F4';
const MOTIF_INK = '#D4380D';

const MOTIFS = {
  蝴蝶: (
    <g fill={MOTIF_INK} opacity="0.85">
      <ellipse cx="38" cy="30" rx="16" ry="20" transform="rotate(-18 38 30)" />
      <ellipse cx="82" cy="30" rx="16" ry="20" transform="rotate(18 82 30)" />
      <ellipse cx="42" cy="62" rx="11" ry="14" transform="rotate(-24 42 62)" />
      <ellipse cx="78" cy="62" rx="11" ry="14" transform="rotate(24 78 62)" />
      <rect x="57" y="18" width="6" height="56" rx="3" />
    </g>
  ),
  豹纹: (
    <g fill={MOTIF_INK} opacity="0.85">
      <circle cx="28" cy="26" r="10" /><circle cx="64" cy="18" r="7" />
      <circle cx="94" cy="32" r="11" /><circle cx="44" cy="56" r="8" />
      <circle cx="78" cy="62" r="10" /><circle cx="20" cy="66" r="6" />
      <circle cx="104" cy="64" r="6" />
    </g>
  ),
  水波纹: (
    <g fill="none" stroke={MOTIF_INK} strokeWidth="5" strokeLinecap="round" opacity="0.85">
      <path d="M10 26 q12 -12 24 0 t24 0 t24 0 t24 0" />
      <path d="M10 46 q12 -12 24 0 t24 0 t24 0 t24 0" />
      <path d="M10 66 q12 -12 24 0 t24 0 t24 0 t24 0" />
    </g>
  ),
  植物插画: (
    <g fill="none" stroke={MOTIF_INK} strokeWidth="5" strokeLinecap="round" opacity="0.85">
      <path d="M60 78 V30" />
      <path d="M60 52 q-22 -4 -28 -24 q22 2 28 24" fill={MOTIF_INK} stroke="none" />
      <path d="M60 40 q22 -4 28 -24 q-22 2 -28 24" fill={MOTIF_INK} stroke="none" />
      <path d="M60 70 q-18 -2 -24 -18 q18 0 24 18" fill={MOTIF_INK} stroke="none" opacity="0.6" />
    </g>
  ),
  圆润鹅卵石: (
    <g fill={MOTIF_INK} opacity="0.85">
      <ellipse cx="60" cy="52" rx="42" ry="28" />
      <ellipse cx="44" cy="40" rx="12" ry="7" fill="#fff" opacity="0.35" />
    </g>
  ),
  '透明 / 果冻质感': (
    <g opacity="0.9">
      <rect x="24" y="18" width="72" height="60" rx="18" fill={MOTIF_INK} opacity="0.28" />
      <rect x="34" y="26" width="30" height="14" rx="7" fill="#fff" opacity="0.8" />
      <rect x="24" y="18" width="72" height="60" rx="18" fill="none" stroke={MOTIF_INK} strokeWidth="3" opacity="0.5" />
    </g>
  ),
  模块化组件: (
    <g fill={MOTIF_INK} opacity="0.85">
      <rect x="26" y="22" width="22" height="22" rx="5" />
      <rect x="52" y="22" width="22" height="22" rx="5" opacity="0.65" />
      <rect x="26" y="48" width="22" height="22" rx="5" opacity="0.65" />
      <rect x="78" y="48" width="22" height="22" rx="5" transform="rotate(12 89 59)" />
    </g>
  ),
  磁吸连接: (
    <g opacity="0.9">
      <circle cx="42" cy="46" r="18" fill={MOTIF_INK} opacity="0.85" />
      <circle cx="78" cy="46" r="18" fill={MOTIF_INK} opacity="0.55" />
      <g fill="none" stroke={MOTIF_INK} strokeWidth="3" strokeLinecap="round" opacity="0.6">
        <path d="M14 34 q6 6 0 12" /><path d="M106 34 q-6 6 0 12" />
      </g>
    </g>
  ),
};

// 通用兜底纹样（未知名称）：三个柔和圆
const FALLBACK_MOTIF = (
  <g fill={MOTIF_INK} opacity="0.85">
    <circle cx="38" cy="46" r="16" />
    <circle cx="66" cy="34" r="12" opacity="0.6" />
    <circle cx="84" cy="56" r="14" opacity="0.35" />
  </g>
);

/** 元素矢量示意块：按名称取 motif，无匹配用兜底；标注"矢量示意" */
function MotifBlock({ name }) {
  return (
    <div style={{ position: 'relative', background: MOTIF_BG, height: 96 }} aria-hidden="true">
      <svg viewBox="0 0 120 90" style={{ width: '100%', height: '100%' }}>
        {MOTIFS[name] || FALLBACK_MOTIF}
      </svg>
      <span style={{
        position: 'absolute', right: 6, bottom: 4, fontSize: 10,
        color: 'var(--color-text-muted)', letterSpacing: 1,
      }}>
        矢量示意
      </span>
    </div>
  );
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

  // 花纹 / 形态共用渲染：矢量示意大块 + 名称 + 来源 + 注解
  const renderElementCard = (item) => (
    <Col xs={12} sm={8} md={6} key={item.name}>
      <div style={{ border: '1px solid var(--color-border)', borderRadius: 8, overflow: 'hidden', height: '100%' }}>
        <MotifBlock name={item.name} />
        <div style={{ padding: 8 }}>
          <b style={{ fontSize: 13, wordBreak: 'break-word' }}>{item.name}</b>
          <Tag style={{ marginLeft: 6 }}>{item.source}</Tag>
          <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 4, wordBreak: 'break-word' }}>{item.note}</div>
        </div>
      </div>
    </Col>
  );

  return (
    <div>
      <PageHeader
        title="流行元素板 · Trend Gallery"
        subtitle="跨品类采集（服装 / 食品 / 美妆 / 潮玩），企划生成时由创意设计模块调用融合"
      />

      {/* 配色趋势：大色块展示（攻坚会 P1） */}
      <Card title="配色趋势" size="small" style={{ marginBottom: 16 }}>
        {colors.length === 0 ? (
          <Empty description="暂无配色数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Row gutter={[12, 12]}>
            {colors.map((c) => (
              <Col xs={12} sm={8} md={6} lg={4} key={c.name}>
                <div style={{ border: '1px solid var(--color-border)', borderRadius: 8, overflow: 'hidden', height: '100%' }}>
                  <div style={{ height: 110, background: safeHex(c.hex) }} aria-label={c.name} />
                  <div style={{ padding: 8 }}>
                    <div style={{ fontWeight: 600, fontSize: 14, wordBreak: 'break-word' }}>{c.name}</div>
                    <div style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>{c.hex}</div>
                    <div style={{ fontSize: 11, color: 'var(--color-text-muted)', wordBreak: 'break-word' }}>{c.source}</div>
                  </div>
                </div>
              </Col>
            ))}
          </Row>
        )}
      </Card>

      {/* 花纹 / 形态：矢量示意 + 文字注解 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="花纹图案" size="small">
            {patterns.length === 0 ? (
              <Empty description="暂无花纹数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <Row gutter={[12, 12]}>{patterns.map(renderElementCard)}</Row>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="形态结构" size="small">
            {shapes.length === 0 ? (
              <Empty description="暂无形态数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <Row gutter={[12, 12]}>{shapes.map(renderElementCard)}</Row>
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
                  <div style={{ fontSize: 56, letterSpacing: 2, lineHeight: 1.4 }}>{e.emoji}</div>
                  <b style={{ wordBreak: 'break-word' }}>{e.name}</b>
                  <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', wordBreak: 'break-word' }}>{e.note}</div>
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Card>

      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 16 }}>
        数据来源：跨品类社媒采集样本；花纹/形态配图为矢量示意（元素视觉语言，非产品实拍）
      </p>
    </div>
  );
}
