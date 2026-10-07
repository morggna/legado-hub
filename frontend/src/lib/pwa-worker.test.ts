/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { expect, it, vi } from 'vitest'
const worker = readFileSync('public/sw.js','utf8')
function load(fetcher: typeof fetch) {
  const handlers: Record<string, (event: any) => void> = {}
  runInNewContext(worker,{self:{addEventListener:(type:string,handler:(event:any)=>void)=>{handlers[type]=handler}},fetch:fetcher,Response})
  return handlers
}
it('leaves APIs and assets to the browser and never substitutes a cached account response', () => {
  const fetcher = vi.fn()
  const handlers = load(fetcher)
  const respondWith = vi.fn()
  for(const mode of ['cors','same-origin','no-cors']) handlers.fetch({request:{method:'GET',mode},respondWith})
  expect(respondWith).not.toHaveBeenCalled()
  expect(fetcher).not.toHaveBeenCalled()
})
it('fetches a fresh navigation and displays a reconnect page only on network failure', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(new Response('current release')).mockRejectedValueOnce(new Error('offline'))
  const handlers = load(fetcher)
  let response: Promise<Response> = Promise.resolve(new Response())
  const event = {request:{method:'GET',mode:'navigate'},respondWith:(value:Promise<Response>)=>{response=value}}
  handlers.fetch(event)
  expect(await (await response).text()).toBe('current release')
  handlers.fetch(event)
  const offline = await response
  expect(offline.status).toBe(503)
  expect(offline.headers.get('Cache-Control')).toBe('no-store')
  expect(await offline.text()).toContain('重新连接')
})
