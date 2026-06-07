<script setup lang="ts">
import { computed, ref } from 'vue'
import { Bot, RotateCcw, ZoomIn, ZoomOut } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import type { GraphEdgeRecord, GraphNodeRecord, GraphNodeStatus } from '@/types/agent'

const props = defineProps<{
  graphNodes: GraphNodeRecord[]
  graphEdges: GraphEdgeRecord[]
  isRunning: boolean
  selectedAgentName?: string | null
}>()

const emit = defineEmits<{
  (e: 'select-agent-node', node: GraphNodeRecord): void
}>()

const GRAPH_WIDTH = 340
const NODE_WIDTH = 156
const NODE_HEIGHT = 62
const TOP_PADDING = 44
const BOTTOM_PADDING = 56
const LAYER_GAP = 104
const SIDE_PADDING = 82
const GRAPH_CANVAS_TOP = 24
const GRAPH_ZOOM_MIN = 0.7
const GRAPH_ZOOM_MAX = 1.8
const GRAPH_ZOOM_STEP = 0.1

type LayoutNode = GraphNodeRecord & {
  x: number
  y: number
  depth: number
}

type LayoutEdge = GraphEdgeRecord & {
  id: string
  path: string
  labelX: number
  labelY: number
}

const activeGraphNode = computed(() => {
  return props.graphNodes.find((node) => node.status === 'running') || null
})

const graphZoom = ref(1)
const graphPanX = ref(0)
const graphPanY = ref(0)
const graphViewport = ref<HTMLDivElement | null>(null)
const isPanningGraph = ref(false)
let panPointerId: number | null = null
let panStartX = 0
let panStartY = 0
let panStartGraphX = 0
let panStartGraphY = 0

const panelStatus = computed(() => {
  if (activeGraphNode.value) return activeGraphNode.value.label
  if (props.isRunning) return 'Starting'
  if (props.graphNodes.length > 0) return 'Complete'
  return 'Idle'
})

const nodeMap = computed(() => {
  return new Map(props.graphNodes.map((node) => [node.id, node]))
})

const normalizedEdges = computed<GraphEdgeRecord[]>(() => {
  const knownNodes = nodeMap.value
  const edges = props.graphEdges.filter((edge) => (
    knownNodes.has(edge.from) && knownNodes.has(edge.to)
  ))

  if (edges.length > 0) return edges

  return props.graphNodes.slice(0, -1).map((node, index) => ({
    from: node.id,
    to: props.graphNodes[index + 1].id,
  }))
})

const graphLayout = computed<LayoutNode[]>(() => {
  const nodes = props.graphNodes
  if (nodes.length === 0) return []

  const incoming = new Map<string, string[]>()
  const outgoing = new Map<string, string[]>()
  for (const node of nodes) {
    incoming.set(node.id, [])
    outgoing.set(node.id, [])
  }

  for (const edge of normalizedEdges.value) {
    incoming.get(edge.to)?.push(edge.from)
    outgoing.get(edge.from)?.push(edge.to)
  }

  const remainingIncoming = new Map<string, number>()
  for (const node of nodes) {
    remainingIncoming.set(node.id, (incoming.get(node.id) || []).length)
  }

  const roots = nodes.filter((node) => (incoming.get(node.id) || []).length === 0)
  const queue = roots.length > 0 ? roots.map((node) => node.id) : [nodes[0].id]
  const depths = new Map<string, number>()
  for (const id of queue) {
    depths.set(id, 0)
  }

  const visited = new Set<string>()
  let cursor = 0
  while (cursor < queue.length) {
    const id = queue[cursor]
    cursor += 1
    visited.add(id)
    const depth = depths.get(id) || 0
    for (const next of outgoing.get(id) || []) {
      const nextDepth = depth + 1
      const currentDepth = depths.get(next)
      if (currentDepth === undefined || nextDepth > currentDepth) {
        depths.set(next, nextDepth)
      }
      const nextRemaining = Math.max((remainingIncoming.get(next) || 0) - 1, 0)
      remainingIncoming.set(next, nextRemaining)
      if (nextRemaining === 0) queue.push(next)
    }
  }

  let fallbackDepth = Math.max(0, ...depths.values())
  for (const node of nodes) {
    if (!visited.has(node.id)) {
      fallbackDepth += 1
      depths.set(node.id, fallbackDepth)
    }
  }

  const byDepth = new Map<number, GraphNodeRecord[]>()
  for (const node of nodes) {
    const depth = depths.get(node.id) || 0
    const layer = byDepth.get(depth) || []
    layer.push(node)
    byDepth.set(depth, layer)
  }

  const layout: LayoutNode[] = []
  const sortedDepths = [...byDepth.keys()].sort((a, b) => a - b)
  for (const depth of sortedDepths) {
    const layer = byDepth.get(depth) || []
    const step = layer.length <= 1
      ? 0
      : (GRAPH_WIDTH - SIDE_PADDING * 2) / (layer.length - 1)
    layer.forEach((node, index) => {
      const x = layer.length <= 1
        ? GRAPH_WIDTH / 2
        : SIDE_PADDING + step * index
      layout.push({
        ...node,
        x,
        y: TOP_PADDING + depth * LAYER_GAP,
        depth,
      })
    })
  }

  return layout
})

const layoutNodeMap = computed(() => {
  return new Map(graphLayout.value.map((node) => [node.id, node]))
})

const canvasHeight = computed(() => {
  const maxY = graphLayout.value.reduce((height, node) => Math.max(height, node.y), 0)
  return Math.max(220, maxY + NODE_HEIGHT / 2 + BOTTOM_PADDING)
})

const zoomPercent = computed(() => `${Math.round(graphZoom.value * 100)}%`)

const setGraphZoom = (value: number, anchor?: { x: number, y: number }) => {
  const viewport = graphViewport.value
  const previousZoom = graphZoom.value
  const clamped = Math.min(Math.max(value, GRAPH_ZOOM_MIN), GRAPH_ZOOM_MAX)
  const nextZoom = Number(clamped.toFixed(2))
  if (nextZoom === previousZoom) return

  const zoomAnchor = viewport
    ? anchor || { x: viewport.clientWidth / 2, y: viewport.clientHeight / 2 }
    : null
  const baseX = viewport ? viewport.clientWidth / 2 - GRAPH_WIDTH / 2 : 0
  const graphPoint = viewport && zoomAnchor
    ? {
        x: (zoomAnchor.x - baseX - graphPanX.value) / previousZoom,
        y: (zoomAnchor.y - GRAPH_CANVAS_TOP - graphPanY.value) / previousZoom,
      }
    : null

  graphZoom.value = nextZoom

  if (viewport && zoomAnchor && graphPoint) {
    graphPanX.value = zoomAnchor.x - baseX - graphPoint.x * nextZoom
    graphPanY.value = zoomAnchor.y - GRAPH_CANVAS_TOP - graphPoint.y * nextZoom
  }
}

const zoomGraphIn = () => {
  setGraphZoom(graphZoom.value + GRAPH_ZOOM_STEP)
}

const zoomGraphOut = () => {
  setGraphZoom(graphZoom.value - GRAPH_ZOOM_STEP)
}

const resetGraphView = () => {
  graphZoom.value = 1
  graphPanX.value = 0
  graphPanY.value = 0
}

const handleGraphWheel = (event: WheelEvent) => {
  if (props.graphNodes.length === 0) return
  const viewport = graphViewport.value
  if (!viewport) return

  event.preventDefault()
  const rect = viewport.getBoundingClientRect()
  const anchor = {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
  }
  setGraphZoom(graphZoom.value * Math.exp(-event.deltaY * 0.001), anchor)
}

const startGraphPan = (event: PointerEvent) => {
  if (event.button !== 0 || props.graphNodes.length === 0) return
  const viewport = graphViewport.value
  if (!viewport) return

  event.preventDefault()
  isPanningGraph.value = true
  panPointerId = event.pointerId
  panStartX = event.clientX
  panStartY = event.clientY
  panStartGraphX = graphPanX.value
  panStartGraphY = graphPanY.value
  viewport.setPointerCapture(event.pointerId)
}

const moveGraphPan = (event: PointerEvent) => {
  if (!isPanningGraph.value || event.pointerId !== panPointerId) return
  const viewport = graphViewport.value
  if (!viewport) return

  event.preventDefault()
  graphPanX.value = panStartGraphX + event.clientX - panStartX
  graphPanY.value = panStartGraphY + event.clientY - panStartY
}

const stopGraphPan = (event: PointerEvent) => {
  if (!isPanningGraph.value || event.pointerId !== panPointerId) return
  const viewport = graphViewport.value
  if (viewport?.hasPointerCapture(event.pointerId)) {
    viewport.releasePointerCapture(event.pointerId)
  }
  isPanningGraph.value = false
  panPointerId = null
}

const edgePath = (source: LayoutNode, target: LayoutNode) => {
  const sameLayer = Math.abs(source.y - target.y) < 1
  const depthGap = Math.abs(target.depth - source.depth)

  if (sameLayer) {
    const direction = source.x <= target.x ? 1 : -1
    const sourceX = source.x + direction * (NODE_WIDTH / 2)
    const targetX = target.x - direction * (NODE_WIDTH / 2)
    const archY = source.y - 34
    return {
      path: `M ${sourceX} ${source.y} C ${sourceX + direction * 26} ${archY}, ${targetX - direction * 26} ${archY}, ${targetX} ${target.y}`,
      labelX: (sourceX + targetX) / 2,
      labelY: archY - 8,
    }
  }

  if (depthGap > 1 && Math.abs(source.x - target.x) < 1) {
    const sourceX = source.x + NODE_WIDTH / 2
    const targetX = target.x + NODE_WIDTH / 2
    const sourceY = source.y
    const targetY = target.y
    const bypassX = Math.min(GRAPH_WIDTH - 20, sourceX + 34)
    return {
      path: `M ${sourceX} ${sourceY} C ${bypassX} ${sourceY}, ${bypassX} ${targetY}, ${targetX} ${targetY}`,
      labelX: bypassX,
      labelY: (sourceY + targetY) / 2,
    }
  }

  const sourceX = source.x
  const sourceY = source.y + NODE_HEIGHT / 2
  const targetX = target.x
  const targetY = target.y - NODE_HEIGHT / 2
  const controlY = sourceY + Math.max(28, (targetY - sourceY) / 2)
  return {
    path: `M ${sourceX} ${sourceY} C ${sourceX} ${controlY}, ${targetX} ${controlY}, ${targetX} ${targetY}`,
    labelX: (sourceX + targetX) / 2,
    labelY: (sourceY + targetY) / 2 - 8,
  }
}

const graphEdgeLayout = computed<LayoutEdge[]>(() => {
  return normalizedEdges.value.flatMap((edge, index) => {
    const source = layoutNodeMap.value.get(edge.from)
    const target = layoutNodeMap.value.get(edge.to)
    if (!source || !target) return []
    const path = edgePath(source, target)
    return [{
      ...edge,
      id: `${edge.from}-${edge.to}-${edge.condition || index}`,
      ...path,
    }]
  })
})

const graphNodeClass = (status: GraphNodeStatus) => {
  if (status === 'running') return 'fill-primary/10 stroke-primary text-primary'
  if (status === 'done') return 'fill-emerald-500/10 stroke-emerald-500/60 text-emerald-700 dark:text-emerald-300'
  if (status === 'skipped') return 'fill-muted/50 stroke-muted-foreground/30 text-muted-foreground'
  if (status === 'error') return 'fill-destructive/10 stroke-destructive text-destructive'
  return 'fill-background stroke-border text-muted-foreground'
}

const statusDotClass = (status: GraphNodeStatus) => {
  if (status === 'running') return 'fill-primary'
  if (status === 'done') return 'fill-emerald-500'
  if (status === 'skipped') return 'fill-muted-foreground'
  if (status === 'error') return 'fill-destructive'
  return 'fill-muted-foreground/40'
}

const graphEdgeClass = (edge: GraphEdgeRecord) => {
  const source = nodeMap.value.get(edge.from)
  const target = nodeMap.value.get(edge.to)
  if (source?.status === 'error' || target?.status === 'error') return 'stroke-destructive'
  if (target?.status === 'running') return 'stroke-primary'
  if (source?.status === 'done' && target?.status && target.status !== 'pending') return 'stroke-primary/70'
  if (source?.status === 'done') return 'stroke-primary/35'
  return 'stroke-muted-foreground/25'
}

const graphStatusLabel = (status: GraphNodeStatus) => {
  if (status === 'running') return 'Running'
  if (status === 'done') return 'Done'
  if (status === 'skipped') return 'Skipped'
  if (status === 'error') return 'Error'
  return 'Pending'
}

const isAgentNode = (node: GraphNodeRecord) => node.node_type === 'agent'

const isSelectedAgentNode = (node: GraphNodeRecord) => (
  isAgentNode(node)
  && Boolean(node.agent_name)
  && node.agent_name === props.selectedAgentName
)

const handleNodePointerDown = (event: PointerEvent, node: GraphNodeRecord) => {
  if (!isAgentNode(node)) return
  event.stopPropagation()
}

const handleNodeClick = (node: GraphNodeRecord) => {
  if (!isAgentNode(node)) return
  emit('select-agent-node', node)
}

const truncateLabel = (value: string, maxLength = 18) => {
  if (value.length <= maxLength) return value
  return `${value.slice(0, maxLength - 3)}...`
}
</script>

<template>
  <aside class="flex min-h-0 flex-col rounded-lg border bg-muted/10">
    <div class="shrink-0 border-b px-4 py-3">
      <div class="flex items-center justify-between gap-3">
        <p class="text-xs text-muted-foreground">Execution</p>
        <div class="flex min-w-0 items-center gap-1">
          <span class="mr-1 hidden truncate text-[10px] uppercase tracking-wide text-muted-foreground sm:inline">
            {{ panelStatus }}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            title="Zoom out"
            class="h-7 w-7"
            :disabled="graphZoom <= GRAPH_ZOOM_MIN"
            @click="zoomGraphOut"
          >
            <ZoomOut class="h-3.5 w-3.5" />
          </Button>
          <span class="w-10 text-center text-[10px] tabular-nums text-muted-foreground">
            {{ zoomPercent }}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            title="Reset view"
            class="h-7 w-7"
            :disabled="graphZoom === 1 && graphPanX === 0 && graphPanY === 0"
            @click="resetGraphView"
          >
            <RotateCcw class="h-3.5 w-3.5" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            title="Zoom in"
            class="h-7 w-7"
            :disabled="graphZoom >= GRAPH_ZOOM_MAX"
            @click="zoomGraphIn"
          >
            <ZoomIn class="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>

    <div
      ref="graphViewport"
      :class="[
        'relative min-h-0 flex-1 overflow-hidden overscroll-contain touch-none select-none',
        graphNodes.length > 0 && (isPanningGraph ? 'cursor-grabbing' : 'cursor-grab'),
      ]"
      @wheel="handleGraphWheel"
      @pointerdown="startGraphPan"
      @pointermove="moveGraphPan"
      @pointerup="stopGraphPan"
      @pointercancel="stopGraphPan"
      @lostpointercapture="stopGraphPan"
    >
      <div v-if="graphNodes.length === 0" class="flex h-full min-h-40 flex-col items-center justify-center gap-2 p-3 text-center text-xs text-muted-foreground">
        <p>{{ isRunning ? 'Waiting for graph events' : 'No graph for this session' }}</p>
      </div>

      <div v-else class="h-full min-h-40 w-full">
        <div
          class="absolute left-1/2"
          :style="{
            top: `${GRAPH_CANVAS_TOP}px`,
            width: `${GRAPH_WIDTH}px`,
            height: `${canvasHeight}px`,
            transform: `translate(calc(-50% + ${graphPanX}px), ${graphPanY}px)`,
          }"
        >
          <svg
            class="block overflow-visible"
            :style="{
              width: `${GRAPH_WIDTH}px`,
              height: `${canvasHeight}px`,
              transform: `scale(${graphZoom})`,
              transformOrigin: 'top left',
            }"
            :viewBox="`0 0 ${GRAPH_WIDTH} ${canvasHeight}`"
            role="img"
            aria-label="Execution graph"
          >
            <defs>
              <marker
                id="execution-graph-arrow"
                markerHeight="7"
                markerWidth="7"
                orient="auto"
                refX="6"
                refY="3.5"
              >
                <path d="M 0 0 L 7 3.5 L 0 7 z" fill="context-stroke" />
              </marker>
            </defs>

            <g class="fill-none">
              <path
                v-for="edge in graphEdgeLayout"
                :key="edge.id"
                :d="edge.path"
                :class="['transition-colors', graphEdgeClass(edge)]"
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                marker-end="url(#execution-graph-arrow)"
              >
                <title>{{ edge.condition || `${edge.from} to ${edge.to}` }}</title>
              </path>
            </g>

            <g
              v-for="node in graphLayout"
              :key="node.id"
              :class="[
                'transition-colors',
                graphNodeClass(node.status),
                isAgentNode(node) && 'cursor-pointer',
              ]"
              :transform="`translate(${node.x - NODE_WIDTH / 2} ${node.y - NODE_HEIGHT / 2})`"
              @pointerdown="handleNodePointerDown($event, node)"
              @click.stop="handleNodeClick(node)"
            >
              <title>{{ [node.description || node.label, isAgentNode(node) ? 'Agent node' : ''].filter(Boolean).join(' - ') }}</title>
              <rect
                :width="NODE_WIDTH"
                :height="NODE_HEIGHT"
                rx="8"
                :stroke-width="isSelectedAgentNode(node) ? 2.5 : 1.5"
              />
              <foreignObject
                v-if="isAgentNode(node)"
                :x="NODE_WIDTH - 28"
                y="10"
                width="18"
                height="18"
              >
                <div
                  xmlns="http://www.w3.org/1999/xhtml"
                  class="flex h-[18px] w-[18px] items-center justify-center text-current opacity-80"
                  aria-label="Agent node"
                >
                  <Bot class="h-3.5 w-3.5" />
                </div>
              </foreignObject>
              <circle
                cx="16"
                cy="18"
                r="4"
                :class="statusDotClass(node.status)"
              />
              <circle
                v-if="node.status === 'running'"
                cx="16"
                cy="18"
                r="7"
                class="fill-transparent stroke-primary/30"
                stroke-width="2"
              >
                <animate
                  attributeName="r"
                  dur="1s"
                  repeatCount="indefinite"
                  values="5;9;5"
                />
                <animate
                  attributeName="opacity"
                  dur="1s"
                  repeatCount="indefinite"
                  values="1;0.35;1"
                />
              </circle>
              <text
                x="30"
                y="20"
                class="fill-current text-[11px]"
              >
                {{ truncateLabel(node.label, isAgentNode(node) ? 17 : 20) }}
              </text>
              <text
                x="30"
                y="39"
                class="fill-current text-[9px] opacity-85"
              >
                {{ graphStatusLabel(node.status) }}<template v-if="node.optional"> / Optional</template>
              </text>
            </g>
          </svg>
        </div>
      </div>
    </div>
  </aside>
</template>
