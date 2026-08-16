/* ============================================================
 * SKU Hunters · InsightBase（名创内部 · IP 资源与洞察资产库）
 *
 * 保留新版 API 四态与响应式契约，并吸收远端 IP 资源库能力：
 * 官方披露数据带 / IP 定位矩阵 / 筛选 / 12 个代表性 IP 卡片。
 * ============================================================ */

import { useEffect, useMemo, useState } from 'react';
import { Card, Col, Empty, Progress, Rate, Row, Segmented, Tag } from 'antd';
import { getInsightBase, getIpResource } from '../../api/dashboard';
import ResponsiveChart from '../../shared/components/ResponsiveChart';
import StateCard from '../../shared/components/StateCard';
import { readCssVar } from '../../shared/utils/cssTokens';
import PageHeader from '../plans/components/PageHeader';

// IP 图片静态资源路径（frontend/public/assets/ip/{slug}/…），素材缺失时前端自动降级
const ipAssetPath = (slug, file) => `/assets/ip/${slug}/${file}`;

function IpImage({ src, alt, className, fallback }) {
  const [failed, setFailed] = useState(false);
  if (failed) return fallback;
  return <img src={src} alt={alt} className={className} onError={() => setFailed(true)} />;
}

function IpMatrix({ ips }) {
  const option = {
    grid: { left: 40, right: 40, top: 40, bottom: 40 },
    xAxis: { min: 0, max: 1, show: false },
    yAxis: { min: 0, max: 1, show: false },
    series: [{
      type: 'scatter',
      symbolSize: 14,
      itemStyle: { color: readCssVar('--chart-series-primary'), opacity: 0.85 },
      label: {
        show: true,
        position: 'top',
        formatter: '{@[2]}',
        fontSize: 11,
        color: readCssVar('--color-text-secondary'),
      },
      data: ips.map((ip) => [ip.matrix.x, ip.matrix.y, ip.nameCn]),
      markLine: {
        silent: true,
        symbol: 'none',
        lineStyle: { color: readCssVar('--color-border-strong'), type: 'dashed' },
        data: [{ xAxis: 0.5 }, { yAxis: 0.5 }],
        label: { show: false },
      },
    }],
    graphic: [
      { type: 'text', left: 44, top: 44, style: { text: '女性向', fontSize: 12, fill: readCssVar('--color-section-label') }, silent: true },
      { type: 'text', right: 44, top: 44, style: { text: '男性 / ACG', fontSize: 12, fill: readCssVar('--color-section-label') }, silent: true },
      { type: 'text', left: '50%', top: 40, style: { text: '潮流个性', fontSize: 12, fill: readCssVar('--color-section-label'), align: 'center' }, silent: true },
      { type: 'text', left: '50%', bottom: 40, style: { text: '可爱萌系', fontSize: 12, fill: readCssVar('--color-section-label'), align: 'center' }, silent: true },
    ],
  };

  return (
    <ResponsiveChart
      option={option}
      height={340}
      ariaLabel="IP 定位四象限，横轴从女性向到男性或 ACG，纵轴从可爱萌系到潮流个性"
      summary="12 个代表性 IP 按受众方向与风格定位分布；该矩阵为基于历史商品特征的演示推演。"
    />
  );
}

function IpCard({ ip }) {
  return (
    <Card className="ip-card" size="small">
      <IpImage
        src={ipAssetPath(ip.slug, 'cover.jpg')}
        alt={ip.nameCn}
        className="ip-cover"
        fallback={<div className="ip-cover ip-cover-fallback">{ip.nameCn}</div>}
      />
      <div className="ip-card-body">
        <div className="ip-card-heading">
          <div className="ip-card-name">
            <IpImage src={ipAssetPath(ip.slug, 'logo.png')} alt="" className="ip-logo" fallback={null} />
            <div>
              <b>{ip.nameCn}</b>
              <span className="ip-name-en">{ip.name}</span>
            </div>
          </div>
          <Rate value={ip.potential} disabled className="ip-potential" aria-label={`合作潜力 ${ip.potential} 星`} />
        </div>
        <div className="ip-tags">
          {ip.styleTags.map((tag) => <Tag key={tag} color="purple">{tag}</Tag>)}
          <Tag>{ip.audience}</Tag>
        </div>
        <div className="ip-field"><span>适合品类</span>{ip.categories.join(' / ')}</div>
        <div className="ip-field"><span>代表角色</span>{ip.characters.join(' / ')}</div>
        <div className="ip-field"><span>设计资产</span>{ip.designAssets.join(' / ')}</div>
        <div className="ip-history">{ip.minisoHistory}</div>
      </div>
    </Card>
  );
}

export default function InsightBase() {
  const [data, setData] = useState(null);
  const [ipData, setIpData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [audience, setAudience] = useState('全部');
  const [style, setStyle] = useState('全部');

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [base, ipResource] = await Promise.all([getInsightBase(), getIpResource()]);
      setData(base || {});
      setIpData(ipResource || {});
    } catch (requestError) {
      setError(requestError);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const ipStats = ipData?.stats || [];
  const ipList = ipData?.ips || [];
  const audienceFilters = ipData?.audienceFilters || ['全部'];
  const styleFilters = ipData?.styleFilters || ['全部'];

  const filteredIps = useMemo(() => ipList.filter((ip) => (
    (audience === '全部' || ip.audienceGroup === audience)
    && (style === '全部' || ip.styleGroup === style)
  )), [ipList, audience, style]);

  if (loading) {
    return <><PageHeader title="名创内部 · IP 资源库" /><StateCard status="loading" /></>;
  }
  if (error) {
    return <><PageHeader title="名创内部 · IP 资源库" /><StateCard status="error" onRetry={load} emptyText="Insight Base 加载失败" /></>;
  }

  const hitProducts = data.hitProducts || [];
  const designLanguage = data.designLanguage || [];

  return (
    <div>
      <PageHeader
        title="名创内部 · IP 资源库"
        subtitle="机会 Agent 的策展弹药库，以及历史爆品与品牌设计语言资产"
      />

      <section className="ip-stats-band" aria-label="IP 资源概览">
        {ipStats.map((stat) => (
          <div key={stat.label} className="ip-stat">
            <div className="ip-stat-value">{stat.value}</div>
            <div className="ip-stat-label">{stat.label}</div>
          </div>
        ))}
        <div className="ip-stats-note">数据来源：名创官方披露</div>
      </section>

      <Card
        title="IP 定位矩阵"
        size="small"
        extra={<span className="ip-matrix-note">基于历史商品特征的 AI 定位，仅作演示参考</span>}
        style={{ marginBottom: 16 }}
      >
        <IpMatrix ips={ipList} />
      </Card>

      <div className="ip-filters" aria-label="IP 筛选">
        <Segmented options={audienceFilters} value={audience} onChange={setAudience} />
        <Segmented options={styleFilters} value={style} onChange={setStyle} />
      </div>

      {filteredIps.length === 0 ? (
        <Empty description="当前筛选下暂无 IP" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Row gutter={[16, 16]}>
          {filteredIps.map((ip) => (
            <Col xs={24} sm={12} lg={8} xl={6} key={ip.slug}>
              <IpCard ip={ip} />
            </Col>
          ))}
        </Row>
      )}

      <Row gutter={[16, 16]} style={{ marginTop: 24 }}>
        <Col xs={24} lg={14}>
          <Card title="历史爆品特征库" size="small">
            {hitProducts.length === 0 ? <Empty description="暂无历史爆品数据" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : hitProducts.map((product) => (
              <Card key={product.name} size="small" style={{ marginBottom: 8 }}>
                <div className="insight-product-heading">
                  <b>{product.name}</b>
                  <span>爆品指数 <b className="brand-accent-text">{product.index}</b></span>
                </div>
                <Progress percent={product.index} showInfo={false} strokeColor="var(--color-brand-accent)" size="small" style={{ margin: '4px 0' }} />
                <div>{(product.factors || []).map((factor) => <Tag key={factor} color="purple">{factor}</Tag>)}</div>
                <div className="insight-product-note">{product.note}</div>
              </Card>
            ))}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title="名创设计语言" size="small">
            {designLanguage.length === 0 ? <Empty description="暂无设计语言数据" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
              <>
                <div>{designLanguage.map((item) => <Tag key={item} color="geekblue">{item}</Tag>)}</div>
                <p className="insight-design-note">企划生成时作为品牌一致性约束注入创意设计模块</p>
              </>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
