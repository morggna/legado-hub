import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate, useParams } from "react-router"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { LegadoReader } from "@/components/legado-reader/LegadoReader"
import { Button } from "@/components/ui/button"
import { bookPath, directRequest, type DirectBook, type DirectChapter, type Progress } from "@/lib/direct-api"

export function DirectReaderPage() {
  const { bookId = "" } = useParams()
  const progress = useQuery({ queryKey: ["direct", "progress", bookId], queryFn: () => directRequest<Progress>(`${bookPath(bookId)}/progress`), staleTime: 0 })
  if (progress.isPending) return <p className="p-8">载入阅读进度…</p>
  if (progress.error) return <div className="p-8" role="alert">{progress.error.message}<Button onClick={() => { void progress.refetch() }}>重试</Button></div>
  return <Reader key={bookId} bookId={bookId} initial={progress.data} />
}
function Reader({ bookId, initial }: { bookId: string; initial: Progress }) {
  const [index, setIndex] = useState(initial.chapterIndex)
  const [resume, setResume] = useState(initial.position)
  const [saveError, setSaveError] = useState("")
  const client = useQueryClient()
  const navigate = useNavigate()
  const userId = client.getQueryData<{ user: { userId: string } }>(["auth", "me"])?.user?.userId ?? "preview"
  const path = bookPath(bookId)
  const detail = useQuery({ queryKey: ["direct", "detail", bookId], queryFn: () => directRequest<DirectBook>(`${path}/detail`) })
  const toc = useQuery({ queryKey: ["direct", "toc", bookId], queryFn: () => directRequest<{ chapters: DirectChapter[] }>(`${path}/toc`) })
  const chapter = useQuery({ queryKey: ["direct", "chapter", bookId, index], queryFn: ({ signal }) => directRequest<{ title: string; content: string }>(`${path}/chapters/${index}`, { signal }), enabled: !!toc.data, retry: false, staleTime: 300000, refetchOnWindowFocus: false })
  const revision = useRef(initial.revision)
  const queue = useRef<Promise<void>>(Promise.resolve())
  const blocked = useRef(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pending = useRef<{ chapterIndex: number; position: number } | null>(null)
  const save = useCallback((value: { chapterIndex: number; position: number }, keepalive = false) => {
    queue.current = queue.current.then(async () => {
      if (blocked.current) return
      try {
        const result = await directRequest<Progress>(`${path}/progress`, { method: "PUT", keepalive, body: JSON.stringify({ ...value, revision: revision.current }) })
        revision.current = result.revision
        setSaveError("")
      } catch (e) {
        blocked.current = true
        setSaveError(e instanceof Error ? e.message : "保存进度失败")
      }
    })
  }, [path])
  useEffect(() => {
    const flush = () => {
      if (timer.current) clearTimeout(timer.current)
      const value = pending.current
      pending.current = null
      if (value) save(value, true)
    }
    window.addEventListener("pagehide", flush)
    return () => { window.removeEventListener("pagehide", flush); flush() }
  }, [save])
  const changeChapter = useCallback((next: number, position = 0) => {
    if (timer.current) clearTimeout(timer.current)
    pending.current = null
    setResume(position)
    save({ chapterIndex: next, position })
    setIndex(next)
  }, [save])
  const updatePosition = useCallback((position: number) => {
    const value = { chapterIndex: index, position }
    pending.current = value
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => { pending.current = null; save(value) }, 700)
  }, [index, save])
  const failure = detail.error || toc.error || chapter.error
  return <LegadoReader userId={userId} title={detail.data?.name || "载入书籍…"} chapters={toc.data?.chapters ?? []} index={index}
    chapter={chapter.data} loading={chapter.isPending || toc.isPending} error={failure?.message || saveError}
    position={resume} onPosition={updatePosition} onChapter={changeChapter} onClose={() => navigate("/console/library")}
    onRetry={() => { if (saveError) window.location.reload(); else { void detail.refetch(); void toc.refetch(); void chapter.refetch() } }} />
}
