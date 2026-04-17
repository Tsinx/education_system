import { useEffect } from 'react'
import { Button, Card, Col, Divider, Form, Input, Row, Select, Space, Switch, Tag, Typography, message } from 'antd'
import { getDefaultLlmSettings, loadLlmSettings, saveLlmSettings, type DefaultAiModel } from '../utils/llmSettings'

type AiSettingsFormValues = {
  autoGenerate: boolean
  defaultModel: DefaultAiModel
  apiKey: string
  qwenModel: string
}

export function SettingsPage() {
  const [messageApi, contextHolder] = message.useMessage()
  const [aiForm] = Form.useForm<AiSettingsFormValues>()
  const selectedModel = Form.useWatch('defaultModel', aiForm)

  useEffect(() => {
    aiForm.setFieldsValue(loadLlmSettings())
  }, [aiForm])

  const handleSave = async () => {
    const values = await aiForm.validateFields()
    saveLlmSettings({
      autoGenerate: values.autoGenerate,
      defaultModel: values.defaultModel,
      apiKey: values.apiKey ?? '',
      qwenModel: values.qwenModel ?? '',
    })
    messageApi.success('设置已保存，下一次 AI 生成会生效')
  }

  const handleRestoreDefaults = () => {
    const defaults = getDefaultLlmSettings()
    aiForm.setFieldsValue(defaults)
    saveLlmSettings(defaults)
    messageApi.success('已恢复默认设置')
  }

  return (
    <>
      {contextHolder}
      <div className="page-stack">
        <Card className="hero-panel">
          <div className="section-header">
            <div>
              <div className="hero-kicker">Notebook 偏好中心</div>
              <Typography.Title level={2} className="hero-title">
                调整平台的教学风格与生成偏好
              </Typography.Title>
              <Typography.Paragraph className="hero-subtitle">
                这里管理你的语言、默认模型、通知方式与 AI 生成习惯，让整个课程设计工作区保持稳定一致的行为。
              </Typography.Paragraph>
            </div>
            <Tag className="soft-tag">浅色教育主题</Tag>
          </div>
        </Card>

        <Row gutter={[16, 16]}>
          <Col xs={24} xl={12}>
            <Card className="notebook-panel" title="基本设置">
              <Form layout="vertical" initialValues={{ language: 'zh-CN', theme: 'light' }}>
                <Form.Item label="语言" name="language">
                  <Select
                    options={[
                      { value: 'zh-CN', label: '简体中文' },
                      { value: 'en-US', label: 'English' },
                    ]}
                  />
                </Form.Item>
                <Form.Item label="主题" name="theme">
                  <Select
                    options={[
                      { value: 'light', label: '浅色模式' },
                      { value: 'dark', label: '深色模式' },
                    ]}
                  />
                </Form.Item>
              </Form>
            </Card>
          </Col>

          <Col xs={24} xl={12}>
            <Card className="notebook-panel" title="通知设置">
              <Form layout="vertical" initialValues={{ emailNotify: false, taskNotify: true }}>
                <Form.Item label="任务完成后邮件通知" name="emailNotify" valuePropName="checked">
                  <Switch />
                </Form.Item>
                <Form.Item label="任务完成后站内通知" name="taskNotify" valuePropName="checked">
                  <Switch />
                </Form.Item>
              </Form>
            </Card>
          </Col>
        </Row>

        <Card className="notebook-panel" title="AI 生成设置">
          <Form form={aiForm} layout="vertical" initialValues={loadLlmSettings()}>
            <Row gutter={16}>
              <Col xs={24} md={12}>
                <Form.Item label="上传资料后自动触发 AI 生成" name="autoGenerate" valuePropName="checked">
                  <Switch />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item label="默认 AI 模型" name="defaultModel">
                  <Select
                    options={[
                      { value: 'deepseek', label: 'DeepSeek' },
                      { value: 'gpt4', label: 'GPT-4o' },
                      { value: 'qwen', label: '通义千问（已接通）' },
                    ]}
                  />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item label="API Key" name="apiKey">
              <Input.Password placeholder="请输入 AI 模型的 API Key" />
            </Form.Item>
            {selectedModel === 'qwen' && (
              <Form.Item label="千问模型名" name="qwenModel" tooltip="默认 qwen3.5-plus">
                <Input placeholder="例如：qwen3.5-plus" />
              </Form.Item>
            )}
            {selectedModel && selectedModel !== 'qwen' && (
              <Typography.Text type="secondary">
                当前版本先支持通义千问自填 API Key，其它模型的前端自填能力后续补齐。
              </Typography.Text>
            )}
          </Form>
        </Card>

        <Divider />
        <Space>
          <Button type="primary" onClick={() => void handleSave()}>保存设置</Button>
          <Button onClick={handleRestoreDefaults}>恢复默认</Button>
        </Space>
      </div>
    </>
  )
}
