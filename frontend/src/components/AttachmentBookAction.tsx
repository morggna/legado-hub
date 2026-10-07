import { useState } from "react"
import { useNavigate } from "react-router"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { bookDetailUrl, directRequest, type DirectBook } from "@/lib/direct-api"
import { txtNovelPath } from "@/components/TxtNovelAccount"

interface Attachment { attachmentId: string; name: string; costText: string; confirmationToken: string }
interface Preview extends DirectBook { attachments: Attachment[] }

export function AttachmentBookAction({book, busy}: {book: DirectBook; busy: boolean}) {
  const client = useQueryClient()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<Attachment | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const preview = useMutation({mutationFn: () => directRequest<Preview>(`${txtNovelPath}/preview?threadId=${encodeURIComponent(book.threadId ?? "")}`)})
  const download = useMutation({retry: false, mutationFn: (attachment: Attachment) => directRequest<DirectBook>(`${txtNovelPath}/download`, {method: "POST", body: JSON.stringify({confirmationToken: attachment.confirmationToken})}),
    onSuccess: async result => {
      await Promise.all([client.invalidateQueries({queryKey: ["direct", "shelf"]}), client.invalidateQueries({queryKey: ["direct", "downloads"]})])
      setOpen(false)
      navigate(bookDetailUrl(result.bookId))
    }})
  function show() {
    setSelected(null); setConfirmed(false); preview.reset(); download.reset(); setOpen(true); preview.mutate()
  }
  return <><Button size="sm" disabled={busy || download.isPending} onClick={show}>下载并加入书库</Button>
    <Dialog open={open} onOpenChange={value => {if (!download.isPending) setOpen(value)}}>
      <DialogContent className="max-h-[85dvh] overflow-y-auto"><DialogHeader><DialogTitle>下载《{book.name}》</DialogTitle><DialogDescription>从书香门第下载整本附件，解压后自动分章并加入你的书库。</DialogDescription></DialogHeader>
        {preview.isPending && <p role="status">正在获取附件信息…</p>}
        {preview.error && <p role="alert" className="text-sm text-red-600">{preview.error.message}</p>}
        {preview.data && <>
          <div className="space-y-2">{preview.data.attachments.map(attachment => <label key={attachment.attachmentId} className="flex cursor-pointer items-start gap-2 rounded-lg border p-3">
            <input type="radio" name="attachment" className="mt-1" checked={selected?.attachmentId === attachment.attachmentId} disabled={download.isPending || !!download.error} onChange={() => {setSelected(attachment);setConfirmed(false)}} />
            <span className="min-w-0 break-words text-sm">{attachment.name}<span className="mt-1 block text-xs text-amber-700">下载积分：{attachment.costText}</span></span>
          </label>)}</div>
          {!preview.data.attachments.length && <p className="text-sm text-slate-500">帖子没有可导入的 TXT 或压缩附件。</p>}
          {selected && <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={confirmed} disabled={download.isPending || !!download.error} onChange={e => setConfirmed(e.target.checked)} /><span>我同意按论坛规则扣除金币，下载选中的附件。VIP 是否免金币由论坛判断。</span></label>}
          <p className="text-xs leading-relaxed text-slate-500">目前支持包含一份 TXT 的 RAR、ZIP、7z 或 TXT 附件。若下载后导入失败，金币可能已扣除；不会自动重试。</p>
          {download.error && <p role="alert" className="text-sm text-red-600">{download.error.message}</p>}
          <Button disabled={!selected || !confirmed || download.isPending || !!download.error} onClick={() => {if (selected) download.mutate(selected)}}>{download.isPending ? "正在下载并导入…" : "确认下载并加入书库"}</Button>
        </>}
      </DialogContent>
    </Dialog>
  </>
}
