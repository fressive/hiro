<script setup lang="ts">
import { ref, computed } from 'vue'
import { AlertCircle, Bot, CheckCircle2, ChevronDown, ChevronRight, Circle, FileText, Loader2, MinusCircle } from '@lucide/vue'
import type { EventRecord, GraphNodeRecord, GraphNodeStatus } from '@/types/agent'
import { isJsonBlocks, parseJsonBlocks } from '@/lib/agent-utils'

const props = defineProps<{
  output: string | any[]
  isRunning: boolean
  streamError: string
  ragSources: string[]
  toolEvents: EventRecord[]
  mcpEvents: EventRecord[]
  graphNodes: GraphNodeRecord[]
}>()

const outputLength = computed(() => props.output.length)

const hasGraphActivity = computed(() => props.isRunning && props.graphNodes.length > 0)

const hasResponseActivity = computed(() => {
  return outputLength.value > 0 || props.isRunning || Boolean(props.streamError) || hasGraphActivity.value
})

const blocks = computed(() => {
  if (Array.isArray(props.output)) return props.output
  if (isJsonBlocks(props.output)) return parseJsonBlocks(props.output)
  return []
})

const activeGraphNode = computed(() => {
  return props.graphNodes.find((node) => node.status === 'running') || null
})

const expandedToolEvents = ref<Record<string, boolean>>({})

const toggleToolEvent = (id: string) => {
  expandedToolEvents.value[id] = !expandedToolEvents.value[id]
}

const graphNodeClass = (status: GraphNodeStatus) => {
  if (status === 'running') return 'border-primary bg-primary/10 text-primary shadow-sm'
  if (status === 'done') return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
  if (status === 'skipped') return 'border-muted bg-muted/40 text-muted-foreground'
  if (status === 'error') return 'border-destructive/50 bg-destructive/10 text-destructive'
  return 'border-border bg-background text-muted-foreground'
}

const graphConnectorClass = (index: number) => {
  const current = props.graphNodes[index]
  const next = props.graphNodes[index + 1]
  if (current?.status === 'error' || next?.status === 'error') return 'bg-destructive/50'
  if (current?.status === 'done' && next?.status !== 'pending') return 'bg-primary/60'
  if (current?.status === 'done') return 'bg-primary/30'
  return 'bg-border'
}

const graphStatusLabel = (status: GraphNodeStatus) => {
  if (status === 'running') return 'Running'
  if (status === 'skipped') return 'Skipped'
  if (status === 'error') return 'Error'
  return 'Pending'
}

const graphNodeCaption = (node: GraphNodeRecord) => {
  if (node.status === 'done') return node.label
  return graphStatusLabel(node.status)
}
</script>

<template>
  <div v-if="hasResponseActivity" class="flex w-full gap-3 text-sm">
    <div class="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border bg-background text-muted-foreground">
      <Bot class="h-4 w-4" />
    </div>
    <div class="min-w-0 max-w-4xl flex-1">
    <div v-if="graphNodes.length > 0" class="mb-3 rounded-lg border bg-muted/20 p-3">
      <div class="flex items-center justify-between gap-3">
        <p class="text-xs font-semibold text-muted-foreground">Execution Graph</p>
        <span class="max-w-[55%] truncate text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          {{ activeGraphNode ? activeGraphNode.label : (isRunning ? 'Starting' : 'Complete') }}
        </span>
      </div>
      <div class="mt-3 overflow-x-auto pb-1">
        <div class="flex min-w-max items-center gap-2">
          <template v-for="(node, index) in graphNodes" :key="node.id">
            <div
              :class="['flex h-16 w-32 shrink-0 items-center gap-2 rounded-md border px-2 transition-colors', graphNodeClass(node.status)]"
              :title="node.description || node.label"
            >
              <div class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-background/80">
                <Loader2 v-if="node.status === 'running'" class="h-4 w-4 animate-spin" />
                <CheckCircle2 v-else-if="node.status === 'done'" class="h-4 w-4" />
                <MinusCircle v-else-if="node.status === 'skipped'" class="h-4 w-4" />
                <AlertCircle v-else-if="node.status === 'error'" class="h-4 w-4" />
                <Circle v-else class="h-4 w-4" />
              </div>
              <div class="min-w-0">
                <p class="truncate text-xs font-semibold" :title="node.label">{{ node.label }}</p>
                <p class="truncate text-[10px] opacity-70">
                  {{ graphNodeCaption(node) }}<template v-if="node.optional"> · Optional</template>
                </p>
              </div>
            </div>
            <div
              v-if="index < graphNodes.length - 1"
              :class="['h-px w-8 shrink-0 transition-colors', graphConnectorClass(index)]"
            />
          </template>
        </div>
      </div>
    </div>

    <p class="text-xs font-semibold text-muted-foreground mb-2">Assistant</p>
    <div v-if="isRunning && outputLength === 0" class="space-y-3">
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
            <CheckCircle2 v-else-if="event.status === 'done'" class="h-3 w-3 text-emerald-500" />
            <AlertCircle v-else class="h-3 w-3 text-destructive" />
            {{ event.name }}
          </span>
          <span class="text-[10px] opacity-50 uppercase">{{ event.status }}</span>
        </div>
        <div v-show="expandedToolEvents[event.id]">
          <div v-if="event.input" class="bg-muted/30 p-2 rounded mb-2 overflow-x-auto">
            <p class="text-[9px] font-bold opacity-50 mb-1">INPUT</p>
            <pre class="whitespace-pre-wrap font-mono">{{ event.input }}</pre>
          </div>
          <div v-if="event.output" :class="['p-2 rounded overflow-x-auto', event.status === 'error' ? 'bg-destructive/10' : 'bg-emerald-50/30']">
            <p :class="['text-[9px] font-bold mb-1', event.status === 'error' ? 'text-destructive/70' : 'text-emerald-600/50']">
              {{ event.status === 'error' ? 'ERROR' : 'OUTPUT' }}
            </p>
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
            <CheckCircle2 v-else-if="event.status === 'done'" class="h-3 w-3 text-emerald-500" />
            <AlertCircle v-else class="h-3 w-3 text-destructive" />
            MCP: {{ event.name }}
          </span>
          <span class="text-[10px] opacity-50 uppercase">{{ event.status }}</span>
        </div>
        <div v-show="expandedToolEvents[event.id]">
          <div v-if="event.input" class="bg-muted/30 p-2 rounded mb-2 overflow-x-auto">
            <p class="text-[9px] font-bold opacity-50 mb-1">INPUT</p>
            <pre class="whitespace-pre-wrap font-mono">{{ event.input }}</pre>
          </div>
          <div v-if="event.output" :class="['p-2 rounded overflow-x-auto', event.status === 'error' ? 'bg-destructive/10' : 'bg-emerald-50/30']">
            <p :class="['text-[9px] font-bold mb-1', event.status === 'error' ? 'text-destructive/70' : 'text-emerald-600/50']">
              {{ event.status === 'error' ? 'ERROR' : 'OUTPUT' }}
            </p>
            <pre class="whitespace-pre-wrap font-mono">{{ event.output }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
