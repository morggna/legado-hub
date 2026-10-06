import { createContext, useContext, type ReactNode } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { AuthUser, ConsoleEntrypoint } from "@/lib/auth.types"

interface AuthContextValue {
  user: AuthUser | null
  authMode: "account_invite" | "legacy"
  entrypoint: ConsoleEntrypoint
  isLoading: boolean
  isAuthenticated: boolean
  authError: string
  isLoggingOut: boolean
  logoutError: string
  retryAuth: () => Promise<void>
  login: (username: string, password: string) => Promise<void>
  loginWithAccessCode: (accessCode: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()

  const {
    data: entrypointData,
    isLoading: isEntrypointLoading,
    error: entrypointError,
    refetch: refetchEntrypoint,
  } = useQuery({
    queryKey: ["auth", "entrypoint"],
    queryFn: api.auth.entrypoint,
    retry: false,
    staleTime: Infinity,
  })

  const {
    data: user,
    isLoading,
    error: userError,
    refetch,
  } = useQuery({
    queryKey: ["auth", "me"],
    queryFn: api.auth.me,
    retry: false,
    staleTime: Infinity,
  })

  const rawEntrypoint = entrypointData?.entrypoint
  const entrypoint: ConsoleEntrypoint = rawEntrypoint === "public" || rawEntrypoint === "admin"
    ? rawEntrypoint
    : "combined"
  const userErrorStatus = Number((userError as { status?: unknown } | null)?.status)
  const authError = entrypointError || (userError && userErrorStatus !== 401)
    ? "无法连接认证服务，请检查网络后重试。"
    : ""

  const refetchAuthenticatedUser = async () => {
    const result = await refetch({ throwOnError: true })
    if (!result.data?.user?.username) {
      throw new Error("登录成功，但未能确认用户身份")
    }
  }

  const loginMutation = useMutation({
    mutationFn: api.auth.login,
    onSuccess: refetchAuthenticatedUser,
  })

  const accessLoginMutation = useMutation({
    mutationFn: api.auth.redeemAccessCode,
    onSuccess: refetchAuthenticatedUser,
  })

  const logoutMutation = useMutation({
    mutationFn: api.auth.logout,
    onSuccess: () => {
      const currentEntrypoint = queryClient.getQueryData(["auth", "entrypoint"])
      queryClient.clear()
      if (currentEntrypoint) {
        queryClient.setQueryData(["auth", "entrypoint"], currentEntrypoint)
      }
      queryClient.setQueryData(["auth", "me"], { authenticated: false, user: null })
    },
  })

  const value: AuthContextValue = {
    user: user?.user || null,
    entrypoint,
    authMode: entrypointData?.authMode === "legacy" ? "legacy" : "account_invite",
    isLoading: isLoading || isEntrypointLoading,
    isAuthenticated: !!user?.user,
    authError,
    isLoggingOut: logoutMutation.isPending,
    logoutError: logoutMutation.error instanceof Error ? logoutMutation.error.message : "",
    retryAuth: async () => {
      await Promise.all([
        refetchEntrypoint({ throwOnError: false }),
        refetch({ throwOnError: false }),
      ])
    },
    login: async (username: string, password: string) => {
      await loginMutation.mutateAsync({ username, password })
    },
    loginWithAccessCode: async (accessCode: string) => {
      await accessLoginMutation.mutateAsync(accessCode)
    },
    logout: async () => {
      await logoutMutation.mutateAsync()
    },
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider")
  }
  return ctx
}
