import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import { DirectReaderPage } from './DirectReaderPage'
import { defaultReaderSettings, loadReaderSettings, saveReaderSettings } from '@/components/legado-reader/readerSettings'

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  const storage = new Map<string, string>()
  vi.stubGlobal('localStorage', {getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value), removeItem: (key: string) => storage.delete(key)})
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
function mount(entry = "/books/test") {
  const fetcher = vi.fn(async (input: string, init?: RequestInit) => {
    let body: unknown = {}
    if (input.endsWith('/progress')) body = init?.method === 'PUT' ? {...JSON.parse(String(init.body)), revision: 1} : {chapterIndex: 0, position: 0, revision: 0}
    if (input.endsWith('/detail')) body = {name: '示例书'}
    if (input.endsWith('/toc')) body = {chapters: [{index:0,title:'第一章'}, {index:1,title:'第二章'}]}
    if (input.endsWith('/chapters/0')) body = {title:'第一章',content:'首章内容'}
    if (input.endsWith('/chapters/1')) body = {title:'第二章',content:'次章内容'}
    return new Response(JSON.stringify(body))
  })
  vi.stubGlobal('fetch', fetcher)
  const client = new QueryClient({defaultOptions: {queries: {retry:false}}})
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[entry]}><Routes><Route path="/books/:bookId" element={<DirectReaderPage />} /><Route path="/console/library/:bookId" element={<p>目录页面</p>} /></Routes></MemoryRouter></QueryClientProvider>)
  return fetcher
}
it('fetches only the current chapter; navigating reads one new chapter without starting a download', async () => {
  const fetcher = mount()
  await screen.findByText('首章内容')
  fireEvent.keyDown(window, {key: 'Escape'})
  expect(fetcher.mock.calls.filter(([url]) => url.includes('/chapters/')).map(([url]) => url)).toEqual(['/api/direct/books/test/chapters/0'])
  fireEvent.click(screen.getByRole('button', {name:'下一章'}))
  await screen.findByText('次章内容')
  expect(fetcher.mock.calls.filter(([url]) => url.includes('/chapters/')).map(([url]) => url)).toEqual(['/api/direct/books/test/chapters/0','/api/direct/books/test/chapters/1'])
  expect(fetcher.mock.calls.some(([url]) => url.includes('/download'))).toBe(false)
  await waitFor(() => expect(fetcher.mock.calls.some(([url,init]) => url.endsWith('/progress') && init?.method === 'PUT' && JSON.parse(String(init.body)).chapterIndex === 1)).toBe(true))
})
it('filters the chapter drawer and opens the selected chapter', async () => {
  mount()
  await screen.findByText('首章内容')
  fireEvent.keyDown(window, {key: 'Escape'})
  fireEvent.click(screen.getByRole('button', {name:'目录'}))
  fireEvent.change(screen.getByRole('textbox', {name:'搜索章节'}), {target: {value:'第二'}})
  expect(screen.queryByRole('button', {name:'第一章'})).toBeNull()
  fireEvent.click(screen.getByRole('button', {name:'第二章'}))
  await screen.findByText('次章内容')
  expect(screen.queryByRole('textbox', {name:'搜索章节'})).toBeNull()
})
it('isolates reading preferences between users', () => {
  saveReaderSettings({...defaultReaderSettings,theme:'dark',fontSize:24}, 'alice')
  expect(loadReaderSettings('alice').theme).toBe('dark')
  expect(loadReaderSettings('bob').theme).toBe('light')
  expect(loadReaderSettings('bob').fontSize).toBe(19)
})

it('opens in immersive mode and toggles both toolbars without fetching another chapter', async () => {
  const fetcher = mount()
  await screen.findByText('首章内容')
  const root = document.querySelector('.legado-reader')!
  expect(root).toHaveClass('toolbars-hidden')
  fireEvent.keyDown(window, {key:'Escape'})
  expect(root).toHaveClass('toolbars-open')
  fireEvent.keyDown(window, {key:'Escape'})
  expect(root).toHaveClass('toolbars-hidden')
  expect(fetcher.mock.calls.filter(([url]) => url.includes('/chapters/'))).toHaveLength(1)
})

it('opens a catalog-selected chapter instead of saved progress and returns to its catalog', async () => {
  const fetcher = mount('/books/test?chapter=1')
  await screen.findByText('次章内容')
  expect(fetcher.mock.calls.filter(([url]) => url.includes('/chapters/')).map(([url]) => url)).toEqual(['/api/direct/books/test/chapters/1'])
  await waitFor(() => expect(fetcher.mock.calls.some(([url,init]) => url.endsWith('/progress') && init?.method === 'PUT' && JSON.parse(String(init.body)).chapterIndex === 1)).toBe(true))
  fireEvent.keyDown(window, {key:'Escape'})
  fireEvent.click(screen.getByRole('button',{name:'返回目录'}))
  await screen.findByText('目录页面')
})
it('rejects an invalid catalog chapter without requesting a body or hanging in loading state', async () => {
  const fetcher = mount('/books/test?chapter=200')
  await screen.findByText('章节不存在，请返回目录选择章节')
  expect(fetcher.mock.calls.some(([url]) => url.includes('/chapters/'))).toBe(false)
})

it('adopts another device’s saved chapter after focus instead of remaining at its initial progress', async () => {
  const fetcher = mount()
  await screen.findByText('首章内容')
  await waitFor(() => expect(fetcher.mock.calls.filter(([url,init]) => url.endsWith('/progress') && init?.method !== 'PUT').length).toBe(2))
  fetcher.mockImplementation(async (url: string) => Response.json(url.endsWith('/progress') ? {chapterIndex:1,position:.6,revision:3} : url.includes('/chapters/1') ? {title:'第二章',content:'次章内容'} : {}))
  fireEvent.focus(window)
  await screen.findByText('次章内容')
})
