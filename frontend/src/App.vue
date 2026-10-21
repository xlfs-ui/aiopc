<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import ResourceCards from './ResourceCards.vue'
import AuthPanel from './AuthPanel.vue'
import AccountSettings from './AccountSettings.vue'
import KnowledgeManager from './KnowledgeManager.vue'
import KnowledgeDocument from './KnowledgeDocument.vue'
import { authUser, authReady, authRequest, bootstrapAuth, clearSession } from './auth'
import type { Resource } from './types'
import {
  Activity, ArrowDownRight, ArrowRight, ArrowUpRight, Bell, BookOpen, Building2, CalendarDays,
  Check, CheckCheck, ChevronDown, CircleHelp, ClipboardList, Clock3, FileText, HeartPulse,
  Home, Inbox, MapPin, MessageCircle, Pencil, Plus, Search, Send, ShieldCheck, Sparkles, Ticket,
  Users, Wrench, X,
} from 'lucide-vue-next'

type TicketStatus = '待受理' | '处理中' | '待确认' | '已完成'
type TicketItem = { id: string; resident: string; phone: string; location: string; category: string; description: string; status: TicketStatus; assignee: string; created_at: string; updated_at: string; priority?: string }
type Policy = { id: string; title: string; category: string; updated_at: string; summary: string; steps: string[]; source: string; phone: string }
type ActivityItem = { id: string; title: string; category: string; date: string; time: string; location: string; capacity: number; registered: number; audience: string; description: string; tag: string; is_registered?: boolean }
type TicketDraft = { location: string; category: string; description: string; resident: string }
type ChatMessage = { role: 'assistant' | 'user'; text: string; sources?: { title: string; updated_at: string }[]; resources?: Resource[]; trace?: string[]; draft?: TicketDraft; notice?: string }
type TicketDetail = TicketItem & { events: { action: string; actor: string; created_at: string }[] }

const isAdmin = computed(() => authUser.value?.role === 'admin')
const accountOpen = ref(false)
const ticketRequestKey = ref(crypto.randomUUID())
const mode = ref<'resident' | 'console'>('resident')
const residentPage = ref<'home' | 'tickets' | 'policies' | 'activities'>('home')
const consolePage = ref<'overview' | 'tickets' | 'policies' | 'activities' | 'knowledge'>('overview')
const tickets = ref<TicketItem[]>([])
const policies = ref<Policy[]>([])
const activities = ref<ActivityItem[]>([])
const overview = ref({ open_tickets: 0, today_new: 0, avg_response: '—', resolution_rate: 0, ticket_trend: [42, 58, 46, 73, 60, 85, 68], category_stats: [] as { name: string; value: number }[] })
const loading = ref(false)
const errorMessage = ref('')
const search = ref('')
const ticketFilter = ref<'全部' | TicketStatus>('全部')
const showTicketModal = ref(false)
const showPolicyModal = ref(false)
const showActivityModal = ref(false)
const ticketSaving = ref(false)
const savingContent = ref(false)
const newTicket = ref({ location: '', category: '公共设施', description: '', phone: '', priority: '普通' as '普通' | '较急' })
const policyDraft = ref({ id: '', title: '', category: '便民服务', summary: '', steps: '', source: '', phone: '0571-12345', keywords: '' })
const activityDraft = ref({ id: '', title: '', category: '便民活动', date: '2026-11-01', time: '09:00–10:00', location: '云水社区党群服务中心', capacity: 30, audience: '全体居民', description: '', tag: '开放报名' })
const activePolicy = ref<Policy | null>(null)
const chatInput = ref('')
const chatBusy = ref(false)
const chatThreadId = ref<string>(crypto.randomUUID())
const chatMessages = ref<ChatMessage[]>([
  { role: 'assistant', text: '你好，我是邻里智服助手。\n你可以问我社区政策、提交报修，或者看看最近有什么活动。' },
])
const chatScroller = ref<HTMLElement | null>(null)
const discoveryOpen = ref(false)
const discoveryInput = ref<HTMLInputElement | null>(null)
const discoveryQuery = ref('')
const discoveryResults = ref<Resource[]>([])
const discoveryBusy = ref(false)
const discoveryError = ref('')
const activeTicket = ref<TicketDetail | null>(null)
const activeDocument = ref<{ id: string; chunkId?: string } | null>(null)
const anyDialogOpen = computed(() => accountOpen.value || discoveryOpen.value || !!activeDocument.value || !!activeTicket.value || !!activePolicy.value || showTicketModal.value || showPolicyModal.value || showActivityModal.value)
let previousFocus: HTMLElement | null = null
let originalOverflow = ''
let hadDialog = false
const agentMode = ref('checking')
const calendarLabel = new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }).format(new Date())
let searchTimer: ReturnType<typeof setTimeout> | undefined
let discoveryController: AbortController | undefined
const welcomeMessage: ChatMessage = { role: 'assistant', text: '你好，我是邻里服务助手。\n告诉我你想办什么，我可以检索资料、整理办理步骤，帮你找到对应服务入口。试试“居住证需要什么材料”或“我要报修”。' }

const residentNav = [
  { id: 'home', label: '智能服务', icon: Sparkles },
  { id: 'tickets', label: '我的工单', icon: ClipboardList },
  { id: 'policies', label: '政策查询', icon: BookOpen },
  { id: 'activities', label: '社区活动', icon: CalendarDays },
] as const
const consoleNav = [
  { id: 'overview', label: '工作概览', icon: Home },
  { id: 'tickets', label: '工单处理', icon: ClipboardList },
  { id: 'policies', label: '政策知识库', icon: BookOpen },
  { id: 'knowledge', label: '文档知识库', icon: FileText },
  { id: 'activities', label: '活动管理', icon: CalendarDays },
] as const

const pageTitle = computed(() => mode.value === 'resident'
  ? ({ home: '智能服务', tickets: '我的工单', policies: '政策查询', activities: '社区活动' }[residentPage.value])
  : ({ overview: '工作概览', tickets: '工单处理', policies: '政策知识库', activities: '活动管理', knowledge: '文档知识库' }[consolePage.value]))
const filteredTickets = computed(() => {
  const q = search.value.trim().toLowerCase()
  return tickets.value.filter((t) => (ticketFilter.value === '全部' || t.status === ticketFilter.value)
    && (!q || `${t.id} ${t.resident} ${t.location} ${t.category} ${t.description}`.toLowerCase().includes(q)))
})
const barMax = computed(() => Math.max(...overview.value.ticket_trend, 1))
function statusClass(status: TicketStatus) { return ({ '待受理': 'status-waiting', '处理中': 'status-working', '待确认': 'status-confirm', '已完成': 'status-done' } as Record<TicketStatus, string>)[status] }
function statusProgress(status: TicketStatus) { return ({ '待受理': 18, '处理中': 66, '待确认': 82, '已完成': 100 } as Record<TicketStatus, number>)[status] }

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  return authRequest<T>(path, init)
}

async function refreshData() {
  if (!authUser.value) return
  const owner = authUser.value.id
  const requestedMode = mode.value
  loading.value = true
  errorMessage.value = ''
  try {
    const [ticketData, policyData, activityData, overviewData] = await Promise.all([
      api<TicketItem[]>(mode.value === 'resident' ? '/api/tickets?mine=true' : '/api/tickets'), api<Policy[]>('/api/policies'), api<ActivityItem[]>('/api/activities'), isAdmin.value && mode.value === 'console' ? api<typeof overview.value>('/api/overview') : Promise.resolve(overview.value),
    ])
    if (authUser.value?.id !== owner || mode.value !== requestedMode) return
    tickets.value = ticketData
    policies.value = policyData
    activities.value = activityData
    overview.value = overviewData
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '服务暂时不可用，请确认后端已启动。'
  } finally {
    loading.value = false
  }
}

function goResident(page: typeof residentPage.value) {
  const changedMode = mode.value !== 'resident'
  residentPage.value = page; mode.value = 'resident'; search.value = ''
  if (changedMode) void refreshData()
}
function goConsole(page: typeof consolePage.value) {
  if (!isAdmin.value) return
  const changedMode = mode.value !== 'console'
  consolePage.value = page; mode.value = 'console'; search.value = ''
  if (changedMode) void refreshData()
}
function setMode(next: 'resident' | 'console') { if (next === 'console' && !isAdmin.value) return; mode.value = next; search.value = ''; void refreshData() }

async function sendChat(text = chatInput.value) {
  const message = text.trim()
  if (!message || chatBusy.value || !authUser.value) return
  const owner = authUser.value.id
  chatMessages.value.push({ role: 'user', text: message })
  chatInput.value = ''
  chatBusy.value = true
  await scrollChat()
  try {
    const result = await api<{ reply: string; intent: string } & Omit<ChatMessage, 'role' | 'text'>>('/api/chat', { method: 'POST', body: JSON.stringify({ message, thread_id: chatThreadId.value }) })
    if (authUser.value?.id !== owner) return
    chatMessages.value.push({ ...result, role: 'assistant', text: result.reply })
    if (result.intent === 'ticket_created' || result.intent === 'activity_registration') await refreshData()
  } catch (error) {
    if (authUser.value?.id !== owner) return
    chatMessages.value.push({ role: 'assistant', text: error instanceof Error ? error.message : '暂时无法连接服务，请稍后再试。' })
  } finally {
    chatBusy.value = false
    await scrollChat()
  }
}

function startNewConversation() {
  if (chatBusy.value) return
  chatThreadId.value = crypto.randomUUID()
  chatMessages.value = [{ ...welcomeMessage }]
}

function openDiscovery(query = '') {
  const unchanged = discoveryQuery.value === query
  discoveryQuery.value = query
  discoveryOpen.value = true
  if (unchanged) void searchDiscovery()
  void nextTick(() => discoveryInput.value?.focus())
}

async function searchDiscovery() {
  clearTimeout(searchTimer)
  if (!authUser.value) return
  const owner = authUser.value.id
  discoveryController?.abort()
  const controller = new AbortController()
  discoveryController = controller
  discoveryBusy.value = true
  discoveryError.value = ''
  try {
    const result = await api<{ results: Resource[] }>(`/api/search?q=${encodeURIComponent(discoveryQuery.value)}`, { signal: controller.signal })
    if (!controller.signal.aborted && authUser.value?.id === owner) discoveryResults.value = result.results
  } catch (error) {
    if (!controller.signal.aborted) discoveryError.value = error instanceof Error ? error.message : '检索失败，请稍后重试'
  } finally {
    if (!controller.signal.aborted) discoveryBusy.value = false
  }
}

watch(discoveryQuery, () => {
  discoveryController?.abort()
  discoveryResults.value = []
  discoveryBusy.value = true
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { if (discoveryOpen.value) void searchDiscovery() }, 280)
})

async function showTicketDetail(ticketId: string) {
  const owner = authUser.value?.id
  try { const result = await api<TicketDetail>(`/api/tickets/${ticketId}`); if (owner === authUser.value?.id) activeTicket.value = result }
  catch (error) { errorMessage.value = error instanceof Error ? error.message : '无法读取工单' }
}

function openDraft(draft: TicketDraft) {
  newTicket.value = { ...newTicket.value, location: draft.location, category: draft.category, description: draft.description }
  showTicketModal.value = true
}

function openResource(resource: Resource) {
  discoveryOpen.value = false
  const action = resource.action
  if (action.type === 'view_policy') {
    activePolicy.value = policies.value.find(p => p.id === action.resource_id) || null
    if (!activePolicy.value) goResident('policies')
  } else if (action.type === 'view_document' && action.resource_id) {
    activeDocument.value = { id: action.resource_id, chunkId: resource.chunk_id }
  } else if (action.type === 'view_ticket' && action.resource_id) {
    void showTicketDetail(action.resource_id)
  } else if (action.type === 'create_ticket') {
    const lastUser = [...chatMessages.value].reverse().find(m => m.role === 'user')?.text || ''
    const description = /报修|漏水|坏了|维修/.test(lastUser) ? lastUser : ''
    const location = description.match(/[一二三四五六七八九十\d]+\s*(?:幢|栋|号楼)(?:\s*[一二三四五六七八九十\d]+\s*单元)?(?:\s*[一二三四五六七八九十\d]+\s*楼)?/)?.[0] || ''
    openDraft({ resident: authUser.value?.display_name || '', location, description, category: '公共设施' })
  } else if (action.type === 'open_tickets') goResident('tickets')
  else if (action.type === 'open_policies') goResident('policies')
  else if (action.type === 'open_activities') goResident('activities')
}

function handleShortcut(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openDiscovery() }
  if (event.key === 'Escape') {
    if (activeDocument.value) { activeDocument.value = null; return }
    if (accountOpen.value) { accountOpen.value = false; return }
    if (discoveryOpen.value) discoveryOpen.value = false
    else if (showTicketModal.value) showTicketModal.value = false
    else if (showPolicyModal.value) showPolicyModal.value = false
    else if (showActivityModal.value) showActivityModal.value = false
    else if (activeTicket.value) activeTicket.value = null
    else activePolicy.value = null
  }
  if (event.key === 'Tab' && anyDialogOpen.value) {
    const dialogs = document.querySelectorAll<HTMLElement>('.modal-backdrop')
    const dialog = discoveryOpen.value ? document.querySelector<HTMLElement>('.discovery-modal') : dialogs[dialogs.length - 1]
    const controls = Array.from(dialog?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select,textarea,summary,[tabindex="0"]') || []).filter(el => el.offsetParent !== null)
    const first = controls[0], last = controls[controls.length - 1]
    if (event.shiftKey && (document.activeElement === first || !dialog?.contains(document.activeElement))) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && (document.activeElement === last || !dialog?.contains(document.activeElement))) { event.preventDefault(); first?.focus() }
  }
}

watch([accountOpen, discoveryOpen, activeTicket, activePolicy, showTicketModal, showPolicyModal, showActivityModal], async () => {
  if (anyDialogOpen.value) {
    if (!hadDialog) { previousFocus = document.activeElement as HTMLElement; originalOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden' }
    hadDialog = true
    await nextTick()
    const dialogs = document.querySelectorAll<HTMLElement>('.modal-backdrop')
    const dialog = discoveryOpen.value ? document.querySelector<HTMLElement>('.discovery-modal') : dialogs[dialogs.length - 1]
    if (discoveryOpen.value) discoveryInput.value?.focus()
    else dialog?.querySelector<HTMLElement>('input,button')?.focus()
  } else if (hadDialog) {
    document.body.style.overflow = originalOverflow
    previousFocus?.focus()
    hadDialog = false
  }
  if (!discoveryOpen.value) { discoveryController?.abort(); clearTimeout(searchTimer); discoveryBusy.value = false }
})

watch(chatThreadId, () => {
  try { if (authUser.value) sessionStorage.setItem('community-thread:' + authUser.value.id, chatThreadId.value) } catch { /* Storage can be disabled. */ }
})
watch(showTicketModal, open => { if (open) ticketRequestKey.value = crypto.randomUUID() })
watch(() => authUser.value?.id, async userId => {
  discoveryController?.abort()
  accountOpen.value = false; discoveryOpen.value = false; showTicketModal.value = false
  showPolicyModal.value = false; showActivityModal.value = false; activePolicy.value = null; activeTicket.value = null; activeDocument.value = null
  tickets.value = []; policies.value = []; activities.value = []; discoveryResults.value = []
  mode.value = 'resident'; residentPage.value = 'home'; ticketFilter.value = '全部'; search.value = ''
  newTicket.value = { location: '', category: '公共设施', description: '', phone: '', priority: '普通' }
  errorMessage.value = ''; chatInput.value = ''; chatBusy.value = false
  chatMessages.value = [{ ...welcomeMessage }]
  if (!userId) return
  let thread = ''
  try { thread = sessionStorage.getItem('community-thread:' + userId) || '' } catch { /* Storage can be disabled. */ }
  chatThreadId.value = /^[A-Za-z0-9_-]{1,80}$/.test(thread) ? thread : crypto.randomUUID()
  void refreshData()
  try {
    const history = await api<{ messages: ChatMessage[] }>(`/api/chat/history/${chatThreadId.value}`)
    if (authUser.value?.id === userId && history.messages.length) chatMessages.value = history.messages
  } catch { /* A new conversation remains usable. */ }
  void scrollChat()
})

async function scrollChat() {
  await nextTick()
  if (chatScroller.value) chatScroller.value.scrollTop = chatScroller.value.scrollHeight
}

function safeMessage(text: string) {
  return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>')
}

async function submitTicket() {
  if (ticketSaving.value) return
  ticketSaving.value = true
  const owner = authUser.value?.id
  errorMessage.value = ''
  try {
    const created = await api<TicketItem>('/api/tickets', { method: 'POST', headers: { 'Idempotency-Key': ticketRequestKey.value }, body: JSON.stringify(newTicket.value) })
    if (owner !== authUser.value?.id) return
    goResident('tickets')
    await refreshData()
    showTicketModal.value = false
    newTicket.value = { location: '', category: '公共设施', description: '', phone: '', priority: '普通' }
    chatMessages.value.push({ role: 'assistant', text: `工单 **${created.id}** 已提交，社区工作人员会尽快跟进。你可以在“我的工单”查看进度。` })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '提交失败，请重试。'
  } finally {
    ticketSaving.value = false
  }
}

function openPolicyEditor(policy?: Policy) {
  policyDraft.value = policy
    ? { id: policy.id, title: policy.title, category: policy.category, summary: policy.summary, steps: policy.steps.join('\n'), source: policy.source, phone: policy.phone, keywords: `${policy.title} ${policy.category}` }
    : { id: '', title: '', category: '便民服务', summary: '', steps: '', source: '', phone: '0571-12345', keywords: '' }
  showPolicyModal.value = true
}

async function submitPolicy() {
  savingContent.value = true
  try {
    const { id, ...draft } = policyDraft.value
    const body = { ...draft, steps: draft.steps.split('\n').map(s => s.trim()).filter(Boolean), keywords: draft.keywords.split(/[，,\s]+/).map(s => s.trim()).filter(Boolean) }
    await api(id ? `/api/policies/${id}` : '/api/policies', { method: id ? 'PUT' : 'POST', body: JSON.stringify(body) })
    showPolicyModal.value = false
    await refreshData()
    errorMessage.value = id ? '政策资料已更新' : '政策资料已添加'
    window.setTimeout(() => { errorMessage.value = '' }, 2400)
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '保存政策失败' }
  finally { savingContent.value = false }
}

async function submitActivity() {
  savingContent.value = true
  try {
    const { id, ...draft } = activityDraft.value
    await api(id ? `/api/activities/${id}` : '/api/activities', { method: id ? 'PUT' : 'POST', body: JSON.stringify(draft) })
    showActivityModal.value = false
    await refreshData()
    errorMessage.value = id ? '活动信息已更新' : '活动已发布，居民端现在可以报名'
    window.setTimeout(() => { errorMessage.value = '' }, 2400)
    if (!id) activityDraft.value = { id: '', title: '', category: '便民活动', date: '2026-11-01', time: '09:00–10:00', location: '云水社区党群服务中心', capacity: 30, audience: '全体居民', description: '', tag: '开放报名' }
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '发布活动失败' }
  finally { savingContent.value = false }
}

function openActivityEditor(activity?: ActivityItem) {
  activityDraft.value = activity
    ? { id: activity.id, title: activity.title, category: activity.category, date: activity.date, time: activity.time, location: activity.location, capacity: activity.capacity, audience: activity.audience, description: activity.description, tag: activity.tag }
    : { id: '', title: '', category: '便民活动', date: '2026-11-01', time: '09:00–10:00', location: '云水社区党群服务中心', capacity: 30, audience: '全体居民', description: '', tag: '开放报名' }
  showActivityModal.value = true
}

async function advanceTicket(ticket: TicketItem) {
  const update = ticket.status === '待受理'
    ? { status: '处理中', assignee: ticket.assignee === '待指派' ? '王师傅' : ticket.assignee }
    : ticket.status === '处理中' ? { status: '待确认' }
      : ticket.status === '待确认' ? { status: '已完成' } : null
  if (!update) return
  try {
    await api(`/api/tickets/${ticket.id}`, { method: 'PATCH', body: JSON.stringify(update) })
    await refreshData()
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '状态更新失败' }
}

async function registerActivity(activity: ActivityItem) {
  try {
    await api(`/api/activities/${activity.id}/register`, { method: 'POST', body: '{}' })
    await refreshData()
    errorMessage.value = '报名成功，请按活动时间前往现场。'
    window.setTimeout(() => { errorMessage.value = '' }, 2600)
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : '报名失败' }
}

function handlePageRestore(event: PageTransitionEvent) {
  if (event.persisted) { authReady.value = false; clearSession('', false); void bootstrapAuth() }
}
onMounted(() => {
  try { localStorage.removeItem('community-chat-v2') } catch { /* Clear legacy unscoped chat storage. */ }
  window.addEventListener('keydown', handleShortcut)
  window.addEventListener('pageshow', handlePageRestore)
  void bootstrapAuth()
  void api<{ mode: string }>('/api/health').then(h => { agentMode.value = h.mode }).catch(() => { agentMode.value = 'offline' })
})
onUnmounted(() => { window.removeEventListener('keydown', handleShortcut); window.removeEventListener('pageshow', handlePageRestore); clearTimeout(searchTimer); discoveryController?.abort(); if (hadDialog) document.body.style.overflow = originalOverflow })
</script>

<template>
  <div v-if="!authReady" class="auth-loading"><Building2 :size="30" /><span>正在验证登录状态…</span></div>
  <AuthPanel v-else-if="!authUser" />
  <div v-else class="app-shell">
    <aside class="sidebar">
      <div class="brand-lockup">
        <div class="brand-mark"><Building2 :size="21" :stroke-width="1.8" /></div>
        <div><div class="brand-name">邻里智服</div><div class="brand-caption">COMMUNITY CARE</div></div>
      </div>

      <div class="community-switch">
        <div class="community-icon"><MapPin :size="16" /></div>
        <div class="community-copy"><strong>云水社区</strong><span>杭州市 · 滨江区</span></div>
        <ChevronDown :size="15" class="muted" />
      </div>

      <div class="nav-label">居民服务</div>
      <nav class="side-nav">
        <button v-for="item in residentNav" :key="item.id" class="nav-item" :class="{ active: mode === 'resident' && residentPage === item.id }" @click="goResident(item.id)">
          <component :is="item.icon" :size="18" :stroke-width="1.8" /><span>{{ item.label }}</span>
          <span v-if="item.id === 'tickets'" class="nav-count">{{ tickets.filter(t => t.status !== '已完成').length }}</span>
        </button>
      </nav>

      <div v-if="isAdmin" class="nav-label work-label">社区工作台</div>
      <nav v-if="isAdmin" class="side-nav">
        <button v-for="item in consoleNav" :key="item.id" class="nav-item" :class="{ active: mode === 'console' && consolePage === item.id }" @click="goConsole(item.id)">
          <component :is="item.icon" :size="18" :stroke-width="1.8" /><span>{{ item.label }}</span>
        </button>
      </nav>

      <div class="sidebar-bottom">
        <div class="help-card"><div class="help-icon"><CircleHelp :size="17" /></div><div><strong>需要帮助？</strong><span>社区服务热线 0571-12345</span></div></div>
        <button class="profile-row" @click="accountOpen = true">
          <div class="avatar">{{ authUser.display_name.slice(0, 1) }}</div><div class="profile-copy"><strong>{{ authUser.display_name }}</strong><span>{{ isAdmin ? '社区管理员' : '居民账号' }}</span></div><ChevronDown :size="15" class="muted" />
        </button>
      </div>
    </aside>

    <main class="main-area">
      <header class="topbar">
        <div class="breadcrumb"><span>云水社区</span><span class="crumb-sep">/</span><strong>{{ pageTitle }}</strong></div>
        <div class="topbar-actions">
          <button class="global-search-trigger" @click="openDiscovery()" aria-label="检索社区服务"><Search :size="15" /><span>搜索服务与资料</span><kbd>Ctrl K</kbd></button>
          <div v-if="isAdmin" class="mode-switch" aria-label="切换使用角色">
            <button :class="{ selected: mode === 'resident' }" @click="setMode('resident')">居民端</button>
            <button :class="{ selected: mode === 'console' }" @click="setMode('console')">工作台</button>
          </div>
          <button class="icon-button notification-button" aria-label="查看我的服务动态" @click="openDiscovery('我的工单')"><Bell :size="18" /><i></i></button>
          <div class="top-date">{{ calendarLabel }}</div>
        </div>
      </header>

      <div v-if="errorMessage" class="toast" :class="{ 'toast-error': !errorMessage.includes('成功') }"><Check :size="15" />{{ errorMessage }}<button @click="errorMessage = ''"><X :size="14" /></button></div>

      <div class="page-content">
        <template v-if="mode === 'resident' && residentPage === 'home'">
          <section class="welcome-row">
            <div><div class="eyebrow"><span class="live-dot"></span>YOUR COMMUNITY, CONNECTED</div><h1>你好，{{ authUser.display_name }} <span class="wave">✳</span></h1><p>从一个问题出发，找到资料、办理流程和下一步。</p></div>
            <button class="button button-primary" @click="showTicketModal = true"><Plus :size="17" />提交报修</button>
          </section>
          <section class="discovery-hero">
            <div class="hero-orb orb-one"></div><div class="hero-orb orb-two"></div>
            <div class="hero-copy"><span class="hero-kicker"><Sparkles :size="14" />邻里服务导航</span><h2>你想办的事，<br />从这里开始。</h2><p>查政策、找流程、办报修、看活动。<br />把你的需求交给邻里助手。</p><button class="hero-search" @click="openDiscovery()"><Search :size="18" /><span>想办居住证？找活动？查一下报修进度…</span><ArrowRight :size="18" /></button><div class="hero-tags"><button v-for="q in ['居住证材料', '报修流程', '亲子活动']" :key="q" @click="openDiscovery(q)">{{ q }} <ArrowUpRight :size="11" /></button></div></div>
            <div class="hero-journey" aria-hidden="true"><div class="journey-node"><Search :size="19" /><span>说出需求</span><small>自然语言描述</small></div><i></i><div class="journey-node"><BookOpen :size="19" /><span>找到内容</span><small>资料 · 流程 · 来源</small></div><i></i><div class="journey-node"><CheckCheck :size="19" /><span>继续办理</span><small>服务入口一键直达</small></div></div>
          </section>
          <div class="resident-grid">
            <section class="chat-card panel">
              <div class="section-heading chat-heading"><div class="heading-icon assistant-icon"><Sparkles :size="17" /></div><div><h2>邻里服务助手</h2><p><span class="live-dot"></span>{{ agentMode === 'deepseek-langgraph' ? '智能服务 · 已连接' : agentMode === 'offline' ? '服务连接中断' : '社区资料与服务检索' }}</p></div><button class="quiet-button" :disabled="chatBusy" @click="startNewConversation"><Plus :size="16" />新对话</button></div>
              <div ref="chatScroller" class="chat-scroll">
                <div class="chat-date"><span></span>{{ calendarLabel }}<span></span></div>
                <div v-for="(message, idx) in chatMessages" :key="idx" class="chat-line" :class="message.role">
                  <div v-if="message.role === 'assistant'" class="chat-avatar"><Sparkles :size="15" /></div>
                  <div class="message-wrap"><div class="message-bubble" v-html="safeMessage(message.text)"></div>
                    <div v-if="message.trace?.length" class="retrieval-trace"><span v-for="step in message.trace" :key="step"><Check :size="10" />{{ step }}</span></div>
                    <p v-if="message.notice" class="result-notice">{{ message.notice }}</p>
                    <ResourceCards v-if="message.resources?.length" :items="message.resources.slice(0, 3)" @open="openResource" />
                    <button v-if="message.resources && message.resources.length > 3" class="more-results" @click="openDiscovery()">检索更多服务与内容 <ArrowRight :size="13" /></button>
                    <button v-if="message.draft" class="button button-primary draft-confirm" @click="openDraft(message.draft)"><ClipboardList :size="15" />核对并提交报修</button>
                    <div v-if="message.sources?.length" class="source-chips"><span v-for="source in message.sources" :key="source.title"><ShieldCheck :size="12" />{{ source.title }} · {{ source.updated_at }}</span></div>
                    <div class="message-time">{{ message.role === 'assistant' ? '邻里助手' : '刚刚' }} <CheckCheck v-if="message.role === 'user'" :size="13" /></div>
                  </div>
                  <div v-if="message.role === 'user'" class="user-chat-avatar">{{ authUser.display_name.slice(0, 1) }}</div>
                </div>
                <div v-if="chatBusy" class="chat-line assistant"><div class="chat-avatar working-avatar"><Sparkles :size="15" /></div><div class="agent-working"><div class="typing"><i></i><i></i><i></i></div><span>正在检索资料、匹配流程与服务入口…</span><div class="working-track"></div></div></div>
              </div>
              <div class="suggestion-row"><span>试试这样问</span><button @click="sendChat('居住证怎么办理？')">居住证怎么办理？</button><button @click="sendChat('查一下我的报修进度')">查报修进度</button><button @click="sendChat('最近有什么社区活动？')">最近的活动</button></div>
              <form class="chat-composer" @submit.prevent="sendChat()"><input v-model="chatInput" maxlength="1000" placeholder="描述你想办的事，查内容、找流程、进入服务…" aria-label="输入消息" /><button class="send-button" :disabled="!chatInput.trim() || chatBusy" aria-label="发送"><Send :size="17" /></button></form>
              <div class="chat-disclaimer"><ShieldCheck :size="13" />涉及个人情况的政策，请以主管部门最新答复为准</div>
            </section>

            <aside class="resident-rail">
              <section class="service-card panel"><div class="section-heading"><div><h2>快捷服务</h2><p>常用服务一键直达</p></div><button class="text-link" @click="goResident('tickets')">全部服务 <ArrowRight :size="14" /></button></div>
                <div class="service-grid">
                  <button @click="showTicketModal = true"><span class="service-icon mint"><Wrench :size="19" /></span><strong>报事报修</strong><small>问题随时报</small></button>
                  <button @click="goResident('policies')"><span class="service-icon lavender"><BookOpen :size="19" /></span><strong>政策查询</strong><small>办事有指引</small></button>
                  <button @click="goResident('activities')"><span class="service-icon peach"><CalendarDays :size="19" /></span><strong>社区活动</strong><small>报名看这里</small></button>
                  <button @click="goResident('tickets')"><span class="service-icon blue"><ClipboardList :size="19" /></span><strong>我的工单</strong><small>进度随时查</small></button>
                </div>
              </section>
              <section class="ticket-peek panel"><div class="section-heading"><div><h2>工单进度</h2><p>最近的服务记录</p></div><button class="round-arrow" @click="goResident('tickets')"><ArrowUpRight :size="16" /></button></div>
                <div v-if="tickets[0]" class="peek-ticket"><div class="peek-ticket-top"><span class="status-dot" :class="statusClass(tickets[0].status)"></span><strong>{{ tickets[0].category }}</strong><span :class="['status-pill', statusClass(tickets[0].status)]">{{ tickets[0].status }}</span></div><p>{{ tickets[0].description }}</p><div class="peek-meta"><span>{{ tickets[0].id }}</span><span>{{ tickets[0].updated_at }}</span></div></div>
                <div v-else class="empty-state">还没有工单记录</div>
                <button class="full-link" @click="goResident('tickets')">查看全部工单 <ArrowRight :size="14" /></button>
              </section>
              <section class="notice-card"><div class="notice-icon"><HeartPulse :size="17" /></div><div><div class="notice-title">本周六 · 银龄健康义诊</div><p>社区党群服务中心一楼 · 免费参加</p><button @click="goResident('activities')">查看活动详情 <ArrowRight :size="13" /></button></div></section>
            </aside>
          </div>
          <section class="bottom-info"><div class="bottom-info-item"><div class="small-icon"><ShieldCheck :size="16" /></div><div><strong>信息安全有保障</strong><span>你的个人信息仅用于社区服务</span></div></div><div class="bottom-divider"></div><div class="bottom-info-item"><div class="small-icon"><Clock3 :size="16" /></div><div><strong>服务时间</strong><span>线上服务全天开放 · 人工服务工作日 9:00–17:00</span></div></div><button class="bottom-more" @click="goResident('policies')">了解社区服务 <ArrowRight :size="14" /></button></section>
        </template>

        <template v-else-if="mode === 'resident' && residentPage === 'tickets'">
          <section class="page-intro"><div><div class="eyebrow">居民服务 · 进度透明</div><h1>我的工单</h1><p>查看你提交的社区诉求和处理进度</p></div><button class="button button-primary" @click="showTicketModal = true"><Plus :size="17" />提交新工单</button></section>
          <section class="panel list-panel"><div class="list-toolbar"><div class="filter-tabs"><button v-for="status in ['全部','待受理','处理中','待确认','已完成']" :key="status" :class="{ chosen: ticketFilter === status }" @click="ticketFilter = status as '全部' | TicketStatus">{{ status }}<span>{{ status === '全部' ? tickets.length : tickets.filter(t => t.status === status).length }}</span></button></div><label class="search-box"><Search :size="16" /><input v-model="search" placeholder="搜索工单" /></label></div>
            <div class="ticket-list"><article v-for="ticket in filteredTickets" :key="ticket.id" class="ticket-row"><div class="ticket-category-icon"><Wrench :size="18" /></div><div class="ticket-main"><div class="ticket-title-row"><strong>{{ ticket.category }}</strong><span :class="['status-pill', statusClass(ticket.status)]">{{ ticket.status }}</span><span v-if="ticket.priority === '较急'" class="priority-tag">较急</span></div><p>{{ ticket.description }}</p><div class="ticket-subline"><span><MapPin :size="13" />{{ ticket.location }}</span><span>{{ ticket.id }}</span><span>{{ ticket.created_at }}</span></div><div class="progress-track"><span :style="{ width: statusProgress(ticket.status) + '%' }"></span></div><div class="progress-label"><span>已提交</span><span>社区受理</span><span>处理中</span><span>已完成</span></div></div><div class="ticket-owner"><span>处理人员</span><strong>{{ ticket.assignee }}</strong><small>更新于 {{ ticket.updated_at }}</small></div><button class="round-arrow" aria-label="工单详情" @click="showTicketDetail(ticket.id)"><ArrowUpRight :size="16" /></button></article>
              <div v-if="!filteredTickets.length" class="empty-state">没有找到相关工单</div>
            </div>
          </section>
          <div class="page-footnote"><ShieldCheck :size="15" />如需补充信息或有紧急情况，请拨打社区服务热线 <strong>0571-12345</strong></div>
        </template>

        <template v-else-if="mode === 'resident' && residentPage === 'policies'">
          <section class="page-intro"><div><div class="eyebrow">本地政策 · 办事指南</div><h1>政策查询</h1><p>按需查找社区常见政策与办事指引</p></div><label class="search-box large-search"><Search :size="17" /><input v-model="search" placeholder="试试搜索“居住证”“养老补贴”…" /></label></section>
          <div class="policy-layout"><section class="policy-list"><button v-for="policy in policies.filter(p => !search || `${p.title}${p.category}${p.summary}`.includes(search))" :key="policy.id" class="policy-card panel" @click="activePolicy = policy"><div class="policy-topline"><span class="policy-category">{{ policy.category }}</span><span class="policy-updated">更新于 {{ policy.updated_at }}</span></div><h2>{{ policy.title }}<ArrowRight :size="17" /></h2><p>{{ policy.summary }}</p><div class="policy-source"><ShieldCheck :size="14" />{{ policy.source }}</div></button></section><aside class="policy-aside panel"><div class="policy-aside-icon"><CircleHelp :size="21" /></div><h3>没有找到想了解的政策？</h3><p>你可以通过邻里助手描述具体问题，我们会优先从本地政策资料中检索。</p><button class="button button-dark" @click="goResident('home')"><MessageCircle :size="16" />咨询邻里助手</button><div class="policy-hotline"><PhoneIcon />社区服务热线<strong>0571-12345</strong></div></aside></div>
        </template>

        <template v-else-if="mode === 'resident' && residentPage === 'activities'">
          <section class="page-intro"><div><div class="eyebrow">邻里相聚 · 一起参与</div><h1>社区活动</h1><p>发现身边的社区活动，线上报名更方便</p></div><div class="activity-count"><CalendarDays :size="17" /><strong>{{ activities.length }}</strong>场近期活动</div></section>
          <div class="activity-grid"><article v-for="(activity, index) in activities" :key="activity.id" class="activity-card panel"><div class="activity-art" :class="`art-${index + 1}`"><div class="art-orbit"></div><div class="art-date"><strong>{{ activity.date.slice(8) }}</strong><span>OCT</span></div><span class="art-label">{{ activity.category }}</span><component :is="index === 0 ? HeartPulse : index === 1 ? ShieldCheck : Users" class="art-icon" :size="50" :stroke-width="1.2" /></div><div class="activity-body"><div class="activity-meta"><span>{{ activity.tag }}</span><span>{{ activity.audience }}</span></div><h2>{{ activity.title }}</h2><p>{{ activity.description }}</p><div class="activity-detail"><span><Clock3 :size="14" />{{ activity.date }} · {{ activity.time }}</span><span><MapPin :size="14" />{{ activity.location }}</span></div><div class="activity-capacity"><span>报名进度</span><strong>{{ activity.registered }}<small> / {{ activity.capacity }} 人</small></strong><div class="capacity-track"><span :style="{ width: Math.min(100, activity.registered / activity.capacity * 100) + '%' }"></span></div></div><button class="button button-primary activity-register" :disabled="activity.is_registered || activity.registered >= activity.capacity" @click="registerActivity(activity)">{{ activity.is_registered ? '已报名' : activity.registered >= activity.capacity ? '名额已满' : '立即报名' }}<ArrowRight :size="16" /></button></div></article></div>
        </template>

        <template v-else-if="mode === 'console' && consolePage === 'overview'">
          <section class="page-intro console-intro"><div><div class="eyebrow"><span class="live-dot"></span>云水社区 · 今日服务</div><h1>社区工作概览</h1><p>把每一件居民诉求都跟进到底</p></div><div class="console-actions"><button class="button button-white" @click="refreshData"><Activity :size="16" />刷新数据</button><button class="button button-primary" @click="goConsole('tickets')"><Inbox :size="16" />处理工单</button></div></section>
          <div class="metric-grid"><article class="metric-card panel"><div class="metric-top"><span class="metric-icon metric-violet"><ClipboardList :size="18" /></span><span class="metric-caption">较昨日 <b>+2</b></span></div><div class="metric-label">待处理工单</div><div class="metric-value">{{ overview.open_tickets }}<small>件</small></div><div class="metric-foot">其中 <strong>{{ tickets.filter(t => t.status === '待受理').length }}</strong> 件待受理</div></article><article class="metric-card panel"><div class="metric-top"><span class="metric-icon metric-green"><ArrowDownRight :size="18" /></span><span class="metric-caption positive">较昨日 <b>-12%</b></span></div><div class="metric-label">今日新增诉求</div><div class="metric-value">{{ overview.today_new }}<small>件</small></div><div class="metric-foot">本周共 <strong>46</strong> 件居民反馈</div></article><article class="metric-card panel"><div class="metric-top"><span class="metric-icon metric-amber"><Clock3 :size="18" /></span><span class="metric-caption positive"><b>效率提升</b></span></div><div class="metric-label">平均响应时间</div><div class="metric-value">{{ overview.avg_response }}</div><div class="metric-foot">目标时间 <strong>30分钟</strong> 内</div></article><article class="metric-card panel"><div class="metric-top"><span class="metric-icon metric-blue"><CheckCheck :size="18" /></span><span class="metric-caption positive"><b>+4.2%</b> 环比</span></div><div class="metric-label">本月工单解决率</div><div class="metric-value">{{ overview.resolution_rate }}<small>%</small></div><div class="metric-foot">已完成 <strong>{{ tickets.filter(t => t.status === '已完成').length }}</strong> 件</div></article></div>
          <div class="dashboard-grid"><section class="panel chart-panel"><div class="section-heading"><div><h2>工单处理趋势</h2><p>近 7 天 · 居民服务请求</p></div><button class="select-button">最近 7 天 <ChevronDown :size="14" /></button></div><div class="chart-legend"><span><i class="legend-dot"></i>工单数量</span><span class="chart-total">本周 <strong>46</strong> 件</span></div><div class="bar-chart"><div v-for="(v, i) in overview.ticket_trend" :key="i" class="bar-column"><span class="bar-value">{{ v }}</span><div class="bar-track"><span :class="{ today: i === overview.ticket_trend.length - 1 }" :style="{ height: `${v / barMax * 100}%` }"></span></div><small>{{ ['周二','周三','周四','周五','周六','周日','今天'][i] }}</small></div></div></section>
            <section class="panel category-panel"><div class="section-heading"><div><h2>诉求类型分布</h2><p>本月工单分类统计</p></div><button class="round-arrow" @click="goConsole('tickets')"><ArrowUpRight :size="16" /></button></div><div class="category-visual"><div class="donut"><div><strong>100<span>%</span></strong><small>已分类</small></div></div><div class="category-legend"><div v-for="(item, i) in overview.category_stats" :key="item.name"><i :class="`cat-color-${i + 1}`"></i><span>{{ item.name }}</span><strong>{{ item.value }}%</strong></div></div></div></section>
          </div>
          <section class="panel recent-panel"><div class="section-heading"><div><h2>最新工单</h2><p>最近居民提交的服务请求</p></div><button class="text-link" @click="goConsole('tickets')">全部工单 <ArrowRight :size="14" /></button></div><TicketTable :items="tickets.slice(0, 4)" @advance="advanceTicket" /></section>
        </template>

        <template v-else-if="mode === 'console' && consolePage === 'tickets'">
          <section class="page-intro"><div><div class="eyebrow">社区工作台 · 服务闭环</div><h1>工单处理</h1><p>跟进居民诉求，及时更新处理状态</p></div><div class="intro-stats"><span><i class="mini-status waiting"></i>待受理 {{ tickets.filter(t => t.status === '待受理').length }}</span><span><i class="mini-status working"></i>处理中 {{ tickets.filter(t => t.status === '处理中').length }}</span></div></section>
          <section class="panel list-panel"><div class="list-toolbar"><div class="filter-tabs"><button v-for="status in ['全部','待受理','处理中','待确认','已完成']" :key="status" :class="{ chosen: ticketFilter === status }" @click="ticketFilter = status as '全部' | TicketStatus">{{ status }}</button></div><label class="search-box"><Search :size="16" /><input v-model="search" placeholder="搜索工单、地址或居民" /></label></div><TicketTable :items="filteredTickets" staff @advance="advanceTicket" /><div v-if="!filteredTickets.length" class="empty-state">没有找到相关工单</div></section>
        </template>

        <template v-else-if="mode === 'console' && consolePage === 'policies'">
          <section class="page-intro"><div><div class="eyebrow">内容运营 · 本地知识</div><h1>政策知识库</h1><p>居民问答引用的社区政策资料（演示数据）</p></div><div class="intro-actions"><label class="search-box"><Search :size="16" /><input v-model="search" placeholder="搜索政策" /></label><button class="button button-primary" @click="openPolicyEditor()"><Plus :size="16" />新增政策</button></div></section><div class="policy-admin-grid"><article v-for="policy in policies.filter(p => !search || `${p.title}${p.category}${p.summary}`.includes(search))" :key="policy.id" class="policy-admin-card panel"><div class="policy-topline"><span class="policy-category">{{ policy.category }}</span><span class="knowledge-ready"><Check :size="12" />已发布</span></div><h2>{{ policy.title }}</h2><p>{{ policy.summary }}</p><div class="admin-policy-foot"><span><FileText :size="14" />{{ policy.source }}</span><span>更新于 {{ policy.updated_at }}</span></div><div class="policy-card-actions"><button class="text-link" @click="activePolicy = policy">查看办事指引 <ArrowRight :size="14" /></button><button class="text-link" @click="openPolicyEditor(policy)">编辑资料 <ArrowRight :size="14" /></button></div></article></div>
        </template>

        <template v-else-if="mode === 'console' && consolePage === 'activities'">
          <section class="page-intro"><div><div class="eyebrow">社区运营 · 活动管理</div><h1>活动管理</h1><p>查看活动安排、报名进度和服务对象</p></div><button class="button button-primary" @click="openActivityEditor()"><Plus :size="17" />新建活动</button></section><section class="panel list-panel"><div class="section-heading list-heading"><div><h2>近期活动</h2><p>居民端可见的活动信息与报名人数</p></div><span class="active-label"><i></i>正在报名</span></div><div class="admin-activity-list"><article v-for="activity in activities" :key="activity.id" class="admin-activity-row"><div class="admin-date"><strong>{{ activity.date.slice(8) }}</strong><span>{{ activity.date.slice(5, 7) }}月</span></div><div class="admin-activity-main"><h3>{{ activity.title }} <span>{{ activity.category }}</span></h3><p><MapPin :size="13" />{{ activity.location }} <Clock3 :size="13" />{{ activity.time }}</p><small>{{ activity.audience }} · {{ activity.description }}</small></div><div class="signup-meter"><strong>{{ activity.registered }}<small> / {{ activity.capacity }}</small></strong><span>已报名</span><div class="capacity-track"><i :style="{ width: `${activity.registered / activity.capacity * 100}%` }"></i></div></div><button class="round-arrow" aria-label="编辑活动" title="编辑活动" @click="openActivityEditor(activity)"><Pencil :size="15" /></button></article></div></section>
        </template>

        <KnowledgeManager v-else-if="mode === 'console' && consolePage === 'knowledge' && isAdmin" :key="authUser.id" />

        <footer class="app-footer"><span>© 2026 邻里智服</span><span>让社区服务更近一步</span><span class="mock-badge"><i></i>演示业务 · 文档以审核发布为准</span></footer>
      </div>
    </main>

    <AccountSettings v-if="accountOpen" @close="accountOpen = false" />
    <KnowledgeDocument v-if="activeDocument" :key="`${authUser.id}:${activeDocument.id}`" :document-id="activeDocument.id" :chunk-id="activeDocument.chunkId" @close="activeDocument = null" />
    <div v-if="discoveryOpen" class="modal-backdrop discovery-backdrop" @click.self="discoveryOpen = false"><section class="discovery-modal" role="dialog" aria-modal="true" aria-label="社区服务与内容检索"><header><div><span class="hero-kicker"><Search :size="14" />COMMUNITY DISCOVERY</span><h2>找内容，也找到下一步</h2><p>同时检索政策、办理流程、社区活动与本人工单</p></div><button class="icon-button" aria-label="关闭检索" @click="discoveryOpen = false"><X :size="20" /></button></header><form class="discovery-search" @submit.prevent="searchDiscovery"><Search :size="20" /><input ref="discoveryInput" v-model="discoveryQuery" maxlength="1000" placeholder="例如：居住证需要什么材料？" aria-label="检索关键词" /><button class="button button-dark">检索</button></form><div class="discovery-suggestions"><button v-for="q in ['居住证', '养老补贴', '报修流程', '我的工单', '社区活动']" :key="q" @click="discoveryQuery = q">{{ q }}</button></div><div class="discovery-results" aria-live="polite"><div class="discovery-result-head"><strong>{{ discoveryQuery ? '相关内容与服务' : '常用内容与服务' }}</strong><span>{{ discoveryBusy ? '检索中…' : `${discoveryResults.length} 项结果` }}</span></div><div v-if="discoveryBusy" class="search-skeleton"><i v-for="n in 3" :key="n"></i></div><div v-else-if="discoveryError" class="empty-state">{{ discoveryError }}<button class="more-results" @click="searchDiscovery">重新检索</button></div><ResourceCards v-else-if="discoveryResults.length" :items="discoveryResults" @open="openResource" /><div v-else class="empty-state"><Search :size="30" /><h3>暂时没有匹配内容</h3><p>换个关键词试试，或描述具体的办理事项。</p></div></div><footer><ShieldCheck :size="13" />本地演示资料 · 办理条件请向对应服务窗口核实 <kbd>ESC 关闭</kbd></footer></section></div>

    <div v-if="activeTicket" class="modal-backdrop" @click.self="activeTicket = null"><article class="policy-modal ticket-detail-modal" role="dialog" aria-modal="true" aria-label="工单详情"><div class="modal-header"><div><span class="modal-kicker">服务记录 · {{ activeTicket.id }}</span><h2>{{ activeTicket.category }}</h2></div><button class="icon-button" aria-label="关闭工单详情" @click="activeTicket = null"><X :size="19" /></button></div><div class="ticket-detail-summary"><span :class="['status-pill', statusClass(activeTicket.status)]">{{ activeTicket.status }}</span><p>{{ activeTicket.description }}</p><span><MapPin :size="14" />{{ activeTicket.location }}</span><span><Users :size="14" />处理人：{{ activeTicket.assignee }}</span></div><h3>流转记录</h3><ol class="ticket-history"><li v-for="(event, i) in activeTicket.events" :key="i"><i></i><div><strong>{{ event.action }}</strong><span>{{ event.actor }} · {{ event.created_at.replace('T', ' ') }}</span></div></li></ol><button class="button button-primary modal-done" @click="activeTicket = null">完成查看 <Check :size="15" /></button></article></div>

    <div v-if="showTicketModal" class="modal-backdrop" @click.self="showTicketModal = false"><form class="ticket-modal" @submit.prevent="submitTicket"><div class="modal-header"><div><span class="modal-kicker">居民服务 · 核对并提交</span><h2>提交报事报修</h2></div><button type="button" class="icon-button" aria-label="关闭" @click="showTicketModal = false"><X :size="19" /></button></div><p class="modal-desc">核对位置与问题，点击提交后才会生成正式工单。</p><label>问题位置 <span>*</span><input v-model="newTicket.location" required minlength="2" maxlength="100" placeholder="例如：3幢2单元5楼" /></label><label>问题类型<select v-model="newTicket.category"><option>公共设施</option><option>公共照明</option><option>道路设施</option><option>给排水</option><option>环境卫生</option><option>噪音问题</option><option>其他诉求</option></select></label><label>问题描述 <span>*</span><textarea v-model="newTicket.description" required minlength="3" maxlength="500" rows="4" placeholder="请描述遇到的问题，便于工作人员处理"></textarea></label><div class="modal-row"><label>联系人<input :value="authUser.display_name" readonly aria-label="当前账号称呼" /></label><label>联系电话<input v-model="newTicket.phone" maxlength="30" placeholder="联系电话，可选填" /></label></div><label class="priority-toggle"><input v-model="newTicket.priority" type="checkbox" true-value="较急" false-value="普通" /><span class="fake-check"><Check :size="13" /></span>情况较急，需要优先处理</label><div class="modal-actions"><button type="button" class="button button-white" @click="showTicketModal = false">取消</button><button class="button button-primary" :disabled="ticketSaving"><Send :size="15" />{{ ticketSaving ? '提交中…' : '提交工单' }}</button></div></form></div>

    <div v-if="activePolicy" class="modal-backdrop" @click.self="activePolicy = null"><article class="policy-modal"><div class="modal-header"><div><span class="policy-category">{{ activePolicy.category }}</span><h2>{{ activePolicy.title }}</h2></div><button class="icon-button" @click="activePolicy = null"><X :size="19" /></button></div><p class="policy-summary">{{ activePolicy.summary }}</p><h3>办理建议</h3><ol><li v-for="step in activePolicy.steps" :key="step">{{ step }}</li></ol><div class="policy-citation"><ShieldCheck :size="16" /><div><strong>{{ activePolicy.source }}</strong><span>资料更新于 {{ activePolicy.updated_at }} · 信息仅供办事参考</span></div></div><div class="policy-contact"><span>咨询电话</span><strong>{{ activePolicy.phone }}</strong></div><button class="button button-primary modal-done" @click="activePolicy = null">我知道了 <Check :size="16" /></button></article></div>

    <div v-if="showPolicyModal" class="modal-backdrop" @click.self="showPolicyModal = false"><form class="ticket-modal" @submit.prevent="submitPolicy"><div class="modal-header"><div><span class="modal-kicker">知识运营 · {{ policyDraft.id ? '编辑资料' : '新增资料' }}</span><h2>{{ policyDraft.id ? '编辑政策资料' : '新增政策资料' }}</h2></div><button type="button" class="icon-button" @click="showPolicyModal = false"><X :size="19" /></button></div><label>政策名称 <span>*</span><input v-model="policyDraft.title" required minlength="2" placeholder="例如：居住证办理指南" /></label><div class="modal-row"><label>政策类别<input v-model="policyDraft.category" required /></label><label>咨询电话<input v-model="policyDraft.phone" /></label></div><label>内容摘要 <span>*</span><textarea v-model="policyDraft.summary" required minlength="5" rows="3" placeholder="用清晰简明的语言说明适用情况"></textarea></label><label>办理步骤 <small>每行一条</small><textarea v-model="policyDraft.steps" rows="3" placeholder="准备所需材料&#10;向社区服务窗口提交申请"></textarea></label><label>资料来源 <span>*</span><input v-model="policyDraft.source" required minlength="2" placeholder="主管部门及资料标题" /></label><label>检索关键词<input v-model="policyDraft.keywords" placeholder="用空格或逗号分隔，如：养老 津贴 补贴" /></label><div class="modal-actions"><button type="button" class="button button-white" @click="showPolicyModal = false">取消</button><button class="button button-primary" :disabled="savingContent"><Check :size="15" />{{ savingContent ? '保存中…' : '保存并发布' }}</button></div></form></div>

    <div v-if="showActivityModal" class="modal-backdrop" @click.self="showActivityModal = false"><form class="ticket-modal" @submit.prevent="submitActivity"><div class="modal-header"><div><span class="modal-kicker">社区运营 · 活动管理</span><h2>{{ activityDraft.id ? '编辑社区活动' : '新建社区活动' }}</h2></div><button type="button" class="icon-button" @click="showActivityModal = false"><X :size="19" /></button></div><label>活动名称 <span>*</span><input v-model="activityDraft.title" required minlength="2" placeholder="填写活动名称" /></label><div class="modal-row"><label>活动类型<input v-model="activityDraft.category" required /></label><label>面向人群<input v-model="activityDraft.audience" required /></label></div><div class="modal-row"><label>活动日期<input v-model="activityDraft.date" type="date" required /></label><label>活动时间<input v-model="activityDraft.time" required placeholder="例如：09:00–10:00" /></label></div><label>活动地点<input v-model="activityDraft.location" required /></label><label>活动说明<textarea v-model="activityDraft.description" required minlength="5" rows="3" placeholder="介绍活动内容与参与方式"></textarea></label><div class="modal-row"><label>报名名额<input v-model.number="activityDraft.capacity" type="number" min="1" required /></label><label>展示标签<input v-model="activityDraft.tag" /></label></div><div class="modal-actions"><button type="button" class="button button-white" @click="showActivityModal = false">取消</button><button class="button button-primary" :disabled="savingContent"><CalendarDays :size="15" />{{ savingContent ? '保存中…' : activityDraft.id ? '保存修改' : '发布活动' }}</button></div></form></div>
  </div>
</template>

<script lang="ts">
import { defineComponent, h } from 'vue'

export default defineComponent({
  components: {
    TicketTable: defineComponent({
      props: { items: { type: Array as () => TicketItem[], required: true }, staff: { type: Boolean, default: false } },
      emits: ['advance'],
      setup(props, { emit }) {
        return () => h('div', { class: 'table-scroll' }, [
          h('table', { class: 'ticket-table' }, [
            h('thead', [h('tr', [h('th', '诉求内容'), h('th', '提交居民'), h('th', '位置'), h('th', '提交时间'), h('th', '当前状态'), ...(props.staff ? [h('th', '处理人员'), h('th', '操作')] : [])])]),
            h('tbody', props.items.map((item) => h('tr', { key: item.id }, [
              h('td', { class: 'td-ticket' }, [h('span', { class: 'table-category-icon' }, [h(Wrench, { size: 15 })]), h('span', [h('strong', item.category), h('small', item.description)])]),
              h('td', [h('span', { class: 'resident-cell' }, [h('span', { class: 'mini-avatar' }, item.resident.slice(0, 1)), item.resident])]),
              h('td', { class: 'location-cell' }, item.location), h('td', { class: 'time-cell' }, item.created_at),
              h('td', [h('span', { class: ['status-pill', ({ '待受理': 'status-waiting', '处理中': 'status-working', '待确认': 'status-confirm', '已完成': 'status-done' } as Record<TicketStatus, string>)[item.status]] }, item.status)]),
              ...(props.staff ? [h('td', { class: 'assignee-cell' }, item.assignee), h('td', [item.status !== '已完成' ? h('button', { class: 'table-action', onClick: () => emit('advance', item) }, ({ '待受理': '受理工单', '处理中': '提交确认', '待确认': '确认完成' } as Record<TicketStatus, string>)[item.status]) : h('span', { class: 'done-check' }, [h(Check, { size: 15 }), '已完成'])])] : []),
            ]))),
          ]),
        ])
      },
    }),
    PhoneIcon: defineComponent({ setup: () => () => h('span', { class: 'phone-symbol', 'aria-hidden': 'true' }, '☎') }),
  },
})

</script>
