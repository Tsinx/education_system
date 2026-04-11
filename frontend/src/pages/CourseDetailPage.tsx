import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ArrowLeftOutlined,
  BookOutlined,
  CalendarOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  DownloadOutlined,
  FileMarkdownOutlined,
  FileTextOutlined,
  InboxOutlined,
  LoadingOutlined,
  NumberOutlined,
  PlusOutlined,
  ThunderboltOutlined,
  UploadOutlined,
  SyncOutlined,
  FileProtectOutlined,
  EditOutlined,
  DeleteOutlined,
} from '@ant-design/icons'
import {
  Button,
  Card,
  Col,
  InputNumber,
  Input,
  List,
  Modal,
  Progress,
  Radio,
  Row,
  Space,
  Tag,
  Typography,
  Upload,
  message,
  Divider,
  Popconfirm,
} from 'antd'
import axios from 'axios'
import { useNavigate, useParams } from 'react-router-dom'
import {
  addChapter,
  buildLessonBatchExportUrl,
  buildExportUrl,
  buildStreamUrl,
  fetchAiResultDetail,
  fetchAiResults,
  fetchChapters,
  fetchCourses,
  deleteMaterial,
  fetchMaterialDetail,
  startAiGeneration,
  refineCourseKnowledgeGraph,
} from '../api/client'
import { useConversionQueue } from '../hooks/useConversionQueue'
import type { AiOutputType, AiResultItem, Chapter, Course } from '../types'

const statusColorMap: Record<string, string> = {
  queued: '#999',
  running: '#1677ff',
  done: '#52c41a',
  failed: '#ff4d4f',
}

const statusLabelMap: Record<string, string> = {
  queued: '排队中',
  running: '生成中',
  done: '已完成',
  failed: '失败',
}

type StructureNode = {
  section: string
  key_points: string[]
}

type MaterialSummaryCard = {
  complexity?: 'multi_chapter' | 'single_chapter' | 'flat'
  title?: string
  chapter_title?: string
  document_type?: string
  summary?: string
  keywords?: string[]
  structure?: StructureNode[]
  key_points?: string[]
  teaching_value?: string
  granularity_hint?: string
}

type LessonPlanScope = 'auto' | 'single' | 'multiple' | 'semester'

function resolveSemesterLessonCount(sessions?: number, hours?: number) {
  if (sessions && sessions > 0) return Math.min(Math.max(sessions, 1), 64)
  if (hours && hours > 0) return Math.min(Math.max(Math.ceil(hours / 2), 1), 64)
  return 16
}

function detectLessonPlanIntent(guidance: string) {
  const text = guidance.trim()
  if (!text) return { scope: 'semester' as const, count: undefined, explicit: false, reason: '未检测到篇数要求，默认整学期' }
  if (/(一篇|1篇|单篇|一节|单节|单次|一次课)/.test(text)) {
    return { scope: 'single' as const, count: 1, explicit: true, reason: '检测到单篇语义' }
  }
  const match = text.match(/([2-9]|[1-4]\d)\s*(篇|节|次课)/)
  if (match) {
    return {
      scope: 'multiple' as const,
      count: Number(match[1]),
      explicit: true,
      reason: '检测到明确篇数',
    }
  }
  if (/(多篇|多节|系列|整学期|全学期|全部课次)/.test(text)) {
    return { scope: 'semester' as const, count: undefined, explicit: true, reason: '检测到整学期语义' }
  }
  return { scope: 'semester' as const, count: undefined, explicit: false, reason: '未检测到篇数要求，默认整学期' }
}

function parsePositiveInt(raw?: string) {
  if (!raw) return undefined
  const n = Number(raw)
  if (!Number.isFinite(n) || n <= 0) return undefined
  return Math.floor(n)
}

export function CourseDetailPage() {
  const { courseId } = useParams<{ courseId: string }>()
  const navigate = useNavigate()
  const [course, setCourse] = useState<Course>()
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [newTitle, setNewTitle] = useState('')
  const [adding, setAdding] = useState(false)
  const [messageApi, contextHolder] = message.useMessage()

  const { files: convertedFiles, enqueue, pendingCount, loading, refresh } = useConversionQueue(courseId)

  const [aiResults, setAiResults] = useState<AiResultItem[]>([])
  const [generating, setGenerating] = useState<Record<string, boolean>>({})
  const [taskStageMap, setTaskStageMap] = useState<Record<string, string>>({})
  const [refiningGraph, setRefiningGraph] = useState(false)
  const [generationModalOpen, setGenerationModalOpen] = useState(false)
  const [selectedOutputType, setSelectedOutputType] = useState<AiOutputType | null>(null)
  const [generationGuidance, setGenerationGuidance] = useState('')
  const [lessonPlanScope, setLessonPlanScope] = useState<LessonPlanScope>('auto')
  const [lessonPlanCount, setLessonPlanCount] = useState(2)

  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewContent, setPreviewContent] = useState('')
  const [previewTitle, setPreviewTitle] = useState('')
  const [previewLoading, setPreviewLoading] = useState(false)
  const [deletingMaterialId, setDeletingMaterialId] = useState<string | null>(null)
  const [llmTraceOpen, setLlmTraceOpen] = useState(true)
  const [llmTraceLogs, setLlmTraceLogs] = useState<string[]>([])
  const [streamPreviewMap, setStreamPreviewMap] = useState<Record<string, string>>({})
  const traceViewportRef = useRef<HTMLDivElement | null>(null)

  const streamingMap = useRef<Record<string, string>>({})
  const activeStreams = useRef<Record<string, boolean>>({})

  const appendLlmTrace = useCallback((line: string) => {
    const stamp = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    setLlmTraceLogs((prev) => {
      const next = [...prev, `[${stamp}] ${line}`]
      return next.length > 240 ? next.slice(next.length - 240) : next
    })
  }, [])

  useEffect(() => {
    if (!traceViewportRef.current) return
    traceViewportRef.current.scrollTop = traceViewportRef.current.scrollHeight
  }, [llmTraceLogs, streamPreviewMap])

  useEffect(() => {
    if (!courseId) return
    fetchCourses().then((list) => {
      const found = list.find((c) => c.id === courseId)
      if (found) setCourse(found)
    })
    fetchChapters(courseId).then(setChapters)
    fetchAiResults(courseId).then(setAiResults).catch(() => {})
  }, [courseId])

  const handleAddChapter = async () => {
    const trimmed = newTitle.trim()
    if (!trimmed || !courseId) return
    setAdding(true)
    try {
      await addChapter(courseId, trimmed)
      messageApi.success(`章节「${trimmed}」添加成功`)
      setNewTitle('')
      setChapters(await fetchChapters(courseId))
    } finally {
      setAdding(false)
    }
  }

  const collectedFiles = useRef<File[]>([])

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

  const showPreview = async (content: string, title: string) => {
    setPreviewTitle(title)
    setPreviewContent(content)
    setPreviewOpen(true)
  }

  const handlePreviewMaterial = async (item: typeof convertedFiles[number]) => {
    setPreviewLoading(true)
    try {
      const detail = await fetchMaterialDetail(item.id)
      await showPreview(detail.markdown ?? '', item.filename)
    } catch {
      messageApi.error('加载预览失败')
    } finally {
      setPreviewLoading(false)
    }
  }

  const handlePreviewAiResult = async (item: AiResultItem) => {
    if (streamingMap.current[item.id]) {
      await showPreview(streamingMap.current[item.id], item.title)
      return
    }
    setPreviewLoading(true)
    try {
      const detail = await fetchAiResultDetail(item.id)
      await showPreview(detail.content ?? '', item.title)
    } catch {
      messageApi.error('加载预览失败')
    } finally {
      setPreviewLoading(false)
    }
  }

  const handleDeleteMaterial = async (item: typeof convertedFiles[number]) => {
    setDeletingMaterialId(item.id)
    try {
      await deleteMaterial(item.id)
      messageApi.success(`资料「${item.filename}」已删除`)
      await refresh()
    } catch {
      messageApi.error('删除资料失败')
    } finally {
      setDeletingMaterialId((prev) => (prev === item.id ? null : prev))
    }
  }

  const handleOpenGenerationModal = (outputType: AiOutputType) => {
    if (outputType === 'ideology_case') {
      const hasCompletedOutline = aiResults.some((item) => item.output_type === 'outline' && item.status === 'done')
      if (!hasCompletedOutline) {
        messageApi.warning('请先生成并完成课程大纲，再创建思政案例')
        return
      }
    }
    setSelectedOutputType(outputType)
    setGenerationGuidance('')
    setLessonPlanScope('auto')
    setLessonPlanCount(2)
    setGenerationModalOpen(true)
  }

  const handleStartGeneration = async () => {
    if (!courseId || !selectedOutputType) return
    const outputType = selectedOutputType
    const userGuidance = generationGuidance.trim()
    const detectedIntent = detectLessonPlanIntent(userGuidance)
    const semesterCount = resolveSemesterLessonCount(course?.sessions, course?.hours)
    let submitScope: LessonPlanScope = lessonPlanScope
    let submitCount: number | undefined
    if (outputType === 'lesson_plan') {
      if (lessonPlanScope === 'auto') {
        submitScope = detectedIntent.scope
      }
      if (submitScope === 'multiple') {
        submitCount = Math.min(Math.max(lessonPlanCount, 2), 64)
      } else if (submitScope === 'semester') {
        submitCount = semesterCount
      } else {
        submitCount = 1
      }
      if (lessonPlanScope === 'auto' && !detectedIntent.explicit) {
        const confirmed = await new Promise<boolean>((resolve) => {
          Modal.confirm({
            title: '确认生成整学期教案',
            content: `你未明确指定篇数，系统将按整学期生成约 ${semesterCount} 篇教案，会消耗较多 token。是否继续？`,
            okText: '继续生成',
            cancelText: '取消',
            onOk: () => resolve(true),
            onCancel: () => resolve(false),
          })
        })
        if (!confirmed) return
      }
    }
    setGenerating((prev) => ({ ...prev, [outputType]: true }))
    try {
      const results = await startAiGeneration(courseId, [outputType], userGuidance, {
        lesson_plan_scope: outputType === 'lesson_plan' ? submitScope : undefined,
        lesson_count: outputType === 'lesson_plan' ? submitCount : undefined,
      })
      setAiResults((prev) => [...results, ...prev])
      setGenerationModalOpen(false)
      if (results.length > 1) {
        messageApi.success(`已提交 ${results.length} 个教案生成任务`)
      } else {
        messageApi.success(`已提交「${results[0].title}」生成任务`)
      }
      results.forEach((r) => startStreaming(r.id))
    } catch (error) {
      const detail = axios.isAxiosError(error) ? error.response?.data?.detail : undefined
      messageApi.error(typeof detail === 'string' && detail ? detail : '提交生成任务失败')
    } finally {
      setGenerating((prev) => ({ ...prev, [outputType]: false }))
    }
  }

  const handleRefineKnowledgeGraph = async () => {
    if (!courseId) return
    setRefiningGraph(true)
    try {
      const result = await refineCourseKnowledgeGraph(courseId)
      messageApi.success(
        `知识图谱完善完成：资料${result.material_total}，补全知识库${result.material_backfilled}，知识点${result.knowledge_points_total}，关系更新${result.relation_updated}，图谱边${result.graph_edges_total}，同义连接${result.duplicate_merged}`,
      )
      await refresh()
    } catch {
      messageApi.error('完善知识图谱失败')
    } finally {
      setRefiningGraph(false)
    }
  }

  const startStreaming = useCallback((resultId: string) => {
    if (activeStreams.current[resultId]) return
    activeStreams.current[resultId] = true
    const url = buildStreamUrl(resultId)
    const evtSource = new EventSource(url)
    let doneTimer: ReturnType<typeof setTimeout> | null = null
    streamingMap.current[resultId] = ''
    setStreamPreviewMap((prev) => ({ ...prev, [resultId]: '' }))
    const resultTitle = aiResults.find((r) => r.id === resultId)?.title ?? resultId
    appendLlmTrace(`任务「${resultTitle}」已连接流式通道`)

    evtSource.onopen = () => {
      appendLlmTrace(`任务「${resultTitle}」流式连接已建立`)
    }

    evtSource.onmessage = (e) => {
      try {
        const payload = JSON.parse(e.data)
        if (payload.status === 'done') {
          appendLlmTrace(`任务「${resultTitle}」收到完成信号，正在收尾流式输出`)
          if (!doneTimer) {
            doneTimer = setTimeout(() => {
              const finalText = streamingMap.current[resultId] ?? ''
              appendLlmTrace(`任务「${resultTitle}」生成完成（实时输出 ${finalText.length} 字符）`)
              evtSource.close()
              delete activeStreams.current[resultId]
              if (!finalText) {
                delete streamingMap.current[resultId]
                setStreamPreviewMap((prev) => {
                  const next = { ...prev }
                  delete next[resultId]
                  return next
                })
              }
              setTaskStageMap((prev) => {
                const next = { ...prev }
                delete next[resultId]
                return next
              })
              setAiResults((prev) =>
                prev.map((r) => (r.id === resultId ? { ...r, status: 'done' as const } : r)),
              )
              if (courseId) {
                fetchAiResults(courseId).then(setAiResults)
              }
            }, 400)
          }
          return
        }
        if (payload.status === 'planning') {
          appendLlmTrace(`任务「${resultTitle}」进入阶段：教学策略推演`)
          setTaskStageMap((prev) => ({ ...prev, [resultId]: '阶段 1：教学策略推演' }))
          return
        }
        if (payload.status === 'agentic') {
          appendLlmTrace(`任务「${resultTitle}」进入阶段：Agentic 编排`)
          setTaskStageMap((prev) => ({ ...prev, [resultId]: '前置阶段：Agentic 任务编排' }))
          return
        }
        if (payload.status === 'outline_ready') {
          appendLlmTrace(`任务「${resultTitle}」已关联历史大纲`)
          setTaskStageMap((prev) => ({ ...prev, [resultId]: '前置阶段：已关联历史大纲' }))
          return
        }
        if (payload.status === 'searching') {
          appendLlmTrace(`任务「${resultTitle}」进入阶段：联网检索补充`)
          setTaskStageMap((prev) => ({ ...prev, [resultId]: '前置阶段：联网检索补充' }))
          return
        }
        if (payload.status === 'search_ready') {
          appendLlmTrace(`任务「${resultTitle}」已完成联网资料补充`)
          setTaskStageMap((prev) => ({ ...prev, [resultId]: '前置阶段：已补充外部资料' }))
          return
        }
        if (payload.status === 'drafting') {
          appendLlmTrace(`任务「${resultTitle}」进入阶段：文稿生成`)
          setTaskStageMap((prev) => ({ ...prev, [resultId]: '阶段 2：文稿生成' }))
          return
        }
        if (payload.status === 'failed') {
          if (doneTimer) clearTimeout(doneTimer)
          appendLlmTrace(`任务「${resultTitle}」失败：${payload.error ?? '未知错误'}`)
          evtSource.close()
          delete activeStreams.current[resultId]
          delete streamingMap.current[resultId]
          setStreamPreviewMap((prev) => {
            const next = { ...prev }
            delete next[resultId]
            return next
          })
          setTaskStageMap((prev) => {
            const next = { ...prev }
            delete next[resultId]
            return next
          })
          if (courseId) {
            fetchAiResults(courseId).then(setAiResults)
          }
          return
        }
        if ('chunk' in payload && typeof payload.chunk === 'string') {
          streamingMap.current[resultId] = (streamingMap.current[resultId] ?? '') + payload.chunk
          setStreamPreviewMap((prev) => ({
            ...prev,
            [resultId]: (prev[resultId] ?? '') + payload.chunk,
          }))
        }
      } catch {
        appendLlmTrace(`任务「${resultTitle}」收到不可解析流片段：${String(e.data).slice(0, 120)}`)
      }
    }

    evtSource.onerror = () => {
      if (doneTimer) clearTimeout(doneTimer)
      appendLlmTrace(`任务「${resultTitle}」流式连接中断`)
      evtSource.close()
      delete activeStreams.current[resultId]
      delete streamingMap.current[resultId]
      setStreamPreviewMap((prev) => {
        const next = { ...prev }
        delete next[resultId]
        return next
      })
      setTaskStageMap((prev) => {
        const next = { ...prev }
        delete next[resultId]
        return next
      })
      if (courseId) {
        fetchAiResults(courseId).then(setAiResults)
      }
    }
  }, [aiResults, appendLlmTrace, courseId])

  useEffect(() => {
    aiResults
      .filter((item) => item.status === 'queued' || item.status === 'running')
      .forEach((item) => startStreaming(item.id))
  }, [aiResults, startStreaming])

  const statusIcon = (status: string) => {
    switch (status) {
      case 'converting':
      case 'running':
        return <LoadingOutlined style={{ color: '#1677ff', fontSize: 18 }} />
      case 'done':
        return <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 18 }} />
      case 'error':
      case 'failed':
        return <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 18 }} />
      default:
        return <ClockCircleOutlined style={{ color: '#999', fontSize: 18 }} />
    }
  }

  const materialStatusText = (item: typeof convertedFiles[number]) => {
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

  const renderMaterialSummary = (raw?: string | null) => {
    if (!raw) return null
    try {
      const parsed = JSON.parse(raw) as MaterialSummaryCard
      if (!parsed.summary && !parsed.structure && !parsed.key_points) return null
      const complexity = parsed.complexity || 'flat'

      const complexityLabel = {
        multi_chapter: { text: '多章节', color: 'purple' },
        single_chapter: { text: '单章节', color: 'green' },
        flat: { text: '片段', color: 'orange' },
      }[complexity]

      const renderStructure = (nodes: StructureNode[]) => (
        <div style={{ marginTop: 4 }}>
          {nodes.map((node, idx) => (
            <div key={idx} style={{ marginBottom: 6 }}>
              <Typography.Text style={{ fontSize: 12, fontWeight: 500 }}>
                {idx + 1}. {node.section}
              </Typography.Text>
              <div style={{ paddingLeft: 16 }}>
                {node.key_points.map((pt, pi) => (
                  <Typography.Text key={pi} type="secondary" style={{ fontSize: 11, display: 'block' }}>
                    · {pt}
                  </Typography.Text>
                ))}
              </div>
            </div>
          ))}
        </div>
      )

      const renderFlatPoints = (points: string[]) => (
        <div style={{ marginTop: 4 }}>
          {points.map((pt, idx) => (
            <Typography.Text key={idx} type="secondary" style={{ fontSize: 11, display: 'block' }}>
              · {pt}
            </Typography.Text>
          ))}
        </div>
      )

      return (
        <Card size="small" style={{ marginTop: 8, background: '#fafafa' }}>
          <Space direction="vertical" size={6} style={{ width: '100%' }}>
            <Space>
              <Typography.Text strong>{parsed.title ?? '资料摘要卡片'}</Typography.Text>
              {parsed.document_type && <Tag color="blue">{parsed.document_type}</Tag>}
              {complexityLabel && <Tag color={complexityLabel.color}>{complexityLabel.text}</Tag>}
            </Space>
            {complexity === 'single_chapter' && parsed.chapter_title && (
              <Typography.Text style={{ fontSize: 12, color: '#666' }}>
                章节：{parsed.chapter_title}
              </Typography.Text>
            )}
            {parsed.summary && <Typography.Text type="secondary">{parsed.summary}</Typography.Text>}
            {parsed.structure && parsed.structure.length > 0 && renderStructure(parsed.structure)}
            {complexity === 'flat' && parsed.key_points && parsed.key_points.length > 0 && renderFlatPoints(parsed.key_points)}
            {parsed.keywords && parsed.keywords.length > 0 && (
              <Space wrap>
                {parsed.keywords.map((kw) => (
                  <Tag key={kw}>{kw}</Tag>
                ))}
              </Space>
            )}
          </Space>
        </Card>
      )
    } catch {
      return (
        <Card size="small" style={{ marginTop: 8, background: '#fafafa' }}>
          <Typography.Text type="secondary">{raw}</Typography.Text>
        </Card>
      )
    }
  }

  const actionButtons = [
    { key: 'outline' as AiOutputType, label: '生成课程大纲', icon: <FileTextOutlined /> },
    { key: 'lesson_plan' as AiOutputType, label: '生成教案设计', icon: <EditOutlined /> },
    { key: 'teaching_plan' as AiOutputType, label: '生成教学计划', icon: <CalendarOutlined /> },
    { key: 'ideology_case' as AiOutputType, label: '生成思政案例', icon: <BookOutlined /> },
    { key: 'knowledge' as AiOutputType, label: '更新知识库', icon: <FileProtectOutlined /> },
  ]
  const guidancePresets = ['PBL 项目式学习', 'OBE 成果导向', 'BOPPPS', '布鲁姆目标分类', '翻转课堂', '混合式教学', '案例教学', 'ISW']
  const lessonIntent = detectLessonPlanIntent(generationGuidance)
  const semesterCount = resolveSemesterLessonCount(course?.sessions, course?.hours)
  const lessonScopeLabelMap: Record<LessonPlanScope, string> = {
    auto: '自动判断',
    single: '单篇',
    multiple: '多篇',
    semester: '整学期',
  }
  const autoScopeLabel = lessonScopeLabelMap[lessonIntent.scope]

  const activeTasks = aiResults.filter((r) => r.status === 'running' || r.status === 'queued')
  const completedTasks = aiResults.filter((r) => r.status === 'done')
  const hasCompletedOutline = aiResults.some((item) => item.output_type === 'outline' && item.status === 'done')

  return (
    <>
      {contextHolder}
      <div className="page-stack">
        <Card className="hero-panel">
          <Row align="top" gutter={[16, 16]}>
            <Col>
              <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/dashboard')}>
                返回工作台
              </Button>
            </Col>
            <Col flex="auto">
              <div className="hero-kicker">Course Notebook</div>
              <Typography.Title level={2} className="hero-title">
                {course?.name ?? '课程详情'}
              </Typography.Title>
              <Space wrap>
                {course?.hours ? <Tag className="soft-tag">{course.hours} 学时</Tag> : null}
                {course?.sessions ? <Tag className="soft-tag">{course.sessions} 课次</Tag> : null}
                <Tag className="soft-tag">{chapters.length} 个章节</Tag>
                <Tag className="soft-tag">{convertedFiles.length} 份资料</Tag>
              </Space>
            </Col>
          </Row>
          {course?.description && (
            <Typography.Paragraph className="hero-subtitle" style={{ marginTop: 16, marginBottom: 0 }}>
              {course.description}
            </Typography.Paragraph>
          )}
        </Card>

        <div className="studio-grid">
          <div className="stack-grid">
            <Card
              className="notebook-panel"
              title={
                <Space>
                  <UploadOutlined />
                  上传课程资料
                  {pendingCount > 0 && (
                    <Typography.Text type="secondary" style={{ fontSize: 13, fontWeight: 'normal' }}>
                      （{pendingCount} 个转换中）
                    </Typography.Text>
                  )}
                </Space>
              }
            >
              <Upload.Dragger
                className="notebook-dropzone"
                multiple
                beforeUpload={handleBeforeUpload}
                onChange={handleUploadChange}
                showUploadList={false}
                disabled={!courseId || loading}
              >
                <p className="ant-upload-drag-icon">
                  <InboxOutlined />
                </p>
                <p>将课程资料拖拽到此处，或点击选择文件</p>
                <p className="ant-upload-hint">
                  支持 PDF / Word / PPT / Excel / 图片 / 文本，系统将自动转换为 Markdown 并切片。
                  可随时继续添加文件，后台队列依次处理。
                </p>
              </Upload.Dragger>
            </Card>

            {convertedFiles.length > 0 && (
              <Card
                className="notebook-panel"
                title={
                  <Space>
                    <FileMarkdownOutlined />
                    已上传资料（{convertedFiles.length} 份）
                    {pendingCount > 0 && (
                      <Progress
                        percent={Math.round(((convertedFiles.length - pendingCount) / convertedFiles.length) * 100)}
                        size="small"
                        style={{ width: 120, marginBottom: -2 }}
                      />
                    )}
                  </Space>
                }
              >
                <List
                  className="notebook-list"
                  dataSource={convertedFiles}
                  renderItem={(item) => (
                    <List.Item
                      actions={[
                        item.status === 'done' ? (
                          <Button key="view" size="small" loading={previewLoading} onClick={() => void handlePreviewMaterial(item)}>
                            预览
                          </Button>
                        ) : null,
                        <Popconfirm
                          key="delete"
                          title={`确定删除资料「${item.filename}」吗？`}
                          description="仅删除该资料本身，不会删除课程。"
                          okText="删除"
                          cancelText="取消"
                          onConfirm={() => void handleDeleteMaterial(item)}
                        >
                          <Button
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                            loading={deletingMaterialId === item.id}
                          >
                            删除
                          </Button>
                        </Popconfirm>,
                      ]}
                    >
                      <List.Item.Meta
                        avatar={statusIcon(item.status)}
                        title={item.filename}
                        description={
                          <>
                            <Space direction="vertical" size={0}>
                              <Typography.Text type="secondary">{materialStatusText(item)}</Typography.Text>
                              {item.status !== 'done' && item.processStage && (
                                <Typography.Text type="secondary" style={{ fontSize: 11, color: '#999' }}>
                                  {item.processStage}
                                </Typography.Text>
                              )}
                            </Space>
                            {item.status === 'done' && renderMaterialSummary(item.summary)}
                          </>
                        }
                      />
                    </List.Item>
                  )}
                />
              </Card>
            )}
          </div>

          <div className="stack-grid">
            <Card
              className="notebook-panel floating-subtle"
              title={
                <Space>
                  <ThunderboltOutlined />
                  AI 操作台
                </Space>
              }
            >
              <div className="toolbar-group">
                {actionButtons.map((btn) => (
                  <Button
                    key={btn.key}
                    type="primary"
                    icon={btn.icon}
                    loading={generating[btn.key]}
                    disabled={btn.key === 'ideology_case' && !hasCompletedOutline}
                    onClick={() => handleOpenGenerationModal(btn.key)}
                    size="large"
                  >
                    {btn.label}
                  </Button>
                ))}
              </div>

              {!hasCompletedOutline && (
                <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
                  思政案例依赖已完成的课程大纲，请先生成课程大纲。
                </Typography.Text>
              )}

              <Divider style={{ margin: '16px 0' }} />

              <div className="toolbar-group">
                <Button
                  icon={<SyncOutlined />}
                  loading={refiningGraph}
                  onClick={() => void handleRefineKnowledgeGraph()}
                  disabled={!courseId || convertedFiles.length === 0}
                  size="large"
                >
                  完善知识图谱
                </Button>
                <Button
                  icon={<FileProtectOutlined />}
                  onClick={() => courseId && navigate(`/courses/${courseId}/knowledge-graph`)}
                  disabled={!courseId}
                  size="large"
                >
                  查看知识图谱
                </Button>
              </div>

              {(activeTasks.length > 0 || completedTasks.length > 0) && (
                <>
                  <Divider style={{ margin: '16px 0 12px' }} />
                  <Typography.Text type="secondary" className="list-muted" style={{ display: 'block', marginBottom: 8 }}>
                    任务队列（{activeTasks.length} 进行中，{completedTasks.length} 已完成）
                  </Typography.Text>
                  <List
                    className="notebook-list"
                    size="small"
                    dataSource={[...activeTasks, ...completedTasks.slice(0, 5)]}
                    renderItem={(item) => (
                      <List.Item
                        actions={[
                          item.status === 'done' ? (
                            <Space>
                              <Button
                                key="view"
                                size="small"
                                loading={previewLoading}
                                onClick={() => void handlePreviewAiResult(item)}
                              >
                                预览
                              </Button>
                              <Button
                                key="dl"
                                size="small"
                                icon={<DownloadOutlined />}
                                href={buildExportUrl(item.id)}
                              >
                                下载
                              </Button>
                              {item.request_context?.lesson_batch_id && (parsePositiveInt(item.request_context?.lesson_count) ?? 1) > 1 ? (
                                <Button
                                  key="zip"
                                  size="small"
                                  icon={<DownloadOutlined />}
                                  href={buildLessonBatchExportUrl(item.request_context.lesson_batch_id)}
                                >
                                  打包下载
                                </Button>
                              ) : null}
                            </Space>
                          ) : null,
                        ]}
                      >
                        <List.Item.Meta
                          avatar={statusIcon(item.status)}
                          title={item.title}
                          description={
                            <Space wrap>
                              <Tag color={statusColorMap[item.status] ?? '#999'}>
                                {statusLabelMap[item.status] ?? item.status}
                              </Tag>
                              {taskStageMap[item.id] && (
                                <Tag color="processing">{taskStageMap[item.id]}</Tag>
                              )}
                              {item.request_context?.user_guidance && (
                                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                                  方向：{item.request_context.user_guidance}
                                </Typography.Text>
                              )}
                              {item.status === 'done' && (
                                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                                  {item.char_count.toLocaleString()} 字符
                                </Typography.Text>
                              )}
                            </Space>
                          }
                        />
                      </List.Item>
                    )}
                  />
                </>
              )}
            </Card>

            <Card
              className="notebook-panel"
              title={
                <Space>
                  <NumberOutlined />
                  章节管理
                </Space>
              }
              extra={
                <Space>
                  <Input
                    placeholder="输入章节名称"
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    onPressEnter={handleAddChapter}
                    style={{ width: 240 }}
                  />
                  <Button type="primary" icon={<PlusOutlined />} loading={adding} onClick={handleAddChapter}>
                    添加章节
                  </Button>
                </Space>
              }
            >
              {chapters.length === 0 ? (
                <Typography.Text type="secondary">
                  暂无章节，请在上方输入章节名称后点击「添加章节」
                </Typography.Text>
              ) : (
                <List
                  className="notebook-list"
                  dataSource={chapters}
                  renderItem={(chapter) => (
                    <List.Item>
                      <List.Item.Meta
                        avatar={
                          <Typography.Text strong style={{ fontSize: 16, color: '#1677ff' }}>
                            {String(chapter.sort_order).padStart(2, '0')}
                          </Typography.Text>
                        }
                        title={
                          <Space>
                            <FileTextOutlined />
                            {chapter.title}
                          </Space>
                        }
                        description={`${chapter.material_count} 份资料`}
                      />
                    </List.Item>
                  )}
                />
              )}
            </Card>
          </div>
        </div>
      </div>

      <Card
        size="small"
        title={
          <Space>
            <ThunderboltOutlined />
            LLM 实时输出
          </Space>
        }
        extra={
          <Button type="link" size="small" onClick={() => setLlmTraceOpen((v) => !v)}>
            {llmTraceOpen ? '收起' : '展开'}
          </Button>
        }
        style={{
          position: 'fixed',
          right: 18,
          bottom: 18,
          width: 420,
          zIndex: 1400,
          boxShadow: '0 10px 24px rgba(0,0,0,0.16)',
          borderRadius: 12,
        }}
        bodyStyle={{ padding: llmTraceOpen ? 10 : 0, display: llmTraceOpen ? 'block' : 'none' }}
      >
        <div
          ref={traceViewportRef}
          style={{
            maxHeight: 300,
            overflow: 'auto',
            background: '#fafafa',
            borderRadius: 8,
            padding: 8,
            fontSize: 12,
            lineHeight: 1.5,
          }}
        >
          {Object.keys(streamPreviewMap).length === 0 && llmTraceLogs.length === 0 ? (
            <Typography.Text type="secondary">暂无实时输出，发起生成任务后会在这里显示。</Typography.Text>
          ) : (
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              {Object.entries(streamPreviewMap).map(([id, text]) => {
                const title = aiResults.find((r) => r.id === id)?.title ?? id
                return (
                  <div key={id} style={{ border: '1px solid #eee', borderRadius: 8, padding: 8, background: '#fff' }}>
                    <Typography.Text strong style={{ display: 'block', marginBottom: 4 }}>
                      {title}
                    </Typography.Text>
                    <Typography.Text style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                      {text.slice(-900) || '等待流式文本...'}
                    </Typography.Text>
                  </div>
                )
              })}
              {llmTraceLogs.length > 0 && (
                <div style={{ borderTop: '1px dashed #ddd', paddingTop: 8 }}>
                  {llmTraceLogs.slice(-40).map((line, idx) => (
                    <Typography.Text key={`${line}-${idx}`} type="secondary" style={{ display: 'block' }}>
                      {line}
                    </Typography.Text>
                  ))}
                </div>
              )}
            </Space>
          )}
        </div>
      </Card>

      <Modal
        title={selectedOutputType ? `配置${actionButtons.find((item) => item.key === selectedOutputType)?.label ?? '生成任务'}` : '配置生成任务'}
        open={generationModalOpen}
        onCancel={() => setGenerationModalOpen(false)}
        onOk={() => void handleStartGeneration()}
        confirmLoading={selectedOutputType ? !!generating[selectedOutputType] : false}
        okText="开始生成"
        cancelText="取消"
        destroyOnHidden
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            教师可选填一些生成方向。系统会先用第一阶段模型推演教学组织方式、教育理念与方法，再进入第二阶段正式生成文稿。
          </Typography.Paragraph>
          <Typography.Text strong>推荐方向</Typography.Text>
          <Space wrap>
            {guidancePresets.map((preset) => (
              <Button
                key={preset}
                size="small"
                onClick={() =>
                  setGenerationGuidance((prev) => (prev.includes(preset) ? prev : `${prev}${prev ? '；' : ''}${preset}`))
                }
              >
                {preset}
              </Button>
            ))}
          </Space>
          <Input.TextArea
            rows={6}
            value={generationGuidance}
            onChange={(e) => setGenerationGuidance(e.target.value)}
            placeholder="例如：希望更突出项目式学习、物流行业案例、线上线下混合教学，课堂活动更强调小组协作与过程性评价。"
          />
          <Typography.Text type="secondary">
            系统会同时参考课程已记录的课时、简介、已构建知识库与知识图谱。
          </Typography.Text>
          {selectedOutputType === 'lesson_plan' && (
            <>
              <Divider style={{ margin: '8px 0' }} />
              <Typography.Text strong>教案生成范围</Typography.Text>
              <Radio.Group
                value={lessonPlanScope}
                onChange={(e) => setLessonPlanScope(e.target.value as LessonPlanScope)}
                optionType="button"
                buttonStyle="solid"
                options={[
                  { label: '自动判断', value: 'auto' },
                  { label: '单篇', value: 'single' },
                  { label: '多篇', value: 'multiple' },
                  { label: '整学期', value: 'semester' },
                ]}
              />
              {lessonPlanScope === 'multiple' && (
                <Space>
                  <Typography.Text type="secondary">篇数</Typography.Text>
                  <InputNumber min={2} max={64} value={lessonPlanCount} onChange={(v) => setLessonPlanCount(Number(v ?? 2))} />
                </Space>
              )}
              {lessonPlanScope === 'auto' && (
                <Typography.Text type="secondary">
                  自动判断结果：{autoScopeLabel}
                  {lessonIntent.scope === 'multiple' && lessonIntent.count ? `（${lessonIntent.count} 篇）` : ''}
                  {lessonIntent.scope === 'semester' ? `（约 ${semesterCount} 篇）` : ''}；{lessonIntent.reason}
                </Typography.Text>
              )}
              {lessonPlanScope === 'semester' && (
                <Typography.Text type="secondary">将按课程课次生成，预计约 {semesterCount} 篇教案。</Typography.Text>
              )}
            </>
          )}
        </Space>
      </Modal>

      <Modal
        title={previewTitle}
        open={previewOpen}
        onCancel={() => setPreviewOpen(false)}
        footer={null}
        width={800}
      >
        <pre
          style={{
            maxHeight: '60vh',
            overflow: 'auto',
            background: '#f4f6f0',
            padding: 16,
            borderRadius: 18,
            fontSize: 13,
            lineHeight: 1.6,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {previewContent}
        </pre>
      </Modal>
    </>
  )
}
