import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { DirectSearchPage } from './DirectSearchPage'
import { DirectShelfPage } from './DirectShelfPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
function mount(page: React.ReactNode) {
  const client = new QueryClient({defaultOptions:{queries:{retry:false}}})
  render(<QueryClientProvider client={client}><MemoryRouter>{page}</MemoryRouter></QueryClientProvider>)
}
const book = {bookId:'agg-one',name:'三国演义',author:'罗贯中',sourceId:'aggregate',sourceName:'多源聚合',coverUrl:'https://covers.example/one.jpg',sourceCount:2,sourceBookIds:['a:one','b:two'],sources:[{bookId:'a:one',sourceId:'a',sourceName:'甲源'},{bookId:'b:two',sourceId:'b',sourceName:'乙源'}]}
it('replaces cumulative search groups and saves every candidate in one shelf entry',async () => {
  const fetcher = vi.fn(async (url:string,init?:RequestInit) => {
    if(url.startsWith('/api/direct/search?')) return new Response(
      `data: ${JSON.stringify({sourceId:'a',items:[],groups:[{...book,sourceCount:1,sourceBookIds:['a:one']}],latencyMs:100})}\n\n`+
      `data: ${JSON.stringify({sourceId:'b',items:[],groups:[book],latencyMs:200})}\n\nevent: done\ndata: {}\n\n`)
    if(url.endsWith('/sources')) return Response.json({items:[{id:'a',name:'甲源',category:'light_novel'},{id:'b',name:'乙源',category:'light_novel'}]})
    if(init?.method === 'POST') return Response.json(book)
    return Response.json({items:[]})
  })
  vi.stubGlobal('fetch',fetcher); mount(<DirectSearchPage />)
  await screen.findByText('甲源')
  fireEvent.change(screen.getByRole('textbox',{name:'书名或作者'}),{target:{value:'三国演义'}})
  fireEvent.click(screen.getByRole('button',{name:'搜索'}))
  await screen.findByText('2 个来源 · 聚合阅读')
  expect(screen.getAllByRole('heading',{name:'三国演义'})).toHaveLength(1)
  expect(screen.getByRole('img',{name:'三国演义封面'})).toHaveAttribute('src',book.coverUrl)
  fireEvent.click(screen.getByRole('button',{name:'加入书库'}))
  await waitFor(() => expect(fetcher.mock.calls.some(([url,init]) => url === '/api/direct/shelf' && init?.method === 'POST' && JSON.parse(String(init.body)).sourceBookIds.length === 2)).toBe(true))
  expect(fetcher.mock.calls.some(([url]) => url.includes('/download'))).toBe(false)
})
it('renders shelf covers with a readable fallback for failed image hosts', async () => {
  vi.stubGlobal('fetch',vi.fn(async (url:string) => Response.json({items:url.endsWith('/shelf')?[book]:[]})))
  mount(<DirectShelfPage />)
  const cover = await screen.findByRole('img',{name:'三国演义封面'})
  expect(cover).toHaveAttribute('referrerPolicy','no-referrer')
  fireEvent.error(cover)
  expect(screen.getByLabelText('三国演义暂无封面')).toBeVisible()
  expect(screen.getByRole('button',{name:'整本下载'})).toBeVisible()
})

it('switches the three source categories and searches only the selected category', async () => {
  const fetcher = vi.fn(async (url: string) => {
    if (url.endsWith('/sources')) return Response.json({items:[{id:'light',name:'轻小说文库',category:'light_novel'},{id:'full',name:'全本源',category:'completed'},{id:'serial',name:'连载源',category:'ongoing'}]})
    if (url.includes('/search?')) return new Response('event: done\ndata: {}\n\n')
    return Response.json({items:[]})
  })
  vi.stubGlobal('fetch', fetcher); mount(<DirectSearchPage />)
  await screen.findByText('轻小说文库')
  fireEvent.click(screen.getByRole('button', {name:/^完结/}))
  await screen.findByText('全本源')
  expect(screen.queryByText('轻小说文库')).toBeNull()
  fireEvent.change(screen.getByRole('textbox', {name:'书名或作者'}), {target:{value:'测试'}})
  fireEvent.click(screen.getByRole('button', {name:'搜索'}))
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes('/search?') && new URL(url, 'https://example.com').searchParams.get('sources') === 'full')).toBe(true))
  fireEvent.click(screen.getByRole('button', {name:/^连载中/}))
  await screen.findByText('连载源')
})
