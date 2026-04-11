import { Button, Card, Col, Divider, Form, Input, Row, Select, Space, Switch, Tag, Typography, message } from 'antd'

export function SettingsPage() {
  const [messageApi, contextHolder] = message.useMessage()

  const handleSave = () => {
    messageApi.success('设置已保存')
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
          <Form layout="vertical" initialValues={{ autoGenerate: true, defaultModel: 'deepseek' }}>
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
                      { value: 'qwen', label: '通义千问' },
                    ]}
                  />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item label="API Key" name="apiKey">
              <Input.Password placeholder="请输入 AI 模型的 API Key" />
            </Form.Item>
          </Form>
        </Card>

        <Divider />
        <Space>
          <Button type="primary" onClick={handleSave}>保存设置</Button>
          <Button>恢复默认</Button>
        </Space>
      </div>
    </>
  )
}
