import { Avatar, Button, Card, Col, Divider, Form, Input, Row, Space, Statistic, Typography, message } from 'antd'
import { BookOutlined, FileTextOutlined, UserOutlined } from '@ant-design/icons'

export function ProfilePage() {
  const [messageApi, contextHolder] = message.useMessage()

  const handleSave = () => {
    messageApi.success('个人信息已更新')
  }

  return (
    <>
      {contextHolder}
      <div className="page-stack">
        <Card className="hero-panel">
          <Space size={24} align="center">
            <Avatar size={88} icon={<UserOutlined />} style={{ backgroundColor: '#5f7f67' }} />
            <div>
              <div className="hero-kicker">Teacher Notebook Profile</div>
              <Typography.Title level={2} className="hero-title">
                张老师
              </Typography.Title>
              <Typography.Paragraph className="hero-subtitle">
                计算机科学与技术学院 · 面向课程设计、资料组织与教学成果生成的个人工作台。
              </Typography.Paragraph>
            </div>
          </Space>
        </Card>

        <Row gutter={[16, 16]}>
          <Col xs={24} xl={15}>
            <Card className="notebook-panel" title="个人信息">
              <Form
                layout="vertical"
                initialValues={{ name: '张老师', email: 'zhang@university.edu.cn', department: '计算机科学与技术学院', title: '副教授' }}
              >
                <Row gutter={16}>
                  <Col xs={24} md={12}>
                    <Form.Item label="姓名" name="name">
                      <Input />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={12}>
                    <Form.Item label="邮箱" name="email">
                      <Input />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={12}>
                    <Form.Item label="院系" name="department">
                      <Input />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={12}>
                    <Form.Item label="职称" name="title">
                      <Input />
                    </Form.Item>
                  </Col>
                </Row>
              </Form>
            </Card>
          </Col>

          <Col xs={24} xl={9}>
            <div className="stack-grid">
              <Card className="stat-panel">
                <Statistic title="已创建课程" value={3} prefix={<BookOutlined />} />
              </Card>
              <Card className="stat-panel">
                <Statistic title="已生成大纲" value={2} prefix={<FileTextOutlined />} />
              </Card>
              <Card className="stat-panel">
                <Statistic title="上传资料数" value={12} />
              </Card>
            </div>
          </Col>
        </Row>

        <Card className="notebook-panel" title="使用概览">
          <div className="detail-metrics">
            <div className="metric-box">
              <Typography.Text strong>已生成教案</Typography.Text>
              <div className="stat-value" style={{ fontSize: 24 }}>1</div>
            </div>
            <div className="metric-box">
              <Typography.Text strong>生成 PPT 数</Typography.Text>
              <div className="stat-value" style={{ fontSize: 24 }}>0</div>
            </div>
            <div className="metric-box">
              <Typography.Text strong>注册时间</Typography.Text>
              <div style={{ marginTop: 10, fontSize: 18, fontWeight: 600 }}>2025-03-01</div>
            </div>
          </div>
        </Card>

        <Divider />
        <Space>
          <Button type="primary" onClick={handleSave}>保存修改</Button>
          <Button danger>修改密码</Button>
        </Space>
      </div>
    </>
  )
}
