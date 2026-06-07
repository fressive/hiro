<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Square, Loader2, Trash2, ChevronLeft, BarChart3, MessageSquare, Files, SlidersHorizontal, X, SendHorizontal, Pencil, Check, GripVertical, Bot, ListFilter } from '@lucide/vue'
import {
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'

import { SidebarProvider, SidebarInset, SidebarTrigger } from '@/components/ui/sidebar'
import AppSidebar from '@/components/AppSidebar.vue'
import { Separator } from '@/components/ui/separator'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { apiFetch, getApiBaseUrl } from '@/lib/api'

import type {
  LLMConfig,
  Tool,
  EventRecord,
  AgentSession,
  AgentSessionTemplate,
  MCPServer,
  AgentMessage,
  AgentGraph,
  GraphEdgeRecord,
  GraphNodeRecord,
  GraphNodeStatus,
} from '@/types/agent'
import MessageItem from '@/components/agent/MessageItem.vue'
import AgentSettings from '@/components/agent/AgentSettings.vue'
import ActiveResponse from '@/components/agent/ActiveResponse.vue'
import ExecutionGraphPanel from '@/components/agent/ExecutionGraphPanel.vue'
import SessionList from '@/components/agent/SessionList.vue'
import FileList from '@/components/agent/FileList.vue'
import { LineChart } from '@/components/ui/chart'

const configs = ref<LLMConfig[]>([])
const availableTools = ref<Tool[]>([])
const selectedTools = ref<string[]>([])
const mcpServers = ref<MCPServer[]>([])
const selectedMcpServers = ref<string[]>([])
const isLoading = ref(false)
const isToolsLoading = ref(false)
const selectedConfigId = ref<number | null>(null)
const prompt = ref('')
const output = ref<any[]>([])
const isRunning = ref(false)
const isDeepAgent = ref(true)
const streamError = ref('')
const sessionSocket = ref<WebSocket | null>(null)
const toolEvents = ref<EventRecord[]>([])
const mcpEvents = ref<EventRecord[]>([])
const graphNodes = ref<GraphNodeRecord[]>([])
const graphEdges = ref<GraphEdgeRecord[]>([])
const backendGraphNodes = ref<GraphNodeRecord[]>([])
const backendGraphEdges = ref<GraphEdgeRecord[]>([])
const agentConfigs = ref<Record<string, number | null>>({})
const selectedGraphAgentName = ref<string | null>(null)
const activeAgentFilter = ref<string | null>(null)
const ragSources = ref<string[]>([])
const sessions = ref<AgentSession[]>([])
const sessionTemplates = ref<AgentSessionTemplate[]>([])
const selectedSessionId = ref<number | null>(null)
const messages = ref<AgentMessage[]>([])
const systemPrompt = ref('')
const temperature = ref(0.3)
const maxTokens = ref(100000)
const enable1mContext = ref(false)
const enableRag = ref(false)
const responseScroll = ref<HTMLDivElement | null>(null)
const chatLayout = ref<HTMLDivElement | null>(null)
const expandedMessages = ref<Record<number, boolean>>({})
const isTemplateDialogOpen = ref(false)
const templateName = ref('')
const templateError = ref('')
const isDeleteSessionDialogOpen = ref(false)
const pendingDeleteSessionId = ref<number | null>(null)
const isDeletingSession = ref(false)
const deleteSessionError = ref('')
const isRenamingSelectedSession = ref(false)
const selectedSessionTitleDraft = ref('')
const selectedTitleInput = ref<HTMLInputElement | null>(null)
const selectedSessionStorageKey = 'HIRO_SELECTED_AGENT_SESSION_ID'
const graphPanelWidthStorageKey = 'HIRO_EXECUTION_GRAPH_PANEL_WIDTH'
const GRAPH_PANEL_MIN_WIDTH = 240
const GRAPH_PANEL_MAX_WIDTH = 560
const GRAPH_PANEL_CHAT_MIN_WIDTH = 420
const GRAPH_PANEL_LAYOUT_RESERVED_WIDTH = 48
let socketSessionId: number | null = null
let socketConnectPromise: Promise<void> | null = null
let manualSocketClose = false

const innerTab = ref<'chat' | 'stats' | 'files'>('chat')
const showSettings = ref(false)
const graphPanelWidth = ref(320)
const isResizingGraphPanel = ref(false)

type SessionStats = {
  total_tokens: number
  total_input_tokens: number
  total_cached_input_tokens: number
  total_output_tokens: number
  model_usage: Record<string, {
    input: number
    cached: number
    output: number
    total: number
  }>
  rounds: Array<{
    step: string
    tokens: number
    input_tokens: number
    cached_input_tokens: number
    output_tokens: number
    model: string
    created_at: string
  }>
}

const currentSessionStats = ref<SessionStats | null>(null)

const chartConfig = {
  tokens: {
    label: 'Tokens',
    color: 'var(--primary)',
  },
  input_tokens: {
    label: 'Input Tokens',
    color: 'var(--vis-color-0)',
  },
  cached_input_tokens: {
    label: 'Cached Tokens',
    color: 'var(--vis-color-1)',
  },
  output_tokens: {
    label: 'Output Tokens',
    color: 'var(--vis-color-2)',
  },
}

const graphNodeStatuses = new Set<GraphNodeStatus>([
  'pending',
  'running',
  'done',
  'skipped',
  'error',
])

const normalizeGraphNode = (
  node: any,
  fallbackStatus: GraphNodeStatus = 'pending',
): GraphNodeRecord | null => {
  if (!node?.id) return null
  const status = graphNodeStatuses.has(node.status as GraphNodeStatus)
    ? node.status as GraphNodeStatus
    : fallbackStatus
  return {
    id: String(node.id),
    label: node.label ? String(node.label) : String(node.id),
    description: node.description ? String(node.description) : undefined,
    status,
    optional: Boolean(node.optional),
    node_type: node.node_type ? String(node.node_type) : undefined,
    agent_name: node.agent_name ? String(node.agent_name) : undefined,
  }
}

const normalizeGraphEdge = (edge: any): GraphEdgeRecord | null => {
  if (!edge?.from || !edge?.to) return null
  return {
    from: String(edge.from),
    to: String(edge.to),
    condition: edge.condition ? String(edge.condition) : undefined,
    bidirectional: edge.bidirectional === undefined ? undefined : Boolean(edge.bidirectional),
  }
}

const normalizeGraphNodes = (nodes: any): GraphNodeRecord[] => {
  if (!Array.isArray(nodes)) return []
  return nodes.flatMap((node) => {
    const normalized = normalizeGraphNode(node)
    return normalized ? [normalized] : []
  })
}

const normalizeGraphEdges = (edges: any): GraphEdgeRecord[] => {
  if (!Array.isArray(edges)) return []
  return edges.flatMap((edge) => {
    const normalized = normalizeGraphEdge(edge)
    return normalized ? [normalized] : []
  })
}

const fetchAgentGraph = async () => {
  try {
    const response = await apiFetch('/api/v1/agent/graph')
    if (!response.ok) return
    const graph = await response.json() as Partial<AgentGraph>
    backendGraphNodes.value = normalizeGraphNodes(graph.nodes)
    backendGraphEdges.value = normalizeGraphEdges(graph.edges)
  } catch (error) {
    console.error('Failed to fetch agent graph:', error)
  }
}

const fetchSessionStats = async () => {
  if (!selectedSessionId.value) return
  
  try {
    const response = await apiFetch(`/api/v1/agent/sessions/${selectedSessionId.value}/stats`)
    if (response.ok) {
      currentSessionStats.value = await response.json()
    }
  } catch (error) {
    console.error('Failed to fetch session stats:', error)
  }
}

// Watch for innerTab changes to fetch stats when needed
watch(innerTab, (newTab) => {
  if (newTab === 'stats') {
    fetchSessionStats()
  }
})

const toggleMessage = (id: number) => {
  expandedMessages.value[id] = !expandedMessages.value[id]
}

const canRun = computed(() => {
  return Boolean(selectedSessionId.value) && Boolean(prompt.value.trim()) && Boolean(selectedConfigId.value) && !isRunning.value
})

const selectedSession = computed(() => {
  if (!selectedSessionId.value) return null
  return sessions.value.find((session) => session.id === selectedSessionId.value) || null
})

const selectedSessionTitle = computed(() => selectedSession.value?.title || 'Chat')

const pendingDeleteSession = computed(() => {
  if (!pendingDeleteSessionId.value) return null
  return sessions.value.find((session) => session.id === pendingDeleteSessionId.value) || null
})

watch(isDeleteSessionDialogOpen, (open) => {
  if (!open && !isDeletingSession.value) {
    pendingDeleteSessionId.value = null
    deleteSessionError.value = ''
  }
})

const hasTraceMetadata = (message: AgentMessage) => {
  const metadata = message.extra_metadata
  return Boolean(
    metadata?.graph_nodes?.length
    || metadata?.graph_edges?.length
    || metadata?.tool_events?.length
    || metadata?.mcp_events?.length
  )
}

const isAssistantPlaceholder = (message: AgentMessage) => {
  return (
    message.role === 'assistant'
    && !message.content.trim()
    && (!message.tool_calls || message.tool_calls.length === 0)
    && !hasTraceMetadata(message)
  )
}

const hasLiveResponseActivity = computed(() => (
  isRunning.value
  || output.value.length > 0
  || graphNodes.value.length > 0
  || toolEvents.value.length > 0
  || mcpEvents.value.length > 0
))

const isActiveAssistantDraft = (message: AgentMessage) => {
  if (message.role !== 'assistant' || !hasLiveResponseActivity.value) return false

  const graph = message.extra_metadata?.graph_nodes || []
  return graph.some((node) => node.status === 'pending' || node.status === 'running')
}

const isInternalToolCallAssistant = (message: AgentMessage) => (
  message.role === 'assistant' && Boolean(message.tool_calls?.length)
)

const traceCarrierScore = (message: AgentMessage) => {
  if (message.role !== 'assistant' || !hasTraceMetadata(message)) return -1
  const hasContent = Boolean(message.content.trim())
  const hasToolCalls = Boolean(message.tool_calls?.length)
  if (hasContent && !hasToolCalls && !message.content.startsWith('Error:')) return 3
  if (hasContent && !hasToolCalls) return 2
  if (hasContent) return 1
  return 0
}

const selectTraceCarrierId = (group: AgentMessage[]) => {
  let selected: AgentMessage | null = null
  let selectedScore = -1

  for (const message of group) {
    const score = traceCarrierScore(message)
    if (score >= selectedScore) {
      selected = score >= 0 ? message : selected
      selectedScore = Math.max(score, selectedScore)
    }
  }

  return selected?.id ?? null
}

const flushDisplayGroup = (group: AgentMessage[], target: AgentMessage[]) => {
  const traceCarrierId = selectTraceCarrierId(group)
  const traceCarrier = group.find((message) => message.id === traceCarrierId)
  const hasFinalTrace = Boolean(
    traceCarrier
    && traceCarrier.role === 'assistant'
    && traceCarrier.content.trim()
    && (!traceCarrier.tool_calls || traceCarrier.tool_calls.length === 0)
  )

  for (const message of group) {
    if (isAssistantPlaceholder(message) || isActiveAssistantDraft(message)) continue
    if (hasFinalTrace && message.role === 'tool') continue
    if (hasFinalTrace && isInternalToolCallAssistant(message)) continue
    if (hasFinalTrace && hasTraceMetadata(message) && message.id !== traceCarrierId) continue
    target.push(message)
  }
}

const displayMessages = computed(() => {
  const items: AgentMessage[] = []
  let group: AgentMessage[] = []

  for (const message of messages.value) {
    if (message.role === 'user' && group.length > 0) {
      flushDisplayGroup(group, items)
      group = []
    }
    group.push(message)
  }
  flushDisplayGroup(group, items)

  const draft = prompt.value.trim()
  if (!draft) return items

  const last = items[items.length - 1]
  if (last?.role === 'user' && last.content === draft) return items

  return items.concat({
    id: Number.MAX_SAFE_INTEGER,
    session_id: selectedSessionId.value || 0,
    role: 'user',
    content: draft,
    created_at: new Date().toISOString(),
  })
})

const latestTraceGraphNodes = computed(() => {
  for (let index = messages.value.length - 1; index >= 0; index -= 1) {
    const message = messages.value[index]
    if (message.role !== 'assistant') continue
    const graph = message.extra_metadata?.graph_nodes
    if (graph?.length) return graph
  }
  return []
})

const latestTraceGraphEdges = computed(() => {
  for (let index = messages.value.length - 1; index >= 0; index -= 1) {
    const message = messages.value[index]
    if (message.role !== 'assistant') continue
    const edges = message.extra_metadata?.graph_edges
    if (edges?.length) return edges
  }
  return []
})

const mergeGraphNodesWithBackendTemplate = (
  sourceNodes: GraphNodeRecord[],
  missingOptionalStatus: GraphNodeStatus = 'pending',
) => {
  if (backendGraphNodes.value.length === 0) return sourceNodes

  const merged = backendGraphNodes.value.map((node) => ({
    ...node,
    status: node.optional ? missingOptionalStatus : node.status,
  }))
  const byId = new Map(merged.map((node, index) => [node.id, index]))

  for (const sourceNode of sourceNodes) {
    const index = byId.get(sourceNode.id)
    if (index === undefined) {
      byId.set(sourceNode.id, merged.length)
      merged.push(sourceNode)
      continue
    }

    const templateNode = merged[index]
    merged[index] = {
      ...templateNode,
      ...sourceNode,
      label: sourceNode.label || templateNode.label,
      description: sourceNode.description ?? templateNode.description,
      optional: sourceNode.optional ?? templateNode.optional,
      node_type: sourceNode.node_type ?? templateNode.node_type,
      agent_name: sourceNode.agent_name ?? templateNode.agent_name,
    }
  }

  return merged
}

const mergeGraphEdgesWithBackendTemplate = (sourceEdges: GraphEdgeRecord[]) => {
  if (backendGraphEdges.value.length === 0) return sourceEdges

  const merged = [...backendGraphEdges.value]
  const seen = new Set(
    merged.map((edge) => `${edge.from}->${edge.to}:${edge.condition || ''}`),
  )
  for (const edge of sourceEdges) {
    const key = `${edge.from}->${edge.to}:${edge.condition || ''}`
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(edge)
  }
  return merged
}

const visibleGraphNodes = computed(() => {
  if (graphNodes.value.length > 0) {
    return mergeGraphNodesWithBackendTemplate(graphNodes.value)
  }
  if (!isRunning.value && latestTraceGraphNodes.value.length > 0) {
    return mergeGraphNodesWithBackendTemplate(latestTraceGraphNodes.value, 'skipped')
  }
  return backendGraphNodes.value
})

const visibleGraphEdges = computed(() => {
  if (graphNodes.value.length > 0) {
    return mergeGraphEdgesWithBackendTemplate(graphEdges.value)
  }
  if (!isRunning.value && latestTraceGraphEdges.value.length > 0) {
    return mergeGraphEdgesWithBackendTemplate(latestTraceGraphEdges.value)
  }
  return backendGraphEdges.value
})

const agentDisplayNames: Record<string, string> = {
  information_collect_agent: 'Information Collect Agent',
  main_agent: 'Main Agent',
  writeup_agent: 'Writeup Agent',
}

const formatAgentName = (agentName: string) => (
  agentDisplayNames[agentName] || agentName
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
)

const graphAgentNodes = computed(() => (
  visibleGraphNodes.value.filter((node) => node.node_type === 'agent' && node.agent_name)
))

const selectedGraphAgentNode = computed(() => {
  if (!selectedGraphAgentName.value) return null
  return graphAgentNodes.value.find((node) => node.agent_name === selectedGraphAgentName.value) || null
})

const selectedGraphAgentModelId = computed({
  get: () => (
    selectedGraphAgentName.value
      ? agentConfigs.value[selectedGraphAgentName.value] ?? ''
      : ''
  ),
  set: (value: string | number | null) => {
    if (!selectedGraphAgentName.value) return
    const next = { ...agentConfigs.value }
    if (value === '' || value === null) {
      next[selectedGraphAgentName.value] = null
    } else {
      const normalized = Number(value)
      next[selectedGraphAgentName.value] = Number.isFinite(normalized)
        ? normalized
        : null
    }
    agentConfigs.value = next
  },
})

const selectedGraphAgentModelName = computed(() => {
  const configId = selectedGraphAgentName.value
    ? agentConfigs.value[selectedGraphAgentName.value]
    : null
  const config = configs.value.find((item) => item.id === configId)
  if (config) return config.name || config.model
  const fallback = configs.value.find((item) => item.id === selectedConfigId.value)
  return fallback ? `Session default: ${fallback.name || fallback.model}` : 'Session default'
})

const handleGraphAgentSelect = (node: GraphNodeRecord) => {
  if (node.node_type !== 'agent' || !node.agent_name) return
  selectedGraphAgentName.value = node.agent_name
  activeAgentFilter.value = node.agent_name
}

const clearAgentFilter = () => {
  activeAgentFilter.value = null
}

const visibleDisplayMessages = computed(() => {
  if (!activeAgentFilter.value) return displayMessages.value
  return displayMessages.value.filter((message) => (
    message.role === 'user'
    || (message.role === 'assistant' && message.name === activeAgentFilter.value)
  ))
})

const chatLayoutStyle = computed<Record<string, string>>(() => ({
  '--execution-graph-width': `${graphPanelWidth.value}px`,
}))

const graphPanelWidthMax = () => {
  const width = chatLayout.value?.getBoundingClientRect().width
  if (!width) return GRAPH_PANEL_MAX_WIDTH
  return Math.min(
    GRAPH_PANEL_MAX_WIDTH,
    Math.max(
      GRAPH_PANEL_MIN_WIDTH,
      width - GRAPH_PANEL_CHAT_MIN_WIDTH - GRAPH_PANEL_LAYOUT_RESERVED_WIDTH,
    ),
  )
}

const clampGraphPanelWidth = (width: number) => {
  return Math.round(Math.min(Math.max(width, GRAPH_PANEL_MIN_WIDTH), graphPanelWidthMax()))
}

const setGraphPanelWidth = (width: number) => {
  graphPanelWidth.value = clampGraphPanelWidth(width)
}

const persistGraphPanelWidth = () => {
  localStorage.setItem(graphPanelWidthStorageKey, String(graphPanelWidth.value))
}

const handleGraphPanelResizeMove = (event: PointerEvent) => {
  if (!isResizingGraphPanel.value) return
  const rect = chatLayout.value?.getBoundingClientRect()
  if (!rect) return
  event.preventDefault()
  setGraphPanelWidth(event.clientX - rect.left)
}

const stopGraphPanelResize = () => {
  if (!isResizingGraphPanel.value) return
  isResizingGraphPanel.value = false
  window.removeEventListener('pointermove', handleGraphPanelResizeMove)
  window.removeEventListener('pointerup', stopGraphPanelResize)
  window.removeEventListener('pointercancel', stopGraphPanelResize)
  persistGraphPanelWidth()
}

const startGraphPanelResize = (event: PointerEvent) => {
  event.preventDefault()
  isResizingGraphPanel.value = true
  window.addEventListener('pointermove', handleGraphPanelResizeMove)
  window.addEventListener('pointerup', stopGraphPanelResize)
  window.addEventListener('pointercancel', stopGraphPanelResize)
  handleGraphPanelResizeMove(event)
}

const handleGraphPanelResizeKeydown = (event: KeyboardEvent) => {
  const step = event.shiftKey ? 40 : 16
  if (event.key === 'ArrowLeft') {
    event.preventDefault()
    setGraphPanelWidth(graphPanelWidth.value - step)
    persistGraphPanelWidth()
  } else if (event.key === 'ArrowRight') {
    event.preventDefault()
    setGraphPanelWidth(graphPanelWidth.value + step)
    persistGraphPanelWidth()
  } else if (event.key === 'Home') {
    event.preventDefault()
    setGraphPanelWidth(GRAPH_PANEL_MIN_WIDTH)
    persistGraphPanelWidth()
  } else if (event.key === 'End') {
    event.preventDefault()
    setGraphPanelWidth(GRAPH_PANEL_MAX_WIDTH)
    persistGraphPanelWidth()
  }
}

const scrollResponseToBottom = async () => {
  await nextTick()
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      const el = responseScroll.value
      if (el) {
        el.scrollTop = el.scrollHeight
      }
    })
  })
}

const fetchSessions = async () => {
  const response = await apiFetch('/api/v1/agent/sessions')
  if (!response.ok) return
  sessions.value = await response.json()
}

const fetchSessionTemplates = async () => {
  const response = await apiFetch('/api/v1/agent/templates')
  if (!response.ok) return
  sessionTemplates.value = await response.json()
}

const fetchMessages = async (sessionId: number) => {
  const response = await apiFetch(`/api/v1/agent/sessions/${sessionId}/messages`)
  if (!response.ok) return
  messages.value = await response.json()
  scrollResponseToBottom()
}

const fetchRunningStatus = async (sessionId: number) => {
  try {
    const response = await apiFetch(`/api/v1/agent/sessions/${sessionId}/status`)
    if (response.ok) {
      const { is_running } = await response.json()
      if (selectedSessionId.value !== sessionId) return
      isRunning.value = is_running
    }
  } catch (err) {
    console.error('Failed to fetch running status:', err)
  }
}

const buildWebSocketUrl = (path: string) => {
  const baseUrl = getApiBaseUrl() || window.location.origin
  const url = new URL(path, baseUrl)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}

const handleWebSocketMessage = (raw: string) => {
  let payload: any = null
  try {
    payload = JSON.parse(raw)
  } catch {
    return
  }

  const event = payload?.event || payload?.type
  if (!event) return
  applyEvent(event, payload.data || {})
}

const closeSessionSocket = () => {
  manualSocketClose = true
  socketConnectPromise = null
  if (sessionSocket.value && sessionSocket.value.readyState <= WebSocket.OPEN) {
    sessionSocket.value.close()
  }
  sessionSocket.value = null
  socketSessionId = null
}

const connectSessionSocket = (sessionId: number): Promise<void> => {
  const current = sessionSocket.value
  if (socketSessionId === sessionId && current?.readyState === WebSocket.OPEN) {
    return Promise.resolve()
  }
  if (
    socketSessionId === sessionId
    && current?.readyState === WebSocket.CONNECTING
    && socketConnectPromise
  ) {
    return socketConnectPromise
  }

  closeSessionSocket()
  manualSocketClose = false
  socketSessionId = sessionId

  const socket = new WebSocket(buildWebSocketUrl(`/api/v1/agent/sessions/${sessionId}/ws`))
  sessionSocket.value = socket

  const connectPromise = new Promise<void>((resolve, reject) => {
    let settled = false

    socket.onopen = () => {
      if (sessionSocket.value !== socket) return
      settled = true
      socketConnectPromise = null
      resolve()
    }

    socket.onmessage = (event) => {
      if (typeof event.data === 'string') {
        handleWebSocketMessage(event.data)
      }
    }

    socket.onerror = () => {
      if (!settled) {
        settled = true
        socketConnectPromise = null
        reject(new Error('WebSocket connection failed.'))
      }
    }

    socket.onclose = () => {
      if (sessionSocket.value === socket) {
        sessionSocket.value = null
      }
      if (socketSessionId === sessionId) {
        socketSessionId = null
      }
      if (!settled) {
        settled = true
        socketConnectPromise = null
        reject(new Error('WebSocket connection closed.'))
      }
      if (
        !manualSocketClose
        && !sessionSocket.value
        && selectedSessionId.value === sessionId
        && isRunning.value
      ) {
        window.setTimeout(() => {
          if (selectedSessionId.value === sessionId && isRunning.value) {
            void connectSessionSocket(sessionId).catch((error) => {
              streamError.value = error?.message || 'WebSocket reconnect failed.'
            })
          }
        }, 1000)
      }
    }
  })

  socketConnectPromise = connectPromise
  return connectPromise
}

const sendSessionCommand = async (sessionId: number, message: Record<string, any>) => {
  await connectSessionSocket(sessionId)
  const socket = sessionSocket.value
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    throw new Error('Session WebSocket is not connected.')
  }
  socket.send(JSON.stringify(message))
}

// Flag to prevent auto-save during session loading
let isInitialLoad = false

const onSessionChange = (id: number | null) => {
  const previousSessionId = selectedSessionId.value
  if (previousSessionId !== id) {
    closeSessionSocket()
  }

  selectedSessionId.value = id
  innerTab.value = 'chat'
  cancelRenameSelectedSession()
  isRunning.value = false
  if (id) {
    localStorage.setItem(selectedSessionStorageKey, String(id))
    const session = sessions.value.find(s => s.id === id)
    if (session) {
      isInitialLoad = true
      selectedConfigId.value = session.config_id || (configs.value.length > 0 ? configs.value[0].id : null)
      systemPrompt.value = session.system_prompt || ''
      temperature.value = session.temperature ?? 0.3
      maxTokens.value = session.max_tokens ?? 512
      enable1mContext.value = !!session.enable_1m_context
      enableRag.value = !!session.enable_rag
      isDeepAgent.value = session.is_deep_agent ?? true
      selectedTools.value = session.tools || availableTools.value.map(t => t.name)
      selectedMcpServers.value = session.mcp_servers || []
      agentConfigs.value = { ...(session.agent_configs || {}) }
      
      // Reset initial load flag after a short delay to let watchers settle
      setTimeout(() => { isInitialLoad = false }, 100)
    }
    clearOutput()
    fetchMessages(id)
    fetchRunningStatus(id)
    void connectSessionSocket(id).catch((error) => {
      streamError.value = error?.message || 'WebSocket connection failed.'
    })
  } else {
    localStorage.removeItem(selectedSessionStorageKey)
    messages.value = []
    agentConfigs.value = {}
    selectedGraphAgentName.value = null
    activeAgentFilter.value = null
    clearOutput()
  }
}

const createSession = async () => {
  const response = await apiFetch('/api/v1/agent/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: 'New Session' }),
  })
  if (!response.ok) return
  const created = await response.json()
  sessions.value.unshift(created)
  onSessionChange(created.id)
  // Save default config for the new session
  saveSessionConfig()
}

const renameSession = async (sessionId: number, title: string) => {
  const nextTitle = title.trim()
  if (!nextTitle) return false

  const response = await apiFetch(`/api/v1/agent/sessions/${sessionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: nextTitle }),
  })
  if (!response.ok) return false

  const updated: AgentSession = await response.json()
  const index = sessions.value.findIndex((session) => session.id === sessionId)
  if (index >= 0) {
    sessions.value[index] = updated
  }
  return true
}

const startRenameSelectedSession = async () => {
  if (!selectedSession.value) return
  selectedSessionTitleDraft.value = selectedSession.value.title || 'Untitled Session'
  isRenamingSelectedSession.value = true
  await nextTick()
  selectedTitleInput.value?.focus()
  selectedTitleInput.value?.select()
}

const cancelRenameSelectedSession = () => {
  isRenamingSelectedSession.value = false
  selectedSessionTitleDraft.value = ''
}

const submitSelectedSessionRename = async () => {
  if (!selectedSession.value) return
  const saved = await renameSession(selectedSession.value.id, selectedSessionTitleDraft.value)
  if (saved) {
    cancelRenameSelectedSession()
  }
}

const deleteSession = async (id?: number) => {
  const sessionId = id || selectedSessionId.value
  if (!sessionId) return
  pendingDeleteSessionId.value = sessionId
  deleteSessionError.value = ''
  isDeleteSessionDialogOpen.value = true
}

const cancelDeleteSession = () => {
  if (isDeletingSession.value) return
  isDeleteSessionDialogOpen.value = false
  pendingDeleteSessionId.value = null
  deleteSessionError.value = ''
}

const confirmDeleteSession = async () => {
  const sessionId = pendingDeleteSessionId.value
  if (!sessionId || isDeletingSession.value) return

  isDeletingSession.value = true
  deleteSessionError.value = ''
  try {
    const response = await apiFetch(`/api/v1/agent/sessions/${sessionId}`, {
      method: 'DELETE',
    })

    if (response.ok) {
      sessions.value = sessions.value.filter((s) => s.id !== sessionId)
      if (sessionId === selectedSessionId.value) {
        onSessionChange(null)
      }
      isDeleteSessionDialogOpen.value = false
      pendingDeleteSessionId.value = null
    } else {
      deleteSessionError.value = 'Failed to delete session.'
    }
  } catch {
    deleteSessionError.value = 'Failed to delete session.'
  } finally {
    isDeletingSession.value = false
  }
}

const fetchConfigs = async () => {
  isLoading.value = true
  try {
    const response = await apiFetch('/api/v1/llm')
    if (!response.ok) return
    configs.value = await response.json()
    if (!selectedConfigId.value && configs.value.length > 0) {
      selectedConfigId.value = configs.value[0].id
    }
  } finally {
    isLoading.value = false
  }
}

const fetchTools = async () => {
  isToolsLoading.value = true
  try {
    const response = await apiFetch('/api/v1/agent/tools')
    if (!response.ok) return
    availableTools.value = await response.json()
    if (selectedTools.value.length === 0) {
        selectedTools.value = availableTools.value.map(t => t.name)
    }
  } finally {
    isToolsLoading.value = false
  }
}

const fetchMcpServers = async () => {
  try {
    const response = await apiFetch('/api/v1/mcp/')
    if (!response.ok) return
    const allServers: MCPServer[] = await response.json()
    mcpServers.value = allServers.filter(s => s.enabled)
  } catch (err) {
    console.error('Failed to fetch MCP servers:', err)
  }
}

const saveSessionConfig = async () => {
  if (!selectedSessionId.value || isRunning.value || isInitialLoad) return

  try {
    await apiFetch(`/api/v1/agent/sessions/${selectedSessionId.value}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        config_id: selectedConfigId.value,
        system_prompt: systemPrompt.value,
        temperature: temperature.value,
        max_tokens: maxTokens.value,
        enable_1m_context: enable1mContext.value,
        is_deep_agent: isDeepAgent.value,
        enable_rag: enableRag.value,
        tools: selectedTools.value,
        mcp_servers: selectedMcpServers.value,
        agent_configs: agentConfigs.value,
      }),
    })
    // Also update the local sessions array to keep it in sync
    const session = sessions.value.find(s => s.id === selectedSessionId.value)
    if (session) {
      session.config_id = selectedConfigId.value
      session.system_prompt = systemPrompt.value
      session.temperature = temperature.value
      session.max_tokens = maxTokens.value
      session.enable_1m_context = enable1mContext.value
      session.is_deep_agent = isDeepAgent.value
      session.enable_rag = enableRag.value
      session.tools = selectedTools.value
      session.mcp_servers = selectedMcpServers.value
      session.agent_configs = { ...agentConfigs.value }
    }
  } catch (error) {
    console.error('Failed to auto-save session config:', error)
  }
}

let saveTimeout: any = null
const debouncedSave = () => {
  if (saveTimeout) clearTimeout(saveTimeout)
  saveTimeout = setTimeout(saveSessionConfig, 1000)
}

const currentSettingsPayload = (name?: string) => ({
  ...(name !== undefined ? { name } : {}),
  config_id: selectedConfigId.value,
  system_prompt: systemPrompt.value,
  temperature: temperature.value,
  max_tokens: maxTokens.value,
  enable_1m_context: enable1mContext.value,
  is_deep_agent: isDeepAgent.value,
  enable_rag: enableRag.value,
  tools: [...selectedTools.value],
  mcp_servers: [...selectedMcpServers.value],
  agent_configs: { ...agentConfigs.value },
})

const saveCurrentSettingsAsTemplate = async (templateName: string) => {
  if (isRunning.value) return false

  const name = templateName.trim()
  if (!name) return false

  const response = await apiFetch('/api/v1/agent/templates', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(currentSettingsPayload(name)),
  })
  if (!response.ok) return false
  await fetchSessionTemplates()
  return true
}

const openSaveTemplateDialog = () => {
  if (isRunning.value || !selectedSessionId.value) return

  const currentSession = sessions.value.find((session) => session.id === selectedSessionId.value)
  templateName.value = currentSession?.title || ''
  templateError.value = ''
  isTemplateDialogOpen.value = true
}

const submitTemplateDialog = async () => {
  const name = templateName.value.trim()
  if (!name) {
    templateError.value = 'Template name is required.'
    return
  }

  const saved = await saveCurrentSettingsAsTemplate(name)
  if (!saved) {
    templateError.value = 'Failed to save template.'
    return
  }

  isTemplateDialogOpen.value = false
  templateName.value = ''
  templateError.value = ''
}

const applySessionTemplate = async (templateId: number) => {
  const template = sessionTemplates.value.find((item) => item.id === templateId)
  if (!template || isRunning.value) return

  selectedConfigId.value = template.config_id || (configs.value.length > 0 ? configs.value[0].id : null)
  systemPrompt.value = template.system_prompt || ''
  temperature.value = template.temperature ?? 0.3
  maxTokens.value = template.max_tokens ?? 100000
  enable1mContext.value = !!template.enable_1m_context
  isDeepAgent.value = template.is_deep_agent ?? true
  enableRag.value = !!template.enable_rag
  selectedTools.value = template.tools || []
  selectedMcpServers.value = template.mcp_servers || []
  agentConfigs.value = { ...(template.agent_configs || {}) }
  await nextTick()
  await saveSessionConfig()
}

const deleteSessionTemplate = async (templateId: number) => {
  if (isRunning.value) return
  const template = sessionTemplates.value.find((item) => item.id === templateId)
  if (!template) return
  if (!confirm(`Delete template "${template.name}"?`)) return

  const response = await apiFetch(`/api/v1/agent/templates/${templateId}`, {
    method: 'DELETE',
  })
  if (!response.ok) return
  sessionTemplates.value = sessionTemplates.value.filter((item) => item.id !== templateId)
}

const startRun = async () => {
  if (!canRun.value || !selectedSessionId.value) return
  const sessionId = selectedSessionId.value
  const currentPrompt = prompt.value.trim()
  isRunning.value = true
  clearOutput()
  prompt.value = ''

  messages.value.push({
    id: Date.now(),
    session_id: selectedSessionId.value || 0,
    role: 'user',
    content: currentPrompt,
    created_at: new Date().toISOString(),
  })

  try {
    await sendSessionCommand(sessionId, {
      type: 'run',
      payload: {
        config_id: selectedConfigId.value,
        input: currentPrompt,
        session_id: sessionId,
        system_prompt: systemPrompt.value,
        temperature: temperature.value,
        max_tokens: maxTokens.value,
        enable_1m_context: enable1mContext.value,
        is_deep_agent: isDeepAgent.value,
        enable_rag: enableRag.value,
        tools: selectedTools.value,
        mcp_servers: selectedMcpServers.value,
        agent_configs: agentConfigs.value,
      },
    })
  } catch (error: any) {
    streamError.value = error?.message || 'Failed to run agent.'
    isRunning.value = false
    if (selectedSessionId.value) {
      fetchMessages(selectedSessionId.value)
    }
  }
}

const stopRun = async () => {
  const sessionId = selectedSessionId.value
  if (!sessionId) return

  try {
    if (sessionSocket.value?.readyState === WebSocket.OPEN) {
      sessionSocket.value.send(JSON.stringify({ type: 'stop' }))
    } else {
      await apiFetch(`/api/v1/agent/sessions/${sessionId}/stop`, {
        method: 'POST',
      })
    }
    isRunning.value = false
  } catch (e) {
    console.error('Failed to stop agent', e)
  }
}

const clearOutput = () => {
  streamError.value = ''
  clearLiveResponse()
}

const clearLiveResponse = () => {
  output.value = []
  toolEvents.value = []
  mcpEvents.value = []
  graphNodes.value = []
  graphEdges.value = []
  ragSources.value = []
}

const upsertEvent = (target: EventRecord[], incoming: EventRecord) => {
  const index = target.findIndex((item) => item.id === incoming.id)
  if (index >= 0) {
    target[index] = { ...target[index], ...incoming }
  } else {
    target.push(incoming)
  }
}

const upsertGraphNode = (incoming: Partial<GraphNodeRecord> & { id: string, status?: GraphNodeStatus }) => {
  const index = graphNodes.value.findIndex((item) => item.id === incoming.id)
  if (index >= 0) {
    const existing = graphNodes.value[index]
    graphNodes.value[index] = {
      ...existing,
      status: incoming.status || existing.status,
      label: incoming.label || existing.label,
      description: incoming.description ?? existing.description,
      optional: incoming.optional ?? existing.optional,
      node_type: incoming.node_type ?? existing.node_type,
      agent_name: incoming.agent_name ?? existing.agent_name,
    }
  } else {
    const template = backendGraphNodes.value.find((node) => node.id === incoming.id)
    graphNodes.value.push({
      id: incoming.id,
      label: incoming.label || template?.label || incoming.id,
      description: incoming.description ?? template?.description,
      status: incoming.status || 'pending',
      optional: incoming.optional ?? template?.optional,
      node_type: incoming.node_type ?? template?.node_type,
      agent_name: incoming.agent_name ?? template?.agent_name,
    })
  }
}

const applyEvent = (event: string, payload: any) => {
  if (event === 'status') {
    const wasRunning = isRunning.value
    isRunning.value = Boolean(payload.is_running)
    if (wasRunning && !isRunning.value && selectedSessionId.value) {
      fetchMessages(selectedSessionId.value)
    }
    return
  }

  if (event === 'token') {
    const text = payload.text
    if (text === undefined) return
    
    const type = payload.type || 'text'
    const lastBlock = output.value[output.value.length - 1]
    
    if (!lastBlock || lastBlock.type !== type) {
      if (type === 'thinking') {
        output.value.push({ type: 'thinking', thinking: text })
      } else {
        output.value.push({ type: 'text', text: text })
      }
    } else {
      if (type === 'thinking') {
        lastBlock.thinking += text
      } else {
        lastBlock.text += text
      }
    }
    return
  }

  if (event === 'rag_search') {
    if (Array.isArray(payload.sources)) {
      ragSources.value = payload.sources
    }
    return
  }

  if (event === 'graph_init') {
    graphNodes.value = normalizeGraphNodes(payload.nodes)
    graphEdges.value = normalizeGraphEdges(payload.edges)
    return
  }

  if (event === 'graph_node') {
    if (payload.id) {
      upsertGraphNode({
        id: payload.id,
        label: payload.label,
        description: payload.description,
        status: payload.status || 'running',
        optional: payload.optional,
        node_type: payload.node_type,
        agent_name: payload.agent_name,
      })
    }
    return
  }

  if (event === 'session') {
    if (payload.id) {
      const sessionId = Number(payload.id)
      const isCurrentRunningSession = selectedSessionId.value === sessionId && isRunning.value
      selectedSessionId.value = sessionId
      localStorage.setItem(selectedSessionStorageKey, String(sessionId))
      fetchSessions()
      if (!isCurrentRunningSession) {
        fetchMessages(sessionId)
      }
    }
    return
  }

  if (event === 'error') {
    const message = payload.message || 'Agent failed.'
    streamError.value = message
    if (payload.is_running === false) {
      isRunning.value = false
    }
    if (payload.session_id) {
      fetchMessages(payload.session_id)
    }
    scrollResponseToBottom()
    return
  }

  if (event === 'done') {
    isRunning.value = false
    if (payload.session_id) {
      fetchSessions()
      void fetchMessages(payload.session_id).finally(clearLiveResponse)
    } else {
      clearLiveResponse()
    }
    return
  }

  if (event === 'tool_start') {
    upsertEvent(toolEvents.value, {
      id: payload.id || crypto.randomUUID(),
      name: payload.name || 'tool',
      status: 'running',
      input: payload.input,
    })
    return
  }

  if (event === 'tool_end') {
    upsertEvent(toolEvents.value, {
      id: payload.id || crypto.randomUUID(),
      name: payload.name || 'tool',
      status: 'done',
      output: payload.output,
    })
    return
  }

  if (event === 'tool_error') {
    upsertEvent(toolEvents.value, {
      id: payload.id || crypto.randomUUID(),
      name: payload.name || 'tool',
      status: 'error',
      output: payload.output,
    })
    return
  }

  if (event === 'mcp_start') {
    upsertEvent(mcpEvents.value, {
      id: payload.id || crypto.randomUUID(),
      name: payload.name || 'mcp',
      status: 'running',
      input: payload.input,
    })
    return
  }

  if (event === 'mcp_end') {
    upsertEvent(mcpEvents.value, {
      id: payload.id || crypto.randomUUID(),
      name: payload.name || 'mcp',
      status: 'done',
      output: payload.output,
    })
    return
  }

  if (event === 'mcp_error') {
    upsertEvent(mcpEvents.value, {
      id: payload.id || crypto.randomUUID(),
      name: payload.name || 'mcp',
      status: 'error',
      output: payload.output,
    })
  }
}

const toggleTool = (toolName: string) => {
  const current = [...selectedTools.value]
  const index = current.indexOf(toolName)
  if (index >= 0) {
    current.splice(index, 1)
  } else {
    current.push(toolName)
  }
  selectedTools.value = current
}

const toggleMcpServer = (serverName: string) => {
  const current = [...selectedMcpServers.value]
  const index = current.indexOf(serverName)
  if (index >= 0) {
    current.splice(index, 1)
  } else {
    current.push(serverName)
  }
  selectedMcpServers.value = current
}

onMounted(async () => {
  const savedGraphPanelWidth = Number(localStorage.getItem(graphPanelWidthStorageKey))
  if (Number.isFinite(savedGraphPanelWidth) && savedGraphPanelWidth > 0) {
    setGraphPanelWidth(savedGraphPanelWidth)
  }

  await fetchAgentGraph()
  await fetchConfigs()
  await fetchTools()
  await fetchMcpServers()
  await fetchSessions()
  await fetchSessionTemplates()

  const savedSessionId = Number(localStorage.getItem(selectedSessionStorageKey))
  if (savedSessionId && sessions.value.some((session) => session.id === savedSessionId)) {
    onSessionChange(savedSessionId)
  }
})

onBeforeUnmount(() => {
  stopGraphPanelResize()
  closeSessionSocket()
})

watch(
  () => [visibleDisplayMessages.value.length, output.value, streamError.value, isRunning.value],
  scrollResponseToBottom,
  { immediate: true },
)

// Auto-save configuration changes
watch(
  [
    selectedConfigId, 
    systemPrompt, 
    temperature, 
    maxTokens, 
    enable1mContext, 
    isDeepAgent, 
    enableRag, 
    selectedTools, 
    selectedMcpServers,
    agentConfigs,
  ],
  () => {
    if (isInitialLoad) return
    debouncedSave()
  },
  { deep: true }
)
</script>

<template>
  <SidebarProvider>
    <AppSidebar />
    <SidebarInset class="flex h-screen flex-col overflow-hidden">
      <header class="grid h-16 shrink-0 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3 border-b px-4">
        <div class="flex min-w-0 items-center gap-2">
          <SidebarTrigger class="-ml-1" />
          <Separator orientation="vertical" class="mr-2 h-4" />
          <Button
            v-if="selectedSessionId"
            variant="ghost"
            size="icon"
            @click="onSessionChange(null)"
            class="h-8 w-8"
          >
            <ChevronLeft class="h-4 w-4" />
          </Button>
          <form
            v-if="selectedSessionId && isRenamingSelectedSession"
            class="flex min-w-0 flex-1 items-center gap-1"
            @submit.prevent="submitSelectedSessionRename"
          >
            <input
              ref="selectedTitleInput"
              v-model="selectedSessionTitleDraft"
              class="h-9 min-w-0 flex-1 rounded-md border bg-background px-2 text-lg font-semibold outline-none ring-offset-background focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              @keydown.esc.prevent="cancelRenameSelectedSession"
            />
            <Button
              type="submit"
              variant="ghost"
              size="icon"
              class="h-8 w-8"
              :disabled="!selectedSessionTitleDraft.trim()"
            >
              <Check class="h-4 w-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              class="h-8 w-8"
              @click="cancelRenameSelectedSession"
            >
              <X class="h-4 w-4" />
            </Button>
          </form>
          <div v-else class="flex min-w-0 flex-1 items-center gap-1">
            <h1 class="truncate text-lg font-semibold">
              {{ selectedSessionId ? selectedSessionTitle : 'Sessions' }}
            </h1>
            <Button
              v-if="selectedSessionId"
              type="button"
              variant="ghost"
              size="icon"
              title="Rename session"
              class="h-8 w-8 shrink-0 text-muted-foreground"
              @click="startRenameSelectedSession"
            >
              <Pencil class="h-4 w-4" />
            </Button>
          </div>
        </div>
        <div v-if="selectedSessionId" class="flex items-center gap-1 rounded-lg bg-muted p-1">
          <Button
            variant="ghost"
            size="sm"
            :class="['gap-2', innerTab === 'chat' && 'bg-background shadow-sm']"
            @click="innerTab = 'chat'"
          >
            <MessageSquare class="h-4 w-4" />
            <span class="hidden sm:inline">Chat</span>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            :class="['gap-2', innerTab === 'stats' && 'bg-background shadow-sm']"
            @click="innerTab = 'stats'"
          >
            <BarChart3 class="h-4 w-4" />
            <span class="hidden sm:inline">Stats</span>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            :class="['gap-2', innerTab === 'files' && 'bg-background shadow-sm']"
            @click="innerTab = 'files'"
          >
            <Files class="h-4 w-4" />
            <span class="hidden sm:inline">Files</span>
          </Button>
        </div>
        <div v-if="selectedSessionId" class="flex min-w-0 justify-end">
          <Button
            v-if="innerTab === 'chat'"
            type="button"
            variant="outline"
            size="sm"
            class="shrink-0 gap-2"
            @click="showSettings = !showSettings"
          >
            <SlidersHorizontal class="h-4 w-4" />
            <span class="hidden md:inline">{{ showSettings ? 'Hide settings' : 'Show settings' }}</span>
          </Button>
        </div>
      </header>

      <main class="flex flex-1 flex-col overflow-hidden p-4 lg:p-5">
        <div v-if="!selectedSessionId" class="flex-1 overflow-auto">
          <SessionList 
            :sessions="sessions" 
            @select-session="onSessionChange"
            @create-session="createSession"
            @delete-session="deleteSession"
            @rename-session="renameSession"
          />
        </div>
        <div v-else class="relative h-full min-h-0 overflow-hidden">
          <template v-if="innerTab === 'chat'">
            <div
              ref="chatLayout"
              class="session-chat-layout grid h-full min-h-0 gap-3 overflow-hidden"
              :class="{ 'is-resizing': isResizingGraphPanel }"
              :style="chatLayoutStyle"
            >
              <ExecutionGraphPanel
                class="min-h-0"
                :graph-nodes="visibleGraphNodes"
                :graph-edges="visibleGraphEdges"
                :is-running="isRunning"
                :selected-agent-name="selectedGraphAgentName"
                @select-agent-node="handleGraphAgentSelect"
              />

              <div
                role="separator"
                aria-label="Resize execution graph panel"
                aria-orientation="vertical"
                :aria-valuemin="GRAPH_PANEL_MIN_WIDTH"
                :aria-valuemax="GRAPH_PANEL_MAX_WIDTH"
                :aria-valuenow="Math.round(graphPanelWidth)"
                tabindex="0"
                :class="[
                  'hidden cursor-col-resize touch-none select-none items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:flex',
                  isResizingGraphPanel && 'bg-muted text-foreground',
                ]"
                @pointerdown="startGraphPanelResize"
                @keydown="handleGraphPanelResizeKeydown"
              >
                <GripVertical class="h-4 w-4" />
              </div>

              <div class="flex min-h-0 flex-col overflow-hidden">
                <div
                  v-if="selectedGraphAgentNode"
                  class="shrink-0 border-b bg-background/95 px-1 py-2"
                >
                  <div class="mx-auto flex max-w-4xl flex-wrap items-center gap-2">
                    <div class="flex min-w-0 items-center gap-2 rounded-md border bg-muted/20 px-2.5 py-1.5 text-xs text-foreground">
                      <Bot class="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      <span class="truncate">{{ formatAgentName(selectedGraphAgentNode.agent_name || '') }}</span>
                    </div>
                    <div class="ml-auto flex min-w-0 flex-1 flex-wrap items-center justify-end gap-2">
                      <div
                        v-if="activeAgentFilter"
                        class="flex items-center gap-1.5 rounded-md border border-primary/20 bg-primary/5 px-2 py-1 text-[11px] text-primary"
                      >
                        <ListFilter class="h-3 w-3 shrink-0" />
                        <span class="truncate">{{ formatAgentName(activeAgentFilter) }}</span>
                      </div>
                      <select
                        v-model="selectedGraphAgentModelId"
                        class="h-8 min-w-[13rem] max-w-full rounded-md border border-input bg-background px-2 py-1 text-xs ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                        :disabled="configs.length === 0 || isRunning"
                        :title="selectedGraphAgentModelName"
                      >
                        <option :value="''">Use session default</option>
                        <option v-for="config in configs" :key="config.id" :value="config.id">
                          {{ config.name }} · {{ config.model }}
                        </option>
                      </select>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        title="Clear agent filter"
                        class="h-8 w-8 shrink-0"
                        :disabled="!activeAgentFilter"
                        @click="clearAgentFilter"
                      >
                        <X class="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </div>
                <div class="min-h-0 flex-1 overflow-hidden">
                  <div ref="responseScroll" class="h-full overflow-auto px-1">
                    <div class="mx-auto flex min-h-full max-w-4xl flex-col py-4">
                      <div class="flex-1 space-y-6">
                        <div v-if="messages.length === 0" class="text-sm text-muted-foreground">
                          No messages yet. Start a run to build history.
                        </div>
                        <template v-for="message in visibleDisplayMessages" :key="message.id">
                          <MessageItem
                            :message="message"
                            :is-expanded="expandedMessages[message.id]"
                            @toggle-expand="toggleMessage(message.id)"
                          />
                        </template>

                        <ActiveResponse
                          :output="output"
                          :is-running="isRunning"
                          :stream-error="streamError"
                          :rag-sources="ragSources"
                          :tool-events="toolEvents"
                          :mcp-events="mcpEvents"
                        />
                      </div>
                    </div>
                  </div>
                </div>

                <div class="shrink-0 border-t bg-background/95 px-1 pb-1 pt-3">
                  <div class="mx-auto max-w-4xl rounded-2xl border bg-background shadow-sm transition-shadow focus-within:ring-1 focus-within:ring-ring">
                    <textarea
                      v-model="prompt"
                      rows="1"
                      placeholder="Message Hiro..."
                      class="max-h-44 min-h-12 w-full resize-none bg-transparent px-4 py-3 text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50"
                      :disabled="isRunning"
                      @keydown.enter.exact.prevent="startRun"
                    />
                    <div class="flex items-center justify-between gap-2 border-t px-3 py-2">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        title="Clear"
                        class="h-8 w-8"
                        :disabled="isRunning || (output.length === 0 && !streamError)"
                        @click="clearOutput"
                      >
                        <Trash2 class="h-4 w-4" />
                      </Button>
                      <div class="flex items-center gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="icon"
                          title="Stop"
                          class="h-8 w-8"
                          :disabled="!isRunning"
                          @click="stopRun"
                        >
                          <Square class="h-4 w-4" />
                        </Button>
                        <Button
                          type="button"
                          size="icon"
                          title="Send"
                          class="h-9 w-9 rounded-full"
                          :disabled="!canRun"
                          @click="startRun"
                        >
                          <Loader2 v-if="isRunning" class="h-4 w-4 animate-spin" />
                          <SendHorizontal v-else class="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <div v-else-if="innerTab === 'stats'" class="h-full space-y-6 overflow-auto animate-in fade-in slide-in-from-bottom-2 duration-300 pr-2">
                <div v-if="!currentSessionStats || currentSessionStats.rounds.length === 0" class="flex flex-col items-center justify-center h-full text-muted-foreground italic">
                  <BarChart3 class="h-12 w-12 mb-2 opacity-20" />
                  <p>No statistics available for this session yet.</p>
                  <p class="text-xs">Start a conversation to see token usage.</p>
                </div>
                <template v-else>
                  <div class="grid gap-4 sm:grid-cols-4">
                    <Card>
                      <CardHeader class="pb-2">
                        <CardDescription>Total Tokens</CardDescription>
                        <CardTitle class="text-2xl font-bold">{{ currentSessionStats.total_tokens.toLocaleString() }}</CardTitle>
                      </CardHeader>
                    </Card>
                    <Card>
                      <CardHeader class="pb-2">
                        <CardDescription>Input Tokens</CardDescription>
                        <CardTitle class="text-2xl font-bold text-blue-500">{{ currentSessionStats.total_input_tokens.toLocaleString() }}</CardTitle>
                      </CardHeader>
                    </Card>
                    <Card>
                      <CardHeader class="pb-2">
                        <CardDescription>Cached Tokens</CardDescription>
                        <CardTitle class="text-2xl font-bold text-cyan-500">{{ currentSessionStats.total_cached_input_tokens.toLocaleString() }}</CardTitle>
                      </CardHeader>
                    </Card>
                    <Card>
                      <CardHeader class="pb-2">
                        <CardDescription>Output Tokens</CardDescription>
                        <CardTitle class="text-2xl font-bold text-green-500">{{ currentSessionStats.total_output_tokens.toLocaleString() }}</CardTitle>
                      </CardHeader>
                    </Card>
                  </div>

                  <div v-if="currentSessionStats.model_usage && Object.keys(currentSessionStats.model_usage).length > 0" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <Card v-for="(usage, model) in currentSessionStats.model_usage" :key="model" class="border-primary/20 bg-primary/5">
                      <CardHeader class="pb-2">
                        <CardDescription class="text-xs truncate" :title="model">{{ model }}</CardDescription>
                        <CardTitle class="text-lg font-bold">{{ usage.total.toLocaleString() }}</CardTitle>
                      </CardHeader>
                    </Card>
                  </div>

                  <Card>
                    <CardHeader>
                      <CardTitle>Usage per Round</CardTitle>
                      <CardDescription>Token consumption for each exchange in this session.</CardDescription>
                    </CardHeader>
                    <CardContent>
                      <div class="h-[300px] w-full pt-4">
                        <LineChart
                          v-if="currentSessionStats && currentSessionStats.rounds.length > 0"
                          :data="currentSessionStats.rounds"
                          index="step"
                          :categories="['input_tokens', 'cached_input_tokens', 'output_tokens']"
                          :config="chartConfig"
                          :show-x-axis="true"
                          :show-y-axis="true"
                          :show-tooltip="true"
                          class="h-full w-full"
                        />
                      </div>
                    </CardContent>
                  </Card>

                  <!-- Rounds Table -->
                  <Card>
                    <CardHeader>
                      <CardTitle>Rounds Detail</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div class="relative w-full overflow-auto">
                        <table class="w-full caption-bottom text-sm">
                          <thead class="[&_tr]:border-b">
                            <tr class="border-b transition-colors hover:bg-muted/50 data-[state=selected]:bg-muted">
                              <th class="h-10 px-2 text-left align-middle font-medium text-muted-foreground">Round</th>
                              <th class="h-10 px-2 text-left align-middle font-medium text-muted-foreground">Model</th>
                              <th class="h-10 px-2 text-right align-middle font-medium text-muted-foreground">Input</th>
                              <th class="h-10 px-2 text-right align-middle font-medium text-muted-foreground">Cached</th>
                              <th class="h-10 px-2 text-right align-middle font-medium text-muted-foreground">Output</th>
                              <th class="h-10 px-2 text-right align-middle font-medium text-muted-foreground">Total</th>
                            </tr>
                          </thead>
                          <tbody class="[&_tr:last-child]:border-0">
                            <tr v-for="round in currentSessionStats.rounds" :key="round.step" class="border-b transition-colors hover:bg-muted/50">
                              <td class="p-2 align-middle font-medium">{{ round.step }}</td>
                              <td class="p-2 align-middle text-xs font-mono truncate max-w-[120px]" :title="round.model">{{ round.model }}</td>
                              <td class="p-2 align-middle text-right">{{ round.input_tokens.toLocaleString() }}</td>
                              <td class="p-2 align-middle text-right text-cyan-600 dark:text-cyan-400">{{ (round.cached_input_tokens || 0).toLocaleString() }}</td>
                              <td class="p-2 align-middle text-right">{{ round.output_tokens.toLocaleString() }}</td>
                              <td class="p-2 align-middle text-right font-bold">{{ round.tokens.toLocaleString() }}</td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </CardContent>
                  </Card>
                </template>
              </div>

          <div v-else-if="innerTab === 'files' && selectedSessionId" class="h-full space-y-6 overflow-auto animate-in fade-in slide-in-from-bottom-2 duration-300 pr-2">
                <FileList :session-id="selectedSessionId" />
              </div>
            <Card
              v-if="innerTab === 'chat' && showSettings"
              class="absolute bottom-0 right-0 top-0 z-30 w-[min(24rem,calc(100vw-2rem))] min-h-0 gap-4 overflow-auto border shadow-2xl py-4 animate-in fade-in slide-in-from-right-2 duration-150"
            >
              <CardHeader class="grid-cols-[1fr_auto] px-4">
                <div>
                  <CardTitle>Settings</CardTitle>
                  <CardDescription>Templates, model, and parameters.</CardDescription>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  class="h-8 w-8"
                  @click="showSettings = false"
                >
                  <X class="h-4 w-4" />
                </Button>
              </CardHeader>
              <AgentSettings
                :canSaveTemplate="Boolean(selectedSessionId)"
                v-model:selectedConfigId="selectedConfigId"
                v-model:systemPrompt="systemPrompt"
                v-model:temperature="temperature"
                v-model:maxTokens="maxTokens"
                v-model:enable1mContext="enable1mContext"
                v-model:isDeepAgent="isDeepAgent"
                v-model:enableRag="enableRag"
                :configs="configs"
                :availableTools="availableTools"
                :selectedTools="selectedTools"
                :mcpServers="mcpServers"
                :selectedMcpServers="selectedMcpServers"
                :isLoading="isLoading"
                :isToolsLoading="isToolsLoading"
                :isRunning="isRunning"
                :templates="sessionTemplates"
                @save-template="openSaveTemplateDialog"
                @apply-template="applySessionTemplate"
                @delete-template="deleteSessionTemplate"
                @toggle-tool="toggleTool"
                @toggle-mcp="toggleMcpServer"
              />
            </Card>
          </div>
      </main>

    </SidebarInset>

    <DialogRoot v-model:open="isDeleteSessionDialogOpen">
      <DialogPortal>
        <DialogOverlay class="fixed inset-0 z-50 bg-black/50 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <DialogContent class="fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-lg border bg-background p-5 shadow-lg outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95">
          <div class="space-y-4">
            <div class="space-y-1.5">
              <DialogTitle class="text-base font-semibold">Delete Session</DialogTitle>
              <DialogDescription class="text-sm text-muted-foreground">
                This will delete "{{ pendingDeleteSession?.title || 'Untitled Session' }}" and its files.
              </DialogDescription>
            </div>

            <p v-if="deleteSessionError" class="text-xs text-destructive">{{ deleteSessionError }}</p>

            <div class="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                :disabled="isDeletingSession"
                @click="cancelDeleteSession"
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="destructive"
                :disabled="isDeletingSession"
                @click="confirmDeleteSession"
              >
                <Loader2 v-if="isDeletingSession" class="h-4 w-4 animate-spin" />
                Delete
              </Button>
            </div>
          </div>
        </DialogContent>
      </DialogPortal>
    </DialogRoot>

    <DialogRoot v-model:open="isTemplateDialogOpen">
      <DialogPortal>
        <DialogOverlay class="fixed inset-0 z-50 bg-black/50 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <DialogContent class="fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-lg border bg-background p-5 shadow-lg outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95">
          <form class="space-y-4" @submit.prevent="submitTemplateDialog">
            <div class="space-y-1.5">
              <DialogTitle class="text-base font-semibold">Save Template</DialogTitle>
              <DialogDescription class="text-sm text-muted-foreground">
                Save the current session configuration as a reusable template.
              </DialogDescription>
            </div>

            <div class="space-y-2">
              <Label for="session-template-name">Template name</Label>
              <Input
                id="session-template-name"
                v-model="templateName"
                autocomplete="off"
                placeholder="Template name"
              />
              <p v-if="templateError" class="text-xs text-destructive">{{ templateError }}</p>
            </div>

            <div class="flex justify-end gap-2">
              <DialogClose as-child>
                <Button type="button" variant="outline">Cancel</Button>
              </DialogClose>
              <Button type="submit" :disabled="!templateName.trim()">Save</Button>
            </div>
          </form>
        </DialogContent>
      </DialogPortal>
    </DialogRoot>
  </SidebarProvider>
</template>

<style scoped>
.session-chat-layout {
  grid-template-rows: 14rem minmax(0, 1fr);
}

.session-chat-layout.is-resizing {
  cursor: col-resize;
  user-select: none;
}

@media (min-width: 1024px) {
  .session-chat-layout {
    grid-template-columns: minmax(15rem, var(--execution-graph-width, 320px)) 0.75rem minmax(0, 1fr);
    grid-template-rows: minmax(0, 1fr);
  }
}

.mask-fade {
  mask-image: linear-gradient(to bottom, black 60%, transparent 100%);
}
</style>
