import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { InstallApp } from './InstallApp'
import { clearInstallPrompt, initializePwa } from '@/lib/pwa'

initializePwa()
beforeEach(() => {
  clearInstallPrompt()
  vi.stubGlobal('matchMedia',vi.fn(() => ({matches:false,addEventListener:vi.fn(),removeEventListener:vi.fn()})))
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); clearInstallPrompt() })
it('explains the Safari share flow on iPhone instead of claiming automatic installation', () => {
  vi.spyOn(navigator,'userAgent','get').mockReturnValue('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)')
  render(<InstallApp />)
  fireEvent.click(screen.getByRole('button',{name:'添加到主屏幕'}))
  expect(screen.getByRole('dialog')).toHaveTextContent('Safari')
  expect(screen.getByRole('dialog')).toHaveTextContent('分享按钮')
  expect(screen.getByRole('dialog')).toHaveTextContent('作为网页 App 打开')
})
it('uses a browser install prompt only after an explicit click', async () => {
  const prompt = vi.fn(async () => {})
  const event = Object.assign(new Event('beforeinstallprompt',{cancelable:true}), {prompt,userChoice:Promise.resolve({outcome:'accepted'})})
  window.dispatchEvent(event)
  render(<InstallApp />)
  expect(prompt).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button',{name:'添加到主屏幕'}))
  await waitFor(() => expect(prompt).toHaveBeenCalledTimes(1))
  await waitFor(() => expect(screen.queryByRole('button',{name:'添加到主屏幕'})).toBeNull())
})
it('hides installation in a standalone window', () => {
  vi.stubGlobal('matchMedia',vi.fn(() => ({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()})))
  render(<InstallApp />)
  expect(screen.queryByRole('button')).toBeNull()
})
