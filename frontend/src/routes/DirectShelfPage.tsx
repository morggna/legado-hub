import { useState } from "react"
import { InstallApp } from "@/components/InstallApp"
import { BookCover } from "@/components/BookCover"
import { Link } from "react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { bookPath, bookDetailUrl, bookReaderUrl, directRequest, type DirectBook, type ShelfCategory } from "@/lib/direct-api"

interface DownloadJob { bookId: string; state: "queued" | "running" | "paused" | "failed" | "completed"; completed: number; total: number; error: string }
const labels = { queued: "等待下载", running: "正在下载", paused: "已暂停", failed: "下载失败", completed: "已下载整本" }

export function DirectShelfPage() {
  const client = useQueryClient()
  const [filter, setFilter] = useState("")
  const [manageOpen, setManageOpen] = useState(false)
  const [editingId, setEditingId] = useState("")
  const [categoryName, setCategoryName] = useState("")
  const [confirmDelete, setConfirmDelete] = useState(false)
  const categories = useQuery({ queryKey: ["direct", "shelf-categories"], queryFn: () => directRequest<{items: ShelfCategory[]}>("/shelf/categories") })
  const shelf = useQuery({ queryKey: ["direct", "shelf"], queryFn: () => directRequest<{items: DirectBook[]}>("/shelf") })
  const jobs = useQuery({ queryKey: ["direct", "downloads"], queryFn: () => directRequest<{items: DownloadJob[]}>("/downloads"), refetchInterval: q => q.state.data?.items.some(j => ["queued", "running"].includes(j.state)) ? 2000 : false })
  const action = useMutation({ mutationFn: (run: () => Promise<unknown>) => run(), onSuccess: async () => { await Promise.all([client.invalidateQueries({ queryKey: ["direct", "shelf"] }), client.invalidateQueries({ queryKey: ["direct", "downloads"] }), client.invalidateQueries({ queryKey: ["direct", "shelf-categories"] })]) } })
  const items = shelf.data?.items ?? []
  const categoryItems = categories.data?.items ?? []
  const activeFilter = filter === "uncategorized" || categoryItems.some(c => c.categoryId === filter) ? filter : categoryItems[0]?.categoryId ?? "uncategorized"
  const visible = items.filter(b => activeFilter === "uncategorized" ? !b.categoryId : b.categoryId === activeFilter)
  const chooseCategory = (id: string) => {
    setEditingId(id); setCategoryName(categories.data?.items.find(c => c.categoryId === id)?.name ?? ""); setConfirmDelete(false)
  }
  const saveCategory = () => action.mutate(async () => {
    await directRequest(`/shelf/categories${editingId ? `/${encodeURIComponent(editingId)}` : ""}`, { method: editingId ? "PATCH" : "POST", body: JSON.stringify({ name: categoryName.trim() }) })
    chooseCategory("")
  })
  return <div className="mx-auto max-w-5xl space-y-5 p-4 md:p-8"><div className="flex items-center justify-between"><h1 className="text-2xl font-semibold">我的书库</h1><Button asChild variant="outline"><Link to="/console/search">搜索新书</Link></Button></div>
    <p className="text-sm text-slate-500">点开书籍查看目录、章节状态和线路，选择章节后阅读。需要离线保存时，再选择整本下载。</p>
    <div className="flex flex-wrap items-center gap-2" aria-label="书架分类">
      {[...categoryItems.map(c => ({id: c.categoryId, name: c.name, count: items.filter(b => b.categoryId === c.categoryId).length})), {id: "uncategorized", name: "未分类", count: items.filter(b => !b.categoryId).length}].map(c => <Button key={c.id} className="max-w-full gap-1" title={c.name} aria-label={`${c.name} · ${c.count}`} variant={activeFilter === c.id ? "default" : "outline"} size="sm" aria-pressed={activeFilter === c.id} onClick={() => setFilter(c.id)}><span className="truncate">{c.name}</span><span className="shrink-0">· {c.count}</span></Button>)}
      <Button variant="ghost" size="sm" onClick={() => { chooseCategory(""); setManageOpen(true) }}>管理分类</Button>
    </div>
    <p className="text-xs text-slate-500">最近阅读的书排在最前面</p>
    <Dialog open={manageOpen} onOpenChange={open => { setManageOpen(open); action.reset() }}><DialogContent><DialogHeader><DialogTitle>管理书架分类</DialogTitle><DialogDescription>创建自己的分类。删除分类后，书籍会回到未分类。</DialogDescription></DialogHeader>
      <label className="space-y-2 text-sm">选择分类<select aria-label="选择要管理的分类" disabled={action.isPending} className="w-full rounded-md border p-2" value={editingId} onChange={e => chooseCategory(e.target.value)}><option value="">新建分类</option>{categories.data?.items.map(c => <option key={c.categoryId} value={c.categoryId}>{c.name}</option>)}</select></label>
      <label className="space-y-2 text-sm">分类名称<Input aria-label="分类名称" disabled={action.isPending} maxLength={40} value={categoryName} onChange={e => setCategoryName(e.target.value)} placeholder="例如：正在读、想读、已读" /></label>
      {action.error && <p role="alert" className="text-sm text-red-600">{action.error.message}</p>}
      <div className="flex gap-2"><Button disabled={action.isPending || !categoryName.trim()} onClick={saveCategory}>{editingId ? "保存名称" : "创建分类"}</Button>{editingId && <Button variant="outline" disabled={action.isPending} onClick={() => setConfirmDelete(true)}>删除分类</Button>}</div>
      {confirmDelete && <div className="space-y-2 rounded-md border p-3"><p className="text-sm">确定删除这个分类？其中的书会回到未分类。</p><Button variant="destructive" disabled={action.isPending} onClick={() => action.mutate(async () => { await directRequest(`/shelf/categories/${encodeURIComponent(editingId)}`, {method: "DELETE"}); if (activeFilter === editingId) setFilter("uncategorized"); chooseCategory("") })}>确认删除分类</Button><Button variant="ghost" onClick={() => setConfirmDelete(false)}>取消</Button></div>}
    </DialogContent></Dialog>
    <InstallApp />
    {(shelf.error || jobs.error || categories.error || action.error) && <p role="alert" className="text-red-600">{(shelf.error || jobs.error || categories.error || action.error)?.message}</p>}
    {shelf.isPending && <p>加载中…</p>}
    {shelf.data?.items.length === 0 && <p className="rounded-lg border bg-white p-8 text-center">书库为空。<Link className="underline" to="/console/search">去搜索一本书</Link></p>}
    {items.length > 0 && visible.length === 0 && <p className="rounded-lg border bg-white p-8 text-center">这个分类还没有书。在书籍卡片上选择分类即可移入。</p>}
    <div className="grid gap-3 sm:grid-cols-2">{visible.map(b => {
      const job = jobs.data?.items.find(j => j.bookId === b.bookId)
      const active = job && ["queued", "running"].includes(job.state)
      return <div className="rounded-lg border bg-white p-5" key={b.bookId}>
        <Link className="flex gap-4" to={bookDetailUrl(b.bookId)}><BookCover name={b.name} url={b.coverUrl} /><div className="min-w-0"><h2 className="font-semibold">{b.name}</h2><p className="mt-1 text-sm text-slate-500">{b.author || "作者未知"}</p><p className="mt-2 text-sm text-slate-500">{b.imported ? `${b.sourceName} · 已导入` : `${b.sourceCount ?? 1} 个来源 · ${b.sourceCount ? "聚合阅读" : b.sourceName}`}</p></div></Link>
        <div className="mt-3 flex flex-wrap items-center gap-2"><select aria-label={`${b.name}的分类`} className="max-w-full rounded-md border p-1.5 text-sm" value={b.categoryId ?? ""} disabled={action.isPending || !categories.data} onChange={e => { const categoryId = e.target.value || null; action.mutate(() => directRequest(`/shelf/${encodeURIComponent(b.bookId)}/category`, {method: "PATCH", body: JSON.stringify({categoryId})})) }}>{categoryItems.map(c => <option key={c.categoryId} value={c.categoryId}>{c.name}</option>)}<option value="">未分类</option></select>{b.lastReadAt && <span className="text-xs text-slate-500">上次读到第 {(b.progress?.chapterIndex ?? 0) + 1} 章</span>}</div>
        <p className="mt-3 text-xs text-slate-500">{job ? `${labels[job.state]} · ${job.completed}/${job.total || "…"} 章` : "按需阅读 · 尚未下载整本"}</p>
        {job?.state === "running" && <progress className="mt-2 w-full" value={job.completed} max={job.total || 1} />}
        {job?.error && <p className="mt-2 text-sm text-red-600">{job.error}</p>}
        <div className="mt-4 flex flex-wrap gap-2">{b.lastReadAt && <Button asChild size="sm"><Link to={bookReaderUrl(b.bookId)}>继续阅读</Link></Button>}<Button asChild size="sm"><Link to={bookDetailUrl(b.bookId)}>查看目录</Link></Button>
          {job?.state === "completed" ? <Button asChild variant="outline" size="sm"><a href={`/api/direct${bookPath(b.bookId)}/download/file`}>保存 TXT</a></Button>
            : active ? <Button variant="outline" size="sm" disabled={action.isPending} onClick={() => action.mutate(() => directRequest(`${bookPath(b.bookId)}/download`, { method: "DELETE" }))}>暂停下载</Button>
            : <Button variant="outline" size="sm" disabled={action.isPending} onClick={() => action.mutate(() => directRequest(`${bookPath(b.bookId)}/download`, { method: "POST" }))}>{job ? "继续下载" : "整本下载"}</Button>}
          <Button variant="ghost" size="sm" disabled={action.isPending || !!active} onClick={() => action.mutate(() => directRequest(`/shelf/${encodeURIComponent(b.bookId)}`, { method: "DELETE" }))}>移出书库</Button>
        </div>
      </div>
    })}</div></div>
}
