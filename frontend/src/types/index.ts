export type Course = {
  id: string
  name: string
  description: string
  hours: number
  sessions: number
  chapter_count: number
  created_at: string
}

export type CreateCoursePayload = {
  name: string
  description?: string
  hours?: number
  sessions?: number
}

export type Chapter = {
  id: string
  course_id: string
  title: string
  sort_order: number
  material_count: number
}

export type Project = {
  id: string
  name: string
  material_count: number
}

export type GenerationTask = {
  id: string
  project_id: string
  status: string
  progress: number
}

export type KnowledgeSummary = {
  project_id: string
  node_count: number
  relation_count: number
  top_topics: string[]
}

export type MaterialStatus = 'queued' | 'running' | 'done' | 'failed'

export type MaterialItem = {
  id: string
  course_id: string | null
  filename: string
  file_size: number
  status: MaterialStatus
  progress: number
  process_stage: string | null
  char_count: number
  summary: string | null
  knowledge_extracted: boolean
  created_at: string
  updated_at: string
}

export type MaterialDetail = MaterialItem & {
  markdown: string | null
  error_message: string | null
}

export type AiOutputType = 'outline' | 'knowledge' | 'teaching_plan' | 'ideology_case' | 'lesson_plan' | 'exercise'

export type AiResultStatus = 'queued' | 'running' | 'done' | 'failed'

export type AiResultItem = {
  id: string
  course_id: string
  output_type: AiOutputType
  title: string
  status: AiResultStatus
  char_count: number
  request_context: Record<string, string>
  created_at: string
  updated_at: string
}

export type AiResultDetail = AiResultItem & {
  content: string | null
  error_message: string | null
}

export type RefineKnowledgeGraphResult = {
  course_id: string
  material_total: number
  material_backfilled: number
  knowledge_points_total: number
  relation_updated: number
  graph_edges_total: number
  duplicate_merged: number
}

export type CourseKnowledgeGraphNode = {
  id: string
  label: string
  chapter: string
  chapter_index: number
  level: number
  parent_name: string | null
  description: string
  prerequisite_points: string[]
  postrequisite_points: string[]
  related_points: string[]
}

export type CourseKnowledgeGraphEdge = {
  id: string
  source: string
  target: string
  type: 'hierarchy' | 'prerequisite' | 'postrequisite' | 'related' | 'equivalent'
}

export type CourseKnowledgeGraph = {
  course_id: string
  course_name: string
  node_count: number
  edge_count: number
  chapter_count: number
  chapters: string[]
  nodes: CourseKnowledgeGraphNode[]
  edges: CourseKnowledgeGraphEdge[]
}

export type DeleteKnowledgePointResult = {
  message: string
  deleted_count: number
  promoted_count: number
  recursive: boolean
}

