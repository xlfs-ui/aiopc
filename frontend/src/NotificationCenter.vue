<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Bell, CheckCheck, RefreshCw, X, CalendarDays, ClipboardList, UserCheck } from 'lucide-vue-next'
import { authRequest, authUser } from './auth'
type Notice = { id: string; kind: string; title: string; body: string; resource_id: string; created_at: string; read_at: string }
const emit = defineEmits<{ ticket: [id: string]; activities: []; account: [] }>()
const open = ref(false), busy = ref(false), error = ref(''), items = ref<Notice[]>([]), unread = ref(0)
const panel = ref<HTMLElement | null>(null), trigger = ref<HTMLButtonElement | null>(null)
const unreadOnly = ref(false)
const visible = computed(() => items.value.filter(n => !unreadOnly.value || !n.read_at))
let serial = 0, timer: ReturnType<typeof setInterval> | undefined
async function refresh() {
  const owner = authUser.value?.id, request = ++serial
  if (!owner) return
  busy.value = true
  try {
    const result = await authRequest<{ items: Notice[]; unread: number }>(unreadOnly.value ? '/api/notifications?unread_only=true' : '/api/notifications')
    if (owner !== authUser.value?.id || request !== serial) return
    items.value = result.items; unread.value = result.unread; error.value = ''
  } catch (e) { if (owner === authUser.value?.id && request === serial) error.value = e instanceof Error ? e.message : '通知暂时不可用' }
  finally { if (request === serial) busy.value = false }
}
async function toggle() { open.value = !open.value; if (open.value) { void refresh(); await nextTick(); panel.value?.querySelector<HTMLButtonElement>('.notification-close')?.focus() } }
async function read(item?: Notice) {
  const owner = authUser.value?.id
  try {
    await authRequest(item ? `/api/notifications/${item.id}/read` : '/api/notifications/read-all', { method: 'POST', body: '{}' })
    if (owner !== authUser.value?.id) return false
    if (item) { if (!item.read_at) unread.value = Math.max(0, unread.value - 1); item.read_at = new Date().toISOString() }
    else { items.value.forEach(n => { n.read_at = new Date().toISOString() }); unread.value = 0 }
    return true
  } catch (e) { if (owner === authUser.value?.id) error.value = e instanceof Error ? e.message : '已读状态保存失败'; return false }
}
async function visit(item: Notice) {
  if (!await read(item)) return
  open.value = false
  if (item.kind === 'ticket') emit('ticket', item.resource_id)
  else if (item.kind.startsWith('activity')) emit('activities')
  else if (item.kind === 'account') emit('account')
}
function outside(event: PointerEvent) { if (event.target instanceof Node && !panel.value?.contains(event.target)) open.value = false }
function keyboard(event: KeyboardEvent) {
  if (!open.value) return
  if (event.key === 'Escape') { event.stopPropagation(); open.value = false; trigger.value?.focus() }
  if (event.key === 'Tab') {
    const controls = Array.from(panel.value?.querySelectorAll<HTMLElement>('button:not(:disabled),input') || []).filter(e => e.offsetParent !== null)
    const first = controls[0], last = controls[controls.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  }
}
function visibleRefresh() { if (document.visibilityState === 'visible') void refresh() }
watch(() => authUser.value?.id, () => { ++serial; open.value = false; items.value = []; unread.value = 0; error.value = ''; busy.value = false; if (authUser.value) void refresh() }, { immediate: true })
watch(unreadOnly, () => { void refresh() })
onMounted(() => { document.addEventListener('pointerdown', outside); document.addEventListener('keydown', keyboard, true); document.addEventListener('visibilitychange', visibleRefresh); timer = setInterval(visibleRefresh, 60000) })
onUnmounted(() => { ++serial; clearInterval(timer); document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', keyboard, true); document.removeEventListener('visibilitychange', visibleRefresh) })
defineExpose({ refresh })
</script>
<template>
  <div ref="panel" class="notification-center">
    <button ref="trigger" class="icon-button notification-button" :aria-label="`我的通知${unread ? `，${unread}条未读` : '，暂无未读'}`" :aria-expanded="open" aria-controls="account-notifications" @click="toggle"><Bell :size="19" /><span v-if="unread" class="notification-count">{{ unread > 99 ? '99+' : unread }}</span></button>
    <section v-if="open" id="account-notifications" class="notification-panel" role="dialog" aria-label="我的账户通知">
      <header><div><h2>我的通知 <small>{{ unread }} 条未读</small></h2><p>仅展示 {{ authUser?.display_name }} 的服务动态</p></div><button class="icon-button notification-close" aria-label="关闭通知" @click="open = false"><X :size="18" /></button></header>
      <div class="notification-tools"><label><input v-model="unreadOnly" type="checkbox" />只看未读</label><button class="text-link" :disabled="!unread" @click="read()"><CheckCheck :size="15" />全部已读</button><button class="icon-button" :disabled="busy" aria-label="刷新通知" @click="refresh"><RefreshCw :size="15" /></button></div>
      <p v-if="error" class="workflow-error" role="alert">{{ error }}</p>
      <p v-if="busy && !items.length" class="workflow-empty">正在读取个人通知…</p>
      <div class="notification-items"><button v-for="item in visible" :key="item.id" class="notification-item" :class="{ unread: !item.read_at }" @click="visit(item)"><component :is="item.kind === 'ticket' ? ClipboardList : item.kind.startsWith('activity') ? CalendarDays : UserCheck" :size="20" /><span><strong>{{ item.title }}</strong><span>{{ item.body }}</span><small>{{ new Date(item.created_at).toLocaleString('zh-CN') }} · {{ item.read_at ? '已读' : '未读' }}</small></span><i v-if="!item.read_at" aria-label="未读"></i></button></div>
      <p v-if="!busy && !visible.length" class="workflow-empty">{{ unreadOnly ? '暂时没有未读通知' : '暂无服务动态，提交工单或报名活动后会在这里显示' }}</p>
      <footer>工单进度、本人任务与已报名活动提醒 · 可见页面每分钟更新</footer>
    </section>
  </div>
</template>
