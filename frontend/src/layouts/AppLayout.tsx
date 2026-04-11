import {
  DashboardOutlined,
  ReadOutlined,
  SettingOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { Button, Layout, Menu, Space, Tag, Typography } from 'antd'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

const { Header, Content, Sider } = Layout

export function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()

  const selectedKey =
    location.pathname.startsWith('/settings')
      ? '/settings'
      : location.pathname.startsWith('/profile')
        ? '/profile'
        : '/dashboard'
  const routeTitle =
    location.pathname.startsWith('/courses/')
      ? location.pathname.endsWith('/knowledge-graph')
        ? '课程知识图谱'
        : '课程工作区'
      : location.pathname === '/settings'
        ? '偏好设置'
        : location.pathname === '/profile'
          ? '教师主页'
          : '课程工作台'

  return (
    <Layout className="app-shell">
      <Sider width={272} theme="light" className="app-sider">
        <div className="logo-panel notebook-brand">
          <div className="brand-mark">
            <ReadOutlined />
          </div>
          <Space direction="vertical" size={2}>
            <Typography.Title level={4} style={{ margin: 0 }}>
              Edu Notebook
            </Typography.Title>
            <Typography.Text type="secondary">面向教师的课程设计工作台</Typography.Text>
          </Space>
        </div>
        <Menu
          className="notebook-menu"
          mode="inline"
          selectedKeys={[selectedKey]}
          onClick={({ key }) => navigate(key)}
          items={[
            { key: '/dashboard', icon: <DashboardOutlined />, label: '工作台' },
            { key: '/settings', icon: <SettingOutlined />, label: '设置' },
            { key: '/profile', icon: <UserOutlined />, label: '个人中心' },
          ]}
        />
        <div className="side-note-card">
          <Typography.Text strong>Notebook 风格工作流</Typography.Text>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            上传资料、自动构建知识、再通过多阶段 AI 生成课程成果。
          </Typography.Paragraph>
        </div>
      </Sider>
      <Layout className="app-main">
        <Header className="top-header">
          <Space direction="vertical" size={0}>
            <Typography.Text className="header-eyebrow">Notebook Workspace</Typography.Text>
            <Typography.Title level={3} style={{ color: '#1f2a22', margin: 0 }}>
              {routeTitle}
            </Typography.Title>
          </Space>
          <Space>
            <Tag className="soft-tag">教育场景</Tag>
            <Tag className="soft-tag">浅色主题</Tag>
            <Button type="primary" onClick={() => navigate('/dashboard')}>新建笔记式课程</Button>
          </Space>
        </Header>
        <Content className="content-area">
          <div className="content-inner">
            <Outlet />
          </div>
        </Content>
      </Layout>
    </Layout>
  )
}
