<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { Play, Square, Loader2, Trash2, ChevronLeft, BarChart3, MessageSquare, Files } from '@lucide/vue'

import { SidebarProvider, SidebarInset, SidebarTrigger } from '@/components/ui/sidebar'
import AppSidebar from '@/components/AppSidebar.vue'
import { Separator } from '@/components/ui/separator'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { apiFetch } from '@/lib/api'

import type { LLMConfig, Tool, EventRecord, AgentSession, MCPServer, AgentMessage } from '@/types/agent'
import MessageItem from '@/components/agent/MessageItem.vue'
import AgentSettings from '@/components/agent/AgentSettings.vue'
import ActiveResponse from '@/components/agent/ActiveResponse.vue'
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
const streamController = ref<AbortController | null>(null)
const toolEvents = ref<EventRecord[]>([])
const mcpEvents = ref<EventRecord[]>([])
const ragSources = ref<string[]>([])
const sessions = ref<AgentSession[]>([])
const selectedSessionId = ref<number | null>(null)
const messages = ref<AgentMessage[]>([])
const systemPrompt = ref('')
const temperature = ref(0.3)
const maxTokens = ref(100000)
const enable1mContext = ref(false)
const enableRag = ref(false)
const responseScroll = ref<HTMLDivElement | null>(null)
const expandedMessages = ref<Record<number, boolean>>({})

const innerTab = ref<'chat' | 'stats' | 'files'>('chat')

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
  return Boolean(prompt.value.trim()) && Boolean(selectedConfigId.value) && !isRunning.value
})

const displayMessages = computed(() => {
  const items = [...messages.value]
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
      isRunning.value = is_running
    }
  } catch (err) {
    console.error('Failed to fetch running status:', err)
  }
}

// Flag to prevent auto-save during session loading
let isInitialLoad = false

const onSessionChange = (id: number | null) => {
  selectedSessionId.value = id
  innerTab.value = 'chat'
  if (id) {
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
      
      // Reset initial load flag after a short delay to let watchers settle
      setTimeout(() => { isInitialLoad = false }, 100)
    }
    fetchMessages(id)
    fetchRunningStatus(id)
    clearOutput()
  } else {
    messages.value = []
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

const deleteSession = async (id?: number) => {
  const sessionId = id || selectedSessionId.value
  if (!sessionId) return
  if (!confirm('Are you sure you want to delete this session?')) return

  const response = await apiFetch(`/api/v1/agent/sessions/${sessionId}`, {
    method: 'DELETE',
  })

  if (response.ok) {
    sessions.value = sessions.value.filter((s) => s.id !== sessionId)
    if (sessionId === selectedSessionId.value) {
      onSessionChange(null)
    }
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

const startRun = async () => {
  if (!canRun.value) return
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

  const controller = new AbortController()
  streamController.value = controller

  try {
    const response = await apiFetch('/api/v1/agent/run', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify({
        config_id: selectedConfigId.value,
        input: currentPrompt,
        session_id: selectedSessionId.value,
        system_prompt: systemPrompt.value,
        temperature: temperature.value,
        max_tokens: maxTokens.value,
        enable_1m_context: enable1mContext.value,
        is_deep_agent: isDeepAgent.value,
        enable_rag: enableRag.value,
        tools: selectedTools.value,
        mcp_servers: selectedMcpServers.value,
      }),
      signal: controller.signal,
    })

    if (!response.ok) {
      const data = await response.json().catch(() => null)
      throw new Error(data?.detail || 'Failed to run agent')
    }

    if (!response.body) {
      throw new Error('No response stream available')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      if (value) {
        buffer += decoder.decode(value, { stream: true })
        buffer = handleSseBuffer(buffer)
      }
    }
    buffer += decoder.decode()
    handleSseBuffer(buffer)
  } catch (error: any) {
    if (error?.name === 'AbortError') {
      streamError.value = 'Request canceled.'
    } else {
      streamError.value = error?.message || 'Failed to run agent.'
    }
  } finally {
    isRunning.value = false
    streamController.value = null
    // Refresh messages to show persisted tool calls
    if (selectedSessionId.value) {
      fetchMessages(selectedSessionId.value)
    }
  }
}

const stopRun = async () => {
  streamController.value?.abort()
  if (selectedSessionId.value) {
    try {
      await apiFetch(`/api/v1/agent/sessions/${selectedSessionId.value}/stop`, {
        method: 'POST'
      })
      isRunning.value = false
    } catch (e) {
      console.error('Failed to stop agent', e)
    }
  }
}

const clearOutput = () => {
  output.value = []
  streamError.value = ''
  toolEvents.value = []
  mcpEvents.value = []
  ragSources.value = []
}

const handleSseBuffer = (buffer: string) => {
  const chunks = buffer.split('\n\n')
  const remainder = chunks.pop() || ''

  for (const chunk of chunks) {
    const lines = chunk.split('\n').filter(Boolean)
    let event = 'message'
    const dataLines: string[] = []
    for (const line of lines) {
      if (line.startsWith('event:')) {
        event = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trim())
      }
    }

    if (!dataLines.length) continue
    const dataText = dataLines.join('\n')
    let payload: any = null
    try {
      payload = JSON.parse(dataText)
    } catch {
      payload = { text: dataText }
    }

    applyEvent(event, payload)
  }

  return remainder
}

const upsertEvent = (target: EventRecord[], incoming: EventRecord) => {
  const index = target.findIndex((item) => item.id === incoming.id)
  if (index >= 0) {
    target[index] = { ...target[index], ...incoming }
  } else {
    target.push(incoming)
  }
}

const applyEvent = (event: string, payload: any) => {
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
      selectedSessionId.value = payload.id
      fetchSessions()
      fetchMessages(payload.id)
    }
    return
  }

  if (event === 'error') {
    const message = payload.message || 'Agent failed.'
    streamError.value = message
    if (payload.session_id) {
      fetchMessages(payload.session_id)
    }
    scrollResponseToBottom()
    return
  }

  if (event === 'done') {
    if (payload.text) {
      output.value = [] // Clear streaming output as it's now in history
    }
    if (payload.session_id) {
      fetchSessions()
      fetchMessages(payload.session_id)
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
  await fetchConfigs()
  await fetchTools()
  await fetchMcpServers()
  await fetchSessions()
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
    isDeepAgent, 
    enableRag, 
    selectedTools, 
    selectedMcpServers
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
      <header class="flex h-16 shrink-0 items-center gap-2 border-b px-4">
        <div class="flex items-center gap-2 flex-1">
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
          <h1 class="text-lg font-semibold">
            {{ selectedSessionId ? (sessions.find(s => s.id === selectedSessionId)?.title || 'Chat') : 'Sessions' }}
          </h1>
        </div>
      </header>

      <main class="flex-1 p-6 space-y-6 overflow-hidden flex flex-col">
        <div v-if="!selectedSessionId" class="flex-1 overflow-auto">
          <SessionList 
            :sessions="sessions" 
            @select-session="onSessionChange"
            @create-session="createSession"
            @delete-session="deleteSession"
          />
        </div>
        <div v-else :class="['grid gap-6 h-full overflow-hidden', innerTab === 'chat' ? 'lg:grid-cols-[minmax(0,1.85fr)_minmax(0,0.55fr)]' : 'grid-cols-1']">
            <div class="flex h-full min-h-0 flex-col gap-6 overflow-hidden">
              <!-- Inner Tab Switcher -->
              <div class="flex items-center gap-1 p-1 bg-muted rounded-lg w-fit">
                <Button 
                  variant="ghost" 
                  size="sm" 
                  :class="['gap-2', innerTab === 'chat' && 'bg-background shadow-sm']"
                  @click="innerTab = 'chat'"
                >
                  <MessageSquare class="h-4 w-4" />
                  Chat
                </Button>
                <Button 
                  variant="ghost" 
                  size="sm" 
                  :class="['gap-2', innerTab === 'stats' && 'bg-background shadow-sm']"
                  @click="innerTab = 'stats'"
                >
                  <BarChart3 class="h-4 w-4" />
                  Stats
                </Button>
                <Button 
                  variant="ghost" 
                  size="sm" 
                  :class="['gap-2', innerTab === 'files' && 'bg-background shadow-sm']"
                  @click="innerTab = 'files'"
                >
                  <Files class="h-4 w-4" />
                  Files
                </Button>
              </div>

              <template v-if="innerTab === 'chat'">
                <Card class="flex-1 min-h-0 overflow-hidden">
                  <CardHeader>
                    <CardTitle>Response</CardTitle>
                  </CardHeader>
                  <CardContent class="h-full min-h-0 overflow-hidden">
                    <div ref="responseScroll" class="h-full overflow-auto">
                      <div class="mb-4 space-y-3">
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
                      </div>

                      <!-- Active Streaming Output -->
                      <ActiveResponse
                        :output="output"
                        :is-running="isRunning"
                        :stream-error="streamError"
                        :rag-sources="ragSources"
                        :tool-events="toolEvents"
                        :mcp-events="mcpEvents"
                      />
                    </div>
                  </CardContent>
                </Card>

                <div class="-mt-2">
                  <Card>
                    <CardContent class="space-y-4">
                      <textarea
                        v-model="prompt"
                        rows="3"
                        placeholder="Your prompt here..."
                        class="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                        :disabled="isRunning"
                        @keydown.enter.ctrl.prevent="startRun"
                      />
                      <div class="flex flex-wrap gap-3">
                        <Button type="button" class="flex-1" :disabled="!canRun" @click="startRun">
                          <Loader2 v-if="isRunning" class="mr-2 h-4 w-4 animate-spin" />
                          <Play v-else class="mr-2 h-4 w-4" />
                          Run
                        </Button>
                        <Button type="button" variant="outline" :disabled="!isRunning" @click="stopRun">
                          <Square class="mr-2 h-4 w-4" />
                          Stop
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          class="ml-auto"
                          :disabled="isRunning || (!output && !streamError)"
                          @click="clearOutput"
                        >
                          <Trash2 class="mr-2 h-4 w-4" />
                          Clear
                        </Button>
                      </div>

                    </CardContent>
                  </Card>
                </div>
              </template>

              <!-- Session Specific Stats -->
              <div v-else-if="innerTab === 'stats'" class="flex-1 space-y-6 overflow-auto animate-in fade-in slide-in-from-bottom-2 duration-300 pr-2">
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

              <!-- Session Specific Files -->
              <div v-else-if="innerTab === 'files' && selectedSessionId" class="flex-1 space-y-6 overflow-auto animate-in fade-in slide-in-from-bottom-2 duration-300 pr-2">
                <FileList :session-id="selectedSessionId" />
              </div>
            </div>

            <Card v-if="innerTab === 'chat'" class="h-full min-h-0 overflow-auto">
              <CardHeader>
                <div>
                  <CardTitle>Settings</CardTitle>
                  <CardDescription>Session, model, and parameters.</CardDescription>
                </div>
              </CardHeader>
              <AgentSettings

                :selectedSessionId="selectedSessionId"
                @update:selectedSessionId="onSessionChange"
                v-model:selectedConfigId="selectedConfigId"
                v-model:systemPrompt="systemPrompt"
                v-model:temperature="temperature"
                v-model:maxTokens="maxTokens"
                v-model:enable1mContext="enable1mContext"
                v-model:isDeepAgent="isDeepAgent"
                v-model:enableRag="enableRag"
                :sessions="sessions"
                :configs="configs"
                :availableTools="availableTools"
                :selectedTools="selectedTools"
                :mcpServers="mcpServers"
                :selectedMcpServers="selectedMcpServers"
                :isLoading="isLoading"
                :isToolsLoading="isToolsLoading"
                :isRunning="isRunning"
                @create-session="createSession"
                @delete-session="deleteSession"
                @toggle-tool="toggleTool"
                @toggle-mcp="toggleMcpServer"
              />
            </Card>
          </div>
      </main>

    </SidebarInset>
  </SidebarProvider>
</template>

<style scoped>
.mask-fade {
  mask-image: linear-gradient(to bottom, black 60%, transparent 100%);
}
</style>
