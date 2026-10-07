export interface DirectBook { bookId: string; sourceId: string; sourceName: string; name: string; author: string; intro?: string; coverUrl?: string; sourceCount?: number; sourceBookIds?: string[]; sources?: DirectBook[]; attachmentSource?: boolean; imported?: boolean; threadId?: string; preferredSourceBookId?: string | null }
export const sourceCategories = { light_novel: "轻小说", completed: "完结", ongoing: "连载中" } as const
export type SourceCategory = keyof typeof sourceCategories
export interface DirectSource { id: string; name: string; default?: boolean; category?: SourceCategory }
export class DirectRequestError extends Error {
  status: number
  constructor(message: string, status: number) { super(message); this.status = status }
}
export interface DirectChapter { index: number; title: string }
export interface Progress { chapterIndex: number; position: number; revision: number }
export interface SearchResult { sourceId: string; items: DirectBook[]; groups?: DirectBook[]; error?: { message: string } | string; latencyMs: number }

function responseError(body: { detail?: unknown }, status: number, fallback: string): Error {
  const detail = body.detail
  if (typeof detail === "string" && detail.trim()) return new DirectRequestError(detail, status)
  if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string" && detail.message.trim()) {
    return new DirectRequestError(detail.message, status)
  }
  return new DirectRequestError(`${fallback} (${status})`, status)
}

export async function directRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/direct${path}`, { credentials: "same-origin", ...init,
    headers: { "Content-Type": "application/json", ...init.headers } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw responseError(body, response.status, "请求失败")
  }
  return response.json() as Promise<T>
}
export const bookPath = (bookId: string) => `/books/${encodeURIComponent(bookId)}`

export async function streamSearch(keyword: string, sources: string[], page: number, signal: AbortSignal, onResult: (r: SearchResult) => void) {
  const params = new URLSearchParams({ keyword, sources: sources.join(","), page: String(page) })
  const response = await fetch(`/api/direct/search?${params}`, { credentials: "same-origin", signal })
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}))
    throw responseError(body, response.status, "搜索失败")
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let pending = ""
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      pending += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n")
      let end: number
      while ((end = pending.indexOf("\n\n")) >= 0) {
        const frame = pending.slice(0, end)
        pending = pending.slice(end + 2)
        if (!frame.includes("event: done")) {
          const data = frame.split("\n").filter(l => l.startsWith("data: ")).map(l => l.slice(6)).join("\n")
          if (data) onResult(JSON.parse(data) as SearchResult)
        }
      }
    }
  } finally { reader.releaseLock() }
}

export interface DownloadJob { bookId: string; state: "queued" | "running" | "paused" | "failed" | "completed"; completed: number; total: number; error: string }
export const downloadLabels = { queued: "等待下载", running: "正在下载", paused: "已暂停", failed: "下载失败", completed: "已下载整本" }
export interface ChapterAudit { mode: string; selectedSourceName: string; supportCount: number; sources: {sourceId: string; sourceName: string; status: string}[] }
export interface BookOverview {
  book: DirectBook; sources: {sourceId: string; sourceName: string; status: string; chapterCount: number | null; lastChapter: string; latencyMs: number | null}[]
  checkedAt?: number; progress: Progress; download: DownloadJob | null; chapterCount: number; counts: Record<string, number>
  total: number; chapters: (DirectChapter & {status: string; selectedSourceName?: string; aggregation?: ChapterAudit; error?: string})[]; page: number; pageSize: number
}
export const bookDetailUrl = (id: string) => `/console/library/${encodeURIComponent(id)}`
export const bookReaderUrl = (id: string, chapter?: number) => `${bookDetailUrl(id)}/read${chapter === undefined ? "" : `?chapter=${chapter}`}`
