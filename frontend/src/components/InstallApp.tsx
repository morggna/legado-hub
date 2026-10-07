import { useEffect, useState } from 'react'
import { Download, Share } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { clearInstallPrompt, getInstallPrompt, isAppleMobile, isStandalone } from '@/lib/pwa'

export function InstallApp() {
  const [installed, setInstalled] = useState(isStandalone)
  const [prompt, setPrompt] = useState(getInstallPrompt)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const ready = () => setPrompt(getInstallPrompt())
    const complete = () => { setInstalled(true); setOpen(false) }
    const display = window.matchMedia?.('(display-mode: standalone)')
    const changed = () => setInstalled(isStandalone())
    window.addEventListener('legado-install-ready', ready)
    window.addEventListener('appinstalled', complete)
    display?.addEventListener('change', changed)
    return () => {
      window.removeEventListener('legado-install-ready', ready)
      window.removeEventListener('appinstalled', complete)
      display?.removeEventListener('change', changed)
    }
  }, [])
  if (installed) return null
  async function install() {
    if (!prompt) { setOpen(true); return }
    setBusy(true)
    try {
      await prompt.prompt()
      const choice = await prompt.userChoice
      if (choice.outcome === 'accepted') setInstalled(true)
    } catch { setOpen(true) }
    finally { clearInstallPrompt(); setPrompt(null); setBusy(false) }
  }
  return <>
    <Button variant="ghost" size="sm" disabled={busy} onClick={() => { void install() }}><Download className="mr-2 h-4 w-4" />添加到主屏幕</Button>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-[calc(100%-2rem)] sm:max-w-md rounded-xl">
        <DialogTitle>把 LegadoHub 放到主屏幕</DialogTitle>
        <DialogDescription>以后点桌面图标，就能在独立窗口中打开书架。</DialogDescription>
        {isAppleMobile() ? <ol className="list-decimal space-y-3 pl-5 text-sm leading-6 text-slate-700">
          <li>用 Safari 打开本站。若在微信等应用内，请先选择“在 Safari 中打开”。</li>
          <li>点 Safari 的<Share className="mx-1 inline h-4 w-4" aria-hidden="true" />分享按钮，选择“添加到主屏幕”。找不到时，向下滚动分享菜单，或在“编辑操作”中查找。</li>
          <li>如果出现“作为网页 App 打开”选项，请保持开启，再点“添加”。</li>
        </ol> : <p className="text-sm leading-7 text-slate-700">打开浏览器菜单，选择“安装应用”或“添加到主屏幕”。iPhone / iPad 请用 Safari 的分享菜单添加；Mac Safari 可使用“添加到程序坞”。</p>}
        <p className="text-xs leading-5 text-slate-500">若已有旧的桌面书签，请先移除旧图标再重新添加。首次从桌面打开可能需要重新登录。在线搜索和阅读需要网络。</p>
      </DialogContent>
    </Dialog>
  </>
}
