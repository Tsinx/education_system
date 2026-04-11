import { useEffect, useRef, useState } from 'react'
import {
  BookOutlined,
  CalendarOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  DeleteOutlined,
  FileMarkdownOutlined,
  FileTextOutlined,
  FolderOutlined,
  InboxOutlined,
  LoadingOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Popconfirm,
  Progress,
  Row,
  Space,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd'
import { useNavigate } from 'react-router-dom'
import { bindMaterialsToCourse, createCourse, deleteCourse, fetchCourses } from '../api/client'
import { useConversionQueue } from '../hooks/useConversionQueue'
import type { Course } from '../types'

export function DashboardPage() {
  const [courses, setCourses] = useState<Course[]>([])
  const [modalOpen, setModalOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [messageApi, contextHolder] = message.useMessage()
  const [form] = Form.useForm()
  const navigate = useNavigate()

  const { files: convertedFiles, enqueue, pendingCount, clear: clearQueue } = useConversionQueue()

  const collectedFiles = useRef<File[]>([])

  useEffect(() => {
    fetchCourses().then(setCourses)
  }, [])

  const handleCreate = async () => {
    await form.validateFields()
    setCreating(true)
    try {
      const values = form.getFieldsValue()
      const course = await createCourse({
        name: values.name,
        description: values.description,
        hours: values.hours,
        sessions: values.sessions,
      })
      const pendingMaterialIds = convertedFiles.map((f) => f.id)
      if (pendingMaterialIds.length > 0) {
        await bindMaterialsToCourse(course.id, pendingMaterialIds)
      }
      messageApi.success(`课程「${course.name}」创建成功，资料将自动切片并构建知识库`)
      setModalOpen(false)
      form.resetFields()
      clearQueue()
      setCourses(await fetchCourses())
      navigate(`/courses/${course.id}`)
    } finally {
      setCreating(false)
    }
  }

  const handleModalClose = () => {
    setModalOpen(false)
    clearQueue()
  }

  const handleDelete = async (course: Course) => {
    await deleteCourse(course.id)
    messageApi.success(`课程「${course.name}」已删除`)
    setCourses(await fetchCourses())
    window.setTimeout(() => {
      void fetchCourses().then(setCourses)
    }, 1200)
  }

  const handleBeforeUpload = (file: File) => {
    collectedFiles.current.push(file)
    return false
  }

  const handleUploadChange = () => {
    if (collectedFiles.current.length > 0) {
      const files = [...collectedFiles.current]
      collectedFiles.current = []
      enqueue(files)
    }
  }

  const statusIcon = (status: string) => {
    switch (status) {
      case 'converting':
        return <LoadingOutlined style={{ color: '#1677ff', fontSize: 16 }} />
      case 'done':
        return <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 16 }} />
      case 'error':
        return <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 16 }} />
      default:
        return <ClockCircleOutlined style={{ color: '#999', fontSize: 16 }} />
    }
  }

  const statusText = (item: typeof convertedFiles[number]) => {
    switch (item.status) {
      case 'pending':
        return '等待中'
      case 'converting':
        return '转换中…'
      case 'done':
        return `${item.charCount.toLocaleString()} 字符`
      case 'error':
        return '转换失败'
    }
  }

  const stats = [
    { label: '课程总数', value: courses.length, hint: '已建立的课程项目' },
    { label: '待处理资料', value: pendingCount, hint: '正在转换与切片' },
    {
      label: '总学时',
      value: courses.reduce((sum, item) => sum + (item.hours || 0), 0),
      hint: '课程记录中的累计学时',
    },
  ]

  return (
    <>
      {contextHolder}
      <div className="page-stack">
        <Card className="hero-panel">
          <div className="section-header">
            <div>
              <div className="hero-kicker">
                <FolderOutlined />
                教学 Notebook 工作台
              </div>
              <Typography.Title level={2} className="hero-title">
                用资料驱动课程设计，而不是从空白页开始
              </Typography.Title>
              <Typography.Paragraph className="hero-subtitle">
                新建课程后即可持续导入资料，系统自动切片、构建知识库与知识图谱，再按 NotebookLM 风格继续生成大纲、教案与教学计划。
              </Typography.Paragraph>
            </div>
            <Space>
              <Button icon={<CalendarOutlined />}>学期视图</Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
                新建课程
              </Button>
            </Space>
          </div>
        </Card>

        <Row gutter={[16, 16]}>
          {stats.map((item) => (
            <Col key={item.label} xs={24} md={8}>
              <Card className="stat-panel">
                <div className="stat-label">{item.label}</div>
                <div className="stat-value">{item.value}</div>
                <Typography.Text type="secondary">{item.hint}</Typography.Text>
              </Card>
            </Col>
          ))}
        </Row>

        <Card className="notebook-panel">
          <div className="section-header">
            <div>
              <Typography.Title level={4} className="section-title">
                我的课程
              </Typography.Title>
              <Typography.Paragraph className="section-description">
                每门课程都像一个 notebook，围绕资料、知识与生成任务持续迭代。
              </Typography.Paragraph>
            </div>
            <Tag className="soft-tag">{courses.length} 个课程项目</Tag>
          </div>

          {courses.length === 0 ? (
            <Card className="surface-panel">
              <Space direction="vertical" size={8}>
                <Typography.Title level={5} style={{ margin: 0 }}>
                  还没有课程
                </Typography.Title>
                <Typography.Text type="secondary">
                  点击右上角「新建课程」，上传课程资料后即可开始构建知识库与后续成果。
                </Typography.Text>
              </Space>
            </Card>
          ) : (
            <div className="course-grid">
              {courses.map((course) => (
                <Card key={course.id} className="course-card floating-subtle">
                  <Space direction="vertical" size={14} style={{ width: '100%' }}>
                    <Space align="start" style={{ justifyContent: 'space-between', width: '100%' }}>
                      <div>
                        <div className="course-card-title">{course.name}</div>
                        <Typography.Text type="secondary">{course.created_at}</Typography.Text>
                      </div>
                      <Popconfirm
                        title="确认删除"
                        description={`确定要删除课程「${course.name}」吗？此操作不可恢复。`}
                        onConfirm={() => handleDelete(course)}
                        okText="删除"
                        cancelText="取消"
                        okButtonProps={{ danger: true }}
                      >
                        <Button type="text" danger icon={<DeleteOutlined />} size="small" />
                      </Popconfirm>
                    </Space>

                    <Typography.Paragraph className="course-card-desc" ellipsis={{ rows: 2 }}>
                      {course.description || '暂无课程简介，可进入课程后继续完善教学目标与资料结构。'}
                    </Typography.Paragraph>

                    <Space wrap>
                      <Tag className="soft-tag">
                        <ClockCircleOutlined style={{ marginRight: 6 }} />
                        {course.hours || 0} 学时
                      </Tag>
                      <Tag className="soft-tag">
                        <CalendarOutlined style={{ marginRight: 6 }} />
                        {course.sessions || 0} 课次
                      </Tag>
                      <Tag className="soft-tag">
                        <BookOutlined style={{ marginRight: 6 }} />
                        {course.chapter_count || 0} 章节
                      </Tag>
                    </Space>

                    <Space>
                      <Button type="primary" onClick={() => navigate(`/courses/${course.id}`)}>
                        进入课程
                      </Button>
                      <Button icon={<FileTextOutlined />} onClick={() => navigate(`/courses/${course.id}/knowledge-graph`)}>
                        知识图谱
                      </Button>
                    </Space>
                  </Space>
                </Card>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Modal
        title="新建课程"
        open={modalOpen}
        onOk={handleCreate}
        onCancel={handleModalClose}
        confirmLoading={creating}
        okText="创建课程"
        cancelText="取消"
        width={640}
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          preserve={false}
        >
          <Form.Item label="课程名称" name="name" rules={[{ required: true, message: '请输入课程名称' }]}>
            <Input placeholder="如：高等数学（上）" />
          </Form.Item>

          <Row gutter={16}>
            <Col span={8}>
              <Form.Item label="课时（学时）" name="hours">
                <InputNumber min={0} max={999} placeholder="如 64" style={{ width: '100%' }} onChange={(v) => {
                  if (v != null && !form.getFieldValue('sessionsManual')) {
                    form.setFieldValue('sessions', Math.ceil(v / 2))
                  }
                }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="课次" name="sessions">
                <InputNumber min={1} max={999} placeholder="默认 学时/2" style={{ width: '100%' }} onChange={() => {
                  form.setFieldValue('sessionsManual', true)
                }} />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item label="课程简介" name="description">
            <Input.TextArea rows={2} placeholder="简要描述课程内容与目标" />
          </Form.Item>

          <Form.Item label="上传课程资料">
            <Upload.Dragger
              className="notebook-dropzone"
              multiple
              beforeUpload={handleBeforeUpload}
              onChange={handleUploadChange}
              showUploadList={false}
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p>拖拽文件到此处，或点击选择</p>
              <p className="ant-upload-hint">支持 PDF / Word / PPT / 图片 / 文本，上传后自动切片和构建知识库</p>
            </Upload.Dragger>
          </Form.Item>

          {convertedFiles.length > 0 && (
            <Form.Item label={
              <Space>
                <FileMarkdownOutlined />
                资料处理状态
                {pendingCount > 0 && (
                  <Progress
                    percent={Math.round(((convertedFiles.length - pendingCount) / convertedFiles.length) * 100)}
                    size="small"
                    style={{ width: 100, marginBottom: -2 }}
                  />
                )}
              </Space>
            }>
              <List
                className="notebook-list"
                size="small"
                dataSource={convertedFiles}
                renderItem={(item) => (
                  <List.Item>
                    <List.Item.Meta
                      avatar={statusIcon(item.status)}
                      title={<Typography.Text style={{ fontSize: 13 }}>{item.filename}</Typography.Text>}
                      description={
                        <Space direction="vertical" size={0}>
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            {statusText(item)}
                          </Typography.Text>
                          {item.status !== 'done' && item.processStage && (
                            <Typography.Text type="secondary" style={{ fontSize: 11, color: '#999' }}>
                              {item.processStage}
                            </Typography.Text>
                          )}
                        </Space>
                      }
                    />
                  </List.Item>
                )}
              />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </>
  )
}
