import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { directRequest } from "@/lib/direct-api"

export const txtNovelPath = "/attachments/txtnovel"

export function TxtNovelAccount() {
  const client = useQueryClient()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const account = useQuery({queryKey: ["direct", "txtnovel", "account"], queryFn: () => directRequest<{bound: boolean; username: string | null; enabled?: boolean}>(`${txtNovelPath}/account`), retry: false})
  const bind = useMutation({mutationFn: (remove: boolean) => directRequest(`${txtNovelPath}/account`, remove ? {method: "DELETE"} : {method: "POST", body: JSON.stringify({username, password})}),
    onSuccess: async () => {
      setPassword("")
      await Promise.all([client.invalidateQueries({queryKey: ["direct", "txtnovel"]}), client.invalidateQueries({queryKey: ["direct", "sources"]})])
    }})
  return <div className="mt-4 space-y-3 border-t pt-4">
    <h2 className="text-sm font-medium">书香门第账号</h2>
    <p className="text-xs leading-relaxed text-slate-500">绑定后可搜索论坛书籍。附件需要整本下载才能阅读，普通会员按论坛规则扣金币；每次下载前确认。账号会话仅供你使用，密码不保存。</p>
    {account.data?.enabled === false && <p className="text-sm text-slate-500">插件已停用，启用后可绑定账号、搜索和下载附件。</p>}
    {account.data?.bound ? <div className="flex items-center gap-3 text-sm"><span>已绑定：{account.data.username}</span><Button type="button" size="sm" variant="outline" disabled={bind.isPending} onClick={() => bind.mutate(true)}>解除绑定</Button></div>
      : <form className="flex flex-wrap gap-2" onSubmit={e => {e.preventDefault(); bind.mutate(false)}}>
        <Input className="min-w-0 flex-1 basis-36" aria-label="书香门第用户名" placeholder="论坛用户名" autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} />
        <Input className="min-w-0 flex-1 basis-36" aria-label="书香门第密码" placeholder="论坛密码" type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} />
        <Button size="sm" disabled={bind.isPending || account.data?.enabled === false || !username || !password} type="submit">{bind.isPending ? "正在绑定…" : "绑定账号"}</Button>
      </form>}
    {(account.error || bind.error) && <p role="alert" className="text-sm text-red-600">{bind.error?.message || account.error?.message}</p>}
  </div>
}
