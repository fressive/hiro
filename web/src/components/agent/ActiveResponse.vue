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
  liveTokenUsage: {
    input_tokens: number
    cached_input_tokens: number
    output_tokens: number
  }
  toolEvents: EventRecord[]
  mcpEvents: EventRecord[]
}>()

const outputLength = computed(() => props.output.length)

const hasResponseActivity = computed(() => {
  return outputLength.value > 0 || props.isRunning || Boolean(props.streamError)
})

const liveTokenTotal = computed(() => (
  props.liveTokenUsage.input_tokens + props.liveTokenUsage.output_tokens
))

const blocks = computed(() => {
  if (Array.isArray(props.output)) return props.output
  if (isJsonBlocks(props.output)) return parseJsonBlocks(props.output)
  return []
})

const toolEventMap = computed(() => new Map(props.toolEvents.map((event) => [event.id, event])))
const mcpEventMap = computed(() => new Map(props.mcpEvents.map((event) => [event.id, event])))

const displayBlocks = computed(() => blocks.value.map((block: any) => {
  if (block?.type !== 'tool_event') return block
  const event = block.eventKind === 'mcp'
    ? mcpEventMap.value.get(block.eventId)
    : toolEventMap.value.get(block.eventId)
  return { ...block, event }
}))

const expandedToolEvents = ref<Record<string, boolean>>({})

const toggleToolEvent = (id: string) => {
  expandedToolEvents.value[id] = !expandedToolEvents.value[id]
}

const toolEventLabel = (block: any) => {
  if (!block.event) return block.eventKind === 'mcp' ? 'MCP tool' : 'Tool'
  return block.eventKind === 'mcp' ? `MCP: ${block.event.name}` : block.event.name
}
</script>

<template>
  <div v-if="hasResponseActivity" class="flex w-full gap-3 text-sm">
    <div class="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border bg-background text-muted-foreground">
      <Bot class="h-4 w-4" />
    </div>
    <div class="min-w-0 max-w-4xl flex-1">
      <div class="mb-2 flex items-center justify-between gap-2">
        <p class="text-xs font-semibold text-muted-foreground">Assistant</p>
        <span
          v-if="liveTokenTotal > 0"
          class="shrink-0 rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
        >
          in:{{ liveTokenUsage.input_tokens }}
          <template v-if="liveTokenUsage.cached_input_tokens">/cached:{{ liveTokenUsage.cached_input_tokens }}</template>
          /out:{{ liveTokenUsage.output_tokens }}
        </span>
      </div>
      <div v-if="isRunning && outputLength === 0" class="space-y-3">
        <div class="h-4 w-2/3 animate-pulse rounded bg-muted" />
        <div class="h-4 w-5/6 animate-pulse rounded bg-muted" />
        <div class="h-4 w-1/2 animate-pulse rounded bg-muted" />
      </div>
      <template v-else-if="displayBlocks.length > 0">
        <div v-for="(block, idx) in displayBlocks" :key="idx">
          <div v-if="block.type === 'thinking'" class="mb-3 rounded border-l-2 border-primary/30 bg-muted/40 p-2 text-[11px] italic text-muted-foreground">
            <p class="mb-1 flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-tighter opacity-70">
              <Bot class="h-3 w-3" />
              Thinking Process
            </p>
            <pre class="whitespace-pre-wrap font-sans">{{ block.thinking || block.reasoning || block.text }}</pre>
          </div>
          <pre v-else-if="block.text" class="mb-2 whitespace-pre-wrap font-sans text-foreground">{{ block.text }}</pre>
          <div v-else-if="block.type === 'tool_event' && block.event" class="mb-3 rounded-lg border bg-muted/10 p-3 text-xs">
            <div
              class="-m-1 flex cursor-pointer items-center justify-between gap-2 rounded p-1 transition-colors hover:bg-muted/50"
              @click="toggleToolEvent(block.event.id)"
            >
              <span class="flex min-w-0 items-center gap-2 font-semibold">
                <ChevronDown v-if="expandedToolEvents[block.event.id]" class="h-4 w-4 shrink-0 opacity-50" />
                <ChevronRight v-else class="h-4 w-4 shrink-0 opacity-50" />
                <Loader2 v-if="block.event.status === 'running'" class="h-3 w-3 shrink-0 animate-spin" />
                <CheckCircle2 v-else-if="block.event.status === 'done'" class="h-3 w-3 shrink-0 text-emerald-500" />
                <AlertCircle v-else class="h-3 w-3 shrink-0 text-destructive" />
                <span class="truncate">{{ toolEventLabel(block) }}</span>
              </span>
              <span class="text-[10px] uppercase opacity-50">{{ block.event.status }}</span>
            </div>
            <div v-show="expandedToolEvents[block.event.id]" class="mt-2">
              <div v-if="block.event.input" class="mb-2 overflow-x-auto rounded bg-muted/30 p-2">
                <p class="mb-1 text-[9px] font-bold opacity-50">INPUT</p>
                <pre class="whitespace-pre-wrap font-mono">{{ block.event.input }}</pre>
              </div>
              <div v-if="block.event.output" :class="['overflow-x-auto rounded p-2', block.event.status === 'error' ? 'bg-destructive/10' : 'bg-emerald-50/30']">
                <p :class="['mb-1 text-[9px] font-bold', block.event.status === 'error' ? 'text-destructive/70' : 'text-emerald-600/50']">
                  {{ block.event.status === 'error' ? 'ERROR' : 'OUTPUT' }}
                </p>
                <pre class="whitespace-pre-wrap font-mono">{{ block.event.output }}</pre>
              </div>
            </div>
          </div>
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
</template>
