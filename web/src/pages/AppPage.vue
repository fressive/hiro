<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowRight,
  BarChart3,
  Blocks,
  Bot,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Database,
  FileText,
  MessageCircle,
  RefreshCw,
  Server,
  Sparkles,
  TriangleAlert,
  Wrench,
} from '@lucide/vue'

import {
  SidebarProvider,
  SidebarInset,
  SidebarTrigger,
} from '@/components/ui/sidebar'
import AppSidebar from '@/components/AppSidebar.vue'
import { Separator } from '@/components/ui/separator'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { BarChart, LineChart } from '@/components/ui/chart'
import { apiFetch } from '@/lib/api'
import type { AgentSession, MCPServer, Tool } from '@/types/agent'

type UsagePoint = {
  date: string
  tokens: number
  input_tokens: number
  uncached_input_tokens: number
  cached_input_tokens: number
  output_tokens: number
}

type ModelUsage = {
  input: number
  uncached_input: number
  cached: number
  output: number
  total: number
}

type GlobalStats = {
  total_tokens: number
  total_input_tokens: number
  total_uncached_input_tokens: number
  total_cached_input_tokens: number
  total_output_tokens: number
  model_usage: Record<string, ModelUsage>
  usage_over_time: UsagePoint[]
}

type HealthStatus = {
  status?: string
  installed?: boolean
}

type LLMConfig = {
  id: number
  name: string
  provider: string
  base_url?: string
  model: string
  enable_1m_context?: boolean
}

type RagDocument = {
  id: number
  title: string
  source: string
  status: 'indexed' | 'queued' | 'error' | string
  chunks: number
  updated_at?: string
  tags?: string[]
}

type DashboardState = 'ready' | 'warning' | 'error' | 'neutral'

const router = useRouter()
const selectedSessionStorageKey = 'HIRO_SELECTED_AGENT_SESSION_ID'

const emptyStats: GlobalStats = {
  total_tokens: 0,
  total_input_tokens: 0,
  total_uncached_input_tokens: 0,
  total_cached_input_tokens: 0,
  total_output_tokens: 0,
  model_usage: {},
  usage_over_time: [],
}

const isLoading = ref(true)
const dashboardError = ref('')
const stats = ref<GlobalStats>(emptyStats)
const health = ref<HealthStatus | null>(null)
const sessions = ref<AgentSession[]>([])
const configs = ref<LLMConfig[]>([])
const documents = ref<RagDocument[]>([])
const mcpServers = ref<MCPServer[]>([])
const tools = ref<Tool[]>([])

const usageChartConfig = {
  uncached_input_tokens: {
    label: 'Uncached',
    color: 'var(--chart-2)',
  },
  cached_input_tokens: {
    label: 'Cached',
    color: 'var(--chart-4)',
  },
  output_tokens: {
    label: 'Output',
    color: 'var(--chart-1)',
  },
}

const modelChartConfig = {
  uncached_input: {
    label: 'Uncached',
    color: 'var(--chart-2)',
  },
  cached: {
    label: 'Cached',
    color: 'var(--chart-4)',
  },
  output: {
    label: 'Output',
    color: 'var(--chart-1)',
  },
}

const readJson = async <T>(path: string): Promise<T> => {
  const response = await apiFetch(path)
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`)
  }

  return await response.json() as T
}

const applySettled = <T>(
  result: PromiseSettledResult<T>,
  label: string,
  apply: (value: T) => void,
  failures: string[],
) => {
  if (result.status === 'fulfilled') {
    apply(result.value)
  } else {
    failures.push(label)
  }
}

const loadDashboard = async () => {
  isLoading.value = true
  dashboardError.value = ''

  const results = await Promise.allSettled([
    readJson<HealthStatus>('/api/v1/health'),
    readJson<GlobalStats>('/api/v1/agent/stats'),
    readJson<AgentSession[]>('/api/v1/agent/sessions'),
    readJson<LLMConfig[]>('/api/v1/llm'),
    readJson<RagDocument[]>('/api/v1/rag/documents'),
    readJson<MCPServer[]>('/api/v1/mcp/'),
    readJson<Tool[]>('/api/v1/agent/tools'),
  ])

  const failures: string[] = []
  applySettled(results[0], 'health', value => health.value = value, failures)
  applySettled(results[1], 'usage', value => stats.value = normalizeStats(value), failures)
  applySettled(results[2], 'sessions', value => sessions.value = value, failures)
  applySettled(results[3], 'LLM configs', value => configs.value = value, failures)
  applySettled(results[4], 'RAG documents', value => documents.value = value, failures)
  applySettled(results[5], 'MCP servers', value => mcpServers.value = value, failures)
  applySettled(results[6], 'tools', value => tools.value = value, failures)

  if (failures.length > 0) {
    dashboardError.value = `Unable to load ${failures.join(', ')} data.`
  }

  isLoading.value = false
}

const tokenInputParts = (
  inputTokens: number | null | undefined,
  cachedInputTokens: number | null | undefined,
) => {
  const input = Number(inputTokens || 0)
  const cached = Number(cachedInputTokens || 0)
  if (cached > input) {
    return {
      input: input + cached,
      uncached: input,
      cached,
    }
  }
  return {
    input,
    uncached: Math.max(input - cached, 0),
    cached,
  }
}

const normalizeStats = (value: Partial<GlobalStats> | null | undefined): GlobalStats => {
  const inputParts = tokenInputParts(
    value?.total_input_tokens,
    value?.total_cached_input_tokens,
  )

  return {
    total_tokens: Number(value?.total_tokens || 0),
    total_input_tokens: inputParts.input,
    total_uncached_input_tokens: Number(value?.total_uncached_input_tokens ?? inputParts.uncached),
    total_cached_input_tokens: inputParts.cached,
    total_output_tokens: Number(value?.total_output_tokens || 0),
    model_usage: value?.model_usage || {},
    usage_over_time: Array.isArray(value?.usage_over_time) ? value.usage_over_time : [],
  }
}

const formatNumber = (value: number | null | undefined) => {
  return Number(value || 0).toLocaleString()
}

const formatCompactNumber = (value: number | null | undefined) => {
  return new Intl.NumberFormat(undefined, {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(Number(value || 0))
}

const formatDate = (value: string | null | undefined) => {
  if (!value) return 'Never'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Unknown'

  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

const formatShortDate = (value: string) => {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value

  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
  }).format(date)
}

const formatRelativeTime = (value: string | null | undefined) => {
  if (!value) return 'Never'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Unknown'

  const diff = Date.now() - date.getTime()
  if (diff < 60_000) return 'Just now'

  const minutes = Math.floor(diff / 60_000)
  if (minutes < 60) return `${minutes}m ago`

  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`

  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`

  return formatShortDate(value)
}

const isSameLocalDay = (value: string | null | undefined) => {
  if (!value) return false
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return false

  const now = new Date()
  return date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate()
}

const recentSessions = computed(() => sessions.value.slice(0, 5))
const updatedTodayCount = computed(() => {
  return sessions.value.filter(session => isSameLocalDay(session.updated_at)).length
})
const indexedDocumentCount = computed(() => {
  return documents.value.filter(document => document.status === 'indexed').length
})
const queuedDocumentCount = computed(() => {
  return documents.value.filter(document => document.status === 'queued').length
})
const failedDocumentCount = computed(() => {
  return documents.value.filter(document => document.status === 'error').length
})
const enabledMcpCount = computed(() => {
  return mcpServers.value.filter(server => server.enabled).length
})
const usageTrend = computed(() => {
  return stats.value.usage_over_time
    .slice(-14)
    .map(point => {
      const inputParts = tokenInputParts(point.input_tokens, point.cached_input_tokens)
      return {
        ...point,
        date: formatShortDate(point.date),
        input_tokens: inputParts.input,
        uncached_input_tokens: Number(point.uncached_input_tokens ?? inputParts.uncached),
        cached_input_tokens: inputParts.cached,
        output_tokens: Number(point.output_tokens || 0),
        tokens: Number(point.tokens || 0),
      }
    })
})
const tokenBreakdown = computed(() => [
  {
    label: 'Uncached',
    value: stats.value.total_uncached_input_tokens,
    class: 'bg-[var(--chart-2)]',
  },
  {
    label: 'Cached',
    value: stats.value.total_cached_input_tokens,
    class: 'bg-[var(--chart-4)]',
  },
  {
    label: 'Output',
    value: stats.value.total_output_tokens,
    class: 'bg-[var(--chart-1)]',
  },
])
const topModels = computed(() => {
  return Object.entries(stats.value.model_usage)
    .map(([name, usage]) => {
      const inputParts = tokenInputParts(usage.input, usage.cached)
      return {
        name,
        input: inputParts.input,
        uncached_input: Number(usage.uncached_input ?? inputParts.uncached),
        cached: inputParts.cached,
        output: Number(usage.output || 0),
        total: Number(usage.total || 0),
      }
    })
    .sort((a, b) => b.total - a.total)
    .slice(0, 6)
})
const modelUsageChartData = computed(() => {
  return topModels.value.map(model => ({
    model: model.name,
    uncached_input: model.uncached_input,
    cached: model.cached,
    output: model.output,
  }))
})
const maxModelTokens = computed(() => {
  return Math.max(...topModels.value.map(model => model.total), 0)
})
const latestSession = computed(() => sessions.value[0] || null)

const summaryCards = computed(() => [
  {
    label: 'Total Tokens',
    value: formatCompactNumber(stats.value.total_tokens),
    detail: `${formatNumber(stats.value.total_uncached_input_tokens)} uncached / ${formatNumber(stats.value.total_cached_input_tokens)} cached / ${formatNumber(stats.value.total_output_tokens)} output`,
    icon: BarChart3,
    tone: 'bg-primary text-primary-foreground',
  },
  {
    label: 'Sessions',
    value: formatNumber(sessions.value.length),
    detail: `${formatNumber(updatedTodayCount.value)} updated today`,
    icon: MessageCircle,
    tone: 'bg-[var(--chart-2)] text-white',
  },
  {
    label: 'LLM Configs',
    value: formatNumber(configs.value.length),
    detail: configs.value.length ? `${configs.value[0].provider} / ${configs.value[0].model}` : 'No provider configured',
    icon: Bot,
    tone: 'bg-[var(--chart-3)] text-white',
  },
  {
    label: 'Knowledge Base',
    value: formatNumber(indexedDocumentCount.value),
    detail: `${formatNumber(documents.value.length)} documents / ${formatNumber(queuedDocumentCount.value)} queued`,
    icon: Database,
    tone: 'bg-[var(--chart-5)] text-white',
  },
])

const readinessItems = computed(() => [
  {
    label: 'Backend',
    value: health.value?.status === 'healthy' ? 'Healthy' : 'Unavailable',
    state: health.value?.status === 'healthy' ? 'ready' : 'error',
    icon: Server,
    route: null,
  },
  {
    label: 'LLM',
    value: configs.value.length ? `${configs.value.length} configured` : 'Needs config',
    state: configs.value.length ? 'ready' : 'warning',
    icon: Bot,
    route: '/llm',
  },
  {
    label: 'RAG',
    value: documents.value.length
      ? `${indexedDocumentCount.value}/${documents.value.length} indexed`
      : 'No documents',
    state: failedDocumentCount.value
      ? 'error'
      : documents.value.length
        ? 'ready'
        : 'neutral',
    icon: FileText,
    route: '/rag',
  },
  {
    label: 'MCP',
    value: mcpServers.value.length
      ? `${enabledMcpCount.value}/${mcpServers.value.length} enabled`
      : 'No servers',
    state: enabledMcpCount.value ? 'ready' : mcpServers.value.length ? 'warning' : 'neutral',
    icon: Blocks,
    route: '/mcp',
  },
  {
    label: 'Tools',
    value: `${tools.value.length} available`,
    state: tools.value.length ? 'ready' : 'neutral',
    icon: Wrench,
    route: '/sessions',
  },
])

const stateLabel = (state: DashboardState) => {
  if (state === 'ready') return 'Ready'
  if (state === 'warning') return 'Check'
  if (state === 'error') return 'Issue'
  return 'Idle'
}

const stateIcon = (state: DashboardState) => {
  if (state === 'ready') return CheckCircle2
  if (state === 'error') return TriangleAlert
  if (state === 'warning') return CircleAlert
  return Clock3
}

const stateClass = (state: DashboardState) => {
  if (state === 'ready') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
  if (state === 'error') return 'border-destructive/20 bg-destructive/10 text-destructive'
  if (state === 'warning') return 'border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300'
  return 'border-border bg-muted text-muted-foreground'
}

const documentStatusClass = (status: string) => {
  if (status === 'indexed') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
  if (status === 'queued') return 'border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300'
  if (status === 'error') return 'border-destructive/20 bg-destructive/10 text-destructive'
  return 'border-border bg-muted text-muted-foreground'
}

const modelBarWidth = (value: number) => {
  if (!maxModelTokens.value) return '0%'
  return `${Math.max(4, Math.round((value / maxModelTokens.value) * 100))}%`
}

const routeTo = (path: string | null) => {
  if (!path) return
  router.push(path)
}

const openSession = (sessionId: number) => {
  localStorage.setItem(selectedSessionStorageKey, String(sessionId))
  router.push('/sessions')
}

onMounted(loadDashboard)
</script>

<template>
  <SidebarProvider>
    <AppSidebar />
    <SidebarInset class="flex h-screen flex-col overflow-hidden">
      <header class="flex h-16 shrink-0 items-center gap-2 border-b px-4">
        <SidebarTrigger class="-ml-1" />
        <Separator orientation="vertical" class="mr-2 h-4" />
        <div class="min-w-0">
          <h1 class="truncate text-lg font-semibold">Dashboard</h1>
          <p class="hidden text-xs text-muted-foreground sm:block">
            {{ latestSession ? `Latest session updated ${formatRelativeTime(latestSession.updated_at)}` : 'Workspace overview' }}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          class="ml-auto gap-2"
          :disabled="isLoading"
          @click="loadDashboard"
        >
          <RefreshCw :class="['h-4 w-4', isLoading && 'animate-spin']" />
          Refresh
        </Button>
      </header>

      <main class="flex-1 overflow-auto p-4 md:p-6">
        <div class="mx-auto flex w-full max-w-7xl flex-col gap-6">
          <div
            v-if="dashboardError"
            class="flex items-start gap-3 rounded-lg border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200"
          >
            <CircleAlert class="mt-0.5 h-4 w-4 shrink-0" />
            <div class="min-w-0 flex-1">
              <p class="font-medium">Partial dashboard data</p>
              <p class="mt-1 text-amber-700/90 dark:text-amber-200/80">{{ dashboardError }}</p>
            </div>
          </div>

          <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <Card
              v-for="card in summaryCards"
              :key="card.label"
              class="gap-4 py-5"
            >
              <CardHeader class="flex flex-row items-start justify-between gap-4 px-5 pb-0">
                <div class="min-w-0 space-y-1">
                  <CardDescription>{{ card.label }}</CardDescription>
                  <CardTitle class="text-2xl">
                    <Skeleton v-if="isLoading" class="h-8 w-24" />
                    <span v-else>{{ card.value }}</span>
                  </CardTitle>
                </div>
                <div :class="['flex h-10 w-10 shrink-0 items-center justify-center rounded-md', card.tone]">
                  <component :is="card.icon" class="h-5 w-5" />
                </div>
              </CardHeader>
              <CardContent class="px-5 pt-0">
                <Skeleton v-if="isLoading" class="h-4 w-44" />
                <p v-else class="truncate text-sm text-muted-foreground">
                  {{ card.detail }}
                </p>
              </CardContent>
            </Card>
          </section>

          <section class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
            <Card class="min-h-[420px]">
              <CardHeader class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <CardTitle>Token Usage</CardTitle>
                  <CardDescription>Daily usage across all agent sessions</CardDescription>
                </div>
                <Button variant="outline" size="sm" class="gap-2" @click="routeTo('/sessions')">
                  <MessageCircle class="h-4 w-4" />
                  Sessions
                </Button>
              </CardHeader>
              <CardContent class="space-y-6">
                <div v-if="isLoading" class="space-y-4">
                  <Skeleton class="h-[260px] w-full" />
                  <div class="grid gap-3 sm:grid-cols-3">
                    <Skeleton class="h-16 w-full" />
                    <Skeleton class="h-16 w-full" />
                    <Skeleton class="h-16 w-full" />
                  </div>
                </div>

                <template v-else>
                  <div
                    v-if="usageTrend.length"
                    class="h-[260px] min-w-0"
                  >
                    <LineChart
                      :data="usageTrend"
                      index="date"
                      :categories="['uncached_input_tokens', 'cached_input_tokens', 'output_tokens']"
                      :config="usageChartConfig"
                      :show-grid-line="true"
                      class="h-full"
                    />
                  </div>
                  <div
                    v-else
                    class="flex h-[260px] flex-col items-center justify-center gap-3 rounded-lg border border-dashed text-center"
                  >
                    <BarChart3 class="h-8 w-8 text-muted-foreground" />
                    <div>
                      <p class="font-medium">No token usage yet</p>
                      <p class="text-sm text-muted-foreground">Run an agent session to populate usage metrics.</p>
                    </div>
                  </div>

                  <div class="grid gap-3 sm:grid-cols-3">
                    <div
                      v-for="item in tokenBreakdown"
                      :key="item.label"
                      class="rounded-lg border px-4 py-3"
                    >
                      <div class="flex items-center gap-2">
                        <span :class="['h-2.5 w-2.5 rounded-full', item.class]" />
                        <span class="text-sm text-muted-foreground">{{ item.label }}</span>
                      </div>
                      <p class="mt-2 text-xl font-semibold">{{ formatNumber(item.value) }}</p>
                    </div>
                  </div>
                </template>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Model Mix</CardTitle>
                <CardDescription>Top models by token volume</CardDescription>
              </CardHeader>
              <CardContent>
                <div v-if="isLoading" class="space-y-4">
                  <Skeleton class="h-[180px] w-full" />
                  <Skeleton class="h-10 w-full" />
                  <Skeleton class="h-10 w-full" />
                  <Skeleton class="h-10 w-full" />
                </div>

                <template v-else>
                  <div v-if="modelUsageChartData.length" class="h-[180px]">
                    <BarChart
                      :data="modelUsageChartData"
                      index="model"
                      :categories="['uncached_input', 'cached', 'output']"
                      :config="modelChartConfig"
                      :show-x-axis="false"
                      :show-y-axis="false"
                      class="h-full"
                    />
                  </div>

                  <div
                    v-if="topModels.length"
                    class="mt-5 space-y-4"
                  >
                    <div
                      v-for="model in topModels"
                      :key="model.name"
                      class="space-y-2"
                    >
                      <div class="flex items-center justify-between gap-3 text-sm">
                        <span class="min-w-0 truncate font-medium" :title="model.name">{{ model.name }}</span>
                        <span class="shrink-0 font-mono text-xs text-muted-foreground">{{ formatCompactNumber(model.total) }}</span>
                      </div>
                      <div class="h-2 rounded-full bg-muted">
                        <div
                          class="h-2 rounded-full bg-primary"
                          :style="{ width: modelBarWidth(model.total) }"
                        />
                      </div>
                    </div>
                  </div>

                  <div
                    v-else
                    class="flex h-[260px] flex-col items-center justify-center gap-3 rounded-lg border border-dashed text-center"
                  >
                    <Bot class="h-8 w-8 text-muted-foreground" />
                    <div>
                      <p class="font-medium">No model usage yet</p>
                      <p class="text-sm text-muted-foreground">Usage appears after assistant responses are saved.</p>
                    </div>
                  </div>
                </template>
              </CardContent>
            </Card>
          </section>

          <section class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
            <Card>
              <CardHeader class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <CardTitle>Recent Sessions</CardTitle>
                  <CardDescription>Most recently updated agent workspaces</CardDescription>
                </div>
                <Button variant="outline" size="sm" class="gap-2" @click="routeTo('/sessions')">
                  View All
                  <ArrowRight class="h-4 w-4" />
                </Button>
              </CardHeader>
              <CardContent>
                <div v-if="isLoading" class="space-y-3">
                  <Skeleton class="h-16 w-full" />
                  <Skeleton class="h-16 w-full" />
                  <Skeleton class="h-16 w-full" />
                </div>

                <div
                  v-else-if="recentSessions.length"
                  class="divide-y rounded-lg border"
                >
                  <button
                    v-for="session in recentSessions"
                    :key="session.id"
                    type="button"
                    class="group flex min-h-16 w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-muted/60"
                    @click="openSession(session.id)"
                  >
                    <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-muted">
                      <MessageCircle class="h-5 w-5 text-muted-foreground" />
                    </div>
                    <div class="min-w-0 flex-1">
                      <div class="flex min-w-0 items-center gap-2">
                        <p class="truncate font-medium">{{ session.title || 'Untitled session' }}</p>
                        <span
                          v-if="session.enable_rag"
                          class="shrink-0 rounded border border-emerald-500/20 bg-emerald-500/10 px-1.5 py-0.5 text-[11px] font-medium text-emerald-700 dark:text-emerald-300"
                        >
                          RAG
                        </span>
                        <span
                          v-if="session.tools?.length"
                          class="shrink-0 rounded border px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground"
                        >
                          {{ session.tools.length }} tools
                        </span>
                      </div>
                      <p class="mt-1 truncate text-sm text-muted-foreground">
                        Updated {{ formatDate(session.updated_at) }}
                      </p>
                    </div>
                    <ArrowRight class="h-4 w-4 shrink-0 text-muted-foreground transition group-hover:translate-x-0.5" />
                  </button>
                </div>

                <div
                  v-else
                  class="flex min-h-48 flex-col items-center justify-center gap-3 rounded-lg border border-dashed text-center"
                >
                  <MessageCircle class="h-8 w-8 text-muted-foreground" />
                  <div>
                    <p class="font-medium">No sessions yet</p>
                    <p class="text-sm text-muted-foreground">Create a session from the agent workspace.</p>
                  </div>
                  <Button variant="outline" size="sm" class="gap-2" @click="routeTo('/sessions')">
                    <Sparkles class="h-4 w-4" />
                    New Session
                  </Button>
                </div>
              </CardContent>
            </Card>

            <div class="grid gap-6">
              <Card>
                <CardHeader>
                  <CardTitle>Readiness</CardTitle>
                  <CardDescription>Core service and configuration state</CardDescription>
                </CardHeader>
                <CardContent>
                  <div v-if="isLoading" class="space-y-3">
                    <Skeleton class="h-12 w-full" />
                    <Skeleton class="h-12 w-full" />
                    <Skeleton class="h-12 w-full" />
                    <Skeleton class="h-12 w-full" />
                    <Skeleton class="h-12 w-full" />
                  </div>

                  <div v-else class="space-y-3">
                    <button
                      v-for="item in readinessItems"
                      :key="item.label"
                      type="button"
                      :disabled="!item.route"
                      class="flex w-full items-center gap-3 rounded-lg border px-3 py-3 text-left transition enabled:hover:bg-muted/60 disabled:cursor-default"
                      @click="routeTo(item.route)"
                    >
                      <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted">
                        <component :is="item.icon" class="h-4 w-4 text-muted-foreground" />
                      </div>
                      <div class="min-w-0 flex-1">
                        <p class="truncate text-sm font-medium">{{ item.label }}</p>
                        <p class="truncate text-xs text-muted-foreground">{{ item.value }}</p>
                      </div>
                      <span :class="['inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-1 text-xs font-medium', stateClass(item.state as DashboardState)]">
                        <component :is="stateIcon(item.state as DashboardState)" class="h-3.5 w-3.5" />
                        {{ stateLabel(item.state as DashboardState) }}
                      </span>
                    </button>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Knowledge Queue</CardTitle>
                  <CardDescription>Recent RAG document states</CardDescription>
                </CardHeader>
                <CardContent>
                  <div v-if="isLoading" class="space-y-3">
                    <Skeleton class="h-11 w-full" />
                    <Skeleton class="h-11 w-full" />
                    <Skeleton class="h-11 w-full" />
                  </div>

                  <div v-else-if="documents.length" class="space-y-3">
                    <div
                      v-for="document in documents.slice(0, 4)"
                      :key="document.id"
                      class="flex items-center gap-3"
                    >
                      <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted">
                        <FileText class="h-4 w-4 text-muted-foreground" />
                      </div>
                      <div class="min-w-0 flex-1">
                        <p class="truncate text-sm font-medium" :title="document.title">{{ document.title }}</p>
                        <p class="truncate text-xs text-muted-foreground">
                          {{ formatNumber(document.chunks) }} chunks
                        </p>
                      </div>
                      <span :class="['shrink-0 rounded-full border px-2 py-1 text-xs font-medium capitalize', documentStatusClass(document.status)]">
                        {{ document.status }}
                      </span>
                    </div>
                  </div>

                  <div
                    v-else
                    class="flex min-h-32 flex-col items-center justify-center gap-3 rounded-lg border border-dashed text-center"
                  >
                    <Database class="h-7 w-7 text-muted-foreground" />
                    <div>
                      <p class="font-medium">No documents</p>
                      <p class="text-sm text-muted-foreground">Add documents from RAG management.</p>
                    </div>
                    <Button variant="outline" size="sm" @click="routeTo('/rag')">
                      Open RAG
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </div>
          </section>
        </div>
      </main>
    </SidebarInset>
  </SidebarProvider>
</template>
