<script setup lang="ts">
import { computed, ref } from 'vue'
import { AlertCircle, Bot, CheckCircle2, ChevronDown, ChevronRight, FileText, Loader2 } from '@lucide/vue'
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

const outputLength = computed(() => props.output.length)

const hasResponseActivity = computed(() => {
  return outputLength.value > 0 || props.isRunning || Boolean(props.streamError)
})

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
  <div v-if="hasResponseActivity" class="flex w-full gap-3 text-sm">
    <div class="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border bg-background text-muted-foreground">
      <Bot class="h-4 w-4" />
    </div>
    <div class="min-w-0 max-w-4xl flex-1">
      <p class="mb-2 text-xs font-semibold text-muted-foreground">Assistant</p>
      <div v-if="isRunning && outputLength === 0" class="space-y-3">
        <div class="h-4 w-2/3 animate-pulse rounded bg-muted" />
        <div class="h-4 w-5/6 animate-pulse rounded bg-muted" />
        <div class="h-4 w-1/2 animate-pulse rounded bg-muted" />
      </div>
      <template v-else-if="blocks.length > 0">
        <div v-for="(block, idx) in blocks" :key="idx">
          <div v-if="block.type === 'thinking'" class="mb-3 rounded border-l-2 border-primary/30 bg-muted/40 p-2 text-[11px] italic text-muted-foreground">
            <p class="mb-1 flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-tighter opacity-70">
              <Bot class="h-3 w-3" />
              Thinking Process
            </p>
            <pre class="whitespace-pre-wrap font-sans">{{ block.thinking || block.reasoning || block.text }}</pre>
          </div>
          <pre v-else-if="block.text" class="mb-2 whitespace-pre-wrap font-sans text-foreground">{{ block.text }}</pre>
          <pre v-else-if="block.type === 'tool_use'" class="mb-2 whitespace-pre-wrap font-sans text-xs italic text-foreground opacity-70">Using tool: {{ block.name }}</pre>
        </div>
      </template>
      <pre v-else-if="typeof output === 'string' && output" class="whitespace-pre-wrap font-sans text-foreground">{{ output }}</pre>
      <pre v-else-if="streamError" class="whitespace-pre-wrap text-destructive">{{ streamError }}</pre>

      <div v-if="ragSources.length > 0" class="mt-3 border-t border-dashed pt-2">
        <p class="mb-1 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          <FileText class="h-3 w-3" />
          Sources used:
        </p>
        <div class="flex flex-wrap gap-1.5">
          <span
            v-for="source in ragSources"
            :key="source"
            class="rounded border border-primary/20 bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary"
          >
            {{ source }}
          </span>
        </div>
      </div>
    </div>
  </div>

  <div v-if="isRunning && (toolEvents.length || mcpEvents.length)" class="mt-4 space-y-3 border-t pb-4 pt-4">
    <p class="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Active Tool Execution</p>

    <div v-for="event in toolEvents" :key="event.id" class="rounded-lg border p-3 text-xs">
      <div
        class="-m-1 mb-2 flex cursor-pointer items-center justify-between rounded p-1 transition-colors hover:bg-muted/50"
        @click="toggleToolEvent(event.id)"
      >
        <span class="flex items-center gap-2 font-semibold">
          <ChevronDown v-if="expandedToolEvents[event.id]" class="h-4 w-4 opacity-50" />
          <ChevronRight v-else class="h-4 w-4 opacity-50" />
          <Loader2 v-if="event.status === 'running'" class="h-3 w-3 animate-spin" />
          <CheckCircle2 v-else-if="event.status === 'done'" class="h-3 w-3 text-emerald-500" />
          <AlertCircle v-else class="h-3 w-3 text-destructive" />
          {{ event.name }}
        </span>
        <span class="text-[10px] uppercase opacity-50">{{ event.status }}</span>
      </div>
      <div v-show="expandedToolEvents[event.id]">
        <div v-if="event.input" class="mb-2 overflow-x-auto rounded bg-muted/30 p-2">
          <p class="mb-1 text-[9px] font-bold opacity-50">INPUT</p>
          <pre class="whitespace-pre-wrap font-mono">{{ event.input }}</pre>
        </div>
        <div v-if="event.output" :class="['overflow-x-auto rounded p-2', event.status === 'error' ? 'bg-destructive/10' : 'bg-emerald-50/30']">
          <p :class="['mb-1 text-[9px] font-bold', event.status === 'error' ? 'text-destructive/70' : 'text-emerald-600/50']">
            {{ event.status === 'error' ? 'ERROR' : 'OUTPUT' }}
          </p>
          <pre class="whitespace-pre-wrap font-mono">{{ event.output }}</pre>
        </div>
      </div>
    </div>

    <div v-for="event in mcpEvents" :key="event.id" class="rounded-lg border p-3 text-xs">
      <div
        class="-m-1 mb-2 flex cursor-pointer items-center justify-between rounded p-1 transition-colors hover:bg-muted/50"
        @click="toggleToolEvent(event.id)"
      >
        <span class="flex items-center gap-2 font-semibold">
          <ChevronDown v-if="expandedToolEvents[event.id]" class="h-4 w-4 opacity-50" />
          <ChevronRight v-else class="h-4 w-4 opacity-50" />
          <Loader2 v-if="event.status === 'running'" class="h-3 w-3 animate-spin" />
          <CheckCircle2 v-else-if="event.status === 'done'" class="h-3 w-3 text-emerald-500" />
          <AlertCircle v-else class="h-3 w-3 text-destructive" />
          MCP: {{ event.name }}
        </span>
        <span class="text-[10px] uppercase opacity-50">{{ event.status }}</span>
      </div>
      <div v-show="expandedToolEvents[event.id]">
        <div v-if="event.input" class="mb-2 overflow-x-auto rounded bg-muted/30 p-2">
          <p class="mb-1 text-[9px] font-bold opacity-50">INPUT</p>
          <pre class="whitespace-pre-wrap font-mono">{{ event.input }}</pre>
        </div>
        <div v-if="event.output" :class="['overflow-x-auto rounded p-2', event.status === 'error' ? 'bg-destructive/10' : 'bg-emerald-50/30']">
          <p :class="['mb-1 text-[9px] font-bold', event.status === 'error' ? 'text-destructive/70' : 'text-emerald-600/50']">
            {{ event.status === 'error' ? 'ERROR' : 'OUTPUT' }}
          </p>
          <pre class="whitespace-pre-wrap font-mono">{{ event.output }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>
