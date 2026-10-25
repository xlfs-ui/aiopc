<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { X, MapPin, Users } from 'lucide-vue-next'
import { authRequest, authUser } from './auth'
const props = defineProps<{ ticketId: string }>()
const emit = defineEmits<{ close: []; changed: [] }>()
type Ticket = { id: string; category: string; description: string; status: string; location: string; assignee: string; phone: string; resident: string; version: number; resolution: string; due_at: string; assigned_staff_id: string; can_confirm: boolean; can_handle: boolean; can_manage: boolean; handler: { name: string; team: string; phone: string; has_account: boolean; active: number } | null; events: { action: string; actor: string; created_at: string }[] }
type Staff = { id: string; name: string; team: string; active: number; user_id: string | null }
const ticket = ref<Ticket | null>(null), staff = ref<Staff[]>([]), busy = ref(false), loading = ref(false), error = ref(''), action = ref(''), note = ref(''), selected = ref(''), dueAt = ref('')
const owner = authUser.value?.id
const options = computed(() => {
  const t = ticket.value; if (!t || t.status === '已完成') return []
  const result: { id: string; label: string }[] = []
  if (t.can_manage && ['待受理', '处理中'].includes(t.status)) result.push({ id: 'assign', label: t.status === '待受理' ? '分派并受理' : '改派 / 调整安排' })
  if ((t.can_manage || t.can_handle) && t.status === '处理中') result.push({ id: 'progress', label: '记录处理进展' }, { id: 'report', label: '提交处理结果' })
  if ((t.can_confirm || t.can_manage) && t.status === '待确认') result.push({ id: 'confirm', label: t.can_confirm ? '本人确认完成' : '管理员代确认' }, { id: 'reject', label: '退回处理 / 返工' })
  return result
})
const help = computed(() => ({ assign: '选择在岗人员，填写派单要求或改派原因；可约定处理时间。', progress: '记录联系、到场、排查等实际进展，不改变当前状态。', report: '说明实际处理方式和结果，提交后进入待确认，由居民核对。', confirm: ticket.value?.can_confirm ? '请核对下方处理结果，填写确认意见。' : '仅在已核实结果时使用，必须写明代确认依据及原因。', reject: '说明尚未解决的问题或返工原因，工单将回到处理中。' }[action.value] || ''))
async function load() {
  if (busy.value) return
  loading.value = true; error.value = ''
  try {
    const result = await authRequest<Ticket>(`/api/tickets/${props.ticketId}`)
    if (owner !== authUser.value?.id) return
    ticket.value = result
    if (result.can_manage) staff.value = await authRequest<Staff[]>('/api/workforce')
    if (owner !== authUser.value?.id) return
    selected.value = result.assigned_staff_id || ''
    dueAt.value = result.due_at ? new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(result.due_at)).replace(' ', 'T') : ''
    action.value = options.value[0]?.id || ''; note.value = ''
  } catch (e) { error.value = e instanceof Error ? e.message : '工单读取失败' }
  finally { loading.value = false }
}
async function submit() {
  if (busy.value || !ticket.value || !action.value) return
  busy.value = true; error.value = ''
  try {
    await authRequest(`/api/tickets/${props.ticketId}`, { method: 'PATCH', body: JSON.stringify({ action: action.value, expected_version: ticket.value.version, note: note.value, ...(action.value === 'assign' ? { staff_id: selected.value, due_at: dueAt.value ? dueAt.value + '+08:00' : '' } : {}) }) })
    if (owner !== authUser.value?.id) return
    busy.value = false; await load(); emit('changed')
  } catch (e) { error.value = e instanceof Error ? e.message : '操作失败，请重试或刷新详情' }
  finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <div class="modal-backdrop" @click.self="!busy && emit('close')"><article class="workflow-modal" role="dialog" aria-modal="true" aria-label="工单分派与处理"><div class="modal-header"><div><span class="modal-kicker">工单闭环 · {{ ticketId }}</span><h2>{{ ticket?.category || '工单详情' }}</h2></div><button class="icon-button" :disabled="busy" aria-label="关闭工单" @click="emit('close')"><X :size="19" /></button></div>
    <p v-if="error" class="workflow-error" role="alert">{{ error }} <button class="text-link" :disabled="busy || loading" @click="load">刷新详情</button></p><p v-if="loading" class="workflow-empty">正在读取最新记录…</p>
    <template v-if="ticket"><div class="workflow-summary"><strong class="workflow-status">{{ ticket.status }}</strong><p>{{ ticket.description }}</p><span><MapPin :size="16" />{{ ticket.location }}</span><span>提交人：{{ ticket.resident }} · 联系方式：{{ ticket.phone || '未填写' }}</span><span><Users :size="16" />处理人：{{ ticket.assignee }}{{ ticket.handler ? ` · ${ticket.handler.team}` : '' }}</span><span v-if="ticket.handler?.phone">处理人员电话：{{ ticket.handler.phone }}</span><span v-if="ticket.handler && !ticket.handler.has_account">未关联处理账号，由管理员代录进展及结果</span><span v-if="!ticket.handler && ticket.assignee !== '待指派'">历史处理人尚未关联人员档案，需管理员重新选择人员</span><span v-if="ticket.due_at">预约处理时间：{{ new Date(ticket.due_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }}（北京时间）</span></div>
      <div v-if="ticket.resolution" class="workflow-resolution"><h3>最新处理结果</h3><p>{{ ticket.resolution }}</p></div>
      <div class="workflow-columns"><section><h3>流转与反馈记录</h3><ol class="ticket-history"><li v-for="(event, i) in ticket.events" :key="i"><i></i><div><strong>{{ event.action }}</strong><span>{{ event.actor }} · {{ event.created_at.replace('T', ' ') }}</span></div></li></ol></section>
      <form v-if="options.length" class="workflow-form" @submit.prevent="submit"><h3>下一步处理</h3><label>操作<select v-model="action" :disabled="busy"><option v-for="item in options" :key="item.id" :value="item.id">{{ item.label }}</option></select></label><p class="workflow-hint">{{ help }}</p>
      <template v-if="action === 'assign'"><label>处理人员<select v-model="selected" required :disabled="busy"><option value="" disabled>请选择在岗人员</option><option v-for="item in staff.filter(s => s.active)" :key="item.id" :value="item.id">{{ item.name }} · {{ item.team }}{{ item.user_id ? '' : '（管理员代录）' }}</option></select></label><p v-if="!staff.some(s => s.active)" class="workflow-error">请关闭详情，在“工单处理 → 处理人员”中先添加在岗人员。</p><label>预约处理时间（北京时间，可选）<input v-model="dueAt" type="datetime-local" :disabled="busy" /></label></template>
      <label>{{ action === 'report' ? '实际处理结果' : action === 'reject' ? '退回 / 返工原因' : action === 'confirm' ? '确认意见 / 代确认依据' : '处理说明' }}<textarea v-model="note" required minlength="3" maxlength="1000" rows="5" :disabled="busy" placeholder="填写实际情况，至少3个字；内容将进入流转记录，并通知相关账号。"></textarea></label>
      <p v-if="action === 'confirm' && !ticket.resolution" class="workflow-error">历史工单尚无结果，请先退回处理，由处理人员或管理员补充反馈。</p>
      <button class="button button-primary" :disabled="busy || loading || (action === 'confirm' && !ticket.resolution) || (action === 'assign' && !selected)">{{ busy ? '正在保存…' : options.find(o => o.id === action)?.label }}</button></form>
      <section v-else class="workflow-hint"><h3>{{ ticket.status === '已完成' ? '工单已完成' : '等待后续处理' }}</h3><p>{{ ticket.status === '待确认' ? '等待提交居民核对处理结果，或由管理员核实后代确认。' : ticket.status === '待受理' ? '等待管理员选择处理人员并分派。' : '处理人员或管理员会在此记录进展和处理结果。' }}</p></section></div>
    </template>
  </article></div>
</template>
