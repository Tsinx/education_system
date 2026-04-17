import axios from 'axios'
import { mockChapters, mockCourses, mockKnowledgeSummary, mockProjects, mockTasks } from '../data/mock'
import type {
  AiOutputType,
  CourseKnowledgeGraph,
  AiResultDetail,
  AiResultItem,
  Chapter,
  Course,
  CreateCoursePayload,
  DeleteKnowledgePointResult,
  GenerationTask,
  KnowledgeSummary,
  MaterialDetail,
  MaterialItem,
  Project,
  RefineKnowledgeGraphResult,
} from '../types'

const apiBaseUrl =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim().replace(/\/$/, '') ||
  `${window.location.origin}/api/v1`

const api = axios.create({
  baseURL: apiBaseUrl,
  timeout: 60000,
})

export type RuntimeLlmOptions = {
  provider?: string
  apiKey?: string
  model?: string
}

export async function fetchCourses() {
  try {
    const { data } = await api.get<Course[]>('/courses')
    return data
  } catch {
    return mockCourses
  }
}

export async function createCourse(payload: CreateCoursePayload) {
  try {
    const { data } = await api.post<Course>('/courses', payload)
    return data
  } catch {
    const newCourse: Course = {
      id: `course_${Date.now()}`,
      name: payload.name,
      description: payload.description ?? '',
      hours: payload.hours ?? 0,
      sessions: payload.sessions ?? Math.ceil((payload.hours ?? 0) / 2),
      chapter_count: 0,
      created_at: new Date().toISOString().slice(0, 10),
    }
    mockCourses.push(newCourse)
    return newCourse
  }
}

export async function deleteCourse(courseId: string) {
  try {
    await api.delete(`/courses/${courseId}`)
  } catch {
    const idx = mockCourses.findIndex((c) => c.id === courseId)
    if (idx !== -1) mockCourses.splice(idx, 1)
  }
}

export async function fetchChapters(courseId: string) {
  try {
    const { data } = await api.get<Chapter[]>(`/courses/${courseId}/chapters`)
    return data
  } catch {
    return mockChapters[courseId] ?? []
  }
}

export async function addChapter(courseId: string, title: string) {
  try {
    const { data } = await api.post<Chapter>(`/courses/${courseId}/chapters`, { title })
    return data
  } catch {
    const chapters = mockChapters[courseId] ?? []
    const newChapter: Chapter = {
      id: `ch_${Date.now()}`,
      course_id: courseId,
      title,
      sort_order: chapters.length + 1,
      material_count: 0,
    }
    chapters.push(newChapter)
    mockChapters[courseId] = chapters
    return newChapter
  }
}

export async function createMaterialTask(file: File, courseId?: string): Promise<MaterialItem> {
  const formData = new FormData()
  formData.append('file', file)
  if (courseId) formData.append('course_id', courseId)
  const { data } = await api.post<MaterialItem>('/materials/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 30000,
  })
  return data
}

export async function fetchMaterials(courseId?: string) {
  const { data } = await api.get<MaterialItem[]>('/materials', {
    params: { course_id: courseId, limit: 200 },
  })
  return data
}

export async function fetchMaterialDetail(materialId: string) {
  const { data } = await api.get<MaterialDetail>(`/materials/${materialId}`)
  return data
}

export async function deleteMaterial(materialId: string) {
  await api.delete(`/materials/${materialId}`)
}

export async function bindMaterialsToCourse(courseId: string, materialIds: string[]) {
  if (materialIds.length === 0) return
  await api.post('/materials/bind-course', {
    course_id: courseId,
    material_ids: materialIds,
  })
}

export async function refineCourseKnowledgeGraph(courseId: string) {
  const { data } = await api.post<RefineKnowledgeGraphResult>(`/materials/courses/${courseId}/refine-knowledge-graph`)
  return data
}

export async function startAiGeneration(
  courseId: string,
  outputTypes: AiOutputType[],
  userGuidance = '',
  options?: {
    lesson_plan_scope?: 'auto' | 'single' | 'multiple' | 'semester'
    lesson_count?: number
    exercise_requirements?: string
    selected_knowledge_ids?: string[]
    llm?: RuntimeLlmOptions
  },
): Promise<AiResultItem[]> {
  const llmProvider = options?.llm?.provider?.trim()
  const llmApiKey = options?.llm?.apiKey?.trim()
  const llmModel = options?.llm?.model?.trim()
  const { data } = await api.post<AiResultItem[]>('/generation/start', {
    course_id: courseId,
    output_types: outputTypes,
    user_guidance: userGuidance,
    lesson_plan_scope: options?.lesson_plan_scope ?? 'auto',
    lesson_count: options?.lesson_count ?? null,
    exercise_requirements: options?.exercise_requirements ?? '',
    selected_knowledge_ids: options?.selected_knowledge_ids ?? [],
    llm_provider: llmProvider ?? '',
    llm_api_key: llmApiKey ?? '',
    llm_model: llmModel ?? '',
  })
  return data
}

export async function fetchAiResults(courseId: string) {
  const { data } = await api.get<AiResultItem[]>('/generation/results', {
    params: { course_id: courseId },
  })
  return data
}

export async function fetchAiResultDetail(resultId: string) {
  const { data } = await api.get<AiResultDetail>(`/generation/results/${resultId}`)
  return data
}

export function buildStreamUrl(resultId: string, llm?: RuntimeLlmOptions) {
  const base = `${apiBaseUrl}/generation/stream/${resultId}`
  const params = new URLSearchParams()
  const provider = llm?.provider?.trim()
  const apiKey = llm?.apiKey?.trim()
  const model = llm?.model?.trim()
  if (provider) params.set('llm_provider', provider)
  if (apiKey) params.set('llm_api_key', apiKey)
  if (model) params.set('llm_model', model)
  const query = params.toString()
  return query ? `${base}?${query}` : base
}

export function buildExportUrl(resultId: string) {
  return `${apiBaseUrl}/generation/export/${resultId}`
}

export function buildLessonBatchExportUrl(lessonBatchId: string) {
  return `${apiBaseUrl}/generation/export-batch/${lessonBatchId}`
}

export async function fetchProjects() {
  try {
    const { data } = await api.get<Project[]>('/projects')
    return data
  } catch {
    return mockProjects
  }
}

export async function fetchTasks() {
  try {
    const { data } = await api.get<GenerationTask[]>('/generation/tasks')
    return data
  } catch {
    return mockTasks
  }
}

export async function fetchKnowledgeSummary() {
  try {
    const { data } = await api.get<KnowledgeSummary>('/knowledge/summary')
    return data
  } catch {
    return mockKnowledgeSummary
  }
}

export async function fetchCourseKnowledgeGraph(courseId: string) {
  const { data } = await api.get<CourseKnowledgeGraph>(`/knowledge/courses/${courseId}/graph`)
  return data
}

export async function deleteCourseKnowledgeNode(courseId: string, nodeId: string, deleteDescendants: boolean) {
  const { data } = await api.delete<DeleteKnowledgePointResult>(`/knowledge/courses/${courseId}/nodes/${nodeId}`, {
    params: {
      delete_descendants: deleteDescendants,
    },
  })
  return data
}

export async function exportCourseKnowledgeGraph(courseId: string) {
  const response = await api.get(`/knowledge/courses/${courseId}/graph-export`, {
    responseType: 'blob',
  })
  return response
}


