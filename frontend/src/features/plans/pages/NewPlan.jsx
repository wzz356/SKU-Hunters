/* ============================================================
 * SKU Hunters · NewPlan（新建企划）
 * 使用 api/plans.js 的 createPlan，不 import fixtures / 旧 api。
 * 表单分组：基本信息 + 商业约束；跨字段校验（价格带 / 成本与零售价关系）。
 * 提交防重复 + 422 字段映射；离开确认（beforeunload + 取消弹窗）。
 * 响应式：375 单列，价格上下限独立成列可读。
 * ============================================================ */

import { useEffect, useRef, useState } from 'react';
import { useNavigate, useBlocker } from 'react-router-dom';
import { Form, Select, Input, InputNumber, Button, Card, Checkbox, Row, Col, Alert, Modal } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { createPlan } from '../../../api/plans';
import { fromForm } from '../../../shared/utils/normalizeBrief';

// 品类 / 市场 / IP / 目标 的可选项（UI 选项，非 fixture 数据）
const CATEGORIES = ['小风扇', '保温杯', '香薰', '桌面摆件', '雨伞', '冰袖'];
const MARKETS = ['中国大陆', '东南亚', '日本', '欧美'];
const IP_OPTIONS = ['三丽鸥', '迪士尼', 'Chiikawa', '线条小狗', '不带 IP'];
const GOAL_OPTIONS = ['夏季销售提升', '打造IP爆款', '拓展新人群', '提升连带率'];

// 后端 snake_case 字段 → 表单字段（用于 422 映射）
const FIELD_MAP = {
  theme: 'theme',
  category: 'category',
  market: 'market',
  audience: 'audience',
  price_range: ['priceMin', 'priceMax'],
  cost_limit: 'costLimit',
  ip_strategy: 'ipStrategy',
  launch_window: 'launchWindow',
  goals: 'goals',
};

// 从后端 422 的 message 提取字段并映射到表单字段
function mapServerErrors(detail) {
  const message = detail?.error?.message || '';
  const errors = {};
  let matched = false;
  for (const [snake, field] of Object.entries(FIELD_MAP)) {
    if (message.includes(snake)) {
      const targets = Array.isArray(field) ? field : [field];
      targets.forEach((f) => {
        errors[f] = { message };
      });
      matched = true;
    }
  }
  return { errors, matched };
}

export default function NewPlan() {
  const nav = useNavigate();
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(false);
  const [pageError, setPageError] = useState(null);

  // 应用内导航守卫：dirty 时任何导航（侧栏/后退/取消）都需确认
  const blocker = useBlocker(() => dirtyRef.current);

  useEffect(() => {
    if (blocker.state === 'blocked') {
      Modal.confirm({
        title: '离开此页面？',
        content: '你填写的内容尚未保存，离开后将丢失。',
        okText: '离开',
        cancelText: '继续填写',
        onOk: () => blocker.proceed(),
        onCancel: () => blocker.reset(),
      });
    }
  }, [blocker]);

  // 浏览器刷新/关闭：有未保存修改时提示
  useEffect(() => {
    const handler = (e) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  // 取消：dirty 时由 useBlocker 自动弹确认拦截，非 dirty 直接返回
  const handleCancel = () => nav('/');

  const onFinish = async (values) => {
    if (submitting) return; // 防重复提交
    setSubmitting(true);
    setPageError(null);
    try {
      const brief = fromForm(values);
      const res = await createPlan(brief);
      if (res?.plan_id) {
        dirtyRef.current = false;
        setDirty(false); // 已提交，离开无需再确认
        nav(`/tasks/${res.plan_id}`);
      } else {
        setPageError('创建失败：后端未返回 plan_id');
      }
    } catch (e) {
      if (e?.status === 422) {
        const { errors, matched } = mapServerErrors(e?.detail);
        if (matched) {
          form.setFields(Object.entries(errors).map(([name, v]) => ({ name, errors: [v.message] })));
        } else {
          setPageError(`提交内容不完整：${e?.message || '请检查必填项'}`);
        }
      } else {
        setPageError(`创建失败：${e?.message || '请检查后端服务是否在线'}`);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ maxWidth: 760 }}>
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'flex-start', gap: 8 }}>
        <Button
          type="text"
          icon={<ArrowLeftOutlined />}
          aria-label="返回任务中心"
          onClick={() => nav('/')}
          style={{ marginTop: 2 }}
        />
        <div>
          <h2 style={{ margin: 0 }}>新建新品企划</h2>
          <p style={{ margin: '4px 0 0', color: 'var(--color-text-secondary)', fontSize: 13 }}>
            约束由商品经理下达，AI 在约束内做有依据的创意
          </p>
        </div>
      </div>

      {pageError ? (
        <Alert type="error" showIcon role="alert" message={pageError} style={{ marginBottom: 16 }} />
      ) : null}

      <Form
        form={form}
        layout="vertical"
        onFinish={onFinish}
        onValuesChange={() => {
          dirtyRef.current = true;
          setDirty(true);
        }}
        initialValues={{
          market: '中国大陆',
          priceMin: 39,
          priceMax: 99,
          costLimit: 25,
          ipStrategy: [],
          goals: [],
        }}
      >
        {/* ── 基本信息 ── */}
        <Card title="基本信息" size="small" style={{ marginBottom: 16 }}>
          <Form.Item
            label="企划主题"
            name="theme"
            rules={[{ required: true, message: '请填写企划主题' }]}
          >
            <Input placeholder="如 2027夏季户外生活系列" maxLength={80} />
          </Form.Item>

          <Form.Item
            label="品类"
            name="category"
            rules={[{ required: true, message: '请选择品类' }]}
          >
            <Select
              placeholder="选择品类"
              options={CATEGORIES.map((c) => ({ value: c, label: c }))}
            />
          </Form.Item>

          <Row gutter={16}>
            <Col xs={24} sm={12}>
              <Form.Item label="目标市场" name="market">
                <Select options={MARKETS.map((m) => ({ value: m, label: m }))} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item label="目标人群" name="audience">
                <Input placeholder="如 18-30岁年轻女性" maxLength={80} />
              </Form.Item>
            </Col>
          </Row>
        </Card>

        {/* ── 商业约束 ── */}
        <Card title="商业约束" size="small" style={{ marginBottom: 16 }}>
          <Row gutter={16}>
            <Col xs={24} sm={12}>
              <Form.Item
                label="价格带下限（元）"
                name="priceMin"
                rules={[{ required: true, message: '请填写价格带下限' }]}
              >
                <InputNumber min={1} style={{ width: '100%' }} placeholder="如 39" />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item
                label="价格带上限（元）"
                name="priceMax"
                dependencies={['priceMin']}
                rules={[
                  { required: true, message: '请填写价格带上限' },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      const min = getFieldValue('priceMin');
                      if (min != null && value != null && value < min) {
                        return Promise.reject(new Error('价格带上限不能低于下限'));
                      }
                      return Promise.resolve();
                    },
                  }),
                ]}
              >
                <InputNumber min={1} style={{ width: '100%' }} placeholder="如 99" />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            label="成本上限（元）"
            name="costLimit"
            dependencies={['priceMin']}
            rules={[
              { required: true, message: '请填写成本上限' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (value != null && value <= 0) {
                    return Promise.reject(new Error('成本上限必须大于 0'));
                  }
                  const min = getFieldValue('priceMin');
                  if (value != null && min != null && value >= min) {
                    return Promise.reject(new Error('成本上限应低于价格带下限，保证毛利空间'));
                  }
                  return Promise.resolve();
                },
              }),
            ]}
          >
            <InputNumber min={0} style={{ width: '100%' }} placeholder="如 25" />
          </Form.Item>

          <Form.Item label="IP 策略" name="ipStrategy">
            <Checkbox.Group options={IP_OPTIONS} />
          </Form.Item>

          <Form.Item label="上新窗口" name="launchWindow">
            <Input placeholder="如 2027年5月（夏季前）" maxLength={60} />
          </Form.Item>

          <Form.Item label="商业目标" name="goals">
            <Checkbox.Group options={GOAL_OPTIONS} />
          </Form.Item>
        </Card>

        {/* ── 操作区：主 CTA + 取消次操作 ── */}
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <Button type="primary" htmlType="submit" loading={submitting} style={{ minWidth: 160 }}>
            创建企划，进入洞察
          </Button>
          <Button onClick={handleCancel} disabled={submitting}>
            取消
          </Button>
        </div>
      </Form>
    </div>
  );
}
