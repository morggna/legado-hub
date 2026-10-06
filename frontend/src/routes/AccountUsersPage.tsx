import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { accountRequest, type Invitation } from "@/lib/account-api"
import { useAuth } from "@/lib/auth"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

export function AccountUsersPage() {
  const client = useQueryClient()
  const { user } = useAuth()
  const [issued, setIssued] = useState("")
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [role, setRole] = useState("user")
  const [reset, setReset] = useState<string | null>(null)
  const [newPassword, setNewPassword] = useState("")
  const [error, setError] = useState("")
  const [maxUses, setMaxUses] = useState(1)
  const [days, setDays] = useState(7)
  const users = useQuery({ queryKey: ["account-users"], queryFn: api.users.list })
  const invites = useQuery({ queryKey: ["invitations"], queryFn: () => accountRequest<{items: Invitation[]}>("/accounts/invitations") })
  const action = useMutation({ mutationFn: async (run: () => Promise<unknown>) => run(), onSuccess: async () => { setError(""); await Promise.all([client.invalidateQueries({ queryKey: ["account-users"] }), client.invalidateQueries({ queryKey: ["invitations"] })]) }, onError: e => setError(e.message) })
  return <div className="mx-auto max-w-5xl space-y-6 p-4 md:p-8">
    <h1 className="text-2xl font-semibold">用户与邀请码</h1>
    {(error || users.error || invites.error) && <p role="alert" className="text-red-600">{error || users.error?.message || invites.error?.message}</p>}
    <section className="space-y-3 rounded-lg border bg-white p-5"><h2 className="font-semibold">创建注册邀请码</h2><p className="text-sm text-slate-500">邀请码只用于注册。注册完成后使用账号密码登录。</p>
      <form className="flex flex-wrap items-end gap-3" onSubmit={e => { e.preventDefault(); action.mutate(async () => { const result = await accountRequest<{code: string}>("/accounts/invitations", { method: "POST", body: JSON.stringify({ maxUses, expiresDays: days }) }); setIssued(result.code) }) }}>
        <label className="text-sm">可注册人数<Input type="number" min={1} max={100} required value={maxUses} onChange={e => setMaxUses(Number(e.target.value))} /></label>
        <label className="text-sm">有效天数<Input type="number" min={1} max={90} required value={days} onChange={e => setDays(Number(e.target.value))} /></label>
        <Button disabled={action.isPending}>生成邀请码</Button>
      </form>
      {issued && <div className="rounded bg-slate-100 p-3"><p className="text-sm">复制并保存，此完整邀请码只显示一次：</p><code className="block break-all p-2">{issued}</code><Button variant="outline" size="sm" onClick={() => { void navigator.clipboard.writeText(issued).catch(() => setError("复制失败，请手动选择邀请码")) }}>复制</Button></div>}
      <div className="space-y-2">{invites.data?.items.map(i => <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-2 text-sm" key={i.inviteId}><span>…{i.label} · 已用 {i.usedCount}/{i.maxUses} · 到期 {new Date(i.expiresAt * 1000).toLocaleString()} {i.revoked ? "· 已撤销" : ""}</span><Button variant="outline" size="sm" disabled={i.revoked || action.isPending} onClick={() => action.mutate(() => accountRequest(`/accounts/invitations/${i.inviteId}`, { method: "DELETE" }))}>撤销</Button></div>)}</div>
    </section>
    <section className="space-y-4 rounded-lg border bg-white p-5"><h2 className="font-semibold">账号管理</h2>
      <form className="flex flex-wrap gap-2" onSubmit={e => { e.preventDefault(); action.mutate(async () => { await accountRequest("/console/users", { method: "POST", body: JSON.stringify({ username, password, role }) }); setUsername(""); setPassword("") }) }}>
        <Input className="w-44" aria-label="新用户名" placeholder="新用户名" required value={username} onChange={e => setUsername(e.target.value)} />
        <Input className="w-44" aria-label="初始密码" type="password" placeholder="初始密码（至少 8 位）" required minLength={8} value={password} onChange={e => setPassword(e.target.value)} />
        <select className="rounded border p-2" aria-label="账号角色" value={role} onChange={e => setRole(e.target.value)}><option value="user">普通用户</option><option value="admin">管理员</option></select>
        <Button disabled={action.isPending}>创建账号</Button>
      </form>
      {users.data?.items.map(u => <div className="flex flex-wrap items-center justify-between gap-3 border-t py-3" key={u.userId}>
        <span>{u.username} <small className="text-slate-500">{u.role === "admin" ? "管理员" : "普通用户"}{u.disabled ? " · 已禁用" : ""}</small></span>
        {u.userId !== user?.userId && <div className="flex gap-2"><Button variant="outline" size="sm" disabled={action.isPending} onClick={() => action.mutate(() => api.users.setDisabled(u.userId, !u.disabled))}>{u.disabled ? "启用" : "禁用"}</Button><Button variant="outline" size="sm" onClick={() => { setReset(u.userId); setNewPassword("") }}>重置密码</Button><Button variant="ghost" size="sm" disabled={action.isPending} onClick={() => action.mutate(() => api.users.revokeSessions(u.userId))}>退出所有设备</Button></div>}
      </div>)}
      {reset && <form className="flex gap-2 rounded bg-slate-50 p-3" onSubmit={e => { e.preventDefault(); action.mutate(async () => { await api.users.resetPassword(reset, newPassword); setReset(null); setNewPassword("") }) }}><Input type="password" aria-label="新的密码" placeholder="新的密码" required minLength={8} value={newPassword} onChange={e => setNewPassword(e.target.value)} /><Button disabled={action.isPending}>保存新密码</Button><Button type="button" variant="ghost" onClick={() => setReset(null)}>取消</Button></form>}
    </section>
  </div>
}
