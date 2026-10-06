import { BrowserRouter, Routes, Route, Navigate, Outlet, useLocation } from "react-router"
import { QueryClientProvider } from "@tanstack/react-query"
import { queryClient } from "@/lib/query"
import { AuthProvider, useAuth } from "@/lib/auth"
import { Layout } from "@/components/layout/Layout"
import { LoginPage } from "@/routes/LoginPage"
import { Dashboard } from "@/routes/Dashboard"
import { DirectSearchPage } from "@/routes/DirectSearchPage"
import { DirectShelfPage } from "@/routes/DirectShelfPage"
import { DirectReaderPage } from "@/routes/DirectReaderPage"
import { Plugins } from "@/routes/Plugins"
import { SearchJobs } from "@/routes/SearchJobs"
import { SettingsPage } from "@/routes/SettingsPage"
import { SubscriptionDiscoveryPage } from "@/routes/SubscriptionDiscoveryPage"
import { LibraryPage } from "@/routes/LibraryPage"
import { LibraryBookDetailPage } from "@/routes/LibraryBookDetailPage"
import { LibraryChapterDetailPage } from "@/routes/LibraryChapterDetailPage"
import { AccountUsersPage as UsersPage } from "@/routes/AccountUsersPage"

function ProtectedLayout() {
  const location = useLocation()
  const { isLoading, isAuthenticated, authError, retryAuth } = useAuth()
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-muted-foreground">加载中...</div>
      </div>
    )
  }
  if (authError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 p-4">
        <div role="alert" className="w-full max-w-sm rounded-lg border border-rose-200 bg-white p-5 shadow-sm">
          <h1 className="text-base font-semibold text-slate-900">认证服务暂时不可用</h1>
          <p className="mt-2 text-sm text-slate-600">{authError}</p>
          <button
            type="button"
            className="mt-4 inline-flex h-9 items-center justify-center rounded-md bg-slate-900 px-4 text-sm font-medium text-white hover:bg-slate-800"
            onClick={() => { void retryAuth() }}
          >
            重新连接
          </button>
        </div>
      </div>
    )
  }
  if (!isAuthenticated) {
    // Preserve personal ?code= so LoginPage can auto-redeem without re-entry.
    const params = new URLSearchParams(location.search)
    const code = (params.get("code") || "").trim()
    if (code) params.delete("code")
    const cleanedSearch = params.toString()
    const nextPath = `${location.pathname}${cleanedSearch ? `?${cleanedSearch}` : ""}`
    const loginParams = new URLSearchParams()
    if (nextPath && nextPath !== "/") loginParams.set("next", nextPath)
    if (code) loginParams.set("code", code)
    const qs = loginParams.toString()
    return <Navigate to={qs ? `/login?${qs}` : "/login"} replace />
  }
  return <Outlet />
}

export function AdminOnly() {
  const { user, entrypoint } = useAuth()
  if (entrypoint === "public" || user?.role !== "admin") {
    return <Navigate to="/" replace />
  }
  return <Outlet />
}

function HomePage() {
  const { entrypoint } = useAuth()
  return entrypoint === "combined" ? <Navigate to="/console/library" replace /> : <Dashboard />
}

function AuthRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedLayout />}>
          <Route path="/" element={<Layout />}>
            <Route index element={<HomePage />} />
          </Route>
          <Route path="/console/library/:bookId" element={<DirectReaderPage />} />
          <Route path="/console" element={<Layout />}>
            <Route index element={<Navigate to="/" replace />} />
            <Route path="search" element={<DirectSearchPage />} />
            <Route path="direct" element={<Navigate to="/console/search" replace />} />
            <Route path="direct/shelf" element={<Navigate to="/console/library" replace />} />
            <Route path="library" element={<DirectShelfPage />} />
            <Route element={<AdminOnly />}>
              <Route path="plugins" element={<Plugins />} />
              <Route path="admin/search" element={<SearchJobs />} />
              <Route path="official-sources" element={<Navigate to="/console/plugins?tab=official" replace />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="users" element={<UsersPage />} />
              <Route path="library/:bookId/chapters/:chapterId" element={<LibraryChapterDetailPage />} />
              <Route path="admin/subscription" element={<SubscriptionDiscoveryPage mode="admin" />} />
              <Route path="admin/library" element={<LibraryPage />} />
              <Route path="admin/library/:bookId" element={<LibraryBookDetailPage />} />
            </Route>
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <AuthRouter />
      </AuthProvider>
    </QueryClientProvider>
  )
}

export default App
