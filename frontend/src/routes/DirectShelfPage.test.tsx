import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { DirectShelfPage } from './DirectShelfPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
function mount() {
  let categories = [{categoryId:'custom', name:'正在读'}]
  let items = [
    {bookId:'recent', name:'最近的书', categoryId:'custom' as string | null, lastReadAt:'2026-10-07T01:00:00Z', progress:{chapterIndex:3,position:.5,revision:2}},
    {bookId:'unread', name:'未读的书', categoryId:null as string | null, lastReadAt:null},
  ]
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : {}
    if (url === '/api/direct/shelf/categories') {
      if (init?.method === 'POST') categories = [...categories, {categoryId:'new', name:body.name}]
      return Response.json({items:categories})
    }
    if (url.endsWith('/categories/custom')) {
      if (init?.method === 'PATCH') categories[0].name = body.name
      if (init?.method === 'DELETE') { categories = categories.filter(c => c.categoryId !== 'custom'); items = items.map(b => b.categoryId === 'custom' ? ({...b,categoryId:null}) : b) }
      return Response.json({ok:true})
    }
    if (url.endsWith('/unread/category')) { items[1].categoryId = body.categoryId; return Response.json({ok:true}) }
    return Response.json({items: url === '/api/direct/shelf' ? items : []})
  })
  vi.stubGlobal('fetch', fetcher)
  const client = new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})
  render(<QueryClientProvider client={client}><MemoryRouter><DirectShelfPage /></MemoryRouter></QueryClientProvider>)
  return fetcher
}
it('filters custom categories while preserving recent-reading order and resumes saved progress', async () => {
  const fetcher = mount()
  await screen.findByRole('heading',{name:'最近的书'})
  expect(screen.getAllByRole('heading',{level:2}).map(h => h.textContent)).toEqual(['最近的书'])
  expect(screen.getByRole('button',{name:'正在读 · 1'})).toHaveAttribute('aria-pressed','true')
  expect(screen.queryByRole('button',{name:/^全部/})).toBeNull()
  expect(screen.getByRole('link',{name:'继续阅读'})).toHaveAttribute('href','/console/library/recent/read')
  fireEvent.click(screen.getByRole('button',{name:'未分类 · 1'}))
  expect(screen.queryByRole('heading',{name:'最近的书'})).toBeNull()
  fireEvent.change(screen.getByRole('combobox',{name:'未读的书的分类'}),{target:{value:'custom'}})
  await screen.findByText('这个分类还没有书。在书籍卡片上选择分类即可移入。')
  fireEvent.click(screen.getByRole('button',{name:'正在读 · 2'}))
  expect(screen.getAllByRole('heading',{level:2}).map(h => h.textContent)).toEqual(['最近的书','未读的书'])
  expect(fetcher.mock.calls.some(([,init]) => init?.method === 'PATCH')).toBe(true)
})
it('creates, renames and deletes custom categories without removing books', async () => {
  const fetcher = mount()
  fireEvent.click(await screen.findByRole('button',{name:'管理分类'}))
  fireEvent.change(screen.getByRole('textbox',{name:'分类名称'}),{target:{value:'  收藏  '}})
  fireEvent.click(screen.getByRole('button',{name:'创建分类'}))
  await screen.findByRole('button',{name:'收藏 · 0',hidden:true})
  expect(within(screen.getByLabelText('书架分类')).getAllByRole('button',{hidden:true}).map(b => b.getAttribute('aria-label') || b.textContent)).toEqual(['正在读 · 1','收藏 · 0','未分类 · 1','管理分类'])
  fireEvent.change(screen.getByRole('combobox',{name:'选择要管理的分类'}),{target:{value:'custom'}})
  fireEvent.change(screen.getByRole('textbox',{name:'分类名称'}),{target:{value:'已读'}})
  fireEvent.click(screen.getByRole('button',{name:'保存名称'}))
  await screen.findByRole('button',{name:'已读 · 1',hidden:true})
  fireEvent.change(screen.getByRole('combobox',{name:'选择要管理的分类'}),{target:{value:'custom'}})
  fireEvent.click(screen.getByRole('button',{name:'删除分类'}))
  expect(fetcher.mock.calls.some(([,init]) => init?.method === 'DELETE')).toBe(false)
  fireEvent.click(screen.getByRole('button',{name:'确认删除分类'}))
  await waitFor(() => expect(screen.queryByRole('button',{name:'已读 · 1',hidden:true})).toBeNull())
  expect(screen.getByRole('button',{name:'未分类 · 2',hidden:true})).toHaveAttribute('aria-pressed','true')
  expect(within(screen.getByLabelText('书架分类')).getAllByRole('button',{hidden:true}).map(b => b.getAttribute('aria-label') || b.textContent)).toEqual(['收藏 · 0','未分类 · 2','管理分类'])
})
