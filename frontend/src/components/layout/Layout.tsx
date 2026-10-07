import { Outlet, NavLink, useLocation } from "react-router"
import {
  AlertCircle, LogOut, Menu, Search, Settings, BookOpen, UserCog, Users, Library, ShieldAlert, Server,
} from "lucide-react"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

interface NavItem {
  name: string
  href: string
  icon: React.ElementType
  adminOnly?: boolean
  aliases?: string[]
}

const mainNav: NavItem[] = [
  { name: "我的书库", href: "/console/library", icon: Library },
  { name: "搜索书源", href: "/console/search", icon: Search },
]

const adminNav: NavItem[] = [
  { name: "搜索工作台", href: "/console/admin/search", icon: ShieldAlert, adminOnly: true },
  { name: "书源管理", href: "/console/plugins", icon: Server, adminOnly: true },
  { name: "用户管理", href: "/console/users", icon: Users, adminOnly: true },
  { name: "系统设置", href: "/console/settings", icon: Settings, adminOnly: true },
]

function isPathActive(pathname: string, path: string) {
  return path === "/"
    ? pathname === path
    : pathname === path || pathname.startsWith(`${path}/`)
}

function isNavItemActive(item: NavItem, pathname: string) {
  return [item.href, ...(item.aliases || [])].some((path) => isPathActive(pathname, path))
}

export function Layout() {
  const location = useLocation()
  const { user, entrypoint, logout, isLoggingOut, logoutError } = useAuth()
  const isAdmin = entrypoint !== "public" && user?.role === "admin"

  const renderNavItem = (item: NavItem, mobile = false) => {
    if (item.adminOnly && !isAdmin) return null
    const active = isNavItemActive(item, location.pathname)
    return (
      <NavLink
        key={item.name}
        to={item.href}
        end={item.href === "/"}
        aria-current={active ? "page" : undefined}
        className={cn(
          "group flex w-full items-center rounded-md py-2 text-sm font-medium transition-[background-color,color,transform] duration-200 active:scale-[0.98]",
          mobile ? "px-2" : "px-3",
          active
            ? "bg-slate-100 text-slate-900"
            : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
        )}
      >
        <item.icon
          className={cn(
            "mr-3 h-5 w-5 flex-shrink-0",
            active
              ? "text-slate-900"
              : "text-slate-400 group-hover:text-slate-500"
          )}
        />
        {item.name}
      </NavLink>
    )
  }

  return (
    // h-screen + min-h-0 keeps scroll inside <main> so tab height changes never
    // toggle the window scrollbar (which shifts centered content left/right).
    <div className="app-shell flex h-dvh overflow-hidden bg-slate-50">
      <aside className="hidden h-full w-64 shrink-0 flex-col border-r border-slate-200 bg-white md:flex">
        <div className="flex h-16 flex-shrink-0 items-center px-6">
          <BookOpen className="h-6 w-6 text-slate-800" />
          <span className="ml-3 text-lg font-bold tracking-tight text-slate-900">LegadoHub</span>
        </div>
        <div className="flex flex-1 flex-col overflow-y-auto px-4 py-4">
          <nav className="flex-1 space-y-1">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400 px-3">阅读空间</div>
            {mainNav.map((item) => renderNavItem(item))}
            {isAdmin && (
              <>
                <div className="mt-8 mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400 px-3">管理员工具</div>
                {adminNav.map((item) => renderNavItem(item))}
              </>
            )}
          </nav>
        </div>
        <div className="border-t border-slate-200 p-4">
          <div className="flex items-center justify-between rounded-lg bg-slate-50 p-3">
            <div className="flex items-center space-x-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-200">
                <UserCog className="h-4 w-4 text-slate-600" />
              </div>
              <div className="text-sm font-medium text-slate-900">{user?.username || (isAdmin ? "管理员" : "普通用户")}</div>
            </div>
            <button
              type="button"
              disabled={isLoggingOut}
              onClick={() => { void logout().catch(() => undefined) }}
              className="text-xs text-slate-500 hover:text-slate-900 underline disabled:cursor-wait disabled:opacity-60"
            >
              {isLoggingOut ? "退出中..." : "退出登录"}
            </button>
          </div>
        </div>
      </aside>
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <header className="flex h-16 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6 shadow-sm md:hidden">
          <div className="flex items-center">
            <BookOpen className="h-6 w-6 text-slate-800" />
            <span className="ml-3 text-lg font-bold tracking-tight text-slate-900">LegadoHub</span>
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label="打开导航菜单"
                className="inline-flex h-10 w-10 items-center justify-center rounded-md text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2"
              >
                <Menu className="h-5 w-5" aria-hidden="true" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel>{user?.username || (isAdmin ? "管理员" : "普通用户")}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {mainNav.map((item) => (
                <DropdownMenuItem key={item.name} asChild>
                  {renderNavItem(item, true)}
                </DropdownMenuItem>
              ))}
              {isAdmin && (
                <>
                  <DropdownMenuSeparator />
                  {adminNav.map((item) => (
                    <DropdownMenuItem key={item.name} asChild>
                      {renderNavItem(item, true)}
                    </DropdownMenuItem>
                  ))}
                </>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem disabled={isLoggingOut} onSelect={() => { void logout().catch(() => undefined) }}>
                <LogOut className="mr-3 h-5 w-5 text-slate-400" aria-hidden="true" />
                {isLoggingOut ? "退出中..." : "退出登录"}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>
        <main className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-slate-50 p-6 [scrollbar-gutter:stable] md:p-8">
          <div className="mx-auto w-full max-w-6xl flex-1">
            {logoutError && (
              <div role="alert" className="mb-4 flex items-center gap-2 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
                <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
                退出登录失败，请稍后重试。
              </div>
            )}
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
