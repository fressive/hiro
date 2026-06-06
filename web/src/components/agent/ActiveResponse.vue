<script setup lang="ts">
import { ref, computed } from 'vue'
import { Bot, FileText, Loader2, CheckCircle2, ChevronDown, ChevronRight } from '@lucide/vue'
import type { EventRecord } from '@/types/agent'
import { isJsonBlocks, parseJsonBlocks } from '@/lib/agent-utils'

const props = defineProps<{
  output: string | any[]
  isRunning: boolean
  streamError: string
  ragSources: string[]
  toolEvents: EventRecord[]
  mcpEvents: EventRecord[]
}>()

const blocks = computed(() => {
  if (Array.isArray(props.output)) return props.output
  if (isJsonBlocks(props.output)) return parseJsonBlocks(props.output)
  return []
})

const expandedToolEvents = ref<Record<string, boolean>>({})

const toggleToolEvent = (id: string) => {
  expandedToolEvents.value[id] = !expandedToolEvents.value[id]
}
</script>

<template>
  <div v-if="output.length > 0 || isRunning || streamError" class="rounded-lg border p-3 text-sm shadow-sm">
    <p class="text-xs font-semibold text-muted-foreground mb-2">Assistant</p>
    <div v-if="isRunning && output.length === 0" class="space-y-3">
      <div class="h-4 w-2/3 rounded bg-muted animate-pulse" />
      <div class="h-4 w-5/6 rounded bg-muted animate-pulse" />
      <div class="h-4 w-1/2 rounded bg-muted animate-pulse" />
    </div>
    <template v-else-if="blocks.length > 0">
      <div v-for="(block, idx) in blocks" :key="idx">
        <div v-if="block.type === 'thinking'" class="text-[11px] italic text-muted-foreground bg-muted/40 p-2 mb-3 rounded border-l-2 border-primary/30">
          <p class="font-bold mb-1 opacity-70 flex items-center gap-1.5 uppercase tracking-tighter text-[9px]">
            <Bot class="h-3 w-3" />
            Thinking Process
          </p>
          <pre class="whitespace-pre-wrap font-sans">{{ block.thinking || block.reasoning || block.text }}</pre>
        </div>
        <pre v-else-if="block.text" class="whitespace-pre-wrap text-foreground font-sans mb-2">{{ block.text }}</pre>
        <pre v-else-if="block.type === 'tool_use'" class="whitespace-pre-wrap text-foreground font-sans mb-2 text-xs opacity-70 italic">Using tool: {{ block.name }}</pre>
      </div>
    </template>
    <pre v-else-if="typeof output === 'string' && output" class="whitespace-pre-wrap text-foreground font-sans">{{ output }}</pre>
    <pre v-else-if="streamError" class="whitespace-pre-wrap text-destructive">{{ streamError }}</pre>
    
    <!-- RAG Sources -->
    <div v-if="ragSources.length > 0" class="mt-3 border-t pt-2 border-dashed">
      <p class="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1 flex items-center gap-1.5">
        <FileText class="h-3 w-3" />
        Sources used:
      </p>
      <div class="flex flex-wrap gap-1.5">
        <span 
          v-for="source in ragSources" 
          :key="source"
          class="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-[10px] font-medium border border-primary/20"
        >
          {{ source }}
        </span>
      </div>
    </div>
  </div>

  <div class="mt-4 space-y-3 pb-4">
    <!-- Live Tool/MCP Events (during run) -->
    <div v-if="isRunning && (toolEvents.length || mcpEvents.length)" class="space-y-2 border-t pt-4">
      <p class="text-[10px] font-bold text-muted-foreground uppercase tracking-widest">Active Tool Execution</p>
      
      <div v-for="event in toolEvents" :key="event.id" class="rounded-lg border p-3 text-xs">
        <div class="flex items-center justify-between mb-2 cursor-pointer hover:bg-muted/50 p-1 -m-1 rounded transition-colors" @click="toggleToolEvent(event.id)">
          <span class="flex items-center gap-2 font-semibold">
            <ChevronDown v-if="expandedToolEvents[event.id]" class="h-4 w-4 opacity-50" />
            <ChevronRight v-else class="h-4 w-4 opacity-50" />
            <Loader2 v-if="event.status === 'running'" class="h-3 w-3 animate-spin" />
            <CheckCircle2 v-else class="h-3 w-3 text-emerald-500" />
            {{ event.name }}
          </span>
          <span class="text-[10px] opacity-50 uppercase">{{ event.status }}</span>
        </div>
        <div v-show="expandedToolEvents[event.id]">
          <div v-if="event.input" class="bg-muted/30 p-2 rounded mb-2 overflow-x-auto">
            <p class="text-[9px] font-bold opacity-50 mb-1">INPUT</p>
            <pre class="whitespace-pre-wrap font-mono">{{ event.input }}</pre>
          </div>
          <div v-if="event.output" class="bg-emerald-50/30 p-2 rounded overflow-x-auto">
            <p class="text-[9px] font-bold text-emerald-600/50 mb-1">OUTPUT</p>
            <pre class="whitespace-pre-wrap font-mono">{{ event.output }}</pre>
          </div>
        </div>
      </div>

      <div v-for="event in mcpEvents" :key="event.id" class="rounded-lg border p-3 text-xs">
        <div class="flex items-center justify-between mb-2 cursor-pointer hover:bg-muted/50 p-1 -m-1 rounded transition-colors" @click="toggleToolEvent(event.id)">
          <span class="flex items-center gap-2 font-semibold">
            <ChevronDown v-if="expandedToolEvents[event.id]" class="h-4 w-4 opacity-50" />
            <ChevronRight v-else class="h-4 w-4 opacity-50" />
            <Loader2 v-if="event.status === 'running'" class="h-3 w-3 animate-spin" />
            <CheckCircle2 v-else class="h-3 w-3 text-emerald-500" />
            MCP: {{ event.name }}
          </span>
          <span class="text-[10px] opacity-50 uppercase">{{ event.status }}</span>
        </div>
        <div v-show="expandedToolEvents[event.id]">
          <div v-if="event.input" class="bg-muted/30 p-2 rounded mb-2 overflow-x-auto">
            <p class="text-[9px] font-bold opacity-50 mb-1">INPUT</p>
            <pre class="whitespace-pre-wrap font-mono">{{ event.input }}</pre>
          </div>
          <div v-if="event.output" class="bg-emerald-50/30 p-2 rounded overflow-x-auto">
            <p class="text-[9px] font-bold text-emerald-600/50 mb-1">OUTPUT</p>
            <pre class="whitespace-pre-wrap font-mono">{{ event.output }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
