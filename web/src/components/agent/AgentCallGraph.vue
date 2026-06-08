<script setup lang="ts">
import { computed } from 'vue'
import { AlertCircle, Bot, CheckCircle2, Circle, Loader2 } from '@lucide/vue'
import type { SubagentEventRecord } from '@/types/agent'

const props = defineProps<{
  subagentEvents: SubagentEventRecord[]
  isRunning: boolean
}>()

type NodeStatus = 'idle' | 'running' | 'done' | 'error'

type CallNode = {
  id: string
  label: string
  path: string
  parentId: string | null
  status: NodeStatus
  input?: string | null
  depth: number
  x: number
  y: number
}

const rowHeight = 72
const depthWidth = 38
const nodeTopOffset = 22

const agentDisplayNames: Record<string, string> = {
  information_collect_agent: 'Information Collect Agent',
  main_agent: 'Main Agent',
  writeup_agent: 'Writeup Agent',
}

const formatAgentName = (name?: string | null) => {
  if (!name) return 'Subagent'
  if (agentDisplayNames[name]) return agentDisplayNames[name]
  return name
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

const normalizeStatus = (status?: string | null): NodeStatus => {
  if (!status || status === 'started') return 'running'
  if (status === 'completed') return 'done'
  if (status === 'failed' || status === 'cancelled') return 'error'
  if (status === 'done' || status === 'running' || status === 'error') return status
  return 'running'
}

const eventId = (event: SubagentEventRecord, index: number) => (
  event.id || event.path || `${event.name || 'subagent'}-${index + 1}`
)

const parentPath = (path?: string | null) => {
  if (!path) return ''
  const segments = path.split('/').filter(Boolean)
  if (segments.length <= 1) return ''
  return segments.slice(0, -1).join('/')
}

const orderedEvents = computed(() => props.subagentEvents.map((event, index) => ({
  ...event,
  id: eventId(event, index),
})))

const graphNodes = computed<CallNode[]>(() => {
  const childHasError = orderedEvents.value.some((event) => (
    normalizeStatus(event.status) === 'error'
  ))
  const rootStatus: NodeStatus = props.isRunning
    ? 'running'
    : childHasError
      ? 'error'
      : orderedEvents.value.length > 0
        ? 'done'
        : 'idle'
  const nodes: CallNode[] = [
    {
      id: 'main_agent',
      label: 'Main Agent',
      path: '',
      parentId: null,
      status: rootStatus,
      depth: 0,
      x: 0,
      y: nodeTopOffset,
    },
  ]
  const pathToId = new Map<string, string>()

  orderedEvents.value.forEach((event, index) => {
    const path = event.path || event.id
    const id = `subagent:${event.id}`
    const parent = parentPath(path)
    const parentId = parent ? pathToId.get(parent) || 'main_agent' : 'main_agent'
    const parentNode = nodes.find((node) => node.id === parentId)
    const depth = parentNode ? parentNode.depth + 1 : 1
    pathToId.set(path, id)
    nodes.push({
      id,
      label: formatAgentName(event.name),
      path,
      parentId,
      status: normalizeStatus(event.status),
      input: event.input,
      depth,
      x: depth * depthWidth,
      y: nodeTopOffset + (index + 1) * rowHeight,
    })
  })

  return nodes
})

const graphEdges = computed(() => {
  const nodeMap = new Map(graphNodes.value.map((node) => [node.id, node]))
  return graphNodes.value
    .filter((node) => node.parentId)
    .map((node) => {
      const parent = nodeMap.get(node.parentId || '')
      if (!parent) return null
      const startX = parent.x + 14
      const startY = parent.y + 20
      const endX = node.x + 14
      const endY = node.y
      const midX = Math.max(startX + 20, endX - 18)
      return {
        id: `${parent.id}->${node.id}`,
        d: `M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${endY}, ${endX} ${endY}`,
      }
    })
    .filter(Boolean)
})

const graphHeight = computed(() => (
  nodeTopOffset * 2 + Math.max(1, graphNodes.value.length) * rowHeight
))

const nodeStyle = (node: CallNode) => ({
  transform: `translate(${node.x}px, ${node.y - 20}px)`,
  width: `calc(100% - ${node.x + 8}px)`,
})

const statusLabel = (status: NodeStatus) => {
  if (status === 'done') return 'Done'
  if (status === 'error') return 'Error'
  if (status === 'running') return 'Running'
  return 'Idle'
}

const statusClass = (status: NodeStatus) => {
  if (status === 'done') return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300'
  if (status === 'error') return 'border-destructive/30 bg-destructive/10 text-destructive'
  if (status === 'running') return 'border-primary/25 bg-primary/10 text-primary'
  return 'border-muted bg-muted/30 text-muted-foreground'
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col overflow-hidden bg-muted/10">
    <div class="shrink-0 border-b px-4 py-3">
      <div class="flex items-center justify-between gap-2">
        <p class="text-sm font-semibold">Agent Chain</p>
        <span class="rounded bg-background px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
          {{ graphNodes.length }}
        </span>
      </div>
    </div>

    <div class="min-h-0 flex-1 overflow-auto px-3 py-4">
      <div class="relative min-w-0" :style="{ height: `${graphHeight}px` }">
        <svg
          class="pointer-events-none absolute inset-0 h-full w-full overflow-visible"
          :height="graphHeight"
          aria-hidden="true"
        >
          <path
            v-for="edge in graphEdges"
            :key="edge?.id"
            :d="edge?.d"
            class="fill-none stroke-border"
            stroke-width="1.5"
          />
        </svg>

        <div
          v-for="node in graphNodes"
          :key="node.id"
          class="absolute left-0 top-0 min-w-0"
          :style="nodeStyle(node)"
        >
          <div
            :class="[
              'flex h-11 min-w-0 items-center gap-2 rounded-md border bg-background px-2 shadow-sm',
              node.status === 'running' && 'ring-1 ring-primary/15',
            ]"
            :title="node.input || node.path || node.label"
          >
            <div
              :class="[
                'flex h-6 w-6 shrink-0 items-center justify-center rounded-full border',
                statusClass(node.status),
              ]"
            >
              <Loader2 v-if="node.status === 'running'" class="h-3.5 w-3.5 animate-spin" />
              <CheckCircle2 v-else-if="node.status === 'done'" class="h-3.5 w-3.5" />
              <AlertCircle v-else-if="node.status === 'error'" class="h-3.5 w-3.5" />
              <Circle v-else class="h-3.5 w-3.5" />
            </div>
            <div class="min-w-0 flex-1">
              <p class="truncate text-xs font-medium">{{ node.label }}</p>
              <p class="truncate text-[10px] text-muted-foreground">
                <Bot v-if="node.id === 'main_agent'" class="mr-1 inline h-3 w-3 align-[-2px]" />
                {{ statusLabel(node.status) }}
              </p>
            </div>
          </div>
        </div>
      </div>

      <p
        v-if="subagentEvents.length === 0"
        class="mt-1 text-xs text-muted-foreground"
      >
        No subagent calls yet.
      </p>
    </div>
  </div>
</template>
