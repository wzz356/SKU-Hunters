import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Card, Row, Col, Tag, Progress, Button, Popover, Empty } from 'antd';
import { ArrowRightOutlined } from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import ProcessLog from '../../shared/components/ProcessLog';
import { readCssVar } from '../../shared/utils/cssTokens';

const MODULE_TAG = { fontSize: 11, color: 'var(--color-section-label)', marginLeft: 8 };
// Enrichment 区块标注：与「采集数据」标注区分，如实说明来自 AI 二次推理
const AI_TAG = <Tag color="purple" style={{ fontSize: 11, marginLeft: 8 }}>AI 推理生成</Tag>;
const BLOCK_TITLE = { fontSize: 13, fontWeight: 600, margin: '16px 0 8px' };

// 机会来源类型 → 中文标签（与后端 OpportunityType 枚举对齐：机会来源语义，非产品形态）
const OPPORTUNITY_TYPE_LABEL = {
  design_value: '设计价值',
  scenario_growth: '场景增长',
  pain_point_solution: '痛点解决',
  emotional_consumption: '情绪消费',
  technology_upgrade: '技术升级',
};
const RANK_MEDAL = { 1: '🥇', 2: '🥈', 3: '🥉' };

// 洞察模块外壳：标题 + 过程日志 + 日志跑完后显现内容
function InsightModule({ title, tag = 'AI 分析 · 样本可溯', log, children }) {
  const [done, setDone] = useState(false);
  return (
    <Card title={<span>{title}<span style={MODULE_TAG}>{tag}</span></span>} style={{ marginBottom: 16 }}>
      <ProcessLog lines={log || []} onDone={() => setDone(true)} />
      <div style={{ opacity: done ? 1 : 0, transition: 'opacity 0.5s', pointerEvents: done ? 'auto' : 'none' }}>
        {children}
      </div>
    </Card>
  );
}

// 安全默认值：所有数组/曲线/颜色字段兜底，避免 ECharts 因空数据抛错
// 趋势雷达双模式：有 AI Enrichment → 五段式决策视图；无 → 基础视图（原渲染）
// AI 机会池：收口块（排名 + 置信度 + 机会来源类型 + 依据来源 + 推理链）
// 数据来自后端 bundle.opportunityPool（任意品类都产出），与机会生成页消费同一
// OpportunityPoolItem 结构，禁止二次生成；不依赖 enrichment，全品类渲染。
function OpportunityPoolBlock({ opportunityPool = [], chainsByPoolId = {} }) {
  if (!opportunityPool.length) return null;
  return (
    <>
      <div style={BLOCK_TITLE}>AI 机会池{AI_TAG}</div>
      {opportunityPool.map(item => {
        const chains = chainsByPoolId[item.id] || [];
        return (
        <Card key={item.id} size="small" style={{ marginBottom: 12, background: 'var(--surface-danger)', border: '1px solid var(--border-danger)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
            <b style={{ fontSize: 14, color: 'var(--color-brand-accent)' }}>
              {RANK_MEDAL[item.rank] || `#${item.rank}`} {item.title}
              <Tag color="purple" style={{ marginLeft: 8, fontSize: 11 }}>{OPPORTUNITY_TYPE_LABEL[item.opportunityType] || item.opportunityType}</Tag>
            </b>
            <span style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>
              置信度 <b style={{ fontSize: 15, color: 'var(--color-brand-accent)' }}>{item.confidence ?? '—'}%</b>
            </span>
          </div>
          {item.confidence != null && (
            <Progress percent={item.confidence} showInfo={false} strokeColor="var(--color-brand-accent)" size="small" style={{ margin: '6px 0' }} />
          )}
          <div style={{ fontSize: 12, marginBottom: 6 }}>{item.summary}</div>
          <div style={{ fontSize: 12, fontWeight: 600, margin: '6px 0 4px' }}>为什么推荐这个方向</div>
          {(item.evidenceSource || []).map((e, i) => (
            <div key={i} style={{ fontSize: 12, marginBottom: 4 }}>
              <span style={{ color: 'var(--color-brand-accent)', marginRight: 6 }}>✓</span>
              <Tag style={{ fontSize: 11, marginRight: 4 }}>{e.source}</Tag>{e.fact}
            </div>
          ))}
          {/* 用户证据：痛点归因链支撑（代表性原声，非只统计数字） */}
          {chains.length > 0 && (
            <div style={{ fontSize: 12, borderTop: '1px dashed var(--color-border)', paddingTop: 6, marginTop: 6 }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>用户证据（痛点归因）</div>
              {chains.slice(0, 2).map(c => (
                <div key={c.painPoint} style={{ marginBottom: 4 }}>
                  <span>🔥 {c.painPoint}</span>
                  {(c.consumerVoice || []).slice(0, 1).map(v => (
                    <div key={v} style={{ color: 'var(--color-text-secondary)', margin: '2px 0 0 10px' }}>“{v.length > 44 ? `${v.slice(0, 44)}…` : v}”</div>
                  ))}
                </div>
              ))}
            </div>
          )}
          {(item.reasoning || []).length > 0 && (
            <div style={{ fontSize: 12, fontWeight: 600, margin: '10px 0 4px' }}>推理链：信号 → 解读 → 机会</div>
          )}
          {(item.reasoning || []).map(r => (
            <Row key={r.signal} gutter={[8, 4]} style={{ marginBottom: 8, fontSize: 12 }} align="middle">
              <Col xs={24} md={7}><Tag color="purple">{r.signal}</Tag></Col>
              <Col xs={24} md={9}><ArrowRightOutlined style={{ marginRight: 6, color: 'var(--color-text-muted)' }} />{r.interpretation}</Col>
              <Col xs={24} md={8}><b style={{ color: 'var(--color-action-primary)' }}>{r.opportunity}</b></Col>
            </Row>
          ))}
        </Card>
        );
      })}
    </>
  );
}

function TrendRadar({ trendRadar = {}, enrichment = null, opportunityPool = [], chainsByPoolId = {} }) {
  if (!enrichment) return <TrendRadarBasic trendRadar={trendRadar} opportunityPool={opportunityPool} chainsByPoolId={chainsByPoolId} />;
  return <TrendRadarEnriched trendRadar={trendRadar} enrichment={enrichment} opportunityPool={opportunityPool} chainsByPoolId={chainsByPoolId} />;
}

// 基础视图：无 enrichment 数据品类的原始渲染 + AI 机会池（机会池由后端产出，全品类可见）
function TrendRadarBasic({ trendRadar = {}, opportunityPool = [], chainsByPoolId = {} }) {
  const weeks = trendRadar.heatCurve?.weeks || [];
  const series = (trendRadar.heatCurve?.series || []).map(s => ({ ...s, type: 'line', smooth: true, showSymbol: false }));
  const heatOption = {
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0, textStyle: { fontSize: 11 } },
    grid: { left: 40, right: 16, top: 16, bottom: 48 },
    xAxis: { type: 'category', data: weeks },
    yAxis: { type: 'value', name: '热度' },
    series,
  };
  return (
    <>
    <Row gutter={16}>
      <Col xs={24} md={14}>
        {(trendRadar.signals || []).map(s => (
          <Card key={s.name} size="small" style={{ marginBottom: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <b>{s.name}</b>
              <Tag color="red">{s.metric}</Tag>
            </div>
            <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', margin: '6px 0' }}>
              {s.period} · 关联领域：{(s.domains || []).map(d => <Tag key={d} style={{ fontSize: 11 }}>{d}</Tag>)}
            </div>
            <div style={{ fontSize: 12, color: 'var(--color-action-primary)' }}>→ 机会判断：{s.opportunity}</div>
          </Card>
        ))}
      </Col>
      <Col xs={24} md={10}>
        {weeks.length > 0 && <ReactECharts option={heatOption} style={{ height: 240 }} />}
        <div style={{ marginTop: 8 }}>
          {(trendRadar.hotWords || []).map(w => <Tag key={w} color="purple" style={{ marginBottom: 4 }}>{w}</Tag>)}
        </div>
      </Col>
    </Row>
    <OpportunityPoolBlock opportunityPool={opportunityPool} chainsByPoolId={chainsByPoolId} />
  </>
  );
}

// 五段式决策视图：市场发生什么 → 用户讨论什么 → 细分机会 → 上市窗口 → AI 机会池
function TrendRadarEnriched({ trendRadar = {}, enrichment, opportunityPool = [], chainsByPoolId = {} }) {
  const { marketJudgment, trendSummary, topicClusters = [], subCategoryTrends = [], seasonPlan } = enrichment;

  // 品类热度曲线：真实采集快照（Google Trends），作为总览的采集证据
  const weeks = trendRadar.heatCurve?.weeks || [];
  const series = (trendRadar.heatCurve?.series || []).map(s => ({ ...s, type: 'line', smooth: true, showSymbol: false }));
  const heatOption = {
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0, textStyle: { fontSize: 11 } },
    grid: { left: 40, right: 16, top: 16, bottom: 48 },
    xAxis: { type: 'category', data: weeks },
    yAxis: { type: 'value', name: '热度' },
    series,
  };

  // 子品类趋势：横向柱状图（样本量 × 同比增速），独立语义，不复用品类热度曲线
  const MOMENTUM_ARROW = { surge: '↑↑↑', rising: '↑↑', stable: '→', emerging: '↗ 新' };
  const subSorted = [...subCategoryTrends].sort((a, b) => (a.records || 0) - (b.records || 0));
  const subOption = {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: ps => {
        const d = subSorted[ps[0].dataIndex];
        return `${d.name}<br/>样本量：${d.records} 条 · 同比：${d.growthPct != null ? `+${d.growthPct}%` : '—'}<br/>${d.note || ''}`;
      },
    },
    grid: { left: 100, right: 64, top: 8, bottom: 24 },
    xAxis: { type: 'value', name: '样本量（条）', nameTextStyle: { fontSize: 11 } },
    yAxis: { type: 'category', data: subSorted.map(d => d.name), axisLabel: { fontSize: 11 } },
    series: [{
      type: 'bar', barWidth: 14,
      itemStyle: { color: readCssVar('--color-action-primary'), opacity: 0.85, borderRadius: [0, 4, 4, 0] },
      label: {
        show: true, position: 'right', fontSize: 11,
        formatter: p => {
          const d = subSorted[p.dataIndex];
          return `${MOMENTUM_ARROW[d.momentum] || ''} ${d.growthPct != null ? `+${d.growthPct}%` : '大盘'}`;
        },
      },
      data: subSorted.map(d => d.records || 0),
    }],
  };

  return (
    <div>
      {/* 0. AI 市场判断：一句话战略判断（Insight Enrichment Agent 顶部结论） */}
      {marketJudgment && (
        <Card size="small" style={{ background: 'var(--color-surface-alt)', border: '1px solid var(--color-brand-accent)', marginBottom: 12 }}>
          <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 2 }}>AI 市场判断</div>
          <b style={{ color: 'var(--color-brand-accent)', fontSize: 14 }}>{marketJudgment}</b>
        </Card>
      )}

      {/* 1. 品类趋势总览：一句话判断 + 核心指标 + 真实热度曲线 */}
      <div style={{ ...BLOCK_TITLE, marginTop: 0 }}>市场趋势总览<Tag style={{ fontSize: 11, marginLeft: 8 }}>采集数据</Tag>{AI_TAG}</div>
      <Card size="small" style={{ background: 'var(--color-surface-alt)', border: '1px solid var(--color-border-strong)', marginBottom: 12 }}>
        <b style={{ color: 'var(--color-action-primary)' }}>AI 判断：</b>{trendSummary?.verdict || ''}
      </Card>
      <Row gutter={[12, 12]}>
        {(trendSummary?.metrics || []).map(m => (
          <Col key={m.label} xs={24} md={8}>
            <Card size="small">
              <div style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>{m.label}</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: m.direction === 'up' ? 'var(--color-brand-accent)' : 'inherit' }}>
                {m.direction === 'up' ? '↑ ' : ''}{m.value}
              </div>
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>{m.note}</div>
            </Card>
          </Col>
        ))}
      </Row>
      {weeks.length > 0 && <ReactECharts option={heatOption} style={{ height: 200, marginTop: 12 }} />}
      <div style={{ marginTop: 8 }}>
        {(trendSummary?.keywords || []).map(w => <Tag key={w} color="purple" style={{ marginBottom: 4 }}>{w}</Tag>)}
      </div>

      {/* 2. 用户正在讨论什么：TOP 话题按需求类型聚类 */}
      <div style={BLOCK_TITLE}>用户正在讨论{AI_TAG}</div>
      <Row gutter={[12, 12]}>
        {topicClusters.map(c => (
          <Col key={c.type} xs={24} md={8}>
            <Card size="small" title={<span style={{ fontSize: 12 }}>{c.type}</span>}>
              {(c.topics || []).map(t => (
                <div key={t.name} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                  <span># {t.name}</span>
                  <span style={{ color: 'var(--color-text-muted)' }}>{t.count != null ? `${t.count} 条` : ''}</span>
                </div>
              ))}
            </Card>
          </Col>
        ))}
      </Row>

      {/* 3. 子品类趋势：选赛道依据 */}
      <div style={BLOCK_TITLE}>子品类趋势 · 选赛道{AI_TAG}</div>
      {subCategoryTrends.some(d => d.records != null)
        ? <ReactECharts option={subOption} style={{ height: 260 }} />
        : (
          // 采集侧无样本量 → 排名列表（不伪造柱状图数值），保留势头箭头 + 溯源
          <div>
            {subCategoryTrends.map((d, i) => (
              <div key={d.name} style={{ display: 'flex', gap: 10, marginBottom: 6, alignItems: 'baseline', fontSize: 12 }}>
                <span style={{ color: 'var(--color-text-muted)', minWidth: 20 }}>{i + 1}.</span>
                <b style={{ minWidth: 120 }}>{d.name}</b>
                <span style={{ color: 'var(--color-action-primary)', minWidth: 44 }}>{MOMENTUM_ARROW[d.momentum] || ''}</span>
                <span style={{ color: 'var(--color-text-secondary)' }}>{d.note || ''}</span>
              </div>
            ))}
          </div>
        )}

      {/* 4. 季节窗口：零售供应链节奏 → 上市决策 */}
      <div style={BLOCK_TITLE}>季节窗口 · 上市节奏{AI_TAG}</div>
      {(seasonPlan?.cycle || []).map((p, i) => (
        <div key={p.phase} style={{ display: 'flex', gap: 12, marginBottom: 8, alignItems: 'flex-start' }}>
          <Tag color="red" style={{ minWidth: 64, textAlign: 'center' }}>{p.phase}</Tag>
          <span style={{ fontSize: 12, color: 'var(--color-text-secondary)', minWidth: 56 }}>{p.months}</span>
          <span style={{ fontSize: 12 }}>{p.action}</span>
        </div>
      ))}
      {seasonPlan?.launchSuggestion && (
        <Card size="small" style={{ background: 'var(--color-surface-alt)', border: '1px solid var(--color-border-strong)', marginTop: 4 }}>
          <b style={{ color: 'var(--color-action-primary)' }}>上市建议：</b>{seasonPlan.launchSuggestion}
        </Card>
      )}

      {/* 5. AI 机会池：共享组件，与基础视图同一渲染（后端 pool 全品类产出） */}
      <OpportunityPoolBlock opportunityPool={opportunityPool} chainsByPoolId={chainsByPoolId} />
    </div>
  );
}

function ConsumerVoice({ consumerVoice = {}, opportunityPool = [] }) {
  const painPoints = consumerVoice.painPoints || [];
  const scenes = consumerVoice.scenes || [];
  const maxCount = Math.max(1, ...painPoints.map(p => p.count || 0));
  const userProfile = consumerVoice.userProfile;
  const painPointChains = consumerVoice.painPointChains || [];
  const poolById = Object.fromEntries(opportunityPool.map(o => [o.id, o.title]));
  const sceneOption = {
    tooltip: { trigger: 'item', formatter: '{b}: {c}%' },
    legend: { bottom: 0, textStyle: { fontSize: 11 } },
    series: [{
      type: 'pie', radius: ['32%', '52%'], center: ['50%', '40%'],
      label: { fontSize: 11 },
      data: scenes.map(s => ({ name: s.name, value: s.value || 0 })),
    }],
  };

  const PROFILE_SECTIONS = [
    { label: '核心场景', items: userProfile?.usageScenario },
    { label: '使用任务', items: userProfile?.userTask },
    { label: '购买动机', items: userProfile?.purchaseMotivation },
    { label: '决策因素', items: userProfile?.decisionFactors },
  ];

  return (
    <div>
      {/* 决策链：用户是谁 → 为什么买 → 原声 → 支持哪个机会方向（Consumer Voice Agent 产物） */}
      {(userProfile || painPointChains.length > 0) && (
        <div>
          {userProfile && (
            <div style={{ marginBottom: 16 }}>
              <div style={BLOCK_TITLE}>用户决策画像{AI_TAG}</div>
              {userProfile.userSegment && (
                <Card size="small" style={{ background: 'var(--color-surface-alt)', border: '1px solid var(--color-brand-accent)', marginBottom: 8 }}>
                  <b style={{ color: 'var(--color-brand-accent)' }}>{userProfile.userSegment}</b>
                </Card>
              )}
              <Row gutter={[12, 8]}>
                {PROFILE_SECTIONS.filter(s => s.items && s.items.length > 0).map(s => (
                  <Col xs={24} md={12} key={s.label}>
                    <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 4 }}>{s.label}</div>
                    <div>{(s.items || []).map(x => <Tag key={x} style={{ marginBottom: 4 }}>{x}</Tag>)}</div>
                  </Col>
                ))}
              </Row>
            </div>
          )}

          {painPointChains.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={BLOCK_TITLE}>痛点归因 · 为什么买{AI_TAG}</div>
              {painPointChains.map((c, i) => (
                <Card key={i} size="small" style={{ marginBottom: 12, background: 'var(--color-surface-alt)', border: '1px solid var(--color-border-strong)' }}>
                  <b style={{ fontSize: 13 }}>
                    {c.priority > 0 ? `${'⭐'.repeat(Math.min(c.priority, 5))} ` : ''}{c.painPoint}
                  </b>
                  <div style={{ fontSize: 12, margin: '6px 0' }}>
                    <span style={{ color: 'var(--color-text-secondary)' }}>需求归因：</span>{c.demandInterpretation}
                  </div>
                  {(c.consumerVoice || []).map(q => (
                    <div key={q} className="quote-card" style={{ marginBottom: 4 }}>
                      <div style={{ fontSize: 12 }}>“{q}”</div>
                    </div>
                  ))}
                  {(c.supportsOpportunityIds || []).length > 0 && (
                    <div style={{ fontSize: 12, marginTop: 4 }}>
                      → 支持机会：
                      {c.supportsOpportunityIds.map(id => (
                        <Tag key={id} color="purple" style={{ marginRight: 4 }}>{poolById[id] || id}</Tag>
                      ))}
                    </div>
                  )}
                  {c.evidenceSource && (
                    <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
                      证据：{c.evidenceSource.platform || '社媒'} · {(c.evidenceSource.keywords || []).join('、')}
                      {c.evidenceSource.count != null ? ` · ${c.evidenceSource.count} 条原声` : ''}
                    </div>
                  )}
                </Card>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 原始消费者之声：痛点频次 / 场景分布 / 原声 / 总结（带空态兜底） */}
      <Row gutter={16}>
        <Col xs={24} md={9}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>TOP 痛点</div>
          {painPoints.length ? painPoints.map((p, i) => (
            <div key={p.text} style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 12 }}>{i + 1}. {p.text} <span style={{ color: 'var(--color-text-muted)' }}>({p.count} 条)</span></div>
              <Progress percent={Math.round((p.count || 0) / maxCount * 100)} showInfo={false} strokeColor="var(--color-action-primary)" size="small" />
            </div>
          )) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无结构化痛点数据" style={{ padding: '12px 0' }} />
          )}
          <div style={{ fontSize: 13, fontWeight: 600, margin: '12px 0 8px' }}>使用场景分布</div>
          {scenes.length ? (
            <ReactECharts option={sceneOption} style={{ height: 320 }} />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无结构化场景数据" style={{ height: 320, display: 'flex', flexDirection: 'column', justifyContent: 'center' }} />
          )}
        </Col>
        <Col xs={24} md={15}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>消费者原声</div>
          {(consumerVoice.quotes || []).map(q => (
            <div key={q.text} className="quote-card">
              <div style={{ fontSize: 13 }}>"{q.text}"</div>
              <div className="quote-source">{q.source}</div>
            </div>
          ))}
          <Card size="small" style={{ background: 'var(--color-surface-alt)', border: '1px solid var(--color-border-strong)' }}>
            <b style={{ color: 'var(--color-action-primary)' }}>洞察总结：</b>{consumerVoice.summary || ''}
          </Card>
        </Col>
      </Row>
    </div>
  );
}

function CompetitiveMap({ competitiveMap = {}, opportunityPool = [] }) {
  const gapZone = competitiveMap.gapZone;
  const gapX = gapZone?.x?.length >= 2 ? gapZone.x : [30, 60];
  const gapY = gapZone?.y?.length >= 2 ? gapZone.y : [7, 10];
  const scatterOption = {
    tooltip: { formatter: p => `${p.data[2]}<br/>价格：${p.data[0]} 元 · 设计感：${p.data[1]}` },
    grid: { left: 44, right: 24, top: 30, bottom: 36 },
    xAxis: { name: '价格（元）', type: 'value', max: 150 },
    yAxis: { name: '设计感', type: 'value', max: 10 },
    series: [{
      type: 'scatter', symbolSize: 18,
      itemStyle: { color: readCssVar('--color-action-primary'), opacity: 0.8 },
      label: { show: true, position: 'top', formatter: p => p.data[2], fontSize: 11 },
      data: (competitiveMap.products || []).map(p => [p.price, p.design, p.name]),
      markArea: gapZone ? {
        itemStyle: { color: readCssVar('--chart-accent-fill') },
        label: { show: true, position: 'insideTop', color: readCssVar('--color-brand-accent'), fontSize: 11 },
        data: [[{ name: gapZone.label, xAxis: gapX[0], yAxis: gapY[0] }, { xAxis: gapX[1], yAxis: gapY[1] }]],
      } : undefined,
    }],
  };
  const priceBands = competitiveMap.priceBands || [];
  const needDims = competitiveMap.needDimensions || [];
  const needSat = competitiveMap.needSatisfaction || [];
  const gaps = competitiveMap.opportunityGaps || [];
  const poolById = Object.fromEntries(opportunityPool.map(o => [o.id, o.title]));

  // 需求满足矩阵：扁平 {competitor,need,score,reason} → 竞品行 × 需求列
  const matrix = {};
  for (const cell of needSat) {
    (matrix[cell.competitor] = matrix[cell.competitor] || {})[cell.need] = cell;
  }
  const competitors = Object.keys(matrix);

  return (
    <div>
      {/* ① 竞品全景：图片 / 价格 / 卖点 */}
      <div style={BLOCK_TITLE}>竞品全景<Tag style={{ fontSize: 11, marginLeft: 8 }}>采集数据</Tag></div>
      <CompetitorGallery products={competitiveMap.products || []} />

      {/* ② 需求满足矩阵（核心）：竞品 × 用户需求维度，评分绑 reason */}
      {competitors.length > 0 && needDims.length > 0 && (
        <>
          <div style={BLOCK_TITLE}>用户需求满足矩阵{AI_TAG}</div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ background: 'var(--color-surface-alt)' }}>
                  <th style={{ textAlign: 'left', padding: '8px 6px', fontWeight: 600 }}>竞品 \ 需求</th>
                  {needDims.map(d => <th key={d} style={{ padding: '8px 4px', fontWeight: 600 }}>{d}</th>)}
                </tr>
              </thead>
              <tbody>
                {competitors.map(comp => (
                  <tr key={comp} style={{ borderBottom: '1px solid var(--color-border)' }}>
                    <td style={{ padding: '6px', fontWeight: 600 }}>{comp}</td>
                    {needDims.map(d => {
                      const cell = matrix[comp]?.[d];
                      if (!cell) return <td key={d} style={{ padding: 6, textAlign: 'center', color: 'var(--color-text-muted)' }}>—</td>;
                      return (
                        <td key={d} style={{ padding: 6, textAlign: 'center' }}>
                          <Popover
                            content={(cell.reason || []).map((r, i) => <div key={i} style={{ fontSize: 12, maxWidth: 260 }}>• {r}</div>)}
                            title={`${comp} · ${d}`}
                          >
                            <span style={{ cursor: 'help', fontWeight: 600, color: cell.score >= 4 ? 'var(--color-brand-accent)' : 'inherit' }}>
                              {cell.score} 分
                            </span>
                          </Popover>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>评分 0-5，悬停查看依据；需求维度来自用户决策因素</div>
        </>
      )}

      {/* ③ AI 机会空位：用户需求 → 竞品不足 → 已有机会池方向（验证层） */}
      {gaps.length > 0 && (
        <>
          <div style={BLOCK_TITLE}>AI 机会空位{AI_TAG}</div>
          {gaps.map((g, i) => (
            <Card key={i} size="small" style={{ marginBottom: 12, background: 'var(--surface-danger)', border: '1px solid var(--border-danger)' }}>
              <div style={{ fontSize: 12, marginBottom: 4 }}><b>用户需求：</b>{g.userNeed}</div>
              <div style={{ fontSize: 12, marginBottom: 4 }}><b style={{ color: 'var(--color-text-secondary)' }}>当前竞品不足：</b>{g.competitorGap}</div>
              <div style={{ fontSize: 12, marginBottom: 4 }}><b style={{ color: 'var(--color-action-primary)' }}>→ 机会：</b>{g.opportunity}</div>
              {(g.supportsOpportunityIds || []).length > 0 && (
                <div style={{ fontSize: 12, marginBottom: 4 }}>
                  对应机会池：
                  {g.supportsOpportunityIds.map(id => (
                    <Tag key={id} color="purple" style={{ marginRight: 4 }}>{poolById[id] || id}</Tag>
                  ))}
                </div>
              )}
              {(g.why || []).length > 0 && (
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                  为什么：{g.why.map((w, j) => <span key={j}>• {w} </span>)}
                </div>
              )}
            </Card>
          ))}
        </>
      )}

      {/* ④ 价格×设计感（辅助探索）+ 价格带 + 卖点 */}
      <div style={BLOCK_TITLE}>价格 × 设计感 · 辅助视图</div>
      <Row gutter={16}>
        <Col xs={24} md={14}>
          <ReactECharts option={scatterOption} style={{ height: 300 }} />
        </Col>
        <Col xs={24} md={10}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>价格带分布</div>
          {priceBands.map(b => (
            <div key={b.band} style={{ marginBottom: 6, fontSize: 12 }}>
              <b>{b.band}</b>
              {b.price ? <span style={{ color: 'var(--color-brand-accent)', margin: '0 6px' }}>{b.price}</span> : null}
              {b.pct > 0 && (
                <Progress percent={b.pct} showInfo={false} strokeColor="var(--purple-400)" size="small"
                  style={{ display: 'inline-block', width: '50%', margin: '0 8px' }} />
              )}
              {b.pct > 0 ? <b>{b.pct}%</b> : null}
              {b.note ? <div style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>{b.note}</div> : null}
            </div>
          ))}
          <div style={{ fontSize: 13, fontWeight: 600, margin: '12px 0 8px' }}>卖点关键词</div>
          {(competitiveMap.sellingPoints || []).map(s => (
            <Tag key={s.word} style={{ marginBottom: 4 }}>{s.word}{s.count > 0 ? ` ×${s.count}` : ''}</Tag>
          ))}
          {gapZone?.label && (
            <Card size="small" style={{ background: 'var(--surface-danger)', border: '1px solid var(--border-danger)', marginTop: 12 }}>
              <b style={{ color: 'var(--color-brand-accent)' }}>价格×设计感空白（辅助）：</b>{gapZone.label}
            </Card>
          )}
        </Col>
      </Row>
    </div>
  );
}

// 竞品图板：图片 + 价格 + 卖点卡片墙
function CompetitorGallery({ products = [] }) {
  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>竞品图板（图片 / 价格 / 卖点）</div>
      <Row gutter={[12, 12]}>
        {products.map(p => (
          <Col key={p.name} xs={12} sm={8} md={6} lg={4}>
            <Card size="small" cover={
              p.imageUrl
                ? <img src={p.imageUrl} alt={p.name} style={{ height: 100, objectFit: 'cover' }} />
                : <div style={{ height: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--color-bg)', color: 'var(--color-text-muted)', fontSize: 12 }}>{p.name.slice(0, 2)}</div>
            }>
              <div style={{ fontSize: 13, fontWeight: 600 }}>{p.name}</div>
              <div style={{ fontSize: 12, color: 'var(--color-brand-accent)' }}>¥{p.price} · 设计 {p.design}</div>
              <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 4 }}>{p.sellingPoint || '—'}</div>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
}

// 洞察驾驶舱：props 驱动（数据由 TaskFlow 拉取后传入，不再 import 全局 mock）
// category 可选：用于匹配 AI Insight Enrichment（无匹配品类回退基础渲染）
export default function InsightCockpit({ insights, category }) {
  const {
    trendRadar = {},
    consumerVoice = {},
    competitiveMap = {},
    insightBase = {},
    trendGallery = {},
  } = insights || {};

  // 洞察增强：后端 bundle.enrichment 为唯一来源（Insight Enrichment Agent 全品类产出），
  // 无 fixture 回退；enrichment 不存在 → 基础视图。
  const enrichment = insights?.enrichment || null;
  // AI 机会池：后端 bundle.opportunityPool 单一事实源（与机会生成页同一份），禁止二次生成。
  const opportunityPool = insights?.opportunityPool || [];
  // 机会池 ← 痛点归因链 反向索引（pool id → 支撑链），供机会池卡片展示代表性用户证据
  const chainsByPoolId = {};
  for (const c of (consumerVoice?.painPointChains || [])) {
    for (const id of (c.supportsOpportunityIds || [])) {
      (chainsByPoolId[id] = chainsByPoolId[id] || []).push(c);
    }
  }
  const trendLog = enrichment
    ? [...(trendRadar.processLog || []), 'AI 洞察增强：基于采集信号的二次推理（Insight Enrichment Agent）']
    : trendRadar.processLog;

  return (
    <div>
      <InsightModule title="趋势机会雷达" log={trendLog}><TrendRadar trendRadar={trendRadar} enrichment={enrichment} opportunityPool={opportunityPool} chainsByPoolId={chainsByPoolId} /></InsightModule>
      <InsightModule title="用户需求 · 实时摘要" tag="实时摘要 · 样本可溯" log={consumerVoice.processLog}><ConsumerVoice consumerVoice={consumerVoice} opportunityPool={opportunityPool} /></InsightModule>
      <InsightModule title="Competitive Map · 竞品分析" log={competitiveMap.processLog}><CompetitiveMap competitiveMap={competitiveMap} opportunityPool={opportunityPool} /></InsightModule>

      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Card title={<span>名创内部资产<span style={MODULE_TAG}>策展数据</span></span>} size="small">
            {(insightBase.hitProducts || []).slice(0, 2).map(p => (
              <div key={p.name} style={{ marginBottom: 8, fontSize: 13 }}>
                <b>{p.name}</b> <Tag color="red">指数 {p.index}</Tag>
                <div style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>{(p.factors || []).join(' · ')}</div>
              </div>
            ))}
            <Link to="/insight-base"><Button type="link" size="small" style={{ padding: 0 }}>查看完整 Insight Base <ArrowRightOutlined /></Button></Link>
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card title={<span>流行元素<span style={MODULE_TAG}>策展数据</span></span>} size="small">
            <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
              {(trendGallery.colors || []).slice(0, 5).map(c => (
                <div key={c.name} title={`${c.name} · ${c.source}`}
                  style={{ width: 32, height: 32, borderRadius: 8, background: c.hex || 'var(--gray-200)', boxShadow: 'inset 0 0 0 1px rgba(0,0,0,0.05)' }} />
              ))}
            </div>
            <div style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>
              {(trendGallery.patterns || []).map(p => p.name).join(' · ')} ｜ {(trendGallery.shapes || []).map(s => s.name).join(' · ')}
            </div>
            <Link to="/trend-gallery"><Button type="link" size="small" style={{ padding: 0 }}>查看完整 Trend Gallery <ArrowRightOutlined /></Button></Link>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
