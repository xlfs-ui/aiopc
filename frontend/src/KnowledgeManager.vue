<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { BookOpen, FileUp, Search, RefreshCw, Check, Archive, Trash2, X } from 'lucide-vue-next'
import { authRequest } from './auth'
type Doc = { id: string; document_key: string; version: number; title: string; source: string; source_url: string; filename: string; status: 'draft' | 'published' | 'archived'; effective_on: string; expires_on: string; chunk_count: number; content?: string }
type Status = { engine: string; embedding_configured: boolean; embedding_model: string; chunks: number; indexed: number; vector_limit: number; configuration_error: string }
const controller = new AbortController()
const docs = ref<Doc[]>([])
const total = ref(0)
const offset = ref(0)
const status = ref<Status | null>(null)
const busy = ref(false)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const preview = ref<Doc | null>(null)
const importing = ref(false)
const consent = ref(false)
const draft = ref({ title: '', source: '', source_url: '', filename: '资料.txt', text: '', file_base64: '', document_key: '', effective_on: '', expires_on: '' })
const fileInput = ref<HTMLInputElement | null>(null)
const query = ref('')
const results = ref<{ id: string; title: string; excerpt: string; retrieval_method: string; chunk_id: string; metadata: { source: string; page?: number; version?: number } }[]>([])
const labels = { draft: '待审核草稿', published: '已发布', archived: '已归档' }
let reader: FileReader | null = null
function request<T>(path: string, init?: RequestInit) { return authRequest<T>(path, { ...init, signal: controller.signal }) }
async function refresh() {
  loading.value = true
  try {
    const [list, info] = await Promise.all([request<{ items: Doc[]; total: number }>(`/api/knowledge/documents?offset=${offset.value}&limit=25`), request<Status>('/api/knowledge/status')])
    docs.value = list.items; total.value = list.total; status.value = info
  } catch (e) { if (!controller.signal.aborted) error.value = e instanceof Error ? e.message : '加载失败' }
  finally { loading.value = false }
}
async function act(work: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''; notice.value = ''
  try { await work() } catch (e) { if (!controller.signal.aborted) error.value = e instanceof Error ? e.message : '操作失败' }
  finally { busy.value = false }
}
function openImport(doc?: Doc) {
  reader?.abort(); reader = null
  draft.value = { title: doc?.title || '', source: doc?.source || '', source_url: doc?.source_url || '', filename: '资料.txt', text: '', file_base64: '', document_key: doc?.document_key || '', effective_on: '', expires_on: '' }
  importing.value = true; error.value = ''; preview.value = null
}
function selectFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (file.size > 1024 * 1024 || !/\.(txt|md|docx|pdf)$/i.test(file.name)) {
    error.value = '请选择不超过 1 MiB 的 TXT、MD、DOCX 或 PDF'; (event.target as HTMLInputElement).value = ''; return
  }
  reader?.abort(); const selectedReader = new FileReader(); reader = selectedReader
  selectedReader.onload = () => { if (reader !== selectedReader) return; draft.value.file_base64 = String(selectedReader.result || '').split(',')[1] || ''; draft.value.filename = file.name; draft.value.text = '' }
  selectedReader.onerror = () => { if (reader === selectedReader) error.value = '文件读取失败，请重试' }
  selectedReader.readAsDataURL(file)
}
function clearFile() { reader?.abort(); reader = null; draft.value.file_base64 = ''; draft.value.filename = '资料.txt'; if (fileInput.value) fileInput.value.value = '' }
async function save() {
  await act(async () => {
    const doc = await request<Doc>('/api/knowledge/documents', { method: 'POST', body: JSON.stringify(draft.value) })
    importing.value = false; notice.value = `已保存版本 ${doc.version}，请预览核对后发布。`; offset.value = 0; await refresh()
  })
}
async function show(doc: Doc) { await act(async () => { preview.value = await request<Doc>(`/api/knowledge/documents/${doc.id}`) }) }
async function change(doc: Doc, state: 'published' | 'archived') {
  await act(async () => {
    await request(`/api/knowledge/documents/${doc.id}`, { method: 'PATCH', body: JSON.stringify({ status: state }) })
    notice.value = state === 'published' ? '已审核发布；同一资料的上一发布版本自动归档。' : '已归档，居民检索不再引用该版本。'
    preview.value = null; await refresh()
  })
}
async function remove(doc: Doc) {
  if (!window.confirm(`永久删除“${doc.title}”版本 ${doc.version} 及其索引？`)) return
  await act(async () => { await request(`/api/knowledge/documents/${doc.id}`, { method: 'DELETE' }); preview.value = null; await refresh() })
}
async function buildVectors() {
  if (!consent.value) return
  await act(async () => { const result = await request<{ message: string; indexed: number; remaining: number }>('/api/knowledge/reindex', { method: 'POST', body: '{}' }); notice.value = `${result.message}：本次 ${result.indexed} 个，剩余 ${result.remaining} 个。`; await refresh() })
}
async function search() {
  if (!query.value.trim()) return
  await act(async () => { const result = await request<{ results: typeof results.value }>(`/api/knowledge/search?q=${encodeURIComponent(query.value)}`); results.value = result.results; if (!result.results.length) notice.value = '没有达到相关性要求的已发布资料。' })
}
onMounted(refresh)
onUnmounted(() => { controller.abort(); reader?.abort() })
</script>

<template>
  <section class="knowledge-manager">
    <header class="page-intro"><div><div class="eyebrow">资料审核 · 中文检索</div><h1>文档知识库</h1><p>上传资料、核对原文、发布有效版本，为居民问答提供依据。</p></div><button class="button button-primary" :disabled="busy" @click="openImport()"><FileUp :size="16" />导入资料</button></header>
    <p v-if="error" class="knowledge-alert" role="alert">{{ error }}</p><p v-if="notice" class="knowledge-notice" role="status">{{ notice }}</p>
    <section v-if="status" class="panel knowledge-index"><div><BookOpen :size="20" /><strong>全文检索已启用</strong><span>{{ status.engine.startsWith('postgres') ? 'PostgreSQL 全文排序' : 'FTS5 / BM25' }} · {{ status.chunks }} 个索引片段</span></div><p>{{ status.embedding_configured ? `语义模型：${status.embedding_model}；当前配置已索引 ${status.indexed} 个片段。` : '语义检索尚未配置，当前使用中文全文检索。由后端环境变量配置独立的 Embedding 服务。' }}</p><p v-if="status.configuration_error" class="knowledge-alert">{{ status.configuration_error }}</p><label v-if="status.embedding_configured" class="knowledge-consent"><input v-model="consent" type="checkbox" />允许将已发布资料的标题与片段发送至所配置的 Embedding 服务；启用后检索问题也会发送至该服务。</label><button class="button button-white" :disabled="busy || !status.embedding_configured || !consent" @click="buildVectors"><RefreshCw :size="15" />{{ busy ? '处理中…' : '构建 / 继续向量索引' }}</button><small>每次最多 64 个片段，完成后可继续；轻量向量检索上限 {{ status.vector_limit }} 个片段。修改模型后需重新构建。</small></section>
    <form v-if="importing" class="panel knowledge-import" @submit.prevent="save"><header><h2>{{ draft.document_key ? '导入资料新版本' : '导入新资料' }}</h2><button type="button" class="icon-button" aria-label="关闭导入" @click="importing = false"><X :size="18" /></button></header><div class="knowledge-fields"><label>资料标题<input v-model="draft.title" required minlength="2" maxlength="120" /></label><label>来源部门 / 文档名称<input v-model="draft.source" required minlength="2" maxlength="200" /></label><label>来源链接（可选）<input v-model="draft.source_url" type="url" maxlength="1000" placeholder="https://…" /></label><label>生效日期（可选）<input v-model="draft.effective_on" type="date" /></label><label>失效日期（可选）<input v-model="draft.expires_on" type="date" :min="draft.effective_on" /></label></div><label class="knowledge-upload">上传文件<input ref="fileInput" type="file" accept=".txt,.md,.docx,.pdf" @change="selectFile" /><small>单文件 1 MiB；PDF 最多 80 页。扫描件需先 OCR；TXT / MD 使用 UTF-8。</small></label><p v-if="draft.file_base64">已选择：{{ draft.filename }} <button type="button" class="text-link" @click="clearFile">移除文件</button></p><label v-else>或直接粘贴正文<textarea v-model="draft.text" rows="9" maxlength="200000" :required="!draft.file_base64" placeholder="粘贴需要审核入库的社区政策或办事资料" /></label><footer><span>导入后保存为草稿，居民无法检索；请核对来源及正文后发布。</span><button class="button button-primary" :disabled="busy || (!draft.text.trim() && !draft.file_base64)"><FileUp :size="15" />{{ busy ? '正在解析…' : '解析并保存草稿' }}</button></footer></form>
    <section v-if="preview" class="panel knowledge-preview"><header><h2>{{ preview.title }} · 版本 {{ preview.version }}</h2><button class="icon-button" aria-label="关闭预览" @click="preview = null"><X :size="18" /></button></header><p>{{ preview.source }} · {{ labels[preview.status] }}</p><pre>{{ preview.content }}</pre><button v-if="preview.status === 'draft'" class="button button-primary" :disabled="busy" @click="change(preview, 'published')"><Check :size="15" />核对无误，审核发布</button></section>
    <section class="panel knowledge-list"><header><h2>资料版本 <small>共 {{ total }} 个</small></h2><button class="text-link" :disabled="busy || loading" @click="refresh">刷新</button></header><p v-if="loading">正在读取资料…</p><p v-else-if="!docs.length" class="empty-state">还没有导入文档。已有演示政策仍可检索。</p><article v-for="doc in docs" :key="doc.id"><div><strong>{{ doc.title }}</strong><span>{{ labels[doc.status] }} · v{{ doc.version }} · {{ doc.chunk_count }} 个片段</span><small>{{ doc.source }} · {{ doc.filename }}</small><small>有效期：{{ doc.effective_on || '未限定起始日' }} — {{ doc.expires_on || '未限定终止日' }}</small></div><div class="knowledge-row-actions"><button class="text-link" :disabled="busy" @click="show(doc)">预览{{ doc.status === 'draft' ? '并审核' : '' }}</button><button class="text-link" :disabled="busy" @click="openImport(doc)">导入新版本</button><button v-if="doc.status === 'published'" class="text-link" :disabled="busy" @click="change(doc,'archived')"><Archive :size="14" />归档</button><button v-else class="text-link" :disabled="busy" @click="remove(doc)"><Trash2 :size="14" />删除</button></div></article><footer><button class="button button-white" :disabled="offset === 0 || busy || loading" @click="offset -= 25; refresh()">上一页</button><span>{{ offset + (docs.length ? 1 : 0) }}–{{ offset + docs.length }} / {{ total }}</span><button class="button button-white" :disabled="offset + 25 >= total || busy || loading" @click="offset += 25; refresh()">下一页</button></footer></section>
    <section class="panel knowledge-search"><h2>检索预览</h2><form @submit.prevent="search"><input v-model="query" required maxlength="1000" placeholder="用居民的说法试试，例如：外地人长期住这里需要办什么？" /><button class="button button-primary" :disabled="busy"><Search :size="15" />检索</button></form><article v-for="item in results" :key="item.chunk_id"><strong>{{ item.title }}</strong><span>{{ item.retrieval_method }} · {{ item.metadata.source }}<template v-if="item.metadata.page"> · 第 {{ item.metadata.page }} 页</template></span><p>{{ item.excerpt }}</p><small>{{ item.chunk_id }}</small></article></section>
  </section>
</template>
