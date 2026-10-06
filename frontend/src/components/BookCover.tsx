import { useState } from "react"

export function BookCover({ name, url }: { name: string; url?: string }) {
  const [failed, setFailed] = useState<string | undefined>()
  const valid = !!url && /^https?:\/\//i.test(url) && failed !== url
  return <div className="h-32 w-24 shrink-0 overflow-hidden rounded-md bg-gradient-to-br from-slate-100 to-stone-200 shadow-sm">
    {valid ? <img className="h-full w-full object-cover" src={url} alt={`${name}封面`} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(url)} />
      : <div className="flex h-full items-center justify-center px-3 text-center text-sm font-medium text-slate-600" aria-label={`${name}暂无封面`}>{name}</div>}
  </div>
}
