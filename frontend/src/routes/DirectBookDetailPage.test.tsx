import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import { DirectBookDetailPage } from './DirectBookDetailPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
const overview = {
  book: {bookId:'test', name:'山河', author:'李某'}, progress:{chapterIndex:1, position:.4, revision:2}, download:null,
  sources:[{sourceId:'a',sourceName:'甲源',status:'available',chapterCount:120,lastChapter:'终章',latencyMs:200}, {sourceId:'b',sourceName:'乙源',status:'unavailable',chapterCount:0,lastChapter:'',latencyMs:20000}],
  chapterCount:120, total:120, counts:{downloaded:1,cached:1,on_demand:118,failed:0}, page:1,pageSize:50,
  chapters:[{index:0,title:'第一章 出发',status:'downloaded'}, {index:1,title:'第二章 旅途',status:'cached',selectedSourceName:'甲源',aggregation:{mode:'degraded',supportCount:0,sources:[{sourceId:'a',sourceName:'甲源',status:'accepted'}]}}]
}
function mount() {
  const fetcher = vi.fn(async (url:string, init?:RequestInit) => Response.json(init?.method === 'POST' ? {state:'queued'} : overview))
  vi.stubGlobal('fetch',fetcher)
  const client = new QueryClient({defaultOptions:{queries:{retry:false}}})
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/console/library/test']}><Routes><Route path="/console/library/:bookId" element={<DirectBookDetailPage />} /></Routes></MemoryRouter></QueryClientProvider>)
  return fetcher
}
it('opens catalog with cache states and source diagnostics without fetching any body or starting a download',async () => {
  const fetcher = mount()
  await screen.findByRole('heading',{name:'章节目录'})
  expect(screen.getByText('目录暂不可用')).toBeVisible()
  expect(screen.getByText('最新：终章')).toBeVisible()
  expect(screen.getByText('已选线路：甲源 · 上次阅读')).toBeVisible()
  expect(screen.getByRole('link',{name:/第二章 旅途/})).toHaveAttribute('href','/console/library/test/read?chapter=1')
  expect(screen.getByRole('link',{name:/继续阅读/})).toHaveAttribute('href','/console/library/test/read')
  expect(fetcher.mock.calls.every(([url]) => url.includes('/overview?'))).toBe(true)
  fireEvent.click(screen.getByRole('button',{name:'下一页'}))
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes('page=2'))).toBe(true))
  fireEvent.change(await screen.findByRole('combobox',{name:'章节状态'}),{target:{value:'cached'}})
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes('status=cached') && url.includes('page=1'))).toBe(true))
})
it('starts a full-book download only through the explicit action',async () => {
  const fetcher = mount()
  fireEvent.click(await screen.findByRole('button',{name:'整本下载'}))
  await waitFor(() => expect(fetcher.mock.calls.some(([url,init]) => url.endsWith('/download') && init?.method === 'POST')).toBe(true))
})
