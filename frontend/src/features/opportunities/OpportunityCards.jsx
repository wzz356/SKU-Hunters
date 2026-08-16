import { useState } from 'react';
import { Card, Row, Col, Tag, Popover, Button } from 'antd';
import ProcessLog from '../../shared/components/ProcessLog';

// 机会生成：3 张方向卡，每张挂依据链（可回溯洞察），人选定 1 张进入企划生成
// props 驱动：数据由 TaskFlow 拉取后传入，不再 import 全局 mock
export default function OpportunityCards({ opportunities = [], selected, onSelect, processLog = [] }) {
  const [logDone, setLogDone] = useState(false);
  return (
    <div>
      {processLog.length > 0 && (
        <Card size="small" title="机会生成 · 思考过程" style={{ marginBottom: 16, background: 'var(--color-surface-alt)', border: '1px solid var(--color-border-strong)' }}>
          <ProcessLog lines={processLog} onDone={() => setLogDone(true)} />
        </Card>
      )}
      <div style={{ opacity: processLog.length === 0 || logDone ? 1 : 0, transition: 'opacity 0.5s', pointerEvents: processLog.length === 0 || logDone ? 'auto' : 'none' }}>
        <Card size="small" style={{ marginBottom: 16, background: 'var(--color-surface-alt)', border: '1px solid var(--color-border-strong)' }}>
          <b style={{ color: 'var(--color-action-primary)' }}>机会生成：</b>
          消费洞察阶段的市场机会池（同一数据源），完成「市场机会 → 商品机会」补全：目标用户 / 核心场景 / 产品策略 / 价格带——每个方向的依据可点击回溯。
        </Card>
        <Row gutter={16}>
          {opportunities.map(o => (
            <Col xs={24} sm={24} md={8} key={o.id}>
              <Card
                className={`opp-card ${selected === o.id ? 'selected' : ''}`}
                tabIndex={0}
                role="button"
                aria-pressed={selected === o.id}
                onClick={() => onSelect(o.id)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(o.id); } }}
                title={<span style={{ fontSize: 16 }}>{o.emoji} {o.title}</span>}
                extra={
                  <span>
                    {o.confidence > 0 && <Tag color="red" style={{ marginRight: 4 }}>置信度 {o.confidence}%</Tag>}
                    <Tag color="purple">{o.direction}</Tag>
                  </span>
                }
              >
                {/* ── 第一层：3 秒看懂 ── */}
                <p style={{ fontSize: 13, minHeight: 36 }}>{o.pitch}</p>
                <div style={{ fontSize: 12, marginBottom: 6 }}>
                  {(o.targetUser || o.scenario) && <span>👤 {o.targetUser}{o.scenario ? ` · 📍 ${o.scenario}` : ''}</span>}
                  {o.priceBand && <span style={{ marginLeft: 8, color: 'var(--color-brand-accent)' }}><b>{o.priceBand}</b></span>}
                </div>

                {/* ── 第二层：为什么值得做 ── */}
                {(o.painPoint || o.competitorGap || (o.evidence || []).length > 0) && (
                  <div style={{ borderTop: '1px dashed var(--color-border)', paddingTop: 8, marginBottom: 4 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-secondary)', marginBottom: 4 }}>为什么值得做</div>
                    {o.painPoint && <div style={{ fontSize: 12, marginBottom: 3 }}>痛点：{o.painPoint}</div>}
                    {o.competitorGap && <div style={{ fontSize: 12, marginBottom: 3 }}>竞品空白：{o.competitorGap}</div>}
                    {(o.evidence || []).map((e, i) => (
                      <Popover key={i} content={e.text} title={e.from}>
                        <Tag color="default" style={{ fontSize: 11, marginBottom: 4, cursor: 'help' }}>
                          {e.from} #{i + 1}
                        </Tag>
                      </Popover>
                    ))}
                  </div>
                )}

                {/* ── 第三层：怎么做 ── */}
                {(o.assetFit || o.productStrategy) && (
                  <div style={{ borderTop: '1px dashed var(--color-border)', paddingTop: 8, marginBottom: 4 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-secondary)', marginBottom: 4 }}>怎么做</div>
                    {o.assetFit?.ip && <div style={{ fontSize: 12, marginBottom: 3 }}>🤝 IP：<b>{o.assetFit.ip}</b>{(o.assetFit.ipReason ? ` — ${o.assetFit.ipReason}` : '')}</div>}
                    {o.assetFit?.designLanguage && <div style={{ fontSize: 12, marginBottom: 3 }}>🎨 设计语言：{o.assetFit.designLanguage}</div>}
                    {o.assetFit?.color && <div style={{ fontSize: 12, marginBottom: 3 }}>🎨 颜色：{o.assetFit.color}</div>}
                    {o.assetFit?.material && <div style={{ fontSize: 12, marginBottom: 3 }}>🧱 材质：{o.assetFit.material}</div>}
                    {o.assetFit?.packaging && <div style={{ fontSize: 12, marginBottom: 3 }}>📦 包装：{o.assetFit.packaging}</div>}
                    {o.productStrategy && <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 3 }}>🎯 产品策略：{o.productStrategy}</div>}
                  </div>
                )}

                <Button type={selected === o.id ? 'primary' : 'default'} block style={{ marginTop: 8 }}>
                  {selected === o.id ? '✓ 已选定该方向' : '选定该方向'}
                </Button>
              </Card>
            </Col>
          ))}
        </Row>
      </div>
    </div>
  );
}
