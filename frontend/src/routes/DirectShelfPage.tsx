import { BookCover } from "@/components/BookCover"
import { Link } from "react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { bookPath, directRequest, type DirectBook } from "@/lib/direct-api"

interface DownloadJob { bookId: string; state: "queued" | "running" | "paused" | "failed" | "completed"; completed: number; total: number; error: string }
const labels = { queued: "等待下载", running: "正在下载", paused: "已暂停", failed: "下载失败", completed: "已下载整本" }

export function DirectShelfPage() {
  const client = useQueryClient()
  const shelf = useQuery({ queryKey: ["direct", "shelf"], queryFn: () => directRequest<{items: DirectBook[]}>("/shelf") })
  const jobs = useQuery({ queryKey: ["direct", "downloads"], queryFn: () => directRequest<{items: DownloadJob[]}>("/downloads"), refetchInterval: q => q.state.data?.items.some(j => ["queued", "running"].includes(j.state)) ? 2000 : false })
  const action = useMutation({ mutationFn: (run: () => Promise<unknown>) => run(), onSuccess: async () => { await Promise.all([client.invalidateQueries({ queryKey: ["direct", "shelf"] }), client.invalidateQueries({ queryKey: ["direct", "downloads"] })]) } })
  return <div className="mx-auto max-w-5xl space-y-5 p-4 md:p-8"><div className="flex items-center justify-between"><h1 className="text-2xl font-semibold">我的书库</h1><Button asChild variant="outline"><Link to="/console/search">搜索新书</Link></Button></div>
    <p className="text-sm text-slate-500">点开书籍即可阅读，按需获取章节。需要离线保存时，再选择整本下载。</p>
    {(shelf.error || jobs.error || action.error) && <p role="alert" className="text-red-600">{(shelf.error || jobs.error || action.error)?.message}</p>}
    {shelf.isPending && <p>加载中…</p>}
    {shelf.data?.items.length === 0 && <p className="rounded-lg border bg-white p-8 text-center">书库为空。<Link className="underline" to="/console/search">去搜索一本书</Link></p>}
    <div className="grid gap-3 sm:grid-cols-2">{shelf.data?.items.map(b => {
      const job = jobs.data?.items.find(j => j.bookId === b.bookId)
      const active = job && ["queued", "running"].includes(job.state)
      return <div className="rounded-lg border bg-white p-5" key={b.bookId}>
        <Link className="flex gap-4" to={`/console/library/${encodeURIComponent(b.bookId)}`}><BookCover name={b.name} url={b.coverUrl} /><div className="min-w-0"><h2 className="font-semibold">{b.name}</h2><p className="mt-1 text-sm text-slate-500">{b.author || "作者未知"}</p><p className="mt-2 text-sm text-slate-500">{b.sourceCount ?? 1} 个来源 · {b.sourceCount ? "聚合阅读" : b.sourceName}</p></div></Link>
        <p className="mt-3 text-xs text-slate-500">{job ? `${labels[job.state]} · ${job.completed}/${job.total || "…"} 章` : "按需阅读 · 尚未下载整本"}</p>
        {job?.state === "running" && <progress className="mt-2 w-full" value={job.completed} max={job.total || 1} />}
        {job?.error && <p className="mt-2 text-sm text-red-600">{job.error}</p>}
        <div className="mt-4 flex flex-wrap gap-2"><Button asChild size="sm"><Link to={`/console/library/${encodeURIComponent(b.bookId)}`}>继续阅读</Link></Button>
          {job?.state === "completed" ? <Button asChild variant="outline" size="sm"><a href={`/api/direct${bookPath(b.bookId)}/download/file`}>保存 TXT</a></Button>
            : active ? <Button variant="outline" size="sm" disabled={action.isPending} onClick={() => action.mutate(() => directRequest(`${bookPath(b.bookId)}/download`, { method: "DELETE" }))}>暂停下载</Button>
            : <Button variant="outline" size="sm" disabled={action.isPending} onClick={() => action.mutate(() => directRequest(`${bookPath(b.bookId)}/download`, { method: "POST" }))}>{job ? "继续下载" : "整本下载"}</Button>}
          <Button variant="ghost" size="sm" disabled={action.isPending || !!active} onClick={() => action.mutate(() => directRequest(`/shelf/${encodeURIComponent(b.bookId)}`, { method: "DELETE" }))}>移出书库</Button>
        </div>
      </div>
    })}</div></div>
}
