export interface DirectBook { bookId: string; sourceId: string; sourceName: string; name: string; author: string; intro?: string }
export interface DirectSource { id: string; name: string; default?: boolean }
export interface DirectChapter { index: number; title: string }
export interface Progress { chapterIndex: number; position: number; revision: number }
export interface SearchResult { sourceId: string; items: DirectBook[]; error?: { message: string } | string; latencyMs: number }

export async function directRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/direct${path}`, { credentials: "same-origin", ...init,
    headers: { "Content-Type": "application/json", ...init.headers } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(typeof body.detail === "string" ? body.detail : `请求失败 (${response.status})`)
  }
  return response.json() as Promise<T>
}
export const bookPath = (bookId: string) => `/books/${encodeURIComponent(bookId)}`

export async function streamSearch(keyword: string, sources: string[], page: number, signal: AbortSignal, onResult: (r: SearchResult) => void) {
  const params = new URLSearchParams({ keyword, sources: sources.join(","), page: String(page) })
  const response = await fetch(`/api/direct/search?${params}`, { credentials: "same-origin", signal })
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}))
    throw new Error(typeof body.detail === "string" ? body.detail : `搜索失败 (${response.status})`)
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
