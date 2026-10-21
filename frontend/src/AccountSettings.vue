<script setup lang="ts">
import { ref } from 'vue'
import { LockKeyhole, LogOut, ShieldCheck, X } from 'lucide-vue-next'
import { authUser, authRequest, clearSession, logout } from './auth'
defineEmits<{ close: [] }>()
const busy = ref(false), error = ref('')
const form = ref({ current_password: '', new_password: '', password_confirm: '' })
async function changePassword() {
  if (busy.value) return
  if (form.value.new_password !== form.value.password_confirm) { error.value = '两次输入的密码不一致'; return }
  busy.value = true; error.value = ''
  try { await authRequest('/api/auth/password', { method: 'POST', body: JSON.stringify(form.value) }); clearSession('密码已修改，所有会话已退出，请重新登录。') }
  catch (err) { error.value = err instanceof Error ? err.message : '修改失败' }
  finally { busy.value = false }
}
async function signOut() {
  if (busy.value) return
  busy.value = true
  try { await logout() } catch (err) { error.value = err instanceof Error ? err.message : '退出失败' }
  finally { busy.value = false }
}
</script>
<template>
  <div class="modal-backdrop" @click.self="$emit('close')"><section class="ticket-modal account-modal" role="dialog" aria-modal="true" aria-label="账号与安全"><div class="modal-header"><div><span class="modal-kicker">ACCOUNT & SECURITY</span><h2>账号与安全</h2></div><button class="icon-button" aria-label="关闭账号设置" @click="$emit('close')"><X :size="18" /></button></div><div class="account-summary"><ShieldCheck :size="22" /><div><strong>{{ authUser?.display_name }}</strong><span>{{ authUser?.username }} · {{ authUser?.role === 'admin' ? '社区管理员' : '居民账号' }}</span></div></div><div v-if="error" class="auth-error" role="alert">{{ error }}</div><form @submit.prevent="changePassword"><h3><LockKeyhole :size="15" />修改密码</h3><label>当前密码<input v-model="form.current_password" type="password" autocomplete="current-password" required maxlength="128" /></label><label>新密码<input v-model="form.new_password" type="password" autocomplete="new-password" required minlength="12" maxlength="128" placeholder="12–128位，不包含账号" /></label><label>确认新密码<input v-model="form.password_confirm" type="password" autocomplete="new-password" required minlength="12" maxlength="128" /></label><p>修改后所有已登录设备都需要重新登录。</p><button class="button button-primary" :disabled="busy">{{ busy ? '处理中…' : '保存新密码' }}</button></form><button class="account-logout" :disabled="busy" @click="signOut"><LogOut :size="16" />安全退出登录</button></section></div>
</template>
