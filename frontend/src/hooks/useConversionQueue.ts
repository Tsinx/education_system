import { useCallback, useEffect, useMemo, useState } from 'react'
import { createMaterialTask, fetchMaterialDetail, fetchMaterials } from '../api/client'
import type { MaterialItem } from '../types'

export type ConvertedFile = {
  id: string
  filename: string
  markdown?: string
  summary?: string | null
  processStage?: string | null
  charCount: number
  status: 'pending' | 'converting' | 'done' | 'error'
}

const toViewItem = (item: MaterialItem): ConvertedFile => ({
  id: item.id,
  filename: item.filename,
  summary: item.summary,
  processStage: item.process_stage,
  charCount: item.char_count,
  status:
    item.status === 'queued'
      ? 'pending'
      : item.status === 'running'
        ? 'converting'
        : item.status === 'done'
          ? 'done'
          : 'error',
})

export function useConversionQueue(courseId?: string) {
  const [files, setFiles] = useState<ConvertedFile[]>([])
  const [loading, setLoading] = useState(false)

  const refresh = useCallback(async () => {
    if (!courseId) return
    try {
      const materials = await fetchMaterials(courseId)
      setFiles(materials.map(toViewItem))
    } catch {
      setFiles((prev) => prev)
    }
  }, [courseId])

  useEffect(() => {
    refresh()
  }, [refresh])

  const enqueue = useCallback(
    (newFiles: File[]) => {
      if (newFiles.length === 0) return
      setLoading(true)
      Promise.all(newFiles.map((file) => createMaterialTask(file, courseId)))
        .then((created) => {
          setFiles((prev) => [...created.map(toViewItem), ...prev])
        })
        .catch(() => {
          setFiles((prev) => prev)
        })
        .finally(() => {
          setLoading(false)
        })
    },
    [courseId],
  )

  const clear = useCallback(() => {
    setFiles([])
  }, [])

  const pendingCount = useMemo(
    () => files.filter((f) => f.status === 'pending' || f.status === 'converting').length,
    [files],
  )

  useEffect(() => {
    if (pendingCount === 0) return
    const timer = window.setInterval(() => {
      if (courseId) {
        refresh()
        return
      }
      setFiles((prev) => {
        if (prev.length === 0) return prev
        void Promise.all(
          prev.map(async (item) => {
            try {
              const detail = await fetchMaterialDetail(item.id)
              return toViewItem(detail)
            } catch {
              return item
            }
          }),
        ).then((next) => setFiles(next))
        return prev
      })
    }, 3000)
    return () => window.clearInterval(timer)
  }, [pendingCount, refresh, courseId])

  return { files, enqueue, clear, pendingCount, loading, refresh }
}
