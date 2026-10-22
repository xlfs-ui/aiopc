<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowRight, BookOpen, Building2, Check, Eye, EyeOff, LockKeyhole, RefreshCw, ShieldCheck, Sparkles } from 'lucide-vue-next'
import { acceptSession, authNotice, authRequest, type User } from './auth'
const page = ref<'login' | 'register'>('login')
const busy = ref(false), captchaBusy = ref(false), reveal = ref(false)
const error = ref('')
const form = ref({ username: '', display_name: '', password: '', password_confirm: '', captcha_code: '' })
const captcha = ref({ id: '', image: '' })
let captchaSequence = 0
const passwordReady = computed(() => form.value.password.length >= 12 && form.value.password.length <= 128)

async function refreshCaptcha() {
  const sequence = ++captchaSequence
  captchaBusy.value = true
  form.value.captcha_code = ''
  try {
    const value = await authRequest<{ id: string; image: string }>(`/api/auth/captcha?purpose=${page.value}`)
    if (sequence === captchaSequence) captcha.value = value
  } catch (err) { if (sequence === captchaSequence) error.value = err instanceof Error ? err.message : '验证码加载失败，请重试' }
  finally { if (sequence === captchaSequence) captchaBusy.value = false }
}
watch(page, () => { error.value = ''; form.value.password = ''; form.value.password_confirm = ''; reveal.value = false; void refreshCaptcha() })
async function submit() {
  if (busy.value || captchaBusy.value) return
  error.value = ''
  if (page.value === 'register' && form.value.password !== form.value.password_confirm) { error.value = '两次输入的密码不一致'; return }
  if (!captcha.value.id) { error.value = '请先刷新验证码'; return }
  busy.value = true
  try {
    const payload = { username: form.value.username, password: form.value.password, captcha_id: captcha.value.id, captcha_code: form.value.captcha_code, ...(page.value === 'register' ? { display_name: form.value.display_name, password_confirm: form.value.password_confirm } : {}) }
    const result = await authRequest<{ user: User; csrf_token: string }>(`/api/auth/${page.value}`, { method: 'POST', body: JSON.stringify(payload) })
    form.value.password = ''; form.value.password_confirm = ''
    acceptSession(result, true)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '连接失败，请稍后重试'
    await refreshCaptcha()
  } finally { busy.value = false }
}
onMounted(refreshCaptcha)
</script>

<template>
  <main class="auth-screen">
    <section class="auth-story"><div class="auth-brand"><Building2 :size="27" /><div><strong>邻里智服</strong><span>COMMUNITY CARE</span></div></div><div class="auth-story-copy"><span class="hero-kicker"><Sparkles :size="14" />每一件小事，都值得被认真对待</span><h1>让社区服务，<br />离你更近一点。</h1><p>找资料、查流程、提交诉求。<br />从你的专属社区账号开始。</p><div class="auth-benefits"><span><BookOpen :size="17" />社区政策与办事指引</span><span><ShieldCheck :size="17" />个人工单与报名记录</span><span><Check :size="17" />服务进度随时可查</span></div></div><footer>有温度的服务 · 有回应的社区</footer><div class="auth-orbit"></div></section>
    <section class="auth-form-side"><div class="auth-form-box"><div class="auth-tabs"><button :class="{ selected: page === 'login' }" :disabled="busy" @click="page = 'login'">登录</button><button :class="{ selected: page === 'register' }" :disabled="busy" @click="page = 'register'">创建账号</button></div><span class="auth-eyebrow">WELCOME TO YOUR COMMUNITY</span><h2>{{ page === 'login' ? '欢迎回来' : '认识一下，新邻居' }}</h2><p class="auth-subtitle">{{ page === 'login' ? '登录后继续查看你的社区服务。' : '创建居民账号，开始使用社区服务。' }}</p><div v-if="authNotice" class="auth-notice" role="status">{{ authNotice }}</div><div v-if="error" class="auth-error" role="alert">{{ error }}</div>
      <form @submit.prevent="submit">
        <label>账号<input v-model="form.username" autocomplete="username" required minlength="3" maxlength="32" pattern="[a-zA-Z][a-zA-Z0-9_]{2,31}" placeholder="例如：lin_xiao" aria-describedby="username-format-hint" /></label><p id="username-format-hint" class="username-format-hint">3–32 位字母、数字或下划线，须以字母开头。</p>
        <label v-if="page === 'register'">你的称呼<input v-model="form.display_name" autocomplete="nickname" required maxlength="30" placeholder="例如：小林（称呼不作为身份凭证）" /></label>
        <label>密码<div class="password-input"><input v-model="form.password" :type="reveal ? 'text' : 'password'" :autocomplete="page === 'login' ? 'current-password' : 'new-password'" required :minlength="page === 'register' ? 12 : 1" maxlength="128" :placeholder="page === 'login' ? '输入你的密码' : '使用12–128位长密码'" :aria-label="page === 'login' ? '登录密码' : '注册密码'" /><button type="button" :aria-label="reveal ? '隐藏密码' : '显示密码'" @click="reveal = !reveal"><EyeOff v-if="reveal" :size="16" /><Eye v-else :size="16" /></button></div></label>
        <p v-if="page === 'register'" class="password-hint" :class="{ ready: passwordReady }"><LockKeyhole :size="12" />12–128个字符，建议多个词组成，不含账号</p>
        <label v-if="page === 'register'">确认密码<input v-model="form.password_confirm" type="password" autocomplete="new-password" required minlength="12" maxlength="128" placeholder="再次输入密码" /></label>
        <label>图片验证码<div class="captcha-row"><input v-model="form.captcha_code" required maxlength="5" autocomplete="off" placeholder="输入图片中的5位字符" aria-label="图片验证码" /><button type="button" class="captcha-image" :disabled="captchaBusy" aria-label="刷新图片验证码" @click="refreshCaptcha"><img v-if="captcha.image && !captchaBusy" :src="captcha.image" alt="验证码，点击可刷新" /><RefreshCw v-else :size="19" /></button></div></label><div class="captcha-hint">不区分大小写 · 3分钟有效 <button type="button" :disabled="captchaBusy" @click="refreshCaptcha">换一张</button></div>
        <button class="auth-submit" :disabled="busy || captchaBusy">{{ busy ? '正在验证…' : page === 'login' ? '登录社区' : '创建居民账号' }}<ArrowRight :size="17" /></button>
      </form><p class="auth-footnote"><ShieldCheck :size="14" />个人记录仅本人及授权工作人员可访问</p><p v-if="page === 'login'" class="auth-recovery">忘记密码？请联系社区管理员核实身份并重置。</p></div></section>
  </main>
</template>
