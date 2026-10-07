import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { DirectProgressSync } from './direct-progress'

beforeEach(() => {
  const storage = new Map<string, string>()
  vi.stubGlobal('localStorage', {getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value), removeItem: (key: string) => storage.delete(key)})
})
afterEach(() => vi.unstubAllGlobals())
const initial = { chapterIndex: 0, position: 0, revision: 0 }
it('coalesces scrolling while a write is pending and uses the returned revision for the next write', async () => {
  let release!: (response: Response) => void
  const fetcher = vi.fn().mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
    .mockResolvedValueOnce(Response.json({ chapterIndex: 2, position: .6, revision: 2 }))
  vi.stubGlobal('fetch', fetcher)
  const sync = new DirectProgressSync('test', 'alice', initial)
  sync.mark({ chapterIndex: 1, position: .1 })
  const first = sync.flush()
  sync.mark({ chapterIndex: 2, position: .3 })
  sync.mark({ chapterIndex: 2, position: .6 })
  release(Response.json({ chapterIndex: 1, position: .1, revision: 1 }))
  await first
  expect(fetcher).toHaveBeenCalledTimes(2)
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ chapterIndex: 2, position: .6, revision: 1 })
})
it('retries after a network failure instead of permanently blocking future saves', async () => {
  const fetcher = vi.fn().mockRejectedValueOnce(new TypeError('offline')).mockResolvedValueOnce(Response.json({ chapterIndex: 1, position: .8, revision: 1 }))
  vi.stubGlobal('fetch', fetcher)
  const sync = new DirectProgressSync('test', 'alice', initial)
  sync.mark({ chapterIndex: 1, position: .2 }); await sync.flush()
  sync.mark({ chapterIndex: 1, position: .8 }); await sync.flush()
  expect(fetcher).toHaveBeenCalledTimes(2)
  expect(JSON.parse(fetcher.mock.calls[1][1].body).position).toBe(.8)
  expect(localStorage.getItem('reading-pending:alice:test')).toBeNull()
})
it('a stale device adopts the remote revision and never retries its obsolete write on top of it', async () => {
  const remote = { chapterIndex: 8, position: .4, revision: 7 }
  const fetcher = vi.fn().mockResolvedValueOnce(Response.json({ detail: 'conflict' }, { status: 409 }))
    .mockResolvedValueOnce(Response.json(remote)).mockResolvedValueOnce(Response.json({ chapterIndex: 8, position: .6, revision: 8 }))
  vi.stubGlobal('fetch', fetcher)
  const sync = new DirectProgressSync('test', 'alice', initial)
  const listener = vi.fn(); sync.subscribe(listener)
  sync.mark({ chapterIndex: 0, position: .2 }); await sync.flush()
  expect(listener).toHaveBeenCalledWith(remote, '')
  sync.mark({ chapterIndex: 8, position: .6 }); await sync.flush()
  expect(JSON.parse(fetcher.mock.calls[2][1].body).revision).toBe(7)
})
it('reconciles the same chapter at a new position and ignores an in-flight stale GET after a new edit', async () => {
  let release!: (response: Response) => void
  const fetcher = vi.fn().mockResolvedValueOnce(Response.json({ ...initial, position: .7, revision: 1 }))
    .mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
  vi.stubGlobal('fetch', fetcher)
  const sync = new DirectProgressSync('test', 'alice', initial)
  const listener = vi.fn(); sync.subscribe(listener)
  await sync.reconcile()
  expect(listener).toHaveBeenCalledWith({ ...initial, position: .7, revision: 1 }, '')
  const pulling = sync.reconcile()
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2))
  sync.mark({ chapterIndex: 1, position: .3 })
  listener.mockClear()
  release(Response.json({ ...initial, revision: 2 }))
  await pulling
  expect(listener).not.toHaveBeenCalled()
})
it('recovers offline progress only for the same account and unchanged server revision', async () => {
  localStorage.setItem('reading-pending:alice:test', JSON.stringify({ chapterIndex: 3, position: .5, revision: 0 }))
  const fetcher = vi.fn(async (_path, init) => Response.json(init?.method === 'PUT' ? { chapterIndex: 3, position: .5, revision: 1 } : { chapterIndex: 3, position: .5, revision: 1 }))
  vi.stubGlobal('fetch', fetcher)
  const sync = new DirectProgressSync('test', 'alice', initial)
  const listener = vi.fn(); sync.subscribe(listener)
  await sync.recover()
  expect(listener).toHaveBeenCalledWith({ chapterIndex: 3, position: .5, revision: 0 }, '')
  expect(fetcher.mock.calls[0][1]?.method).toBe('PUT')
  const bob = new DirectProgressSync('test', 'bob', initial)
  await bob.flush()
  expect(fetcher.mock.calls.filter(c => c[1]?.method === 'PUT')).toHaveLength(1)
})
