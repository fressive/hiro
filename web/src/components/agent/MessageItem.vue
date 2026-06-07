<script setup lang="ts">
import { computed, ref } from 'vue'
import { AlertCircle, Bot, CheckCircle2, ChevronDown, ChevronRight, FileText, Loader2, Wrench } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import type { AgentMessage, EventRecord } from '@/types/agent'
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

const agentDisplayNames: Record<string, string> = {
  information_collect_agent: 'Information Collect Agent',
  main_agent: 'Main Agent',
  writeup_agent: 'Writeup Agent',
}

const messageAuthorLabel = computed(() => {
  if (props.message.role === 'user') return 'You'
  if (props.message.role !== 'assistant') return props.message.role
  const name = props.message.name || ''
  if (!name) return 'Assistant'
  return agentDisplayNames[name] || name
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
})

const expandedTraceEvents = ref<Record<string, boolean>>({})

const toggleTraceEvent = (id: string) => {
  expandedTraceEvents.value[id] = !expandedTraceEvents.value[id]
}
</script>

<template>
  <div
    v-if="message.role !== 'tool'"
    :class="['group flex w-full gap-3 text-sm', message.role === 'user' ? 'justify-end' : 'justify-start']"
  >
    <div
      v-if="message.role === 'assistant'"
      class="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border bg-background text-muted-foreground"
    >
      <Bot class="h-4 w-4" />
    </div>
    <div :class="['min-w-0', message.role === 'user' ? 'max-w-[min(38rem,85%)]' : 'max-w-4xl flex-1']">
      <div
        :class="[
          'mb-1 flex items-center gap-2 text-xs font-medium text-muted-foreground',
          message.role === 'user' ? 'justify-end' : 'justify-between'
        ]"
      >
        <span class="flex min-w-0 items-center gap-1.5">
          <span class="truncate">{{ messageAuthorLabel }}</span>
          <span
            v-if="message.role === 'assistant' && message.name"
            class="rounded border border-primary/15 bg-primary/10 px-1.5 py-0.5 text-[9px] font-normal text-primary"
          >
            Agent
          </span>
        </span>
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
      <div :class="[message.role === 'user' ? 'rounded-2xl rounded-tr-md bg-muted px-4 py-3' : '']">
        <div v-if="traceToolEvents.length > 0" class="mb-3 space-y-2 rounded-lg border border-dashed bg-muted/10 p-3">
          <p class="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Tool Execution Trace</p>
          <div v-for="event in traceToolEvents" :key="event.id" class="rounded-md border bg-background p-2 text-xs">
            <div
              class="-m-1 flex cursor-pointer items-center justify-between gap-2 rounded p-1 transition-colors hover:bg-muted/50"
              @click="toggleTraceEvent(event.id)"
            >
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

        <template v-if="isJsonBlocks(message.content)">
          <div v-for="(block, idx) in parseJsonBlocks(message.content)" :key="idx">
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
        <pre v-else-if="message.content" class="whitespace-pre-wrap font-sans text-foreground">{{ message.content }}</pre>

        <div v-if="message.tool_calls && message.tool_calls.length > 0" class="mt-2 space-y-2 border-t border-dashed pt-2">
          <p class="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Initiating Tool Calls:</p>
          <div v-for="tc in message.tool_calls" :key="tc.id" class="flex items-center gap-2 rounded bg-muted/40 p-2 text-xs">
            <Wrench class="h-3 w-3" />
            <span class="font-mono">{{ tc.name }}</span>
            <span class="truncate text-[9px] opacity-50">({{ tc.args }})</span>
          </div>
        </div>

        <div v-if="message.extra_metadata?.rag_sources?.length" class="mt-3 border-t border-dashed pt-2">
          <p class="mb-1 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            <FileText class="h-3 w-3" />
            Sources used:
          </p>
          <div class="flex flex-wrap gap-1.5">
            <span
              v-for="source in message.extra_metadata.rag_sources"
              :key="source"
              class="rounded border border-primary/20 bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary"
            >
              {{ source }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div
    v-else
    class="ml-10 overflow-hidden border-l border-dashed py-2 pl-3 text-xs text-muted-foreground"
  >
    <p class="mb-2 flex items-center justify-between font-semibold">
      <span class="flex items-center gap-1.5">
        <Wrench class="h-3 w-3" />
        Tool: {{ message.name || 'Result' }}
      </span>
      <span class="font-mono text-[10px] opacity-50">{{ message.tool_call_id }}</span>
    </p>

    <div class="group relative">
      <pre
        class="whitespace-pre-wrap font-mono text-xs text-foreground transition-all duration-300"
        :class="[!isExpanded && message.content.length > 500 ? 'max-h-[120px] overflow-hidden mask-fade' : '']"
      >{{ message.content }}</pre>

      <div
        v-if="message.content.length > 500"
        class="mt-2 flex justify-center"
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
