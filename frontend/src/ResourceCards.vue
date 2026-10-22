<script setup lang="ts">
import { ArrowUpRight, BookOpen, ClipboardList, Compass, CalendarDays, ChevronDown, ShieldCheck } from 'lucide-vue-next'
import type { Resource } from './types'
import { officialLink } from './officialLinks'
defineProps<{ items: Resource[] }>()
defineEmits<{ open: [resource: Resource] }>()
const labels = { knowledge: '知识文档', policy: '政策资料', service: '办事服务', activity: '社区活动', ticket: '我的工单' }
const icons = { knowledge: BookOpen, policy: BookOpen, service: Compass, activity: CalendarDays, ticket: ClipboardList }
</script>

<template>
  <div class="resource-list">
    <article v-for="(item, index) in items" :key="item.id" class="resource-card" :style="{ '--card-index': index }">
      <div class="resource-top"><span class="resource-kind" :class="item.kind"><component :is="icons[item.kind]" :size="13" />{{ labels[item.kind] }}</span><span class="resource-index">{{ String(index + 1).padStart(2, '0') }}</span></div>
      <h3>{{ item.title }}</h3><p>{{ item.description }}</p>
      <div v-if="item.meta" class="resource-meta">{{ item.meta }}</div>
      <details v-if="item.steps?.length" class="resource-workflow"><summary>办理步骤与所需信息 <ChevronDown :size="13" /></summary><ol><li v-for="(step, i) in item.steps" :key="step"><span>{{ i + 1 }}</span>{{ step }}</li></ol><div v-if="item.materials?.length" class="resource-materials"><strong>请准备</strong><span v-for="material in item.materials" :key="material">{{ material }}</span></div></details>
      <div v-if="item.source" class="resource-source"><ShieldCheck :size="12" /><span>{{ item.source }} · {{ item.updated_at }} · {{ item.is_demo === false ? '已审核发布' : '演示资料' }}</span></div>
      <a v-if="item.kind === 'policy' && officialLink(item.source_url)" class="official-policy-link" :href="officialLink(item.source_url)" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">查看官方原文 <ArrowUpRight :size="15" /></a>
      <button class="resource-open" @click="$emit('open', item)">{{ item.action.label }}<ArrowUpRight :size="15" /></button>
    </article>
  </div>
</template>
