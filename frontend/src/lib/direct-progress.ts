import { bookPath, directRequest, DirectRequestError, type Progress } from './direct-api'

type Location = Pick<Progress, 'chapterIndex' | 'position'>

/** Serialize writes, coalesce scrolling, and reconcile stale devices using server revisions. */
export class DirectProgressSync {
  private current: Progress
  private pending: Location | null = null
  private saving: Promise<void> | null = null
  private pulling: Promise<void> | null = null
  private listeners = new Set<(progress: Progress | null, error: string) => void>()
  private storageKey: string
  private path: string
  constructor(bookId: string, userId: string, initial: Progress) {
    this.current = initial
    this.path = `${bookPath(bookId)}/progress`
    this.storageKey = `reading-pending:${userId}:${bookId}`
    try {
      const saved = JSON.parse(localStorage.getItem(this.storageKey) || 'null')
      if (saved?.revision === initial.revision && Number.isInteger(saved.chapterIndex) && saved.chapterIndex >= 0 && Number.isFinite(saved.position) && saved.position >= 0 && saved.position <= 1) {
        this.pending = { chapterIndex: saved.chapterIndex, position: saved.position }
      } else localStorage.removeItem(this.storageKey)
    } catch { /* Storage can be disabled. Online synchronization still works. */ }
  }
  subscribe(listener: (progress: Progress | null, error: string) => void) {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }
  private emit(progress: Progress | null, error = '') { this.listeners.forEach(listener => listener(progress, error)) }
  private persist() {
    try {
      if (this.pending) localStorage.setItem(this.storageKey, JSON.stringify({ ...this.pending, revision: this.current.revision }))
      else localStorage.removeItem(this.storageKey)
    } catch { /* Quota/private mode must not block progress writes. */ }
  }
  mark(value: Location) {
    this.pending = value
    this.persist()
  }
  flush(): Promise<void> {
    if (this.saving) return this.saving
    if (!this.pending) return Promise.resolve()
    const run = async () => {
      while (this.pending) {
        const value = this.pending
        try {
          const result = await directRequest<Progress>(this.path, { method: 'PUT', keepalive: true, body: JSON.stringify({ ...value, revision: this.current.revision }) })
          this.current = result
          if (this.pending === value) this.pending = null
          this.persist()
          this.emit(null)
        } catch (error) {
          if (error instanceof DirectRequestError && error.status === 409) {
            // An older device must not overwrite the new device's saved position.
            try {
              const remote = await directRequest<Progress>(this.path)
              this.current = remote
              this.pending = null
              this.persist()
              this.emit(remote)
            } catch {
              this.emit(null, '暂时无法同步进度，联网后自动重试')
            }
          } else this.emit(null, '进度暂存于此设备，联网后自动重试')
          break
        }
      }
    }
    this.saving = run().finally(() => { this.saving = null })
    return this.saving
  }
  reconcile(): Promise<void> {
    if (this.pulling) return this.pulling
    const run = async () => {
      await this.flush()
      if (this.pending || this.saving) return
      const revision = this.current.revision
      try {
        const remote = await directRequest<Progress>(this.path)
        if (this.pending || this.saving || revision !== this.current.revision) return
        if (remote.revision > revision) {
          this.current = remote
          this.emit(remote)
        } else this.emit(null)
      } catch { this.emit(null, '暂时无法同步进度，联网后自动重试') }
    }
    this.pulling = run().finally(() => { this.pulling = null })
    return this.pulling
  }
  async recover() {
    if (this.pending) this.emit({ ...this.pending, revision: this.current.revision })
    await this.reconcile()
  }
}
