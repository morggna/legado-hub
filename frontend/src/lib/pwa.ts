export interface InstallPromptEvent extends Event {
  prompt(): Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

let pendingPrompt: InstallPromptEvent | null = null
export const getInstallPrompt = () => pendingPrompt
export function clearInstallPrompt() { pendingPrompt = null }
export function isStandalone() {
  return window.matchMedia?.('(display-mode: standalone)').matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
}
export function isAppleMobile() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}

export function initializePwa() {
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault()
    pendingPrompt = event as InstallPromptEvent
    window.dispatchEvent(new Event('legado-install-ready'))
  })
  window.addEventListener('appinstalled', clearInstallPrompt)
  if (import.meta.env.PROD && 'serviceWorker' in navigator) {
    void navigator.serviceWorker.register('/app-worker', { scope: '/', updateViaCache: 'none' })
      .catch(error => console.warn('Application worker registration failed', error))
  }
}
