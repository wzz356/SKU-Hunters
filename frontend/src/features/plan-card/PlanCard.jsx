import { useEffect, useRef, useState } from 'react';
import { Card, Row, Col, Tag, Timeline, Input, Button, List, Spin, Space, Alert } from 'antd';
import { SendOutlined, LoadingOutlined } from '@ant-design/icons';
import ProcessLog from '../../shared/components/ProcessLog';

const GRADIENTS = {
  'ip-collect': 'var(--grad-ip-collect)',
  'healing-nature': 'var(--grad-healing-nature)',
  'outdoor-clip': 'var(--grad-outdoor-clip)',
};
const DEFAULT_GRADIENT = 'var(--grad-default)';

const QUICK_SUGGESTIONS = [
  '配色再柔和一点',
  '加一个挂绳/挂扣功能',
  '价格压到 55 元以内',
  '增加联名 IP 的视觉占比',
  '材质换成磨砂质感',
];

/**
 * 新品企划卡（纯展示/事件组件）：创意设计 + 商品策略 + 改稿沟通 / 复盘追问。
 * 不 import API、不接收 planId、不发请求；生成/改稿/复盘均通过事件回调由容器执行。
 * 归档只读：plan_card_ready 显示「改稿沟通」，archived 显示「复盘追问」（只读回顾，不改稿）。
 * @param {object} card        已生成企划卡
 * @param {object} opportunity 选中的机会卡
 * @param {object} brief       约束（camelCase）
 * @param {string} status      'idle' | 'loading' | 'success' | 'error'（生成状态）
 * @param {boolean} isArchived 是否已归档（决定改稿 vs 复盘追问）
 * @param {Function} onGenerate(opportunityId) 生成/重试
 * @param {Function} onRevise(message) 改稿（仅 plan_card_ready）
 * @param {Function} onReview(question) 复盘追问（仅 archived，只读）
 */
// 从「39-99 元」「69 元」里提取数字
function nums(s) { return (s || '').match(/\d+(?:\.\d+)?/g)?.map(Number) || []; }

// 企划案六模块外壳（带顶部一句战略判断）
function ModuleCard({ title, subtitle, judge, children }) {
  return (
    <Card size="small" style={{ height: '100%', background: 'var(--color-surface-alt)' }}>
      <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>{subtitle}</div>
      <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>{title}</div>
      {judge && <div style={{ fontSize: 12, color: 'var(--color-brand-accent)', borderLeft: '3px solid var(--color-brand-accent)', paddingLeft: 8, marginBottom: 8 }}>{judge}</div>}
      <div style={{ fontSize: 12, lineHeight: 1.8 }}>{children}</div>
    </Card>
  );
}

// 新品企划案（名创新品立项提案页）：Hero 决策信息 + 五步决策链 + 六模块
function ProductProposalView({ proposal = {}, opportunity }) {
  const emoji = opportunity?.emoji || '✨';
  const bg = proposal.background || {};
  const pos = proposal.positioning || {};
  const d = proposal.design || {};
  const biz = proposal.business || {};
  const specs = proposal.specification || [];
  const growth = proposal.growthPath || [];

  const bandNums = nums(pos.priceRange);
  const low = bandNums[0];
  const high = bandNums[1];
  const retail = nums(biz.retailPrice)[0];

  // 产品关键词：从设计语言/材质里切短词，整句当 tag 会黏成一坨
  const keywordSegments = [d.designLanguage, d.material, d.color]
    .filter(Boolean)
    .flatMap((s) => s.split(/[，,、；;]/).map((x) => x.trim()))
    .filter((s) => s && s.length <= 8);
  const keywords = [...new Set(['IP联名', ...keywordSegments])].slice(0, 5);

  // 五步决策链：市场机会 → 用户洞察 → 商品方向 → 设计验证 → 商业评估
  const steps = [
    { label: '市场机会', text: bg.marketOpportunity },
    { label: '用户洞察', text: bg.userNeed },
    { label: '商品方向', text: proposal.name },
    { label: '设计验证', text: d.designLanguage },
    { label: '商业评估', text: biz.retailPrice ? `${biz.retailPrice} · ${biz.costTarget}` : '' },
  ].filter((s) => s.text);

  return (
    <div>
      {/* Hero：立项决策页（名称 + 战略判断 + 核心决策信息 + 概念图） */}
      <Card style={{ marginBottom: 16, background: 'var(--color-surface-alt)', border: '1px solid var(--color-brand-accent)' }}>
        <Row gutter={24} align="middle">
          <Col xs={24} lg={12}>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 4 }}>新品企划案 · 立项提案</div>
              <h1 style={{ margin: '0 0 6px' }}>{emoji} {proposal.name}</h1>
              {pos.slogan && <p style={{ fontSize: 16, color: 'var(--color-brand-accent)', margin: '0 0 10px' }}>{pos.slogan}</p>}
              {/* 产品关键词：短词 tag */}
              <div style={{ margin: '0 0 12px' }}>
                {keywords.map((k) => <Tag key={k} style={{ fontSize: 11, marginBottom: 4 }}>{k}</Tag>)}
              </div>
              <div style={{ fontSize: 12, lineHeight: 2 }}>
                <div><b>目标人群</b>　{pos.targetUser}</div>
                <div><b>核心场景</b>　{pos.scenario}</div>
                <div><b>价格策略</b>　{pos.priceRange}{biz.retailPrice ? `，主推 ${biz.retailPrice}` : ''}</div>
                <div><b>商业验证</b>　{biz.costTarget}</div>
              </div>
            </div>
          </Col>
          <Col xs={24} lg={12}>
            {d.imageUrl ? (
              <img src={d.imageUrl} alt="产品概念图" style={{ width: '100%', borderRadius: 12 }} />
            ) : (
              <div className="concept-image" style={{ background: 'var(--grad-default)' }}>
                <div>{emoji}</div><div className="concept-caption">产品概念图 · 即梦文生图接入后替换</div>
              </div>
            )}
            <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 8, lineHeight: 1.8 }}>
              <div><b>Concept：</b>{d.concept}</div>
              <div><b>设计方向：</b>{d.designLanguage}</div>
            </div>
          </Col>
        </Row>
      </Card>

      {/* 五步决策链 */}
      <Card size="small" style={{ marginBottom: 16, background: 'var(--color-surface-alt)' }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-secondary)', marginBottom: 8 }}>商品决策链</div>
        {steps.map((s, i) => (
          <div key={s.label} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: i < steps.length - 1 ? 8 : 0, fontSize: 12 }}>
            <Tag color="blue" style={{ minWidth: 64, textAlign: 'center', margin: 0 }}>{s.label}</Tag>
            <span style={{ flex: 1 }}>{s.text}</span>
          </div>
        ))}
      </Card>

      {/* 六模块（商品经理语言） */}
      <Row gutter={[16, 16]}>
        <Col xs={24} md={12}><ModuleCard title="01 市场机会" subtitle="Why Now" judge={bg.marketOpportunity}>
          {bg.trendEvidence && <div><b>趋势：</b>{bg.trendEvidence}</div>}
          {bg.userNeed && <div><b>用户需求：</b>{bg.userNeed}</div>}
        </ModuleCard></Col>

        <Col xs={24} md={12}><ModuleCard title="02 商品定位" subtitle="Who & What" judge={pos.slogan}>
          <div><b>目标消费者：</b>{pos.targetUser}</div>
          <div><b>核心场景：</b>{pos.scenario}</div>
          <div><b>价格带：</b>{pos.priceRange}</div>
        </ModuleCard></Col>

        <Col xs={24} md={12}><ModuleCard title="03 产品概念" subtitle="Product Concept" judge={d.concept}>
          <div style={{ marginBottom: 6 }}><b>设计策略</b></div>
          <div style={{ borderLeft: '3px solid var(--color-border-strong)', paddingLeft: 8, lineHeight: 1.9 }}>
            <div><b>设计主题：</b>{d.concept}</div>
            <div><b>视觉语言：</b>{d.designLanguage}</div>
            {d.pattern && <div><b>核心元素：</b>{d.pattern}</div>}
          </div>
          <div style={{ marginTop: 6, lineHeight: 1.9 }}>
            <div><b>颜色：</b>{d.color}</div>
            <div><b>材质：</b>{d.material}</div>
          </div>
        </ModuleCard></Col>

        <Col xs={24} md={12}><ModuleCard title="04 商品规格" subtitle="Product Spec">
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <tbody>
              {specs.map((s) => (
                <tr key={s.module} style={{ borderBottom: '1px solid var(--color-border)' }}>
                  <td style={{ padding: '4px 8px 4px 0', fontWeight: 600, whiteSpace: 'nowrap', verticalAlign: 'top' }}>{s.module}</td>
                  <td style={{ padding: '4px 0' }}>{s.solution}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ModuleCard></Col>

        <Col xs={24} md={12}><ModuleCard title="05 商业模型" subtitle="Business Model" judge={biz.retailPrice ? `${biz.retailPrice} 主推款，兼顾 IP 溢价与大众购买力` : ''}>
          <div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
            {low != null && <div style={{ flex: 1, textAlign: 'center', padding: '8px 4px', background: 'var(--color-bg)', borderRadius: 8 }}><div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>基础款</div><b>{low} 元</b></div>}
            {retail != null && <div style={{ flex: 1, textAlign: 'center', padding: '8px 4px', background: 'var(--surface-danger)', border: '1px solid var(--color-brand-accent)', borderRadius: 8 }}><div style={{ fontSize: 11 }}>主推款 ⭐</div><b style={{ color: 'var(--color-brand-accent)' }}>{retail} 元</b></div>}
            {high != null && <div style={{ flex: 1, textAlign: 'center', padding: '8px 4px', background: 'var(--color-bg)', borderRadius: 8 }}><div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>限定礼盒</div><b>{high} 元</b></div>}
          </div>
          <div><b>成本约束：</b>{biz.costTarget}</div>
          {biz.skuStrategy && <div><b>SKU 策略：</b>{biz.skuStrategy}</div>}
          {biz.launchPlan && <div><b>首发策略：</b>{biz.launchPlan}</div>}
        </ModuleCard></Col>

        <Col xs={24} md={12}><ModuleCard title="06 增长路线" subtitle="Growth Roadmap">
          <Timeline items={growth.map((g) => ({ children: <span style={{ fontSize: 12 }}><b>{g.stage}</b>　{g.action}</span> }))} />
        </ModuleCard></Col>
      </Row>
    </div>
  );
}

export default function PlanCard({ card, proposal, opportunity, brief, status, isArchived, onGenerate, onRevise, onReview }) {
  const [chats, setChats] = useState([]);
  const [reviewChats, setReviewChats] = useState([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [logDone, setLogDone] = useState(false);
  const chatEnd = useRef(null);

  useEffect(() => { chatEnd.current?.scrollIntoView({ behavior: 'smooth' }); }, [chats, reviewChats]);

  // 改稿（仅 plan_card_ready）
  const sendRevise = async (text) => {
    const message = (text || input).trim();
    if (!message || sending || isArchived) return;
    setInput('');
    setSending(true);
    setChats((cs) => [...cs, { role: 'user', text: message }]);
    try {
      const data = await onRevise(message);
      setChats((cs) => [...cs, { role: 'ai', text: data?.reply || '(无回复)' }]);
    } catch (e) {
      setChats((cs) => [...cs, { role: 'ai', text: `改稿沟通失败：${e?.message || '请确认后端在线'}` }]);
    } finally {
      setSending(false);
    }
  };

  // 复盘追问（仅 archived，只读）
  const sendReview = async (text) => {
    const question = (text || input).trim();
    if (!question || sending || !isArchived) return;
    setInput('');
    setSending(true);
    setReviewChats((cs) => [...cs, { role: 'user', text: question }]);
    try {
      const data = await onReview(question);
      setReviewChats((cs) => [...cs, { role: 'ai', text: data?.answer || '(无回复)' }]);
    } catch (e) {
      setReviewChats((cs) => [...cs, { role: 'ai', text: `复盘追问失败：${e?.message || '请确认后端在线'}` }]);
    } finally {
      setSending(false);
    }
  };

  if (status === 'loading') {
    return <div style={{ textAlign: 'center', padding: 60 }} role="status" aria-busy="true"><Spin size="large" /></div>;
  }

  if (status === 'error' && !card) {
    return (
      <Alert
        type="error" showIcon role="alert" message="企划卡生成失败"
        action={<Button size="small" onClick={() => onGenerate?.(opportunity?.id)}>重试</Button>}
      />
    );
  }

  if (!card) return null;

  const emoji = opportunity?.emoji || '✨';
  const direction = opportunity?.direction || '';
  const gradient = GRADIENTS[card.opportunityId] || DEFAULT_GRADIENT;
  const priceRange = brief?.priceRange || [39, 99];
  const costLimit = brief?.costLimit ?? 25;

  return (
    <div>
      {card.processLog && (
        <Card size="small" title="企划生成 · 思考过程" style={{ marginBottom: 16, background: 'var(--color-surface-alt)', border: '1px solid var(--color-border-strong)' }}>
          <ProcessLog key={opportunity?.id} lines={card.processLog} onDone={() => setLogDone(true)} />
        </Card>
      )}

      <div style={{ opacity: !card.processLog || logDone ? 1 : 0, transition: 'opacity 0.5s', pointerEvents: !card.processLog || logDone ? 'auto' : 'none' }}>
        {proposal ? <ProductProposalView proposal={proposal} opportunity={opportunity} /> : <Card>
          <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 4 }}>
            {brief?.theme} · {brief?.category} · 价格带 {priceRange[0]}-{priceRange[1]} 元 · 成本 ≤{costLimit} 元
          </div>
          <h1 style={{ margin: '0 0 4px' }}>{emoji} {card.name}</h1>
          <p style={{ color: 'var(--color-text-secondary)' }}>{card.concept}</p>

          <Row gutter={24} style={{ marginTop: 16 }}>
            <Col xs={24} lg={10}>
              {card.conceptImage ? (
                <img src={card.conceptImage} alt="产品概念图" style={{ width: '100%', borderRadius: 12 }} />
              ) : (
                <div className="concept-image" style={{ background: gradient }}>
                  <div>{emoji}</div>
                  <div className="concept-caption">产品概念图 · 即梦文生图接入后替换</div>
                </div>
              )}
              {card.costCheck && (
                <div style={{ fontSize: 12, color: card.costCheck.passed ? 'var(--cost-pass-fg)' : 'var(--cost-fail-fg)', marginTop: 6, padding: '6px 10px', background: card.costCheck.passed ? 'var(--cost-pass-bg)' : 'var(--cost-fail-bg)', borderRadius: 6 }}>
                  {card.costCheck.passed ? '✅' : '❌'} 成本校验：{card.costCheck.reason}
                </div>
              )}
            </Col>
            <Col xs={24} lg={14}>
              <h3>设计语言<span className="plan-section-tag">创意设计</span></h3>
              <p style={{ fontSize: 13 }}>{card.designLanguage}</p>
              <h3>关键词<span className="plan-section-tag">创意设计</span></h3>
              <p>{(card.keywords || []).map((k) => <Tag key={k} color="purple" style={{ whiteSpace: 'normal', wordBreak: 'break-word', maxWidth: '100%', height: 'auto', lineHeight: '1.6' }}>{k}</Tag>)}</p>
              <h3>功能点<span className="plan-section-tag">创意设计</span></h3>
              <ul style={{ fontSize: 13, paddingLeft: 18, margin: 0 }}>
                {(card.features || []).map((f) => <li key={f}>{f}</li>)}
              </ul>
            </Col>
          </Row>

          <Card size="small" style={{ margin: '16px 0', background: 'var(--color-surface-alt)' }}>
            <b>跨品类融合说明：</b>{card.fusion}
          </Card>

          <Row gutter={24}>
            <Col xs={24} md={8}>
              <h3>定价<span className="plan-section-tag">商品策略</span></h3>
              <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--color-brand-accent)' }}>{card.pricing?.price || '—'}</div>
              <p style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>{card.pricing?.reason}</p>
            </Col>
            <Col xs={24} md={9}>
              <h3>上新节奏<span className="plan-section-tag">商品策略</span></h3>
              <Timeline
                items={(card.schedule || []).map((s) => ({ children: <span style={{ fontSize: 12 }}><b>{s.time}</b>　{s.action}</span> }))}
              />
            </Col>
            <Col xs={24} md={7}>
              <h3>上市验证计划<span className="plan-section-tag">商品策略</span></h3>
              <ul style={{ fontSize: 12, paddingLeft: 18 }}>
                {(card.validation || []).map((v) => <li key={v} style={{ marginBottom: 6 }}>{v}</li>)}
              </ul>
            </Col>
          </Row>
        </Card>}
      </div>

      {isArchived ? (
        <Card title="💬 复盘追问" size="small" style={{ marginTop: 16 }}>
          <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 8 }}>企划案已归档，仅可复盘回顾，不可再改稿。</div>
          {reviewChats.length > 0 && (
            <div style={{ maxHeight: 320, overflow: 'auto', marginBottom: 12 }}>
              <List
                size="small" split={false} dataSource={reviewChats}
                renderItem={(c) => (
                  <List.Item style={{ padding: '4px 0', border: 'none', flexDirection: c.role === 'user' ? 'row-reverse' : 'row' }}>
                    <div style={{
                      maxWidth: '80%', padding: '8px 12px', borderRadius: 12, fontSize: 13, lineHeight: 1.6,
                      background: c.role === 'user' ? 'var(--chat-user-bg)' : 'var(--chat-ai-bg)', color: c.role === 'user' ? 'var(--chat-user-fg)' : 'var(--chat-ai-fg)',
                      borderTopRightRadius: c.role === 'user' ? 4 : 12, borderTopLeftRadius: c.role === 'ai' ? 4 : 12,
                    }}>
                      <span style={{ fontSize: 11, opacity: 0.7, display: 'block', marginBottom: 2 }}>
                        {c.role === 'user' ? '我' : 'AI 复盘助手'}
                      </span>
                      {c.text}
                    </div>
                  </List.Item>
                )}
              />
              {sending && (
                <div style={{ textAlign: 'left', padding: '8px 12px' }}>
                  <Spin indicator={<LoadingOutlined />} size="small" /> <span style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>正在复盘…</span>
                </div>
              )}
              <div ref={chatEnd} />
            </div>
          )}
          <Input.Search
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onSearch={() => sendReview()}
            enterButton={<><SendOutlined /> 提交追问</>}
            placeholder="如：这个定价的依据是什么？"
            loading={sending}
          />
        </Card>
      ) : (
        <Card title="💬 改稿沟通" size="small" style={{ marginTop: 16 }}>
          {chats.length > 0 && (
            <div style={{ maxHeight: 320, overflow: 'auto', marginBottom: 12 }}>
              <List
                size="small" split={false} dataSource={chats}
                renderItem={(c) => (
                  <List.Item style={{ padding: '4px 0', border: 'none', flexDirection: c.role === 'user' ? 'row-reverse' : 'row' }}>
                    <div style={{
                      maxWidth: '80%', padding: '8px 12px', borderRadius: 12, fontSize: 13, lineHeight: 1.6,
                      background: c.role === 'user' ? 'var(--chat-user-bg)' : 'var(--chat-ai-bg)', color: c.role === 'user' ? 'var(--chat-user-fg)' : 'var(--chat-ai-fg)',
                      borderTopRightRadius: c.role === 'user' ? 4 : 12, borderTopLeftRadius: c.role === 'ai' ? 4 : 12,
                    }}>
                      <span style={{ fontSize: 11, opacity: 0.7, display: 'block', marginBottom: 2 }}>
                        {c.role === 'user' ? '我' : 'AI 企划助手'}
                      </span>
                      {c.text}
                    </div>
                  </List.Item>
                )}
              />
              {sending && (
                <div style={{ textAlign: 'left', padding: '8px 12px' }}>
                  <Spin indicator={<LoadingOutlined />} size="small" /> <span style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>正在分析修改意见…</span>
                </div>
              )}
              <div ref={chatEnd} />
            </div>
          )}

          {chats.length === 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 6 }}>快捷改稿建议：</div>
              <Space wrap size={[6, 6]}>
                {QUICK_SUGGESTIONS.map((s) => (
                  <Button key={s} size="small" onClick={() => sendRevise(s)}>{s}</Button>
                ))}
              </Space>
            </div>
          )}

          <Input.Search
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onSearch={() => sendRevise()}
            enterButton={<><SendOutlined /> 提交修改意见</>}
            placeholder="如：配色再粉一点 / 加一个挂绳功能 / 价格压到 55 元以内"
            loading={sending}
          />
        </Card>
      )}
    </div>
  );
}
