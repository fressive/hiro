<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Square, Loader2, Trash2, ChevronLeft, BarChart3, MessageSquare, Files, SlidersHorizontal, X, SendHorizontal, Pencil, Check } from '@lucide/vue'
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
  SubAgent,
  EventRecord,
  SubagentEventRecord,
  AgentSession,
  AgentSessionTemplate,
  MCPServer,
  AgentMessage,
} from '@/types/agent'
import MessageItem from '@/components/agent/MessageItem.vue'
import AgentSettings from '@/components/agent/AgentSettings.vue'
import ActiveResponse from '@/components/agent/ActiveResponse.vue'
import AgentCallGraph from '@/components/agent/AgentCallGraph.vue'
import SessionList from '@/components/agent/SessionList.vue'
import FileList from '@/components/agent/FileList.vue'
import { LineChart } from '@/components/ui/chart'

const configs = ref<LLMConfig[]>([])
const availableTools = ref<Tool[]>([])
const availableSubagents = ref<SubAgent[]>([])
const selectedTools = ref<string[]>([])
const mcpServers = ref<MCPServer[]>([])
const selectedMcpServers = ref<string[]>([])
const isLoading = ref(false)
const isToolsLoading = ref(false)
const isSubagentsLoading = ref(false)
const selectedConfigId = ref<number | null>(null)
const prompt = ref('')
const output = ref<any[]>([])
const isRunning = ref(false)
const streamError = ref('')
const sessionSocket = ref<WebSocket | null>(null)
const liveTokenUsage = ref({
  input_tokens: 0,
  cached_input_tokens: 0,
  output_tokens: 0,
})
const toolEvents = ref<EventRecord[]>([])
const mcpEvents = ref<EventRecord[]>([])
const subagentEvents = ref<SubagentEventRecord[]>([])
const agentConfigs = ref<Record<string, number | null>>({})
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
const agentGraphPanelWidthStorageKey = 'HIRO_AGENT_GRAPH_PANEL_WIDTH'
const agentGraphPanelMinWidth = 224
const agentGraphPanelMaxWidth = 520
const agentGraphPanelDefaultWidth = 288
const agentGraphPanelWidth = ref(agentGraphPanelDefaultWidth)
const isResizingAgentGraphPanel = ref(false)
let liveSnapshots: Record<string, {
  output: any[]
  toolEvents: EventRecord[]
  mcpEvents: EventRecord[]
  subagentEvents: SubagentEventRecord[]
  liveTokenUsage: {
    input_tokens: number
    cached_input_tokens: number
    output_tokens: number
  }
}> = {}
let socketSessionId: number | null = null
let socketConnectPromise: Promise<void> | null = null
let manualSocketClose = false
let agentGraphResizeStartX = 0
let agentGraphResizeStartWidth = agentGraphPanelDefaultWidth
let restoreBodyCursor = ''
let restoreBodyUserSelect = ''

const innerTab = ref<'chat' | 'stats' | 'files'>('chat')
const showSettings = ref(false)

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

const clampAgentGraphPanelWidth = (width: number) => (
  Math.min(agentGraphPanelMaxWidth, Math.max(agentGraphPanelMinWidth, width))
)

const agentGraphPanelStyle = computed(() => ({
  '--agent-graph-panel-width': `${agentGraphPanelWidth.value}px`,
}))

const persistAgentGraphPanelWidth = () => {
  localStorage.setItem(agentGraphPanelWidthStorageKey, String(agentGraphPanelWidth.value))
}

const setAgentGraphPanelWidth = (width: number, shouldPersist = true) => {
  agentGraphPanelWidth.value = clampAgentGraphPanelWidth(width)
  if (shouldPersist) {
    persistAgentGraphPanelWidth()
  }
}

const resizeAgentGraphPanelBy = (delta: number) => {
  setAgentGraphPanelWidth(agentGraphPanelWidth.value + delta)
}

const stopAgentGraphPanelResize = () => {
  if (!isResizingAgentGraphPanel.value) return
  isResizingAgentGraphPanel.value = false
  document.body.style.cursor = restoreBodyCursor
  document.body.style.userSelect = restoreBodyUserSelect
  persistAgentGraphPanelWidth()
  window.removeEventListener('pointermove', handleAgentGraphPanelResize)
  window.removeEventListener('pointerup', stopAgentGraphPanelResize)
  window.removeEventListener('pointercancel', stopAgentGraphPanelResize)
}

const handleAgentGraphPanelResize = (event: PointerEvent) => {
  if (!isResizingAgentGraphPanel.value) return
  setAgentGraphPanelWidth(agentGraphResizeStartWidth + event.clientX - agentGraphResizeStartX, false)
}

const startAgentGraphPanelResize = (event: PointerEvent) => {
  if (event.button !== 0) return
  event.preventDefault()
  agentGraphResizeStartX = event.clientX
  agentGraphResizeStartWidth = agentGraphPanelWidth.value
  isResizingAgentGraphPanel.value = true
  restoreBodyCursor = document.body.style.cursor
  restoreBodyUserSelect = document.body.style.userSelect
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  window.addEventListener('pointermove', handleAgentGraphPanelResize)
  window.addEventListener('pointerup', stopAgentGraphPanelResize)
  window.addEventListener('pointercancel', stopAgentGraphPanelResize)
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
    metadata?.tool_events?.length
    || metadata?.mcp_events?.length
    || metadata?.subagent_events?.length
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
  || toolEvents.value.length > 0
  || mcpEvents.value.length > 0
  || subagentEvents.value.length > 0
))

const isActiveAssistantDraft = (message: AgentMessage) => {
  if (message.role !== 'assistant' || !hasLiveResponseActivity.value) return false
  return !message.content.trim() && (!message.tool_calls || message.tool_calls.length === 0)
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

const latestPersistedSubagentEvents = computed<SubagentEventRecord[]>(() => {
  for (let index = messages.value.length - 1; index >= 0; index -= 1) {
    const message = messages.value[index]
    const events = message.extra_metadata?.subagent_events
    if (message.role === 'assistant' && events?.length) {
      return events
    }
  }
  return []
})

const latestPersistedTraceMetadata = computed(() => {
  for (let index = messages.value.length - 1; index >= 0; index -= 1) {
    const message = messages.value[index]
    const metadata = message.extra_metadata
    if (
      message.role === 'assistant'
      && (
        metadata?.tool_events?.length
        || metadata?.mcp_events?.length
        || metadata?.subagent_events?.length
      )
    ) {
      return metadata
    }
  }
  return null
})

const visibleSubagentEvents = computed(() => {
  if (isRunning.value || subagentEvents.value.length > 0) {
    return subagentEvents.value
  }
  return latestPersistedTraceMetadata.value?.subagent_events || latestPersistedSubagentEvents.value
})

const visibleToolEvents = computed(() => {
  if (isRunning.value || toolEvents.value.length > 0 || mcpEvents.value.length > 0 || subagentEvents.value.length > 0) {
    return toolEvents.value
  }
  return latestPersistedTraceMetadata.value?.tool_events || []
})

const visibleMcpEvents = computed(() => {
  if (isRunning.value || toolEvents.value.length > 0 || mcpEvents.value.length > 0 || subagentEvents.value.length > 0) {
    return mcpEvents.value
  }
  return latestPersistedTraceMetadata.value?.mcp_events || []
})

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

const fetchSubagents = async () => {
  isSubagentsLoading.value = true
  try {
    const response = await apiFetch('/api/v1/agent/subagents')
    if (!response.ok) return
    availableSubagents.value = await response.json()
  } finally {
    isSubagentsLoading.value = false
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
  subagentEvents.value = []
  liveTokenUsage.value = {
    input_tokens: 0,
    cached_input_tokens: 0,
    output_tokens: 0,
  }
  liveSnapshots = {}
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

const appendLiveToolBlock = (eventKind: 'tool' | 'mcp', eventId: string) => {
  const exists = output.value.some((block) => (
    block?.type === 'tool_event'
    && block.eventKind === eventKind
    && block.eventId === eventId
  ))
  if (!exists) {
    output.value.push({ type: 'tool_event', eventKind, eventId })
  }
}

const cloneLiveOutput = () => output.value.map((block) => ({ ...block }))
const cloneEvents = (events: EventRecord[]) => events.map((event) => ({ ...event }))
const cloneSubagentEvents = (events: SubagentEventRecord[]) => events.map((event) => ({ ...event }))
const normalizeLiveTokenUsage = (usage: any) => ({
  input_tokens: Number(usage?.input_tokens || 0),
  cached_input_tokens: Number(usage?.cached_input_tokens || 0),
  output_tokens: Number(usage?.output_tokens || 0),
})

const normalizeSubagentStatus = (status: any) => {
  if (status === 'started') return 'running'
  if (status === 'completed') return 'done'
  if (status === 'failed') return 'error'
  return status || 'running'
}

const upsertSubagentEvent = (incoming: SubagentEventRecord) => {
  const eventId = incoming.id || incoming.path || incoming.name || crypto.randomUUID()
  const nextEvent = { ...incoming, id: eventId, path: incoming.path || eventId }
  const index = subagentEvents.value.findIndex((item) => item.id === eventId)
  if (index >= 0) {
    subagentEvents.value[index] = { ...subagentEvents.value[index], ...nextEvent }
  } else {
    subagentEvents.value.push(nextEvent)
  }
}

const applyEvent = (event: string, payload: any) => {
  if (event === 'live_checkpoint') {
    const checkpointId = payload.id || 'default'
    liveSnapshots[checkpointId] = {
      output: cloneLiveOutput(),
      toolEvents: cloneEvents(toolEvents.value),
      mcpEvents: cloneEvents(mcpEvents.value),
      subagentEvents: cloneSubagentEvents(subagentEvents.value),
      liveTokenUsage: { ...liveTokenUsage.value },
    }
    return
  }

  if (event === 'live_rollback') {
    const checkpointId = payload.id || 'default'
    const snapshot = liveSnapshots[checkpointId]
    if (snapshot) {
      output.value = snapshot.output.map((block) => ({ ...block }))
      toolEvents.value = cloneEvents(snapshot.toolEvents)
      mcpEvents.value = cloneEvents(snapshot.mcpEvents)
      subagentEvents.value = cloneSubagentEvents(snapshot.subagentEvents)
      liveTokenUsage.value = { ...snapshot.liveTokenUsage }
    }
    delete liveSnapshots[checkpointId]
    return
  }

  if (event === 'live_commit') {
    delete liveSnapshots[payload.id || 'default']
    return
  }

  if (event === 'token_usage') {
    liveTokenUsage.value = normalizeLiveTokenUsage(
      payload.total_usage || payload.usage,
    )
    return
  }

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

  if (event === 'subagent_start') {
    const eventId = payload.path || payload.name || crypto.randomUUID()
    upsertSubagentEvent({
      id: eventId,
      name: payload.name || 'subagent',
      path: payload.path || eventId,
      status: 'running',
      input: payload.input,
    })
    return
  }

  if (event === 'subagent_status') {
    const eventId = payload.path || payload.name || crypto.randomUUID()
    upsertSubagentEvent({
      id: eventId,
      name: payload.name || 'subagent',
      path: payload.path || eventId,
      status: normalizeSubagentStatus(payload.status),
      input: payload.input,
      error: payload.error,
    })
    return
  }

  if (event === 'subagent_end') {
    const eventId = payload.path || payload.name || crypto.randomUUID()
    upsertSubagentEvent({
      id: eventId,
      name: payload.name || 'subagent',
      path: payload.path || eventId,
      status: normalizeSubagentStatus(payload.status),
      error: payload.error,
    })
    return
  }

  if (event === 'tool_start') {
    const eventId = payload.id || crypto.randomUUID()
    upsertEvent(toolEvents.value, {
      id: eventId,
      name: payload.name || 'tool',
      status: 'running',
      input: payload.input,
      agent: payload.agent,
      agent_path: payload.agent_path,
    })
    appendLiveToolBlock('tool', eventId)
    return
  }

  if (event === 'tool_end') {
    upsertEvent(toolEvents.value, {
      id: payload.id || crypto.randomUUID(),
      name: payload.name || 'tool',
      status: 'done',
      output: payload.output,
      agent: payload.agent,
      agent_path: payload.agent_path,
    })
    return
  }

  if (event === 'tool_error') {
    upsertEvent(toolEvents.value, {
      id: payload.id || crypto.randomUUID(),
      name: payload.name || 'tool',
      status: 'error',
      output: payload.output,
      agent: payload.agent,
      agent_path: payload.agent_path,
    })
    return
  }

  if (event === 'mcp_start') {
    const eventId = payload.id || crypto.randomUUID()
    upsertEvent(mcpEvents.value, {
      id: eventId,
      name: payload.name || 'mcp',
      status: 'running',
      input: payload.input,
      agent: payload.agent,
      agent_path: payload.agent_path,
    })
    appendLiveToolBlock('mcp', eventId)
    return
  }

  if (event === 'mcp_end') {
    upsertEvent(mcpEvents.value, {
      id: payload.id || crypto.randomUUID(),
      name: payload.name || 'mcp',
      status: 'done',
      output: payload.output,
      agent: payload.agent,
      agent_path: payload.agent_path,
    })
    return
  }

  if (event === 'mcp_error') {
    upsertEvent(mcpEvents.value, {
      id: payload.id || crypto.randomUUID(),
      name: payload.name || 'mcp',
      status: 'error',
      output: payload.output,
      agent: payload.agent,
      agent_path: payload.agent_path,
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
  const savedAgentGraphPanelWidthValue = localStorage.getItem(agentGraphPanelWidthStorageKey)
  const savedAgentGraphPanelWidth = Number(savedAgentGraphPanelWidthValue)
  if (savedAgentGraphPanelWidthValue && Number.isFinite(savedAgentGraphPanelWidth)) {
    agentGraphPanelWidth.value = clampAgentGraphPanelWidth(savedAgentGraphPanelWidth)
  }

  await fetchConfigs()
  await fetchTools()
  await fetchSubagents()
  await fetchMcpServers()
  await fetchSessions()
  await fetchSessionTemplates()

  const savedSessionId = Number(localStorage.getItem(selectedSessionStorageKey))
  if (savedSessionId && sessions.value.some((session) => session.id === savedSessionId)) {
    onSessionChange(savedSessionId)
  }
})

onBeforeUnmount(() => {
  stopAgentGraphPanelResize()
  closeSessionSocket()
})

watch(
  () => [displayMessages.value.length, output.value, streamError.value, isRunning.value],
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
              class="session-chat-layout flex h-full min-h-0 flex-col overflow-hidden xl:flex-row"
            >
              <aside
                class="h-56 w-full shrink-0 overflow-hidden border-b xl:h-full xl:w-[var(--agent-graph-panel-width)] xl:border-b-0 xl:border-r"
                :style="agentGraphPanelStyle"
              >
                <AgentCallGraph
                  :subagent-events="visibleSubagentEvents"
                  :tool-events="visibleToolEvents"
                  :mcp-events="visibleMcpEvents"
                  :is-running="isRunning"
                />
              </aside>

              <div
                role="separator"
                aria-label="Resize agent graph panel"
                aria-orientation="vertical"
                :aria-valuemin="agentGraphPanelMinWidth"
                :aria-valuemax="agentGraphPanelMaxWidth"
                :aria-valuenow="agentGraphPanelWidth"
                tabindex="0"
                :class="[
                  'group hidden w-3 shrink-0 cursor-col-resize touch-none items-center justify-center outline-none xl:flex',
                  isResizingAgentGraphPanel && 'bg-accent/50',
                ]"
                title="Resize agent graph panel"
                @pointerdown="startAgentGraphPanelResize"
                @keydown.left.prevent="resizeAgentGraphPanelBy(-24)"
                @keydown.right.prevent="resizeAgentGraphPanelBy(24)"
                @keydown.home.prevent="setAgentGraphPanelWidth(agentGraphPanelMinWidth)"
                @keydown.end.prevent="setAgentGraphPanelWidth(agentGraphPanelMaxWidth)"
              >
                <span class="h-10 w-px rounded-full bg-border transition-colors group-hover:bg-foreground/35 group-focus-visible:bg-foreground/35" />
              </div>

              <div class="flex min-h-0 flex-1 flex-col overflow-hidden">
                <div class="min-h-0 flex-1 overflow-hidden">
                  <div ref="responseScroll" class="h-full overflow-auto px-1">
                    <div class="mx-auto flex min-h-full max-w-4xl flex-col py-4">
                      <div class="flex-1 space-y-6">
                        <div v-if="messages.length === 0" class="text-sm text-muted-foreground">
                          No messages yet. Start a run to build history.
                        </div>
                        <template v-for="message in displayMessages" :key="message.id">
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
                          :live-token-usage="liveTokenUsage"
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
                v-model:enableRag="enableRag"
                v-model:agentConfigs="agentConfigs"
                :configs="configs"
                :availableTools="availableTools"
                :availableSubagents="availableSubagents"
                :selectedTools="selectedTools"
                :mcpServers="mcpServers"
                :selectedMcpServers="selectedMcpServers"
                :isLoading="isLoading"
                :isToolsLoading="isToolsLoading"
                :isSubagentsLoading="isSubagentsLoading"
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
.mask-fade {
  mask-image: linear-gradient(to bottom, black 60%, transparent 100%);
}
</style>
