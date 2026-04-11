import type { Chapter, Course, GenerationTask, KnowledgeSummary, Project } from '../types'

export const mockCourses: Course[] = [
  {
    id: 'course_001',
    name: '高等数学（上）',
    description: '极限、连续、导数与微分、微分中值定理与导数的应用',
    hours: 64,
    sessions: 32,
    chapter_count: 5,
    created_at: '2026-03-28',
  },
  {
    id: 'course_002',
    name: '大学物理·电磁学',
    description: '静电场、稳恒磁场、电磁感应与电磁波',
    hours: 48,
    sessions: 24,
    chapter_count: 4,
    created_at: '2026-03-25',
  },
  {
    id: 'course_003',
    name: '数据结构与算法',
    description: '线性表、树与二叉树、图、排序与查找算法',
    hours: 56,
    sessions: 28,
    chapter_count: 6,
    created_at: '2026-03-20',
  },
]

export const mockChapters: Record<string, Chapter[]> = {
  course_001: [
    { id: 'ch_001', course_id: 'course_001', title: '第一章 函数与极限', sort_order: 1, material_count: 3 },
    { id: 'ch_002', course_id: 'course_001', title: '第二章 导数与微分', sort_order: 2, material_count: 5 },
    { id: 'ch_003', course_id: 'course_001', title: '第三章 微分中值定理与导数的应用', sort_order: 3, material_count: 2 },
    { id: 'ch_004', course_id: 'course_001', title: '第四章 不定积分', sort_order: 4, material_count: 4 },
    { id: 'ch_005', course_id: 'course_001', title: '第五章 定积分及其应用', sort_order: 5, material_count: 1 },
  ],
  course_002: [
    { id: 'ch_006', course_id: 'course_002', title: '第一章 静电场', sort_order: 1, material_count: 4 },
    { id: 'ch_007', course_id: 'course_002', title: '第二章 静电场中的导体与电介质', sort_order: 2, material_count: 3 },
    { id: 'ch_008', course_id: 'course_002', title: '第三章 稳恒磁场', sort_order: 3, material_count: 2 },
    { id: 'ch_009', course_id: 'course_002', title: '第四章 电磁感应与电磁波', sort_order: 4, material_count: 3 },
  ],
  course_003: [
    { id: 'ch_010', course_id: 'course_003', title: '第一章 绪论与算法分析', sort_order: 1, material_count: 2 },
    { id: 'ch_011', course_id: 'course_003', title: '第二章 线性表', sort_order: 2, material_count: 6 },
    { id: 'ch_012', course_id: 'course_003', title: '第三章 栈与队列', sort_order: 3, material_count: 4 },
    { id: 'ch_013', course_id: 'course_003', title: '第四章 树与二叉树', sort_order: 4, material_count: 5 },
    { id: 'ch_014', course_id: 'course_003', title: '第五章 图', sort_order: 5, material_count: 3 },
    { id: 'ch_015', course_id: 'course_003', title: '第六章 排序', sort_order: 6, material_count: 4 },
  ],
}

export const mockProjects: Project[] = [
  {
    id: 'project_demo_001',
    name: '高等数学（上）',
    material_count: 5,
  },
]

export const mockTasks: GenerationTask[] = [
  {
    id: 'task_demo_001',
    project_id: 'project_demo_001',
    status: 'running',
    progress: 30,
  },
  {
    id: 'task_demo_002',
    project_id: 'project_demo_001',
    status: 'completed',
    progress: 100,
  },
]

export const mockKnowledgeSummary: KnowledgeSummary = {
  project_id: 'project_demo_001',
  node_count: 28,
  relation_count: 46,
  top_topics: ['极限', '连续性', '导数', '微分中值定理'],
}
