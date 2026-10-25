<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Plus, X, Save } from 'lucide-vue-next'
import { authRequest, authUser } from './auth'
type Staff = { id: string; name: string; team: string; phone: string; user_id: string | null; active: number; username?: string }
type Account = { id: string; username: string; display_name: string }
const emit = defineEmits<{ close: []; changed: [] }>()
const staff = ref<Staff[]>([]), accounts = ref<Account[]>([]), error = ref(''), saving = ref(false), ready = ref(false)
const blank = () => ({ id: '', name: '', team: '', phone: '', user_id: '', active: true })
const draft = ref(blank())
const owner = authUser.value?.id
async function load() {
  try { const result = await Promise.all([authRequest<Staff[]>('/api/workforce'), authRequest<Account[]>('/api/workforce/accounts')]); if (owner !== authUser.value?.id) return; [staff.value, accounts.value] = result; ready.value = true }
  catch (e) { error.value = e instanceof Error ? e.message : '处理人员读取失败' }
}
function edit(item: Staff) { draft.value = { id: item.id, name: item.name, team: item.team, phone: item.phone, user_id: item.user_id || '', active: !!item.active }; error.value = '' }
async function save() {
  if (saving.value) return
  saving.value = true; error.value = ''
  try {
    const { id, ...fields } = draft.value
    await authRequest(id ? `/api/workforce/${id}` : '/api/workforce', { method: id ? 'PUT' : 'POST', body: JSON.stringify({ ...fields, user_id: fields.user_id || null }) })
    if (owner !== authUser.value?.id) return
    draft.value = blank(); await load(); emit('changed')
  } catch (e) { error.value = e instanceof Error ? e.message : '保存失败' }
  finally { saving.value = false }
}
onMounted(load)
</script>
<template>
  <div class="modal-backdrop" @click.self="!saving && emit('close')"><article class="workflow-modal" role="dialog" aria-modal="true" aria-label="处理人员管理"><div class="modal-header"><div><span class="modal-kicker">社区工作台 · 人员与职责</span><h2>处理人员管理</h2></div><button class="icon-button" aria-label="关闭人员管理" :disabled="saving" @click="emit('close')"><X :size="19" /></button></div>
    <p class="workflow-hint">可关联已有登录账号，关联后该账号重新登录即可查看本人被分派的工单。未关联账号的人员，由管理员代录处理反馈；不会自动创建账户或默认密码。</p>
    <p v-if="error" class="workflow-error" role="alert">{{ error }}</p>
    <div class="workflow-columns"><section><h3>人员档案</h3><p v-if="ready && !staff.length" class="workflow-empty">尚无人员，请先添加，再分派工单。</p><button v-for="item in staff" :key="item.id" class="staff-record" @click="edit(item)"><strong>{{ item.name }} · {{ item.team }}</strong><span>{{ item.active ? '在岗' : '已停用' }} · {{ item.username ? `关联 ${item.username}` : '未关联账号 · 管理员代录' }}</span><small>{{ item.phone || '未填写联系号码' }}</small></button></section>
    <form class="workflow-form" @submit.prevent="save"><h3>{{ draft.id ? '编辑人员' : '添加处理人员' }}</h3><label>姓名<input v-model="draft.name" required minlength="2" maxlength="40" /></label><label>班组 / 职责<input v-model="draft.team" required minlength="2" maxlength="60" placeholder="例如：物业维修班 / 公共照明" /></label><label>联系电话<input v-model="draft.phone" maxlength="30" /></label><label>关联登录账号<select v-model="draft.user_id"><option value="">暂不关联（管理员代录反馈）</option><option v-for="account in accounts" :key="account.id" :value="account.id">{{ account.display_name }}（{{ account.username }}）</option></select></label><p class="workflow-hint">关联账号将获得本人分派工单的查看与反馈权限，不获得管理员权限。请核对人员身份。</p><label class="workflow-check"><input v-model="draft.active" type="checkbox" />在岗，可接收分派</label><p class="workflow-hint">有未完成任务时，须先改派或结单，再停用或更换账号。</p><div class="workflow-buttons"><button class="button button-white" type="button" @click="draft = blank()"><Plus :size="15" />新增</button><button class="button button-primary" :disabled="saving || !ready"><Save :size="15" />{{ saving ? '保存中…' : '保存人员' }}</button></div></form></div>
  </article></div>
</template>
