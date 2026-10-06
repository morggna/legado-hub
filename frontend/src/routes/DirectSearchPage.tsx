import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { BookCover } from "@/components/BookCover"
import { Input } from "@/components/ui/input"
import { directRequest, streamSearch, type DirectBook, type DirectSource } from "@/lib/direct-api"

export function DirectSearchPage() {
  const navigate = useNavigate()
  const client = useQueryClient()
  const shelf = useQuery({ queryKey: ["direct", "shelf"], queryFn: () => directRequest<{ items: DirectBook[] }>("/shelf") })
  const add = useMutation({ mutationFn: async ({ book, read }: {book: DirectBook; read: boolean}) => {
    const saved = await directRequest<DirectBook>("/shelf", { method: "POST", body: JSON.stringify({ sourceBookIds: book.sourceBookIds ?? [book.bookId], expectedBookId: book.bookId.startsWith("agg-") ? book.bookId : undefined }) })
    return {book: saved, read}
  }, onSuccess: async ({book, read}) => {
    await client.invalidateQueries({ queryKey: ["direct", "shelf"] })
    if (read) navigate(`/console/library/${encodeURIComponent(book.bookId)}`)
  } })
  const { data, error: sourceError } = useQuery({ queryKey: ["direct", "sources"], queryFn: () => directRequest<{ items: DirectSource[] }>("/sources") })
  const [selection, setSelection] = useState<string[] | null>(null)
  const selected = selection ?? (data?.items.map(s => s.id) || [])
  const [keyword, setKeyword] = useState("")
  const [books, setBooks] = useState<DirectBook[]>([])
  const [status, setStatus] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [page, setPage] = useState(1)
  const pages = useRef<Record<number, DirectBook[]>>({})
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  async function search(nextPage = 1) {
    controller.current?.abort()
    const active = new AbortController()
    controller.current = active
    setBusy(true); setError(""); setStatus({}); setPage(nextPage)
    if (nextPage === 1) { setBooks([]); pages.current = {} }
    try {
      await streamSearch(keyword.trim(), selected, nextPage, active.signal, result => {
        if (active.signal.aborted) return
        pages.current[nextPage] = result.groups ?? [...(pages.current[nextPage] ?? []), ...result.items]
        const merged = new Map<string, DirectBook>()
        for (const book of Object.values(pages.current).flat()) {
          const old = merged.get(book.bookId)
          const sourceBookIds = [...new Set([...(old?.sourceBookIds ?? []), ...(book.sourceBookIds ?? [book.bookId])])]
          const sources = [...new Map([...(old?.sources ?? []), ...(book.sources ?? [])].map(s => [s.bookId, s])).values()]
          merged.set(book.bookId, {...book, coverUrl: book.coverUrl || old?.coverUrl, sourceBookIds, sources, sourceCount: sources.length ? new Set(sources.map(s => s.sourceId)).size : book.sourceCount})
        }
        setBooks([...merged.values()])
        const message = result.error ? (typeof result.error === "string" ? result.error : result.error.message) : `${result.items.length} 本 · ${(result.latencyMs / 1000).toFixed(1)} 秒`
        setStatus(old => ({ ...old, [result.sourceId]: message }))
      })
    } catch (e) {
      if (!active.signal.aborted) setError(e instanceof Error ? e.message : "搜索失败")
    } finally { if (controller.current === active) setBusy(false) }
  }
  return <div className="mx-auto max-w-5xl space-y-5 p-4 md:p-8">
    <div><h1 className="text-2xl font-semibold">搜索书源</h1><p className="mt-2 text-sm text-slate-500">搜索全部已启用书源，同书合并。加入书库后，阅读当前章节时自动对齐多源并择优；整本下载可选。</p></div>
    <form className="flex gap-2" onSubmit={e => { e.preventDefault(); void search() }}>
      <Input aria-label="书名或作者" placeholder="输入书名或作者" value={keyword} onChange={e => setKeyword(e.target.value)} />
      <Button className="shrink-0 whitespace-nowrap" disabled={!keyword.trim() || !selected.length} type="submit">搜索</Button>
      {busy && <Button variant="outline" type="button" onClick={() => controller.current?.abort()}>停止</Button>}
    </form>
    <details className="rounded-lg border bg-white p-4">
      <summary className="cursor-pointer font-medium">书源（已选 {selected.length}）</summary>
      {sourceError && <p role="alert" className="text-red-600">{sourceError.message}</p>}
      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{data?.items.map(s => <label key={s.id} className="flex items-start gap-2 text-sm">
        <input type="checkbox" checked={selected.includes(s.id)} onChange={e => setSelection(e.target.checked ? [...selected, s.id].slice(0, 64) : selected.filter(id => id !== s.id))} />
        <span>{s.name}<span className="block text-xs text-slate-500">{status[s.id] || (busy && selected.includes(s.id) ? "搜索中…" : "")}</span></span>
      </label>)}</div>
    </details>
    {(error || add.error) && <p role="alert" className="text-red-600">{error || add.error?.message}</p>}
    <div aria-live="polite" className="text-sm text-slate-500">{books.length} 个结果{busy ? "，正在汇总各书源；搜索完成或停止后可加入书库" : ""}</div>
    <div className="grid gap-3 sm:grid-cols-2">{books.map(b => {
      const owned = shelf.data?.items.find(item => item.bookId === b.bookId || b.sourceBookIds?.includes(item.bookId))
      return <div key={b.bookId} className="rounded-lg border bg-white p-4">
        <div className="flex gap-4"><BookCover name={b.name} url={b.coverUrl} /><div className="min-w-0"><h2 className="font-semibold">{b.name}</h2><p className="mt-1 text-sm text-slate-500">{b.author || "作者未知"}</p><p className="mt-2 text-sm text-slate-500">{b.sourceCount ?? 1} 个来源 · 聚合阅读</p><p className="mt-2 line-clamp-2 text-xs text-slate-400">{b.sources?.map(s => s.sourceName).join("、") || b.sourceName}</p></div></div>
        <div className="mt-4 flex gap-2"><Button size="sm" disabled={add.isPending || busy} onClick={() => add.mutate({book: b, read: true})}>{owned ? "打开阅读" : "加入并阅读"}</Button>
          {<Button variant="outline" size="sm" disabled={add.isPending || busy} onClick={() => add.mutate({book: b, read: false})}>{owned ? "更新来源" : "加入书库"}</Button>}
        </div>
      </div>
    })}</div>
    {!busy && books.length > 0 && <Button variant="outline" onClick={() => { void search(page + 1) }}>搜索下一页</Button>}
  </div>
}
