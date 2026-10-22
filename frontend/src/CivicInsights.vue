<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Activity, ArrowDownToLine, ArrowUpRight, Building2, Check, FileText, MapPin, Plus, RefreshCw, Sparkles, Trash2, Users, X } from 'lucide-vue-next'
import { authRequest } from './auth'

type Place = { id: string; name: string; zone: string; kind: '小区' | '楼栋' | '公共空间'; households: number; note: string }
type Resident = { id: string; username: string; display_name: string; place_id: string | null }
type Report = { id: string; created_at: string; days: number; markdown?: string; title?: string }
type Insight = {
  start: string; end: string; generated_at: string; demo: boolean
  metrics: { consultations: number; tickets: number; previous_tickets: number; pending: number; completion_rate: number; areas: number }
  daily: { date: string; tickets: number; consultations: number }[]
  consultation_topics: { name: string; count: number }[]
  topics: { name: string; count: number; previous: number; delta: number; change_pct: number | null; signal: string }[]
  areas: { name: string; count: number; pending: number }[]
  suggestions: { topic: string; evidence: string; action: string; priority: string }[]
  ledger: { residents: number; places: number; households: number; linked_residents: number; published_documents: number }
  quality: { undated_tickets: number; unassigned_tickets: number; notes: string[] }
}
const days = ref(30)
const demo = ref(false)
const tab = ref<'analysis' | 'ledger' | 'reports'>('analysis')
const data = ref<Insight | null>(null)
const places = ref<Place[]>([])
const residents = ref<Resident[]>([])
const reports = ref<Report[]>([])
const activeReport = ref<Report | null>(null)
const loading = ref(false)
const saving = ref(false)
const busyId = ref('')
const error = ref('')
const notice = ref('')
const hover = ref<number | null>(null)
const editing = ref<string | null>(null)
const formOpen = ref(false)
const draft = ref({ name: '', zone: '', kind: '小区' as Place['kind'], households: 0, note: '' })
let sequence = 0
let controller: AbortController | undefined
const ceiling = computed(() => Math.max(1, ...(data.value?.daily.flatMap(d => [d.tickets, d.consultations]) || [])))
const totalQueries = computed(() => data.value?.metrics.consultations || 0)
const maxArea = computed(() => Math.max(1, ...(data.value?.areas.map(a => a.count) || [])))
const selectedDay = computed(() => data.value?.daily[hover.value ?? -1])
const ring = computed(() => `conic-gradient(#638d78 0% ${data.value?.metrics.completion_rate || 0}%, #e9eeeb 0)`)
const metrics = computed(() => data.value ? [
  { label: '居民咨询', value: data.value.metrics.consultations, unit: '次', caption: '完成对话 · 非独立人数', icon: Users },
  { label: '新增诉求', value: data.value.metrics.tickets, unit: '件', caption: `上期 ${data.value.metrics.previous_tickets} 件`, icon: Activity },
  { label: '待完成事项', value: data.value.metrics.pending, unit: '件', caption: '按当前工单状态统计', icon: FileText },
  { label: '涉及区域', value: data.value.metrics.areas, unit: '处', caption: '地点归并 · 含未归属', icon: MapPin },
] : [])
function line(key: 'tickets' | 'consultations') {
  const rows = data.value?.daily || []
  return rows.map((d, i) => `${i ? 'L' : 'M'} ${20 + i / Math.max(1, rows.length - 1) * 660} ${160 - d[key] / ceiling.value * 125}`).join(' ')
}
function message(e: unknown) { return e instanceof Error ? e.message : '操作未完成，请稍后重试' }
async function load() {
  const current = ++sequence
  controller?.abort(); controller = new AbortController()
  loading.value = true; error.value = ''; hover.value = null
  try {
    const result = await authRequest<Insight>(`/api/civic/analytics?days=${days.value}&demo=${demo.value}`, { signal: controller.signal })
    if (current === sequence) data.value = result
  } catch (e) { if (current === sequence && !controller?.signal.aborted) error.value = message(e) }
  finally { if (current === sequence) loading.value = false }
}
async function loadLedger() {
  const result = await authRequest<{ places: Place[]; residents: Resident[] }>('/api/civic/ledger')
  places.value = result.places; residents.value = result.residents
}
async function loadReports() { reports.value = await authRequest<Report[]>('/api/civic/reports') }
async function initialize() { await load(); try { await Promise.all([loadLedger(), loadReports()]) } catch (e) { error.value = message(e) } }
async function generate() {
  if (saving.value || (demo.value && tab.value === 'analysis')) return
  saving.value = true; error.value = ''; notice.value = ''
  try {
    activeReport.value = await authRequest<Report>('/api/civic/reports', { method: 'POST', body: JSON.stringify({ days: days.value }) })
    await loadReports(); tab.value = 'reports'; notice.value = '真实数据报告已保存，可随时查看或导出。'
  } catch (e) { error.value = message(e) } finally { saving.value = false }
}
async function openReport(id: string) {
  busyId.value = id; error.value = ''
  try { activeReport.value = await authRequest<Report>(`/api/civic/reports/${encodeURIComponent(id)}`) }
  catch (e) { error.value = message(e) } finally { busyId.value = '' }
}
function download() {
  if (!activeReport.value?.markdown) return
  const url = URL.createObjectURL(new Blob(['\ufeff' + activeReport.value.markdown], { type: 'text/markdown;charset=utf-8' }))
  const a = document.createElement('a'); a.href = url; a.download = `民情分析-${activeReport.value.created_at.slice(0, 10)}.md`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
}
async function removeReport(id: string) {
  if (!window.confirm('删除这份已保存的报告？此操作不能恢复。')) return
  busyId.value = id
  try { await authRequest(`/api/civic/reports/${encodeURIComponent(id)}`, { method: 'DELETE' }); if (activeReport.value?.id === id) activeReport.value = null; await loadReports() }
  catch (e) { error.value = message(e) } finally { busyId.value = '' }
}
function editPlace(place?: Place) {
  editing.value = place?.id || null
  draft.value = place ? { name: place.name, zone: place.zone, kind: place.kind, households: place.households, note: place.note } : { name: '', zone: '', kind: '小区', households: 0, note: '' }
  formOpen.value = true
}
async function savePlace() {
  if (saving.value) return
  saving.value = true; error.value = ''
  try {
    await authRequest(editing.value ? `/api/civic/places/${editing.value}` : '/api/civic/places', { method: editing.value ? 'PUT' : 'POST', body: JSON.stringify(draft.value) })
    formOpen.value = false; await loadLedger(); await load(); notice.value = '地点底册已更新。'
  } catch (e) { error.value = message(e) } finally { saving.value = false }
}
async function removePlace(place: Place) {
  if (!window.confirm(`删除地点“${place.name}”？已有关联居民时将禁止删除。`)) return
  busyId.value = place.id
  try { await authRequest(`/api/civic/places/${place.id}`, { method: 'DELETE' }); await loadLedger(); await load() }
  catch (e) { error.value = message(e) } finally { busyId.value = '' }
}
async function linkPlace(person: Resident, event: Event) {
  const select = event.target as HTMLSelectElement
  busyId.value = person.id
  try {
    await authRequest(`/api/civic/residents/${person.id}/place`, { method: 'PUT', body: JSON.stringify({ place_id: select.value || null }) })
    await loadLedger(); await load()
  } catch (e) { select.value = person.place_id || ''; error.value = message(e) } finally { busyId.value = '' }
}
watch([days, demo], () => { notice.value = ''; void load() })
onMounted(() => { void initialize() })
onBeforeUnmount(() => { sequence++; controller?.abort() })
</script>

<template>
  <section class="civic-module" :aria-busy="loading">
    <header class="civic-hero">
      <div class="civic-orbit orbit-one"></div><div class="civic-orbit orbit-two"></div>
      <div class="civic-hero-copy"><span class="civic-eyebrow"><i></i> COMMUNITY INSIGHTS · 民情洞察</span><h2>听见需求，让服务更有方向<span>。</span></h2><p>从居民咨询与日常诉求中，发现值得跟进的问题，为社区资源安排提供依据。</p><div class="civic-hero-tags"><span><Check :size="13" /> 可追溯统计口径</span><span><Check :size="13" /> 报告持久保存</span><span><Check :size="13" /> 管理员专属</span></div></div>
      <div class="civic-radar" aria-hidden="true"><div class="radar-sweep"></div><i></i><i></i><i></i><Building2 :size="29" /><span>民情 · 人 · 房 · 事</span></div>
    </header>
    <div class="civic-toolbar"><div class="civic-tabs" aria-label="民情功能"><button :class="{ selected: tab === 'analysis' }" @click="tab = 'analysis'">民情分析</button><button :class="{ selected: tab === 'ledger' }" @click="tab = 'ledger'">人房事底册</button><button :class="{ selected: tab === 'reports' }" @click="tab = 'reports'">分析报告 <small>{{ reports.length }}</small></button></div><div class="civic-controls"><label>统计周期 <select v-model.number="days"><option :value="7">近 7 天</option><option :value="30">近 30 天</option><option :value="90">近 90 天</option></select></label><button class="civic-icon-btn" :disabled="loading" aria-label="刷新数据" @click="load"><RefreshCw :size="16" :class="{ 'civic-spin': loading }" /></button></div></div>
    <p v-if="error" class="civic-error" role="alert">{{ error }}</p><p v-if="notice" class="civic-notice" role="status">{{ notice }}</p>
    <template v-if="tab === 'analysis'">
      <div class="civic-mode-line"><span><i :class="{ demo }"></i>{{ demo ? '演示数据 · 不写入业务库' : '真实数据 · 自动汇总' }} <small v-if="data">{{ data.start }} — {{ data.end }} · 北京时间</small></span><label class="civic-toggle"><input v-model="demo" type="checkbox" />查看演示效果</label></div>
      <div v-if="loading && !data" class="civic-skeleton"><i v-for="i in 4" :key="i"></i></div>
      <template v-if="data">
        <div :key="`${days}-${demo}-${data.generated_at}`" class="civic-kpis"><article v-for="(metric, i) in metrics" :key="metric.label" class="civic-kpi" :style="{ '--delay': `${i * 65}ms` }"><div><span>{{ metric.label }}</span><component :is="metric.icon" :size="18" /></div><strong>{{ metric.value }}<small>{{ metric.unit }}</small></strong><p>{{ metric.caption }}</p></article></div>
        <div class="civic-main-grid"><article class="civic-card civic-trend"><div class="civic-card-heading"><div><h3>咨询与诉求走势</h3><p>{{ selectedDay ? `${selectedDay.date} · 咨询 ${selectedDay.consultations} 次 / 诉求 ${selectedDay.tickets} 件` : '悬停查看每日数据 · 两类计数分别统计' }}</p></div><div class="civic-chart-key"><span>咨询</span><span>诉求</span></div></div><svg viewBox="0 0 720 190" role="img" aria-label="每日咨询与诉求趋势图" @mouseleave="hover = null"><defs><linearGradient id="civicTrendFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#729a88" stop-opacity=".24" /><stop offset="100%" stop-color="#729a88" stop-opacity="0" /></linearGradient></defs><g class="civic-grid-lines"><line v-for="y in [35, 76, 118, 160]" :key="y" x1="20" :y1="y" x2="680" :y2="y" /></g><path :d="`${line('consultations')} L 680 160 L 20 160 Z`" fill="url(#civicTrendFill)" /><path :d="line('consultations')" class="civic-line green" /><path :d="line('tickets')" class="civic-line amber" /><g v-for="(day, i) in data.daily" :key="day.date"><rect :x="20 + i / Math.max(1, data.daily.length - 1) * 660 - 4" y="20" :width="Math.max(8, 660 / data.daily.length)" height="150" fill="transparent" @mouseenter="hover = i"><title>{{ day.date }}：咨询 {{ day.consultations }}，诉求 {{ day.tickets }}</title></rect></g></svg><div class="civic-chart-dates"><span>{{ data.start }}</span><span>{{ data.end }}</span></div><details class="civic-data-table"><summary>查看趋势数据表</summary><div class="civic-table-wrap"><table><thead><tr><th>日期</th><th>咨询次数</th><th>诉求件数</th></tr></thead><tbody><tr v-for="day in data.daily" :key="day.date"><td>{{ day.date }}</td><td>{{ day.consultations }}</td><td>{{ day.tickets }}</td></tr></tbody></table></div></details></article><article class="civic-card civic-completion"><div class="civic-card-heading"><div><h3>本期事项完成率</h3><p>当前状态为已完成 / 本期新建诉求</p></div></div><div class="civic-ring" :style="{ background: ring }"><div><strong>{{ data.metrics.completion_rate }}<small>%</small></strong><span>{{ data.metrics.tickets ? '持续跟进每一个诉求' : '暂无本期诉求' }}</span></div></div><p>尚有 <b>{{ data.metrics.pending }}</b> 件事项需要跟进</p></article></div>
        <div class="civic-half-grid"><article class="civic-card"><div class="civic-card-heading"><div><h3>居民最常咨询什么</h3><p>按问句关键词自动分类，不保存咨询原文</p></div><Sparkles :size="18" /></div><div v-if="!data.consultation_topics.length" class="civic-empty">暂无咨询统计。功能上线后，完成对话将自动计入。</div><div v-for="(item, i) in data.consultation_topics" :key="item.name" class="civic-rank-row"><span class="civic-rank">{{ String(i + 1).padStart(2, '0') }}</span><div><div><span>{{ item.name }}</span><b>{{ item.count }} <small>次</small></b></div><div class="civic-meter"><i :style="{ width: `${item.count / Math.max(totalQueries, 1) * 100}%` }"></i></div></div></div></article><article class="civic-card"><div class="civic-card-heading"><div><h3>哪些区域报修集中</h3><p>地点名称匹配 · 楼栋归并</p></div><MapPin :size="18" /></div><div v-if="!data.areas.length" class="civic-empty">本期暂无带有效日期的报修记录。</div><div v-for="area in data.areas" :key="area.name" class="civic-area"><div><span>{{ area.name }}</span><b>{{ area.count }} 件 <small>· 待完成 {{ area.pending }}</small></b></div><div class="civic-meter amber"><i :style="{ width: `${area.count / maxArea * 100}%` }"></i></div></div></article></div>
        <article class="civic-card"><div class="civic-card-heading"><div><h3>诉求变化与关注线索</h3><p>与前一个相同长度周期对比；诉求数量不等于已核实的矛盾事件数量。</p></div><Activity :size="18" /></div><div v-if="!data.topics.length" class="civic-empty">数据积累后，将在这里展示诉求变化。</div><div v-else class="civic-table-wrap"><table><thead><tr><th>类型</th><th>本期</th><th>上期</th><th>数量变化</th><th>环比</th><th>关注提示</th></tr></thead><tbody><tr v-for="topic in data.topics" :key="topic.name"><td>{{ topic.name }}</td><td>{{ topic.count }}</td><td>{{ topic.previous }}</td><td :class="{ 'civic-up': topic.delta > 0 }">{{ topic.delta > 0 ? '+' : '' }}{{ topic.delta }}</td><td>{{ topic.change_pct === null ? '无上期基数' : `${topic.change_pct > 0 ? '+' : ''}${topic.change_pct}%` }}</td><td><span class="civic-badge" :class="{ warm: topic.signal === '上升' || topic.signal === '新增关注' }">{{ topic.signal }}</span></td></tr></tbody></table></div></article>
        <section class="civic-advice"><div class="civic-advice-heading"><div><span class="civic-eyebrow">ACTIONABLE INSIGHTS</span><h3>把发现，变成下一步行动</h3><p>基于统计规则生成建议，实际调度需人工核实。</p></div><button class="button button-primary" :disabled="saving || demo || loading" @click="generate"><FileText :size="16" />{{ saving ? '正在生成…' : '生成并保存分析报告' }}<ArrowUpRight :size="15" /></button></div><div v-if="!data.suggestions.length" class="civic-empty">暂无足够数据形成具体建议。可先维护地点底册、发布知识文档，并持续记录诉求。</div><div class="civic-advice-grid"><article v-for="(item, i) in data.suggestions" :key="item.topic"><span>0{{ i + 1 }} / {{ item.priority }}</span><h4>{{ item.topic }}</h4><p class="civic-evidence">{{ item.evidence }}</p><p>{{ item.action }}</p></article></div></section>
        <details class="civic-method"><summary>统计口径与数据质量 <span v-if="data.quality.undated_tickets">· {{ data.quality.undated_tickets }} 件记录日期不规范</span></summary><ul><li v-for="note in data.quality.notes" :key="note">{{ note }}</li><li>当前 {{ data.quality.unassigned_tickets }} 件诉求未匹配具体地点，可在底册中补充地点名称。</li></ul></details>
      </template>
    </template>
    <template v-else-if="tab === 'ledger'">
      <div class="civic-ledger-intro"><div><h3>人有归属，房有记录，事有线索</h3><p>维护小区与楼栋、关联已注册居民，为新网格员提供交接入口。仅登记服务必需信息，不记录身份证、产权或资格结论。</p></div><button class="button button-primary" @click="editPlace()"><Plus :size="16" />添加地点</button></div>
      <div v-if="data" class="civic-ledger-stats"><span><Users :size="18" />居民账号 <b>{{ data.ledger.residents }}</b></span><span><Building2 :size="18" />登记地点 <b>{{ data.ledger.places }}</b></span><span>登记户数 <b>{{ data.ledger.households }}</b></span><span>已关联居民 <b>{{ data.ledger.linked_residents }}</b></span><span>已发布文档 <b>{{ data.ledger.published_documents }}</b></span></div>
      <form v-if="formOpen" class="civic-place-form civic-card" @submit.prevent="savePlace"><div class="civic-card-heading"><h3>{{ editing ? '编辑地点' : '登记新地点' }}</h3><button type="button" class="civic-icon-btn" aria-label="关闭地点表单" @click="formOpen = false"><X :size="17" /></button></div><div class="civic-form-grid"><label>地点名称<input v-model="draft.name" required minlength="2" maxlength="50" placeholder="例如：云水花园 / 3幢" /></label><label>所属网格<input v-model="draft.zone" required maxlength="40" placeholder="例如：第一网格" /></label><label>地点类型<select v-model="draft.kind"><option>小区</option><option>楼栋</option><option>公共空间</option></select></label><label>登记户数<input v-model.number="draft.households" type="number" min="0" max="100000" required /></label><label class="wide">交接备注<textarea v-model="draft.note" maxlength="300" rows="2" placeholder="填写公共服务与巡查提示，勿填写敏感身份信息" /></label></div><button class="button button-primary" :disabled="saving">{{ saving ? '保存中…' : '保存地点' }}</button></form>
      <article class="civic-card"><div class="civic-card-heading"><div><h3>地点底册</h3><p>名称匹配用于区域统计；户数为人工登记，不等于已关联居民人数。</p></div></div><div v-if="!places.length" class="civic-empty">还没有登记地点，点击“添加地点”开始维护。</div><div class="civic-place-grid"><article v-for="place in places" :key="place.id"><div><Building2 :size="20" /><span>{{ place.kind }}</span></div><h4>{{ place.name }}</h4><p>{{ place.zone }} · {{ place.households }} 户</p><p class="civic-place-note">{{ place.note || '暂无交接备注' }}</p><footer><button @click="editPlace(place)">编辑底册</button><button :disabled="busyId === place.id" :aria-label="`删除${place.name}`" @click="removePlace(place)"><Trash2 :size="14" /></button></footer></article></div></article>
      <article class="civic-card"><div class="civic-card-heading"><div><h3>居民与地点关联</h3><p>展示最近注册的最多 300 个居民账号；关联信息仅管理员可见。</p></div></div><div v-if="!residents.length" class="civic-empty">暂无已注册居民账号。</div><div v-else class="civic-table-wrap"><table><thead><tr><th>居民称呼</th><th>账号</th><th>关联地点</th></tr></thead><tbody><tr v-for="person in residents" :key="person.id"><td>{{ person.display_name }}</td><td>{{ person.username }}</td><td><select :value="person.place_id || ''" :disabled="busyId === person.id" :aria-label="`${person.display_name}的关联地点`" @change="linkPlace(person, $event)"><option value="">未关联</option><option v-for="place in places" :key="place.id" :value="place.id">{{ place.name }} · {{ place.zone }}</option></select></td></tr></tbody></table></div></article>
      <aside class="civic-handover"><Sparkles :size="22" /><div><h3>新网格员快速交接</h3><p>① 查看民情分析中的高频诉求与区域分布 → ② 通过地点底册了解网格与巡查提示 → ③ 在工单处理中核查未完成事项 → ④ 阅读文档知识库中的已发布办事资料。报告提供线索，个案细节请在有权限的业务页面核实。</p></div></aside>
    </template>
    <template v-else>
      <div class="civic-ledger-intro"><div><h3>让每一次判断，都有记录可循</h3><p>报告保存生成时的真实数据快照与统计口径，后续业务变化不会改写历史报告。</p></div><button class="button button-primary" :disabled="saving" @click="generate"><Plus :size="16" />生成近 {{ days }} 天报告</button></div>
      <div class="civic-report-grid"><article class="civic-card civic-report-list"><h3>已保存报告</h3><p v-if="!reports.length" class="civic-empty">还没有报告，点击右上角生成。</p><div v-for="report in reports" :key="report.id" :class="{ active: activeReport?.id === report.id }"><button :disabled="busyId === report.id" @click="openReport(report.id)"><FileText :size="18" /><span>近 {{ report.days }} 天民情分析<small>{{ report.created_at.slice(0, 16).replace('T', ' ') }}</small></span></button><button class="civic-icon-btn" :disabled="busyId === report.id" aria-label="删除此报告" @click="removeReport(report.id)"><Trash2 :size="14" /></button></div></article><article class="civic-card civic-report-paper"><div class="civic-card-heading"><div><span class="civic-eyebrow">COMMUNITY REPORT</span><h3>{{ activeReport ? '民情需求分析报告' : '选择一份报告查看' }}</h3></div><button v-if="activeReport?.markdown" class="button" @click="download"><ArrowDownToLine :size="16" />导出 Markdown</button></div><pre v-if="activeReport?.markdown">{{ activeReport.markdown }}</pre><div v-else class="civic-empty"><FileText :size="36" /><p>热门咨询、区域分布、诉求变化与行动建议，将在此汇成一份可交接的报告。</p></div></article></div>
    </template>
  </section>
</template>
