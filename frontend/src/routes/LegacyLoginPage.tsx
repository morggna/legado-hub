import { useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router"
import { BookOpen, KeyRound, Loader2, ShieldCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { apiErrorMessage } from "@/lib/api"
import { useAuth } from "@/lib/auth"

function safeNextPath(raw: string | null): string {
  const value = (raw || "").trim()
  if (!value.startsWith("/") || value.startsWith("//")) return "/"
  return value
}

export function LegacyLoginPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { user, entrypoint, isLoading, authError, retryAuth, login, loginWithAccessCode } = useAuth()
  const [mode, setMode] = useState<"access" | "admin">(searchParams.get("code") ? "access" : "admin")
  const [accessCode, setAccessCode] = useState("")
  const [username, setUsername] = useState("admin")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(() =>
    searchParams.get("error") === "invalid_code"
      ? "订阅链接无效或已重置，请联系管理员重新发放。"
      : null,
  )
  const [submitting, setSubmitting] = useState(false)
  const [autoRedeeming, setAutoRedeeming] = useState(false)
  const attemptedAutoCodeRef = useRef<string>("")
  const effectiveEntrypoint = entrypoint || "combined"
  const effectiveMode = effectiveEntrypoint === "admin" ? "admin" : effectiveEntrypoint === "public" ? "access" : mode
  const nextPath = safeNextPath(searchParams.get("next"))

  useEffect(() => {
    if (!isLoading && user) {
      navigate(nextPath, { replace: true })
    }
  }, [isLoading, navigate, nextPath, user])

  // Personal subscription link / book-source open: ?code= auto-login (once per code).
  useEffect(() => {
    if (isLoading || user || effectiveMode === "admin" || autoRedeeming) return
    const code = (searchParams.get("code") || "").trim()
    if (!code) return
    if (attemptedAutoCodeRef.current === code) return
    attemptedAutoCodeRef.current = code
    let cancelled = false
    setAutoRedeeming(true)
    setError(null)
    void (async () => {
      try {
        await loginWithAccessCode(code)
        if (!cancelled) navigate(nextPath, { replace: true })
      } catch (loginError) {
        if (!cancelled) {
          setAccessCode(code)
          setError(apiErrorMessage(loginError, "订阅链接登录失败，请检查链接是否已重置。"))
        }
      } finally {
        if (!cancelled) setAutoRedeeming(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [autoRedeeming, effectiveMode, isLoading, loginWithAccessCode, navigate, nextPath, searchParams, user])

  if (isLoading || autoRedeeming) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-3">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
        {autoRedeeming && <p className="text-sm text-slate-500">正在通过订阅链接登录…</p>}
      </div>
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (effectiveMode === "access" && !accessCode.trim()) {
      setError("请输入授权码")
      return
    }
    if (effectiveMode === "admin" && (!username.trim() || !password)) {
      setError("请输入用户名和密码")
      return
    }
    setSubmitting(true)
    try {
      if (effectiveMode === "access") {
        await loginWithAccessCode(accessCode.trim())
        setAccessCode("")
      } else {
        await login(username.trim(), password)
        setPassword("")
      }
      navigate(nextPath, { replace: true })
    } catch (loginError) {
      setError(apiErrorMessage(loginError, "登录失败，请稍后重试。"))
    } finally {
      setSubmitting(false)
    }
  }

  const loginForm = (
    <form onSubmit={handleSubmit} className="space-y-4">
      {effectiveMode === "access" ? (
        <div className="space-y-2">
          <Label htmlFor="access-code">授权码 / 订阅链接</Label>
          <Input
            id="access-code"
            type="password"
            value={accessCode}
            onChange={(e) => setAccessCode(e.target.value)}
            autoComplete="current-password"
            autoFocus
            placeholder="粘贴授权码，或通过专属链接自动登录"
          />
          <p className="text-xs text-slate-500">管理员可发放「专属书源/订阅链接」，打开后无需再手动输入。</p>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="username">用户名</Label>
            <Input id="username" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">密码</Label>
            <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          </div>
        </div>
      )}
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {authError && (
        <Alert variant="destructive">
          <AlertDescription className="flex items-center justify-between gap-2">
            <span>{authError}</span>
            <Button type="button" variant="outline" size="sm" onClick={() => { void retryAuth() }}>重试</Button>
          </AlertDescription>
        </Alert>
      )}
      <Button
        type="submit"
        className="w-full"
        disabled={submitting}
      >
        {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
        登录
      </Button>
    </form>
  )

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 p-4">
      <Card className="w-full max-w-md shadow-sm">
        <CardHeader className="space-y-1">
          <div className="flex items-center gap-2 text-slate-900">
            <BookOpen className="h-5 w-5" />
            <CardTitle className="text-xl">LegadoHub</CardTitle>
          </div>
          <CardDescription>
            {effectiveMode === "access" ? "读者登录：授权码或专属订阅链接" : effectiveEntrypoint === "combined" ? "账号登录，阅读与管理共用一个入口" : "管理员登录"}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {effectiveEntrypoint === "combined" && (
            <Tabs value={effectiveMode} onValueChange={(v) => setMode(v as "access" | "admin")}>
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="access"><KeyRound className="mr-1.5 h-3.5 w-3.5" />授权码</TabsTrigger>
                <TabsTrigger value="admin"><ShieldCheck className="mr-1.5 h-3.5 w-3.5" />账号登录</TabsTrigger>
              </TabsList>
            </Tabs>
          )}
          {loginForm}
        </CardContent>
      </Card>
    </div>
  )
}
