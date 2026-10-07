import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate, useParams, useSearchParams } from "react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { DirectProgressSync } from "@/lib/direct-progress"
import { LegadoReader } from "@/components/legado-reader/LegadoReader"
import { Button } from "@/components/ui/button"
import { bookPath, bookDetailUrl, directRequest, type DirectBook, type DirectChapter, type Progress } from "@/lib/direct-api"

export function DirectReaderPage() {
  const { bookId = "" } = useParams()
  const [params] = useSearchParams()
  const target = params.get("chapter")
  const entryIndex = target === null ? undefined : /^\d+$/.test(target) && Number(target) <= 1000000 ? Number(target) : -1
  const progress = useQuery({ queryKey: ["direct", "progress", bookId], queryFn: () => directRequest<Progress>(`${bookPath(bookId)}/progress`), staleTime: 0, refetchOnMount: "always", refetchOnWindowFocus: false, refetchOnReconnect: false })
  if (progress.isPending || progress.isFetching) return <p className="p-8">载入阅读进度…</p>
  if (progress.error) return <div className="p-8" role="alert">{progress.error.message}<Button onClick={() => { void progress.refetch() }}>重试</Button></div>
  return <Reader key={`${bookId}:${target ?? "resume"}`} bookId={bookId} initial={progress.data} entryIndex={entryIndex} />
}
function Reader({ bookId, initial, entryIndex }: { bookId: string; initial: Progress; entryIndex?: number }) {
  const [index, setIndex] = useState(entryIndex ?? initial.chapterIndex)
  const [resume, setResume] = useState(entryIndex === undefined ? initial.position : 0)
  const [saveError, setSaveError] = useState("")
  const client = useQueryClient()
  const navigate = useNavigate()
  const userId = client.getQueryData<{ user: { userId: string } }>(["auth", "me"])?.user?.userId ?? "preview"
  const path = bookPath(bookId)
  const detail = useQuery({ queryKey: ["direct", "detail", bookId], queryFn: () => directRequest<DirectBook>(`${path}/detail`) })
  const source = useMutation({ mutationFn: (sourceBookId: string | null) => directRequest<DirectBook>(`${path}/source`, { method: "PUT", body: JSON.stringify({ sourceBookId }) }),
    onSuccess: async result => {
      client.setQueryData(["direct", "detail", bookId], result)
      await client.invalidateQueries({ queryKey: ["direct", "chapter", bookId] })
    } })
  const toc = useQuery({ queryKey: ["direct", "toc", bookId], queryFn: () => directRequest<{ chapters: DirectChapter[] }>(`${path}/toc`) })
  const validIndex = !!toc.data && toc.data.chapters.some(c => c.index === index)
  const entrySaved = useRef(false)
  const chapter = useQuery({ queryKey: ["direct", "chapter", bookId, index, detail.data?.preferredSourceBookId ?? "auto"], queryFn: ({ signal }) => directRequest<{ title: string; content: string; aggregation?: { mode: string; selectedSourceName: string; acceptedCount: number; supportCount: number } }>(`${path}/chapters/${index}`, { signal }), enabled: validIndex, retry: false, staleTime: 300000, refetchOnWindowFocus: false })
  const [sync] = useState(() => new DirectProgressSync(bookId, userId, initial))
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const save = useCallback((value: { chapterIndex: number; position: number }) => {
    sync.mark(value)
    void sync.flush()
  }, [sync])
  useEffect(() => {
    const unsubscribe = sync.subscribe((remote, error) => {
      setSaveError(error)
      if (remote) {
        if (timer.current) clearTimeout(timer.current)
        entrySaved.current = true
        setIndex(remote.chapterIndex)
        setResume(remote.position)
        client.setQueryData(["direct", "progress", bookId], remote)
      }
      void client.invalidateQueries({ queryKey: ["direct", "overview", bookId] })
    })
    const flush = () => {
      if (timer.current) clearTimeout(timer.current)
      void sync.flush()
    }
    const resumeSync = () => { if (document.visibilityState !== "hidden") void sync.reconcile() }
    const visibility = () => { if (document.visibilityState === "hidden") flush(); else resumeSync() }
    window.addEventListener("pagehide", flush)
    window.addEventListener("pageshow", resumeSync)
    window.addEventListener("focus", resumeSync)
    window.addEventListener("online", resumeSync)
    document.addEventListener("visibilitychange", visibility)
    const interval = setInterval(resumeSync, 15000)
    if (entryIndex === undefined) void sync.recover()
    return () => {
      unsubscribe(); clearInterval(interval); flush()
      window.removeEventListener("pagehide", flush)
      window.removeEventListener("pageshow", resumeSync)
      window.removeEventListener("focus", resumeSync)
      window.removeEventListener("online", resumeSync)
      document.removeEventListener("visibilitychange", visibility)
    }
  }, [sync, client, bookId, entryIndex])
  useEffect(() => {
    if (entryIndex !== undefined && index === entryIndex && chapter.data && validIndex && !entrySaved.current) {
      entrySaved.current = true
      save({ chapterIndex: entryIndex, position: 0 })
    }
  }, [entryIndex, index, chapter.data, validIndex, save])
  const changeChapter = useCallback((next: number, position = 0) => {
    entrySaved.current = true
    if (timer.current) clearTimeout(timer.current)
    setResume(position)
    save({ chapterIndex: next, position })
    setIndex(next)
  }, [save])
  const updatePosition = useCallback((position: number) => {
    if (document.visibilityState === "hidden") return
    sync.mark({ chapterIndex: index, position })
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => { void sync.flush() }, 700)
  }, [index, sync])
  const failure = detail.error || toc.error || chapter.error || source.error
  return <LegadoReader userId={userId} title={detail.data?.name || "载入书籍…"} chapters={toc.data?.chapters ?? []} index={index}
    sourceControl={!detail.data?.imported && detail.data?.sources?.length ? <select aria-label="阅读线路" className="max-w-32 rounded border bg-transparent p-1 text-sm" value={detail.data.preferredSourceBookId ?? ""} disabled={source.isPending} onChange={e => source.mutate(e.target.value || null)}><option value="">自动择优</option>{detail.data.sources.map(s => <option key={s.bookId} value={s.bookId}>{s.sourceName}</option>)}</select> : undefined}
    chapter={chapter.data} sourceStatus={chapter.data?.aggregation ? `${chapter.data.aggregation.selectedSourceName} · ${chapter.data.aggregation.mode === "manual" ? "手动选线" : chapter.data.aggregation.mode === "consensus" ? `${chapter.data.aggregation.supportCount + 1} 源正文一致` : "降级阅读：来源不足或尚无共识"}` : undefined} loading={toc.isPending || (validIndex && chapter.isPending)} error={failure?.message || (toc.data && !validIndex ? "章节不存在，请返回目录选择章节" : saveError)}
    position={resume} onPosition={updatePosition} onChapter={changeChapter} onClose={() => navigate(bookDetailUrl(bookId))}
    onRetry={() => { if (saveError) void sync.reconcile(); else { void detail.refetch(); void toc.refetch(); if (validIndex) void chapter.refetch() } }} />
}
