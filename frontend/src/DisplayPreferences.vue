<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Accessibility, Check, Contrast, Sparkles, Type, X } from 'lucide-vue-next'

type Preferences = { size: 'standard' | 'comfortable' | 'large'; contrast: boolean; reduceMotion: boolean }
const key = 'community-display-v1'
function restore(): Preferences {
  try {
    const saved = JSON.parse(localStorage.getItem(key) || '{}')
    return { size: ['standard', 'comfortable', 'large'].includes(saved?.size) ? saved.size : 'comfortable', contrast: saved?.contrast === true, reduceMotion: saved?.reduceMotion === true }
  } catch { return { size: 'comfortable', contrast: false, reduceMotion: false } }
}
const preferences = ref<Preferences>(restore())
const open = ref(false)
const panel = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const choices = [{ id: 'standard', label: '标准', example: 'Aa' }, { id: 'comfortable', label: '舒适', example: 'Aa' }, { id: 'large', label: '大字', example: 'Aa' }] as const
function apply() {
  const root = document.documentElement
  root.dataset.reading = preferences.value.size
  root.dataset.contrast = preferences.value.contrast ? 'strong' : 'normal'
  root.dataset.motion = preferences.value.reduceMotion ? 'reduced' : 'system'
  try { localStorage.setItem(key, JSON.stringify(preferences.value)) } catch { /* Preferences are optional on restricted browsers. */ }
}
watch(preferences, apply, { deep: true, immediate: true })
function outside(event: PointerEvent) { if (event.target instanceof Node && !panel.value?.contains(event.target)) open.value = false }
function keyboard(event: KeyboardEvent) { if (event.key === 'Escape' && open.value) { open.value = false; trigger.value?.focus() } }
onMounted(() => { document.addEventListener('pointerdown', outside); document.addEventListener('keydown', keyboard) })
onBeforeUnmount(() => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', keyboard) })
</script>

<template>
  <aside ref="panel" class="display-preferences" aria-label="阅读与显示设置">
    <Transition name="display-panel">
      <section v-if="open" id="reading-preferences" class="display-panel" aria-label="阅读与动效偏好">
        <header><div><span>为每一位邻居，清晰呈现</span><h2>阅读与显示</h2></div><button aria-label="关闭显示设置" @click="open = false"><X :size="18" /></button></header>
        <fieldset><legend><Type :size="17" />文字大小</legend><div class="reading-options"><button v-for="choice in choices" :key="choice.id" :aria-pressed="preferences.size === choice.id" :class="[choice.id, { selected: preferences.size === choice.id }]" @click="preferences.size = choice.id"><span>{{ choice.example }}</span><strong>{{ choice.label }}</strong><Check v-if="preferences.size === choice.id" :size="13" /></button></div></fieldset>
        <label class="preference-toggle"><span><Contrast :size="18" /><span><strong>增强文字对比</strong><small>加深文字，便于长时间阅读</small></span></span><input v-model="preferences.contrast" type="checkbox" /></label>
        <label class="preference-toggle"><span><Sparkles :size="18" /><span><strong>减少动态效果</strong><small>默认同时尊重系统动态偏好</small></span></span><input v-model="preferences.reduceMotion" type="checkbox" /></label>
        <p>仅保存在当前浏览器，随时可以调整。</p>
      </section>
    </Transition>
    <button ref="trigger" class="reading-trigger" :aria-expanded="open" aria-controls="reading-preferences" @click="open = !open"><Accessibility :size="20" /><span>阅读设置</span><i></i></button>
  </aside>
</template>
