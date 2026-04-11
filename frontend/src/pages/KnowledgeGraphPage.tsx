import { useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react'
import { ApartmentOutlined, ArrowLeftOutlined, DeleteOutlined, DownloadOutlined } from '@ant-design/icons'
import { Button, Card, Empty, Modal, Space, Spin, Tag, Typography, message } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { deleteCourseKnowledgeNode, exportCourseKnowledgeGraph, fetchCourseKnowledgeGraph } from '../api/client'
import type { CourseKnowledgeGraph, CourseKnowledgeGraphEdge, CourseKnowledgeGraphNode } from '../types'

type EdgeType = CourseKnowledgeGraphEdge['type']
type TreeNode = { node: CourseKnowledgeGraphNode; children: TreeNode[]; descendantCount: number }
type ChapterTree = {
  chapter: string
  chapterIndex: number
  nodes: CourseKnowledgeGraphNode[]
  roots: TreeNode[]
}

const edgeTypeMeta: Record<EdgeType, { label: string; color: string; dash?: string }> = {
  hierarchy: { label: '层级', color: '#93a19b' },
  prerequisite: { label: '前置', color: '#2f6fed' },
  postrequisite: { label: '后置', color: '#1f9d72' },
  related: { label: '关联', color: '#d97706', dash: '8 6' },
  equivalent: { label: '同义', color: '#7c3aed', dash: '4 5' },
}

const edgeTypes = Object.keys(edgeTypeMeta) as EdgeType[]

const chapterPalette = [
  { accent: '#487a66', soft: 'rgba(72, 122, 102, 0.14)', glow: 'rgba(127, 180, 157, 0.24)', surface: '#eff7f2' },
  { accent: '#9a6238', soft: 'rgba(154, 98, 56, 0.14)', glow: 'rgba(221, 167, 126, 0.22)', surface: '#faf1e8' },
  { accent: '#4f6db5', soft: 'rgba(79, 109, 181, 0.14)', glow: 'rgba(141, 166, 225, 0.24)', surface: '#eef3fd' },
  { accent: '#7a5b9f', soft: 'rgba(122, 91, 159, 0.14)', glow: 'rgba(181, 155, 216, 0.24)', surface: '#f4effa' },
  { accent: '#8a6b2f', soft: 'rgba(138, 107, 47, 0.14)', glow: 'rgba(215, 190, 124, 0.24)', surface: '#fbf5e7' },
]

function getChapterTheme(index: number) {
  return chapterPalette[index % chapterPalette.length]
}

function buildChapterVars(index: number, extra?: CSSProperties) {
  const theme = getChapterTheme(index)
  return {
    '--chapter-accent': theme.accent,
    '--chapter-soft': theme.soft,
    '--chapter-glow': theme.glow,
    '--chapter-surface': theme.surface,
    ...extra,
  } as CSSProperties
}

function renderRelationGroup(title: string, items: string[], emptyLabel: string) {
  return (
    <div className="graph-detail-section">
      <Typography.Text strong className="graph-section-title">
        {title}
      </Typography.Text>
      {items.length > 0 ? (
        <div className="chip-row">
          {items.map((item) => (
            <Tag className="soft-tag" key={item}>
              {item}
            </Tag>
          ))}
        </div>
      ) : (
        <Typography.Text type="secondary">{emptyLabel}</Typography.Text>
      )}
    </div>
  )
}

type TreeNodeViewProps = {
  chapterIndex: number
  item: TreeNode
  selectedNodeId: string | null
  relationCountMap: Map<string, number>
  onSelect: (node: CourseKnowledgeGraphNode) => void
  onDelete: (node: CourseKnowledgeGraphNode) => void
  depth?: number
}

function TreeNodeView({
  chapterIndex,
  item,
  selectedNodeId,
  relationCountMap,
  onSelect,
  onDelete,
  depth = 0,
}: TreeNodeViewProps) {
  const relationCount = relationCountMap.get(item.node.id) ?? 0
  const isSelected = selectedNodeId === item.node.id

  return (
    <div
      className={`chapter-tree-item depth-${Math.min(depth, 3)} ${item.children.length > 0 ? 'has-children' : ''}`}
    >
      <div className={`chapter-tree-row ${depth > 0 ? 'has-parent' : ''}`} style={buildChapterVars(chapterIndex)}>
        <button
          type="button"
          className={`chapter-tree-node ${isSelected ? 'is-selected' : ''}`}
          onClick={() => onSelect(item.node)}
        >
          <div className="chapter-tree-node-top">
            <span className="chapter-tree-level">L{item.node.level}</span>
            <span className="chapter-tree-chip">{relationCount} 条关系</span>
          </div>
          <strong className="chapter-tree-title">{item.node.label}</strong>
          <div className="chapter-tree-meta">
            <span>{item.node.parent_name ? `上级：${item.node.parent_name}` : '主干主题'}</span>
            <span>{item.children.length} 个下级</span>
          </div>
        </button>

        <Button
          type="text"
          danger
          size="small"
          className="chapter-tree-delete"
          icon={<DeleteOutlined />}
          onClick={(event) => {
            event.stopPropagation()
            void Promise.resolve(onDelete(item.node))
          }}
        />
      </div>

      {item.children.length > 0 && (
        <div className="chapter-tree-children">
          {item.children.map((child) => (
            <TreeNodeView
              key={child.node.id}
              chapterIndex={chapterIndex}
              item={child}
              selectedNodeId={selectedNodeId}
              relationCountMap={relationCountMap}
              onSelect={onSelect}
              onDelete={onDelete}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  )
}

type DeleteDialogState = {
  node: CourseKnowledgeGraphNode
  directChildCount: number
  descendantCount: number
  nextFocusId: string | null
}

export function KnowledgeGraphPage() {
  const { courseId } = useParams<{ courseId: string }>()
  const navigate = useNavigate()
  const [graph, setGraph] = useState<CourseKnowledgeGraph | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedNode, setSelectedNode] = useState<CourseKnowledgeGraphNode | null>(null)
  const [deletingNodeId, setDeletingNodeId] = useState<string | null>(null)
  const [deleteDialog, setDeleteDialog] = useState<DeleteDialogState | null>(null)
  const [exporting, setExporting] = useState(false)
  const [messageApi, contextHolder] = message.useMessage()

  const loadGraph = useCallback(
    async (preferredNodeId?: string | null) => {
      if (!courseId) return
      setLoading(true)
      try {
        const data = await fetchCourseKnowledgeGraph(courseId)
        setGraph(data)
        setSelectedNode((current) => {
          const nextId = preferredNodeId ?? current?.id ?? data.nodes[0]?.id ?? null
          return data.nodes.find((node) => node.id === nextId) ?? data.nodes[0] ?? null
        })
      } catch {
        messageApi.error('加载知识图谱失败')
      } finally {
        setLoading(false)
      }
    },
    [courseId, messageApi],
  )

  useEffect(() => {
    setLoading(true)
    void loadGraph()
  }, [loadGraph])

  const relationCountMap = useMemo(() => {
    const counts = new Map<string, number>()
    graph?.edges
      .filter((edge) => edge.type !== 'hierarchy')
      .forEach((edge) => {
        counts.set(edge.source, (counts.get(edge.source) ?? 0) + 1)
        counts.set(edge.target, (counts.get(edge.target) ?? 0) + 1)
      })
    return counts
  }, [graph])

  const chapterStats = useMemo(() => {
    if (!graph) return []

    return graph.chapters.map((chapter, chapterIndex) => {
      const nodes = graph.nodes.filter((node) => node.chapter_index === chapterIndex)
      const chapterNodeIds = new Set(nodes.map((node) => node.id))
      const relationCount = graph.edges.filter(
        (edge) => chapterNodeIds.has(edge.source) || chapterNodeIds.has(edge.target),
      ).length
      const levelCount = new Set(nodes.map((node) => node.level)).size
      return {
        chapter,
        chapterIndex,
        count: nodes.length,
        relationCount,
        levelCount,
        firstNode: nodes[0] ?? null,
      }
    })
  }, [graph])

  const selectedEdgeBreakdown = useMemo(() => {
    return edgeTypes.map((type) => ({
      type,
      count:
        graph?.edges.filter(
          (edge) => edge.type === type && (edge.source === selectedNode?.id || edge.target === selectedNode?.id),
        ).length ?? 0,
    }))
  }, [graph, selectedNode])

  const chapterTrees = useMemo<ChapterTree[]>(() => {
    if (!graph) return []

    const compareNodes = (a: CourseKnowledgeGraphNode, b: CourseKnowledgeGraphNode) =>
      a.level - b.level || a.label.localeCompare(b.label, 'zh-Hans-CN')

    return graph.chapters.map((chapter, chapterIndex) => {
      const nodes = graph.nodes
        .filter((node) => node.chapter_index === chapterIndex)
        .sort(compareNodes)
      const nodeById = new Map(nodes.map((node) => [node.id, node]))
      const labelMap = new Map<string, CourseKnowledgeGraphNode[]>()
      const childrenById = new Map<string, Set<string>>()
      const parentById = new Map<string, string>()

      nodes.forEach((node) => {
        const list = labelMap.get(node.label) ?? []
        list.push(node)
        labelMap.set(node.label, list)
      })

      const setLink = (parentId: string, childId: string) => {
        if (parentId === childId) return
        if (!nodeById.has(parentId) || !nodeById.has(childId)) return

        const currentParentId = parentById.get(childId)
        if (currentParentId === parentId) return
        if (currentParentId) return

        const list = childrenById.get(parentId) ?? new Set<string>()
        list.add(childId)
        childrenById.set(parentId, list)
        parentById.set(childId, parentId)
      }

      graph.edges
        .filter((edge) => edge.type === 'hierarchy')
        .forEach((edge) => {
          const source = nodeById.get(edge.source)
          const target = nodeById.get(edge.target)
          if (!source || !target) return

          if (target.parent_name === source.label) {
            setLink(source.id, target.id)
            return
          }

          if (source.parent_name === target.label) {
            setLink(target.id, source.id)
            return
          }

          if (source.level < target.level) {
            setLink(source.id, target.id)
            return
          }

          if (target.level < source.level) {
            setLink(target.id, source.id)
          }
        })

      nodes.forEach((node) => {
        if (parentById.has(node.id) || !node.parent_name) return
        const parentCandidate = (labelMap.get(node.parent_name) ?? [])
          .filter((candidate) => candidate.level < node.level)
          .sort((a, b) => b.level - a.level || a.label.localeCompare(b.label, 'zh-Hans-CN'))[0]

        if (parentCandidate) {
          setLink(parentCandidate.id, node.id)
        }
      })

      const buildTree = (node: CourseKnowledgeGraphNode): TreeNode => {
        const children = [...(childrenById.get(node.id) ?? new Set<string>())]
          .map((childId) => nodeById.get(childId))
          .filter((child): child is CourseKnowledgeGraphNode => Boolean(child))
          .sort(compareNodes)
          .map(buildTree)

        const descendantCount = children.reduce((sum, child) => sum + child.descendantCount + 1, 0)

        return {
          node,
          children,
          descendantCount,
        }
      }

      const roots = nodes
        .filter((node) => !parentById.has(node.id))
        .sort(compareNodes)
        .map(buildTree)

      return {
        chapter,
        chapterIndex,
        nodes,
        roots,
      }
    })
  }, [graph])

  const hierarchyLookup = useMemo(() => {
    const parentMap = new Map<string, CourseKnowledgeGraphNode>()
    const childrenMap = new Map<string, CourseKnowledgeGraphNode[]>()
    const treeMap = new Map<string, TreeNode>()

    const walk = (item: TreeNode, parent: CourseKnowledgeGraphNode | null) => {
      treeMap.set(item.node.id, item)
      if (parent) {
        parentMap.set(item.node.id, parent)
        const siblings = childrenMap.get(parent.id) ?? []
        siblings.push(item.node)
        childrenMap.set(parent.id, siblings)
      }

      if (!childrenMap.has(item.node.id)) {
        childrenMap.set(item.node.id, [])
      }

      item.children.forEach((child) => walk(child, item.node))
    }

    chapterTrees.forEach((chapter) => {
      chapter.roots.forEach((root) => walk(root, null))
    })

    return { parentMap, childrenMap, treeMap }
  }, [chapterTrees])

  const parentNode = selectedNode ? hierarchyLookup.parentMap.get(selectedNode.id) ?? null : null
  const childNodes = selectedNode ? hierarchyLookup.childrenMap.get(selectedNode.id) ?? [] : []
  const siblingNodes =
    selectedNode && parentNode
      ? (hierarchyLookup.childrenMap.get(parentNode.id) ?? []).filter((node) => node.id !== selectedNode.id)
      : []

  const requestDeleteNode = (node: CourseKnowledgeGraphNode) => {
    const directChildren = hierarchyLookup.childrenMap.get(node.id) ?? []
    const treeNode = hierarchyLookup.treeMap.get(node.id)
    const parent = hierarchyLookup.parentMap.get(node.id) ?? null
    const nextFocusId =
      directChildren[0]?.id ??
      parent?.id ??
      (parent ? (hierarchyLookup.childrenMap.get(parent.id) ?? []).find((item) => item.id !== node.id)?.id : null) ??
      null

    setDeleteDialog({
      node,
      directChildCount: directChildren.length,
      descendantCount: treeNode?.descendantCount ?? directChildren.length,
      nextFocusId,
    })
  }

  const handleDeleteNode = async (deleteDescendants: boolean) => {
    if (!courseId || !deleteDialog) return
    setDeletingNodeId(deleteDialog.node.id)
    try {
      const result = await deleteCourseKnowledgeNode(courseId, deleteDialog.node.id, deleteDescendants)
      messageApi.success(result.message)
      setDeleteDialog(null)
      await loadGraph(deleteDialog.nextFocusId)
    } catch {
      messageApi.error('删除知识点失败')
    } finally {
      setDeletingNodeId(null)
    }
  }

  const handleExportGraph = async () => {
    if (!courseId) return
    setExporting(true)
    try {
      const response = await exportCourseKnowledgeGraph(courseId)
      const blob = response.data as Blob
      const contentDisposition = String(response.headers['content-disposition'] ?? '')
      const match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i)
      const fileName = match?.[1] ? decodeURIComponent(match[1]) : `${graph?.course_name ?? '课程'}_学习通知识图谱导入.xlsx`

      const objectUrl = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = objectUrl
      link.download = fileName
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(objectUrl)
      messageApi.success('知识点模板导出成功')
    } catch {
      messageApi.error('导出失败，请稍后重试')
    } finally {
      setExporting(false)
    }
  }

  if (loading) {
    return (
      <Card className="notebook-panel">
        <Space direction="vertical" align="center" style={{ width: '100%', padding: '48px 0' }}>
          {contextHolder}
          <Spin size="large" />
          <Typography.Text type="secondary">正在加载知识图谱…</Typography.Text>
        </Space>
      </Card>
    )
  }

  if (!graph || graph.nodes.length === 0) {
    return (
      <>
        {contextHolder}
        <Card className="notebook-panel">
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>
              返回课程
            </Button>
            <Empty description="该课程暂未构建知识图谱" />
          </Space>
        </Card>
      </>
    )
  }

  return (
    <>
      {contextHolder}
      <div className="page-stack">
        <Card className="hero-panel graph-hero-panel">
          <Space direction="vertical" size={18} style={{ width: '100%' }}>
            <Space wrap size={12}>
              <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>
                返回课程
              </Button>
              <Button icon={<DownloadOutlined />} loading={exporting} onClick={() => void handleExportGraph()}>
                导出学习通模板
              </Button>
              <div className="hero-kicker">Knowledge Atlas</div>
            </Space>

            <div className="graph-hero-head">
              <div>
                <Typography.Title level={2} className="hero-title" style={{ marginBottom: 8 }}>
                  {graph.course_name} · 知识图谱
                </Typography.Title>
                <Typography.Paragraph className="hero-subtitle" style={{ marginBottom: 0 }}>
                  现在按章节分区、按层级展开，并用不同连线区分前置、后置、关联与同义关系。点击任一知识点，右侧会聚焦显示它的学习依赖与延展方向。
                </Typography.Paragraph>
                <div className="graph-chapter-ribbon">
                  {chapterStats.map((item) => (
                    <button
                      key={item.chapterIndex}
                      type="button"
                      className={`graph-chapter-pill ${selectedNode?.chapter_index === item.chapterIndex ? 'is-active' : ''}`}
                      style={buildChapterVars(item.chapterIndex)}
                      onClick={() => item.firstNode && setSelectedNode(item.firstNode)}
                    >
                      <span className="graph-chapter-pill-index">CH {item.chapterIndex + 1}</span>
                      <strong>{item.chapter}</strong>
                      <span>{item.count} 个知识点</span>
                    </button>
                  ))}
                </div>
              </div>
              <div className="graph-summary-grid">
                <div className="graph-summary-card">
                  <span className="graph-summary-label">知识点</span>
                  <strong>{graph.node_count}</strong>
                </div>
                <div className="graph-summary-card">
                  <span className="graph-summary-label">关系</span>
                  <strong>{graph.edge_count}</strong>
                </div>
                <div className="graph-summary-card">
                  <span className="graph-summary-label">章节</span>
                  <strong>{graph.chapter_count}</strong>
                </div>
              </div>
            </div>
          </Space>
        </Card>

        <div className="studio-grid knowledge-studio-grid">
          <Card
            className="notebook-panel hierarchy-panel"
            title={
              <Space>
                <ApartmentOutlined />
                层级树视图
              </Space>
            }
          >
            <div className="graph-toolbar">
              <div>
                <Typography.Text strong>主干优先</Typography.Text>
                <Typography.Paragraph className="list-muted" style={{ marginBottom: 0, marginTop: 4 }}>
                  每章按树状结构展开：一级主题最醒目，子知识点逐层缩进，并用连接线直接表现从属关系。这样先看主干，再看分支。
                </Typography.Paragraph>
              </div>
            </div>

            <div className="chapter-tree-list">
              {chapterTrees.map((chapter) => (
                <section
                  key={chapter.chapterIndex}
                  className="chapter-tree-section"
                  style={buildChapterVars(chapter.chapterIndex)}
                >
                  <div className="chapter-tree-header">
                    <div>
                      <div className="chapter-tree-kicker">Chapter {chapter.chapterIndex + 1}</div>
                      <Typography.Title level={4} style={{ margin: '6px 0 0' }}>
                        {chapter.chapter}
                      </Typography.Title>
                    </div>
                    <div className="chapter-tree-summary">
                      <span>{chapter.nodes.length} 个知识点</span>
                      <span>{chapter.roots.length} 条主干</span>
                    </div>
                  </div>

                  <div className="chapter-tree-body">
                    {chapter.roots.length > 0 ? (
                      chapter.roots.map((root) => (
                        <TreeNodeView
                          key={root.node.id}
                          chapterIndex={chapter.chapterIndex}
                          item={root}
                          selectedNodeId={selectedNode?.id ?? null}
                          relationCountMap={relationCountMap}
                          onSelect={setSelectedNode}
                          onDelete={requestDeleteNode}
                        />
                      ))
                    ) : (
                      <Typography.Text type="secondary">当前章节暂无可展示的层级主干。</Typography.Text>
                    )}
                  </div>
                </section>
              ))}
            </div>
          </Card>

          <div className="knowledge-side-stack">
            {selectedNode && (
              <Card
                className="notebook-panel floating-subtle graph-detail-card"
                title={selectedNode.label}
                extra={
                  <Button
                    type="text"
                    danger
                    size="small"
                    className="graph-detail-delete"
                    icon={<DeleteOutlined />}
                    loading={deletingNodeId === selectedNode.id}
                    onClick={() => requestDeleteNode(selectedNode)}
                  />
                }
                styles={{ body: buildChapterVars(selectedNode.chapter_index) }}
              >
                <Space direction="vertical" size={16} style={{ width: '100%' }}>
                  <Space wrap>
                    <Tag className="soft-tag">{selectedNode.chapter}</Tag>
                    <Tag className="soft-tag">层级 {selectedNode.level}</Tag>
                    {selectedNode.parent_name && <Tag className="soft-tag">上级：{selectedNode.parent_name}</Tag>}
                  </Space>

                  <div className="detail-metrics">
                    <div className="metric-box">
                      <div className="stat-label">层级</div>
                      <strong>L{selectedNode.level}</strong>
                    </div>
                    <div className="metric-box">
                      <div className="stat-label">前置知识</div>
                      <strong>{selectedNode.prerequisite_points.length}</strong>
                    </div>
                    <div className="metric-box">
                      <div className="stat-label">后置知识</div>
                      <strong>{selectedNode.postrequisite_points.length}</strong>
                    </div>
                    <div className="metric-box">
                      <div className="stat-label">关联知识</div>
                      <strong>{selectedNode.related_points.length}</strong>
                    </div>
                  </div>

                  <Typography.Paragraph className="graph-detail-copy" style={{ marginBottom: 0 }}>
                    {selectedNode.description || '暂无知识点说明'}
                  </Typography.Paragraph>

                  <div className="graph-detail-breakdown">
                    {selectedEdgeBreakdown
                      .filter((item) => item.count > 0)
                      .map((item) => (
                        <span className="graph-breakdown-item" key={item.type}>
                          <span
                            className="edge-filter-dot"
                            style={{ background: edgeTypeMeta[item.type].color }}
                          />
                          {edgeTypeMeta[item.type].label} {item.count}
                        </span>
                      ))}
                  </div>

                  {renderRelationGroup(
                    '上级知识',
                    parentNode ? [parentNode.label] : [],
                    '当前节点位于章节主干顶部，没有上级知识。',
                  )}
                  {renderRelationGroup(
                    '下级知识',
                    childNodes.map((node) => node.label),
                    '当前节点没有继续拆分的下级知识。',
                  )}
                  {renderRelationGroup(
                    '同级知识',
                    siblingNodes.map((node) => node.label),
                    '当前节点没有同级兄弟知识。',
                  )}
                  {renderRelationGroup('前置知识', selectedNode.prerequisite_points, '当前没有记录前置知识。')}
                  {renderRelationGroup('后置知识', selectedNode.postrequisite_points, '当前没有记录后置知识。')}
                  {renderRelationGroup('关联知识', selectedNode.related_points, '当前没有记录关联知识。')}
                </Space>
              </Card>
            )}

            <Card className="notebook-panel graph-outline-card" title="章节导览">
              <div className="chapter-overview-list">
                {chapterStats.map((item) => (
                  <button
                    key={item.chapterIndex}
                    type="button"
                    className={`chapter-overview-item ${selectedNode?.chapter_index === item.chapterIndex ? 'is-active' : ''}`}
                    style={buildChapterVars(item.chapterIndex)}
                    onClick={() => item.firstNode && setSelectedNode(item.firstNode)}
                    disabled={!item.firstNode}
                  >
                    <div>
                      <strong>{item.chapter}</strong>
                      <span>
                        {item.count} 个知识点 · {item.levelCount} 层级
                      </span>
                    </div>
                    <Tag className="soft-tag">关系 {item.relationCount}</Tag>
                  </button>
                ))}
              </div>
            </Card>

            <Card className="notebook-panel graph-outline-card" title="图谱说明">
              <Space direction="vertical" size={10} style={{ width: '100%' }}>
                {edgeTypes.map((edgeType) => (
                  <div className="graph-legend-row" key={edgeType}>
                    <span className="graph-legend-swatch" style={{ background: edgeTypeMeta[edgeType].color }} />
                    <div>
                      <Typography.Text strong>{edgeTypeMeta[edgeType].label}</Typography.Text>
                      <Typography.Paragraph className="list-muted" style={{ marginBottom: 0 }}>
                        {edgeType === 'hierarchy' && '表示课程内部的概念层次与归属。'}
                        {edgeType === 'prerequisite' && '表示先学后学的依赖关系。'}
                        {edgeType === 'postrequisite' && '表示该知识点会支撑哪些后续主题。'}
                        {edgeType === 'related' && '表示内容关联、应用互通或常见联想。'}
                        {edgeType === 'equivalent' && '表示术语近义、表达等价或名称映射。'}
                      </Typography.Paragraph>
                    </div>
                  </div>
                ))}
              </Space>
            </Card>
          </div>
        </div>
      </div>

      <Modal
        title="删除知识点"
        open={Boolean(deleteDialog)}
        onCancel={() => setDeleteDialog(null)}
        footer={
          deleteDialog
            ? [
                <Button key="cancel" onClick={() => setDeleteDialog(null)}>
                  取消
                </Button>,
                deleteDialog.directChildCount > 0 ? (
                  <Button
                    key="promote"
                    loading={deletingNodeId === deleteDialog.node.id}
                    onClick={() => void handleDeleteNode(false)}
                  >
                    仅删当前节点
                  </Button>
                ) : null,
                <Button
                  key="delete"
                  danger
                  type="primary"
                  loading={deletingNodeId === deleteDialog?.node.id}
                  onClick={() => void handleDeleteNode(true)}
                >
                  {deleteDialog.directChildCount > 0 ? '递归删除子节点' : '删除'}
                </Button>,
              ]
            : undefined
        }
      >
        {deleteDialog && (
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            <Typography.Text>
              确定删除知识点「{deleteDialog.node.label}」吗？
            </Typography.Text>
            {deleteDialog.directChildCount > 0 ? (
              <>
                <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                  该节点下还有 {deleteDialog.directChildCount} 个直接子节点，整棵子树共 {deleteDialog.descendantCount} 个后代节点。
                </Typography.Paragraph>
                <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                  选择“递归删除子节点”会整棵子树一起删除；选择“仅删当前节点”会保留后代，并把直接子节点整体提升一级。
                </Typography.Paragraph>
              </>
            ) : (
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                当前节点没有子节点，将只删除它本身。
              </Typography.Paragraph>
            )}
          </Space>
        )}
      </Modal>
    </>
  )
}
