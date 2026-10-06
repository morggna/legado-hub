import { useState } from "react"
import { Link, useParams } from "react-router"
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, BookOpen, ChevronLeft, ChevronRight, RefreshCw } from "lucide-react"
import { BookCover } from "@/components/BookCover"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { bookPath, bookReaderUrl, directRequest, downloadLabels, type BookOverview } from "@/lib/direct-api"

const statusLabels: Record<string, string> = {on_demand: "按需获取", cached: "已有缓存", downloaded: "已下载", failed: "下载失败"}
const auditLabels: Record<string, string> = {accepted: "正文可用", no_aligned_chapter: "未找到对应章节", title_mismatch: "章节不匹配", too_large: "正文过大", incomplete: "正文不完整", unavailable: "请求失败"}

export function DirectBookDetailPage() {
  const { bookId = "" } = useParams()
  return <BookDetail key={bookId} bookId={bookId} />
}
function BookDetail({ bookId }: {bookId: string}) {
  const client = useQueryClient()
  const [keyword, setKeyword] = useState("")
  const [status, setStatus] = useState("all")
  const [page, setPage] = useState(1)
  const path = bookPath(bookId)
  const overview = useQuery({queryKey: ["direct", "overview", bookId, keyword, status, page],
    queryFn: ({signal}) => directRequest<BookOverview>(`${path}/overview?${new URLSearchParams({keyword, status, page: String(page), pageSize: "50"})}`, {signal}),
    placeholderData: keepPreviousData, retry: false, refetchInterval: q => q.state.data?.download && ["queued", "running"].includes(q.state.data.download.state) ? 3000 : false})
  const action = useMutation({mutationFn: (method: string) => directRequest(`${path}/download`, {method}), onSuccess: async () => {
    await Promise.all([client.invalidateQueries({queryKey:["direct", "overview", bookId]}), client.invalidateQueries({queryKey:["direct", "downloads"]})])
  }})
  const data = overview.data
  const job = data?.download
  const active = job && ["running", "queued"].includes(job.state)
  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0)/50))
  return <div className="mx-auto max-w-6xl space-y-6 py-4 md:p-8">
    <div className="flex items-center justify-between gap-3"><Button asChild variant="ghost"><Link to="/console/library"><ArrowLeft />我的书库</Link></Button><Button variant="outline" disabled={overview.isFetching} onClick={() => { void overview.refetch() }}><RefreshCw className={overview.isFetching ? "animate-spin" : ""} />重新载入</Button></div>
    {overview.isPending && <p role="status" className="rounded-xl border bg-white p-8">正在载入书籍目录和线路…</p>}
    {(overview.error || action.error) && <p role="alert" className="rounded-lg bg-red-50 p-4 text-red-700">{overview.error?.message || action.error?.message}</p>}
    {data && <>
      <section className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-5 gap-y-3 rounded-xl border bg-white p-5 md:p-6"><BookCover name={data.book.name} url={data.book.coverUrl} /><div className="min-w-0 flex-1 space-y-3">
        <h1 className="text-2xl font-semibold">{data.book.name}</h1><p className="text-sm text-slate-500">{data.book.author || "作者未知"} · {data.chapterCount} 章 · {data.sources.length} 条线路</p>
        {data.book.intro && <details className="text-sm leading-relaxed text-slate-600"><summary className="cursor-pointer">内容简介</summary><p className="mt-2 whitespace-pre-wrap">{data.book.intro}</p></details>}
        </div><div className="col-span-2 flex flex-wrap gap-2 sm:col-start-2 sm:col-span-1">{data.chapterCount > 0 && <Button asChild><Link to={bookReaderUrl(bookId)}><BookOpen />{data.progress.revision ? `继续阅读 · 第 ${data.progress.chapterIndex + 1} 章` : "开始阅读"}</Link></Button>}
          {job?.state === "completed" ? <Button asChild variant="outline"><a href={`/api/direct${path}/download/file`}>保存 TXT</a></Button> : <Button variant="outline" disabled={action.isPending || !data.chapterCount} onClick={() => action.mutate(active ? "DELETE" : "POST")}>{active ? "暂停下载" : job ? "继续下载" : "整本下载"}</Button>}
        </div>
        <p className="col-span-2 text-xs text-slate-500 sm:col-start-2 sm:col-span-1">{job ? `${downloadLabels[job.state]} · ${job.completed}/${job.total || "…"} 章` : "选择章节后获取正文，也可按阅读进度继续。"}</p>
        {active && <progress className="col-span-2 w-full" value={job.completed} max={job.total || 1} />}{job?.error && <p className="col-span-2 text-sm text-red-600">{job.error}</p>}
      </section>
      <section className="overflow-hidden rounded-xl border bg-white"><div className="border-b p-5"><h2 className="font-semibold">书源线路</h2><p className="mt-1 text-xs text-slate-500">阅读时自动对齐并比较来源；目录可用不代表每章正文都可用。响应时间是最近一次目录查询耗时。
        {data.checkedAt && <> 检查于 {new Date(data.checkedAt*1000).toLocaleTimeString()}。</>}</p></div>
        <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3">{data.sources.map((source, i) => <div key={`${source.sourceId}-${i}`} className="space-y-2 rounded-lg border p-3">
          <div className="flex items-center justify-between gap-2"><strong className="text-sm">{source.sourceName}</strong><span className={`shrink-0 text-xs ${source.status === "available" ? "text-emerald-600" : source.status === "unavailable" ? "text-red-600" : "text-slate-400"}`}>{source.status === "available" ? "目录可用" : source.status === "unavailable" ? "目录暂不可用" : "尚未检查"}</span></div>
          <p className="text-xs text-slate-500">{source.chapterCount === null ? "章节数待检查" : `${source.chapterCount} 章`}{source.latencyMs !== null && ` · ${(source.latencyMs/1000).toFixed(2)} 秒`}</p>
          <p className="truncate text-xs text-slate-500" title={source.lastChapter}>最新：{source.lastChapter || "暂无记录"}</p>
        </div>)}</div>
      </section>
      <section className="overflow-hidden rounded-xl border bg-white"><header className="space-y-3 border-b p-5"><div className="flex items-center justify-between"><h2 className="font-semibold">章节目录</h2><span className="text-xs text-slate-500">共 {data.chapterCount} 章</span></div>
        <p className="text-xs text-slate-500">已下载 {data.counts.downloaded} · 已缓存 {data.counts.cached} · 按需获取 {data.counts.on_demand}{data.counts.failed ? ` · 下载失败 ${data.counts.failed}` : ""}</p>
        <div className="flex flex-wrap gap-2"><Input className="min-w-0 flex-1 basis-48" aria-label="搜索章节" placeholder="搜索章节标题" value={keyword} onChange={e => {setKeyword(e.target.value);setPage(1)}} />
          <select className="rounded-md border bg-white px-3 text-sm" aria-label="章节状态" value={status} onChange={e => {setStatus(e.target.value);setPage(1)}}><option value="all">全部状态</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        </div></header>
        <div className={overview.isFetching ? "opacity-60" : ""}>{data.chapters.map(chapter => <div key={chapter.index} className="border-b last:border-b-0">
          <Link className="flex items-start gap-3 px-4 py-3 transition-colors hover:bg-slate-50 md:px-5" to={bookReaderUrl(bookId, chapter.index)}>
            <span className="w-8 shrink-0 text-sm text-slate-400">{chapter.index + 1}</span><div className="min-w-0 flex-1"><p className="text-sm font-medium">{chapter.title}</p><p className="mt-1 text-xs text-slate-400">{chapter.selectedSourceName ? `已选线路：${chapter.selectedSourceName}` : "阅读时自动选线"}{chapter.index === data.progress.chapterIndex && data.progress.revision > 0 && " · 上次阅读"}</p>{chapter.error && <p className="mt-1 text-xs text-red-600">{chapter.error}</p>}</div>
            <span className={`shrink-0 text-xs ${chapter.status === "failed" ? "text-red-600" : chapter.status === "on_demand" ? "text-slate-400" : "text-emerald-600"}`}>{statusLabels[chapter.status]}</span>
          </Link>
          {chapter.aggregation && <details className="px-5 pb-3 text-xs text-slate-500"><summary className="cursor-pointer">本章线路记录 · {chapter.aggregation.mode === "consensus" ? `${chapter.aggregation.supportCount + 1} 源正文一致` : "降级选线"}</summary><ul className="mt-2 space-y-1">{chapter.aggregation.sources.map(s => <li key={s.sourceId}>{s.sourceName}：{auditLabels[s.status] || s.status}</li>)}</ul></details>}
        </div>)}{!data.chapters.length && <p className="p-8 text-center text-sm text-slate-400">没有符合条件的章节</p>}</div>
        <footer className="flex items-center justify-between border-t p-4"><Button variant="outline" disabled={page <= 1 || overview.isFetching} onClick={() => setPage(p => p-1)}><ChevronLeft />上一页</Button><span className="text-sm text-slate-500">{page} / {totalPages}</span><Button variant="outline" disabled={page >= totalPages || overview.isFetching} onClick={() => setPage(p => p+1)}>下一页<ChevronRight /></Button></footer>
      </section>
    </>}
  </div>
}
