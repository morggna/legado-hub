export async function accountRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, { credentials: "same-origin", ...init, headers: { "Content-Type": "application/json", ...init.headers } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(typeof body.detail === "string" ? body.detail : `请求失败 (${response.status})`)
  }
  return response.json() as Promise<T>
}
export interface Invitation { inviteId: string; label: string; maxUses: number; usedCount: number; expiresAt: number; revoked: boolean }
