import { InstallApp } from "@/components/InstallApp"
import { useEffect, useState } from "react"
import { useNavigate, useSearchParams } from "react-router"
import { useQueryClient } from "@tanstack/react-query"
import { BookOpen } from "lucide-react"
import { useAuth } from "@/lib/auth"
import { accountRequest } from "@/lib/account-api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LegacyLoginPage } from "./LegacyLoginPage"

export function LoginPage() {
  const auth = useAuth()
  // Dedicated upstream entrypoints are retained only for compatibility tests;
  // the deployed combined app always uses account_invite.
  if (auth.authMode === "legacy" || (!auth.authMode && auth.entrypoint !== "combined")) return <LegacyLoginPage />
  return <AccountLoginPage />
}

function AccountLoginPage() {
  const navigate = useNavigate()
  const client = useQueryClient()
  const [params] = useSearchParams()
  const { user, isLoading, login } = useAuth()
  const [register, setRegister] = useState(false)
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [invitationCode, setInvitationCode] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const rawNext = params.get("next") || "/console/library"
  const next = rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "/console/library"
  useEffect(() => { if (!isLoading && user) navigate(next, { replace: true }) }, [isLoading, user, next, navigate])
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError("")
    try {
      if (register) {
        await accountRequest("/auth/register", { method: "POST", body: JSON.stringify({ username: username.trim(), password, invitationCode: invitationCode.trim() }) })
        await client.invalidateQueries({ queryKey: ["auth", "me"] })
      } else await login(username.trim(), password)
      setPassword(""); navigate(next, { replace: true })
    } catch (e) { setError(e instanceof Error ? e.message : "登录失败") }
    finally { setBusy(false) }
  }
  return <div className="flex min-h-dvh items-center justify-center bg-slate-50 p-4">
    <div className="w-full max-w-md rounded-xl border bg-white p-7 shadow-sm">
      <h1 className="flex items-center gap-2 text-xl font-semibold"><BookOpen /> LegadoHub</h1>
      <p className="mb-6 mt-2 text-sm text-slate-500">{register ? "使用管理员提供的邀请码创建账号" : "登录后搜索书源，管理书库与阅读进度"}</p>
      <form className="space-y-4" onSubmit={e => { void submit(e) }}>
        <div className="space-y-2"><Label htmlFor="username">用户名</Label><Input id="username" autoComplete="username" autoFocus required value={username} onChange={e => setUsername(e.target.value)} maxLength={64} /></div>
        <div className="space-y-2"><Label htmlFor="password">密码</Label><Input id="password" type="password" autoComplete={register ? "new-password" : "current-password"} required minLength={register ? 8 : undefined} maxLength={128} value={password} onChange={e => setPassword(e.target.value)} /></div>
        {register && <div className="space-y-2"><Label htmlFor="invitation">邀请码</Label><Input id="invitation" required value={invitationCode} onChange={e => setInvitationCode(e.target.value)} autoComplete="off" /></div>}
        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
        <Button type="submit" className="w-full" disabled={busy}>{busy ? "处理中…" : register ? "注册账号" : "登录"}</Button>
      </form>
      <Button className="mt-4 w-full" variant="ghost" disabled={busy} onClick={() => { setRegister(!register); setError("") }}>{register ? "已有账号，返回登录" : "有邀请码？注册账号"}</Button>
      <div className="mt-2 text-center"><InstallApp /></div>
    </div>
  </div>
}
