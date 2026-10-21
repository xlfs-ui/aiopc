<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import { X, ExternalLink, BookOpen } from 'lucide-vue-next'
import { authRequest } from './auth'
const props = defineProps<{ documentId: string; chunkId?: string }>()
defineEmits<{ close: [] }>()
const controller = new AbortController()
const doc = ref<{ title: string; version: number; source: string; source_url: string; updated_at: string; chunks: { id: string; ordinal: number; page?: number; content: string }[] } | null>(null)
const error = ref('')
onMounted(async () => {
  try {
    doc.value = await authRequest(`/api/knowledge/documents/${encodeURIComponent(props.documentId)}`, { signal: controller.signal })
    await nextTick()
    if (props.chunkId) document.getElementById(`citation-${props.chunkId}`)?.scrollIntoView({ block: 'center' })
  } catch (e) { if (!controller.signal.aborted) error.value = e instanceof Error ? e.message : '资料暂不可用' }
})
onUnmounted(() => controller.abort())
</script>
<template>
  <div class="modal-backdrop" @click.self="$emit('close')"><article class="policy-modal knowledge-document" role="dialog" aria-modal="true" aria-label="知识资料原文"><header class="modal-header"><div><span class="modal-kicker"><BookOpen :size="14" />资料原文</span><h2>{{ doc?.title || '读取资料' }}</h2></div><button class="icon-button" aria-label="关闭资料" @click="$emit('close')"><X :size="19" /></button></header><p v-if="error" class="knowledge-alert" role="alert">{{ error }}</p><p v-else-if="!doc">正在读取…</p><template v-else><p>{{ doc.source }} · 版本 {{ doc.version }} · {{ doc.updated_at.slice(0,10) }}</p><a v-if="doc.source_url" :href="doc.source_url" target="_blank" rel="noopener noreferrer" class="text-link">打开来源网页 <ExternalLink :size="14" /></a><p class="knowledge-note">下列片段含上下文重叠，高亮处是本次引用。请结合完整资料核对办理要求。</p><section v-for="chunk in doc.chunks" :id="`citation-${chunk.id}`" :key="chunk.id" class="knowledge-chunk" :class="{ cited: chunk.id === chunkId }"><small>片段 {{ chunk.ordinal + 1 }}<template v-if="chunk.page"> · 第 {{ chunk.page }} 页</template></small><p>{{ chunk.content }}</p></section></template></article></div>
</template>
