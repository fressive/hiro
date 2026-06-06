<script setup lang="ts">
import { computed, ref } from 'vue'
import { AlertCircle, Bot, CheckCircle2, ChevronDown, ChevronRight, Circle, FileText, Loader2, MinusCircle, Wrench } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import type { AgentMessage, EventRecord, GraphNodeRecord, GraphNodeStatus } from '@/types/agent'
import { isJsonBlocks, parseJsonBlocks } from '@/lib/agent-utils'

const props = defineProps<{
  message: AgentMessage
  isExpanded?: boolean
}>()

const emit = defineEmits<{
  (e: 'toggle-expand'): void
}>()

const traceToolEvents = computed<EventRecord[]>(() => {
  return [
    ...(props.message.extra_metadata?.tool_events || []),
    ...(props.message.extra_metadata?.mcp_events || []).map((event) => ({
      ...event,
      name: `MCP: ${event.name}`,
    })),
  ]
})

const graphNodes = computed(() => props.message.extra_metadata?.graph_nodes || [])
const expandedTraceEvents = ref<Record<string, boolean>>({})

const toggleTraceEvent = (id: string) => {
  expandedTraceEvents.value[id] = !expandedTraceEvents.value[id]
}

const graphNodeClass = (status: GraphNodeStatus) => {
  if (status === 'running') return 'border-primary bg-primary/10 text-primary shadow-sm'
  if (status === 'done') return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
  if (status === 'skipped') return 'border-muted bg-muted/40 text-muted-foreground'
  if (status === 'error') return 'border-destructive/50 bg-destructive/10 text-destructive'
  return 'border-border bg-background text-muted-foreground'
}

const graphConnectorClass = (index: number) => {
  const current = graphNodes.value[index]
  const next = graphNodes.value[index + 1]
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
  <!-- Standard Message -->
  <div 
    v-if="message.role !== 'tool'"
    class="rounded-lg border p-3 text-sm shadow-sm"
    :class="message.role === 'assistant' ? 'bg-background' : 'bg-muted/10'"
  >
    <div class="text-xs font-semibold text-muted-foreground mb-2 flex items-center justify-between">
      <span>{{ message.role === 'user' ? 'User' : 'Assistant' }}</span>
      <div class="flex items-center gap-2">
        <span v-if="message.model" class="text-[9px] px-1 rounded bg-primary/10 text-primary border border-primary/20 font-medium">
          {{ message.model }}
        </span>
        <span v-if="message.input_tokens || message.output_tokens" class="text-[9px] px-1 rounded bg-muted font-mono opacity-80">
        <template v-if="message.input_tokens">in:{{ message.input_tokens }}</template>
          <template v-if="message.input_tokens && message.output_tokens">/</template>
          <template v-if="message.output_tokens">out:{{ message.output_tokens }}</template>
        </span>
        <span v-if="message.created_at" class="text-[10px] font-normal opacity-50">{{ new Date(message.created_at).toLocaleTimeString() }}</span>
      </div>
    </div>

    <div v-if="graphNodes.length > 0" class="mb-3 rounded-lg border bg-muted/20 p-3">
      <p class="text-xs font-semibold text-muted-foreground">Execution Graph</p>
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

    <div v-if="traceToolEvents.length > 0" class="mb-3 space-y-2 rounded-lg border border-dashed bg-muted/10 p-3">
      <p class="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Tool Execution Trace</p>
      <div v-for="event in traceToolEvents" :key="event.id" class="rounded-md border bg-background p-2 text-xs">
        <div class="flex items-center justify-between gap-2 cursor-pointer hover:bg-muted/50 p-1 -m-1 rounded transition-colors" @click="toggleTraceEvent(event.id)">
          <span class="flex min-w-0 items-center gap-2 font-semibold">
            <ChevronDown v-if="expandedTraceEvents[event.id]" class="h-4 w-4 shrink-0 opacity-50" />
            <ChevronRight v-else class="h-4 w-4 shrink-0 opacity-50" />
            <Loader2 v-if="event.status === 'running'" class="h-3 w-3 shrink-0 animate-spin" />
            <CheckCircle2 v-else-if="event.status === 'done'" class="h-3 w-3 shrink-0 text-emerald-500" />
            <AlertCircle v-else class="h-3 w-3 shrink-0 text-destructive" />
            <span class="truncate">{{ event.name }}</span>
          </span>
          <span class="text-[10px] uppercase opacity-50">{{ event.status }}</span>
        </div>
        <div v-show="expandedTraceEvents[event.id]" class="mt-2">
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
    
    <!-- Multi-part Content Blocks (e.g. Thinking + Text) -->
    <template v-if="isJsonBlocks(message.content)">
      <div v-for="(block, idx) in parseJsonBlocks(message.content)" :key="idx">
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
    <pre v-else-if="message.content" class="whitespace-pre-wrap text-foreground font-sans">{{ message.content }}</pre>
    
    <!-- Inline Tool Calls (within Assistant message) -->
    <div v-if="message.tool_calls && message.tool_calls.length > 0" class="mt-2 space-y-2 border-t pt-2 border-dashed">
      <p class="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Initiating Tool Calls:</p>
      <div v-for="tc in message.tool_calls" :key="tc.id" class="text-xs bg-muted/40 p-2 rounded flex items-center gap-2">
        <Wrench class="h-3 w-3" />
        <span class="font-mono">{{ tc.name }}</span>
        <span class="opacity-50 text-[9px] truncate">({{ tc.args }})</span>
      </div>
    </div>

    <!-- RAG Sources (from extra_metadata) -->
    <div v-if="message.extra_metadata?.rag_sources?.length" class="mt-3 border-t pt-2 border-dashed">
      <p class="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1 flex items-center gap-1.5">
        <FileText class="h-3 w-3" />
        Sources used:
      </p>
      <div class="flex flex-wrap gap-1.5">
        <span 
          v-for="source in message.extra_metadata.rag_sources" 
          :key="source"
          class="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-[10px] font-medium border border-primary/20"
        >
          {{ source }}
        </span>
      </div>
    </div>
  </div>

  <!-- Tool Execution Result -->
  <div 
    v-else
    class="rounded-lg border border-dashed p-3 text-sm bg-muted/20 overflow-hidden"
  >
    <p class="text-xs font-semibold text-muted-foreground mb-2 flex items-center justify-between">
      <span class="flex items-center gap-1.5">
        <Wrench class="h-3 w-3" />
        Tool: {{ message.name || 'Result' }}
      </span>
      <span class="text-[10px] opacity-50 font-mono">{{ message.tool_call_id }}</span>
    </p>
    
    <div class="relative group">
      <pre 
        class="whitespace-pre-wrap text-foreground font-mono text-xs transition-all duration-300"
        :class="[!isExpanded && message.content.length > 500 ? 'max-h-[120px] overflow-hidden mask-fade' : '']"
      >{{ message.content }}</pre>
      
      <div 
        v-if="message.content.length > 500" 
        class="flex justify-center mt-2"
        :class="[!isExpanded ? 'absolute bottom-0 left-0 right-0 pt-8 pb-1 bg-gradient-to-t from-muted/30 to-transparent' : '']"
      >
        <Button 
          variant="ghost" 
          size="sm" 
          class="h-6 px-2 text-[10px] hover:bg-muted/50" 
          @click="emit('toggle-expand')"
        >
          {{ isExpanded ? 'Show Less' : 'Show More' }}
        </Button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mask-fade {
  mask-image: linear-gradient(to bottom, black 60%, transparent 100%);
}
</style>
