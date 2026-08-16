/* ============================================================
 * SKU Hunters · BriefEditModal（企划约束编辑弹窗）
 * 攻坚会 P0（2026-08-16）：约束提交后不可改不合理 → 新增编辑入口。
 * 风险提示：已有下游产物（洞察/机会/企划卡）时明确告知"修改将作废重来"，
 * 避免用户为改约束而重复创建企划。
 * 字段与校验规则和 NewPlan 一致（单一事实源：PlanBrief schema）。
 * ============================================================ */

import { useEffect } from 'react';
import { Form, Select, Input, InputNumber, Modal, Checkbox, Row, Col, Alert } from 'antd';
import { fromForm } from '../../../shared/utils/normalizeBrief';

// 与 NewPlan 相同的可选项（UI 选项，非 fixture 数据）
const CATEGORIES = ['小风扇', '保温杯', '香薰', '桌面摆件', '雨伞', '冰袖'];
const MARKETS = ['中国大陆', '东南亚', '日本', '欧美'];
const IP_OPTIONS = ['三丽鸥', '迪士尼', 'Chiikawa', '线条小狗', '不带 IP'];
const GOAL_OPTIONS = ['夏季销售提升', '打造IP爆款', '拓展新人群', '提升连带率'];

/** 后端 brief（camel 消费形态）→ 表单初值 */
function toFormValues(brief) {
  return {
    theme: brief?.theme || '',
    category: brief?.category || undefined,
    market: brief?.market || '中国大陆',
    audience: brief?.audience || '',
    priceMin: brief?.priceRange?.[0] ?? 39,
    priceMax: brief?.priceRange?.[1] ?? 99,
    costLimit: brief?.costLimit ?? 25,
    ipStrategy: brief?.ipStrategy || [],
    launchWindow: brief?.launchWindow || '',
    goals: brief?.goals || [],
  };
}

export default function BriefEditModal({ open, brief, hasDownstream, submitting, onCancel, onSubmit }) {
  const [form] = Form.useForm();

  // 每次打开用当前 brief 重置表单（避免残留上次编辑值）
  useEffect(() => {
    if (open) form.setFieldsValue(toFormValues(brief));
  }, [open, brief, form]);

  const handleOk = async () => {
    const values = await form.validateFields();
    onSubmit(fromForm(values));
  };

  return (
    <Modal
      title="编辑企划约束"
      open={open}
      onOk={handleOk}
      onCancel={onCancel}
      okText="保存约束"
      cancelText="取消"
      confirmLoading={submitting}
      destroyOnHidden
      width={640}
    >
      {hasDownstream ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="修改约束将作废已生成的下游产物"
          description="本任务已生成洞察/机会/企划卡。保存后这些产物将全部清空、流程回到「企划约束」步骤，需要重新生成。归档任务不可编辑。"
        />
      ) : (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="约束由商品经理下达，AI 在约束内做有依据的创意"
        />
      )}

      <Form form={form} layout="vertical" initialValues={toFormValues(brief)}>
        <Form.Item
          label="企划主题"
          name="theme"
          rules={[{ required: true, message: '请填写企划主题' }]}
        >
          <Input maxLength={80} />
        </Form.Item>

        <Row gutter={16}>
          <Col xs={24} sm={12}>
            <Form.Item
              label="品类"
              name="category"
              rules={[{ required: true, message: '请选择品类' }]}
            >
              <Select options={CATEGORIES.map((c) => ({ value: c, label: c }))} />
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item label="目标市场" name="market">
              <Select options={MARKETS.map((m) => ({ value: m, label: m }))} />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item label="目标人群" name="audience">
          <Input maxLength={80} />
        </Form.Item>

        <Row gutter={16}>
          <Col xs={24} sm={12}>
            <Form.Item
              label="价格带下限（元）"
              name="priceMin"
              rules={[{ required: true, message: '请填写价格带下限' }]}
            >
              <InputNumber min={1} style={{ width: '100%' }} />
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
              <InputNumber min={1} style={{ width: '100%' }} />
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
          <InputNumber min={0} style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item label="IP 策略" name="ipStrategy">
          <Checkbox.Group options={IP_OPTIONS} />
        </Form.Item>

        <Form.Item label="上新窗口" name="launchWindow">
          <Input maxLength={60} />
        </Form.Item>

        <Form.Item label="商业目标" name="goals">
          <Checkbox.Group options={GOAL_OPTIONS} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
