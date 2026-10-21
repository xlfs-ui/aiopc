import { ref } from 'vue'

export type User = { id: string; username: string; display_name: string; role: 'resident' | 'admin'; created_at: string }
export const authUser = ref<User | null>(null)
export const authReady = ref(false)
export const authNotice = ref('')
let csrfToken = ''
const channel = typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel('community-auth')

export function acceptSession(result: { user: User; csrf_token: string }, notify = false) {
  authUser.value = result.user
  csrfToken = result.csrf_token
  authNotice.value = ''
  if (notify) channel?.postMessage({ type: 'login' })
}

export function clearSession(message = '', notify = true) {
  authUser.value = null
  csrfToken = ''
  authNotice.value = message
  if (notify) channel?.postMessage({ type: 'logout' })
}

export async function authRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  headers.set('Content-Type', 'application/json')
  if (!['GET', 'HEAD', 'OPTIONS'].includes((init?.method || 'GET').toUpperCase()) && csrfToken) headers.set('X-CSRF-Token', csrfToken)
  const response = await fetch(path, { ...init, headers, credentials: 'same-origin', signal: init?.signal || AbortSignal.timeout(60000) })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const detail = Array.isArray(body.detail) ? body.detail.map((item: { msg: string }) => item.msg).join('；') : body.detail
    if (response.status === 401 && path !== '/api/auth/login') clearSession(path === '/api/auth/me' ? '' : '登录已过期，请重新登录。')
    throw new Error(detail || `请求失败（${response.status}）`)
  }
  return response.json() as Promise<T>
}

export async function bootstrapAuth() {
  try { acceptSession(await authRequest('/api/auth/me')) }
  catch { /* The login form handles an expired or absent session. */ }
  finally { authReady.value = true }
}

export async function logout() {
  await authRequest('/api/auth/logout', { method: 'POST', body: '{}' })
  clearSession('已安全退出登录。')
}

if (channel) channel.onmessage = event => {
  if (event.data?.type === 'logout') clearSession('登录状态已改变，请重新登录。', false)
  else if (event.data?.type === 'login') { clearSession('', false); void bootstrapAuth() }
}
