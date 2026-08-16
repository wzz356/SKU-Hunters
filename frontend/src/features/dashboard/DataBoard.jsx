/* ============================================================
 * SKU Hunters · DataBoard（数据看板 · 品类大盘）
 * 使用 api/dashboard.js 的 getDataBoard，接口失败不回退 fixture。
 * 四态：loading / error / empty / success；图表用 ResponsiveChart
 * （aria-label + 可见文本摘要）；热销表格 375 下局部横向滚动。
 * 响应式：375 单列，768/1440 双列。
 * ============================================================ */

import { useEffect, useState } from 'react';
import { Card, Row, Col, Table, Tag, Progress, Empty } from 'antd';
import { getDataBoard } from '../../api/dashboard';
import ResponsiveChart from '../../shared/components/ResponsiveChart';
import StateCard from '../../shared/components/StateCard';
import { readCssVar } from '../../shared/utils/cssTokens';
import PageHeader from '../plans/components/PageHeader';

export default function DataBoard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await getDataBoard();
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
        <PageHeader title="数据看板 · 品类大盘" />
        <StateCard status="loading" />
      </div>
    );
  }
  if (error) {
    return (
      <div>
        <PageHeader title="数据看板 · 品类大盘" />
        <StateCard status="error" onRetry={load} emptyText="大盘数据加载失败" />
      </div>
    );
  }

  const categoryRank = data.categoryRank || [];
  const hotProducts = data.hotProducts || [];
  const priceBands = data.priceBands || [];
  const voiceTrend = data.voiceTrend || { weeks: [], xhs: [], douyin: [] };
  const hasVoiceTrend = voiceTrend.weeks?.length > 0;
  const sourceLabel = data.sourceLabel || '数据来源未知';

  const rankOption = {
    tooltip: {},
    grid: { left: 70, right: 30, top: 16, bottom: 24 },
    xAxis: { type: 'value', name: '热度' },
    yAxis: { type: 'category', data: categoryRank.map((c) => c.name).reverse() },
    series: [
      {
        type: 'bar',
        data: categoryRank.map((c) => c.heat).reverse(),
        itemStyle: { color: readCssVar('--color-brand-accent'), borderRadius: [0, 6, 6, 0] },
        barWidth: 16,
      },
    ],
  };

  const voiceOption = {
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0 },
    grid: { left: 44, right: 16, top: 16, bottom: 44 },
    xAxis: { type: 'category', data: voiceTrend.weeks || [] },
    yAxis: { type: 'value', name: '声量' },
    series: [
      { name: '小红书', type: 'line', smooth: true, data: voiceTrend.xhs || [], itemStyle: { color: readCssVar('--color-brand-accent') } },
      { name: '抖音', type: 'line', smooth: true, data: voiceTrend.douyin || [], itemStyle: { color: readCssVar('--color-action-primary') } },
    ],
  };

  const columns = [
    { title: '排名', dataIndex: 'rank', width: 60 },
    { title: '商品', dataIndex: 'name', width: 180 },
    { title: '价格', dataIndex: 'price', width: 80, render: (v) => `¥${v}` },
    { title: '核心卖点', dataIndex: 'point', width: 140, render: (v) => <Tag>{v}</Tag> },
    { title: '热度指数', dataIndex: 'sales', width: 140, render: (v) => <Progress percent={v} showInfo={false} strokeColor="var(--color-brand-accent)" size="small" /> },
  ];

  return (
    <div>
      <PageHeader title="数据看板 · 品类大盘" subtitle="基于采集记录的实时聚合，不把互动量伪装成销量" />
      <div style={{ marginBottom: 16 }}>
        <Tag color={data.dataSource === 'feishu' ? 'blue' : 'default'}>{sourceLabel}</Tag>
        {data.recordCount != null ? <span style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>共 {data.recordCount} 条记录</span> : null}
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="品类热度排行" size="small">
            {categoryRank.length === 0 ? (
              <Empty description="暂无品类热度数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <ResponsiveChart
                option={rankOption}
                height={260}
                ariaLabel="品类热度排行条形图"
                summary="各品类热度对比，按热度从高到低排列"
              />
            )}
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card title="社媒声量趋势（小风扇品类）" size="small">
            {!hasVoiceTrend ? (
              <Empty description="暂无声量趋势数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <ResponsiveChart
                option={voiceOption}
                height={260}
                ariaLabel="小红书与抖音声量趋势折线图"
                summary="近 8 周小红书与抖音声量走势，抖音声量整体高于小红书"
              />
            )}
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card title="热销商品榜" size="small">
            {hotProducts.length === 0 ? (
              <Empty description="暂无热销商品数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <Table
                columns={columns}
                dataSource={hotProducts}
                rowKey="rank"
                pagination={false}
                size="small"
                scroll={{ x: 600 }}
              />
            )}
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card title="价格带分布" size="small">
            {priceBands.length === 0 ? (
              <Empty description="暂无价格带数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              priceBands.map((b) => (
                <div key={b.band} style={{ marginBottom: 10, fontSize: 13 }}>
                  {b.band}
                  <Progress
                    percent={b.pct}
                    showInfo={false}
                    strokeColor="var(--color-action-primary)"
                    size="small"
                    style={{ display: 'inline-block', width: '62%', margin: '0 10px' }}
                  />
                  <b>{b.pct}%</b>
                </div>
              ))
            )}
            <p style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 12 }}>价格带按采集记录中的价格字段统计；缺失价格的记录不计入分母。</p>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
