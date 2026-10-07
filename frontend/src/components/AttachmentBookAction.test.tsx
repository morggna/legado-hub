import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { AttachmentBookAction } from './AttachmentBookAction'
import { TxtNovelAccount } from './TxtNovelAccount'

afterEach(() => {cleanup(); vi.unstubAllGlobals()})
function mount(component: React.ReactNode) {
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter>{component}</MemoryRouter></QueryClientProvider>)
}
it('requires selecting the attachment and explicitly accepting the debit before downloading', async () => {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return Response.json({bookId:'import-one',name:'测试书'})
    return Response.json({attachments:[{attachmentId:'123',name:'测试.rar',costText:'金币 -1 枚',confirmationToken:'signed'}]})
  })
  vi.stubGlobal('fetch',fetcher)
  mount(<AttachmentBookAction book={{bookId:'attachment-one',sourceId:'txtnovel_vip',sourceName:'书香门第',name:'测试书',author:'作者',threadId:'456'}} busy={false} />)
  fireEvent.click(screen.getByRole('button',{name:'下载并加入书库'}))
  await screen.findByText('测试.rar')
  expect(screen.getByRole('button',{name:'确认下载并加入书库'})).toBeDisabled()
  fireEvent.click(screen.getByRole('radio'))
  expect(screen.getByRole('button',{name:'确认下载并加入书库'})).toBeDisabled()
  expect(fetcher.mock.calls.some(([,init]) => init?.method === 'POST')).toBe(false)
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button',{name:'确认下载并加入书库'}))
  await waitFor(() => expect(fetcher.mock.calls.filter(([,init]) => init?.method === 'POST')).toHaveLength(1))
  const body = fetcher.mock.calls.find(([,init]) => init?.method === 'POST')?.[1]?.body
  expect(JSON.parse(String(body))).toEqual({confirmationToken:'signed'})
})
it('stores no password in browser storage and clears it after binding', async () => {
  let bound = false
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {bound=true; return Response.json({bound:true,username:'forum'})}
    return Response.json({bound,username:bound?'forum':null})
  })
  vi.stubGlobal('fetch',fetcher)
  const storage = vi.spyOn(Storage.prototype,'setItem')
  mount(<TxtNovelAccount />)
  const password = await screen.findByLabelText('书香门第密码')
  fireEvent.change(screen.getByLabelText('书香门第用户名'),{target:{value:'forum'}})
  fireEvent.change(password,{target:{value:'private-secret'}})
  fireEvent.click(screen.getByRole('button',{name:'绑定账号'}))
  await screen.findByText('已绑定：forum')
  expect(storage).not.toHaveBeenCalled()
  storage.mockRestore()
})
