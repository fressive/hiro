<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { 
  Plus, Trash2, Loader2, ChevronUp, ChevronDown
} from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { CardContent } from '@/components/ui/card'
import type { LLMConfig, AgentSession, Tool, MCPServer } from '@/types/agent'

const props = defineProps<{
  sessions: AgentSession[]
  selectedSessionId: number | null
  configs: LLMConfig[]
  availableTools: Tool[]
  selectedTools: string[]
  mcpServers: MCPServer[]
  selectedMcpServers: string[]
  systemPrompt: string
  temperature: number
  maxTokens: number
  enable1mContext: boolean
  isDeepAgent: boolean
  enableRag: boolean
  isLoading: boolean
  isToolsLoading: boolean
  isRunning: boolean
  selectedConfigId: number | null
}>()

const emit = defineEmits<{
  (e: 'update:selectedSessionId', val: number | null): void
  (e: 'update:selectedConfigId', val: number | null): void
  (e: 'update:systemPrompt', val: string): void
  (e: 'update:temperature', val: number): void
  (e: 'update:maxTokens', val: number): void
  (e: 'update:enable1mContext', val: boolean): void
  (e: 'update:isDeepAgent', val: boolean): void
  (e: 'update:enableRag', val: boolean): void
  (e: 'create-session'): void
  (e: 'delete-session'): void
  (e: 'toggle-tool', toolName: string): void
  (e: 'toggle-mcp', serverName: string): void
}>()

const showTools = ref(false)
const showMcp = ref(false)
const isEditingTemperature = ref(false)
const isEditingMaxTokens = ref(false)
const temperatureText = ref(String(props.temperature))
const maxTokensText = ref(String(props.maxTokens))

const numberText = (value: number, fallback: number) => (
  Number.isFinite(value) ? String(value) : String(fallback)
)

watch(
  () => props.temperature,
  (value) => {
    if (!isEditingTemperature.value) {
      temperatureText.value = numberText(value, 0.3)
    }
  },
)

watch(
  () => props.maxTokens,
  (value) => {
    if (!isEditingMaxTokens.value) {
      maxTokensText.value = numberText(value, 100000)
    }
  },
)

const temperatureModel = computed({
  get: () => temperatureText.value,
  set: (value: string | number) => {
    const text = String(value)
    temperatureText.value = text
    if (!text) return

    const parsed = Number(text)
    if (Number.isFinite(parsed)) {
      emit('update:temperature', parsed)
    }
  },
})

const maxTokensModel = computed({
  get: () => maxTokensText.value,
  set: (value: string | number) => {
    const text = String(value)
    maxTokensText.value = text
    if (!text) return

    const parsed = Number(text)
    if (Number.isFinite(parsed)) {
      emit('update:maxTokens', parsed)
    }
  },
})

const normalizeTemperature = () => {
  isEditingTemperature.value = false
  const parsed = Number(temperatureText.value)
  if (!Number.isFinite(parsed)) {
    temperatureText.value = numberText(props.temperature, 0.3)
    return
  }

  const normalized = Math.min(2, Math.max(0, parsed))
  temperatureText.value = String(normalized)
  emit('update:temperature', normalized)
}

const normalizeMaxTokens = () => {
  isEditingMaxTokens.value = false
  const parsed = Number(maxTokensText.value)
  if (!Number.isFinite(parsed)) {
    maxTokensText.value = numberText(props.maxTokens, 100000)
    return
  }

  const normalized = Math.max(1, Math.trunc(parsed))
  maxTokensText.value = String(normalized)
  emit('update:maxTokens', normalized)
}

const onSessionChange = (e: Event) => {
  const target = e.target as HTMLSelectElement
  emit('update:selectedSessionId', target.value ? Number(target.value) : null)
}

const onConfigChange = (e: Event) => {
  const target = e.target as HTMLSelectElement
  emit('update:selectedConfigId', target.value ? Number(target.value) : null)
}
</script>

<template>
  <CardContent class="space-y-4 p-4">
    <div class="space-y-2">
      <Label>Session</Label>
      <div class="flex gap-2">
        <select
          :value="selectedSessionId"
          @change="onSessionChange"
          class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="isRunning"
        >
          <option v-if="sessions.length === 0" disabled :value="null">No sessions</option>
          <option v-for="session in sessions" :key="session.id" :value="session.id">
            #{{ session.id }} · {{ session.title || 'Untitled' }}
          </option>
        </select>
        <div class="flex gap-1">
          <Button type="button" variant="outline" size="icon" @click="emit('create-session')" :disabled="isRunning" title="New Session">
            <Plus class="h-4 w-4" />
          </Button>
          <Button type="button" variant="outline" size="icon" class="text-destructive hover:text-destructive hover:bg-destructive/10" @click="emit('delete-session')" :disabled="isRunning || !selectedSessionId" title="Delete Session">
            <Trash2 class="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>

    <div class="space-y-2">
      <Label>Model</Label>
      <div v-if="isLoading" class="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 class="h-4 w-4 animate-spin" />
        Loading models...
      </div>
      <select
        v-else
        :value="selectedConfigId"
        @change="onConfigChange"
        class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="configs.length === 0 || isRunning"
      >
        <option v-if="configs.length === 0" disabled :value="null">No models configured</option>
        <option v-for="config in configs" :key="config.id" :value="config.id">
          {{ config.name }} · {{ config.model }}
        </option>
      </select>
    </div>

    <div class="space-y-2">
      <Label>System Prompt</Label>
      <textarea
        :value="systemPrompt"
        @input="emit('update:systemPrompt', ($event.target as HTMLTextAreaElement).value)"
        rows="6"
        class="flex min-h-[140px] w-full rounded-md border border-input bg-background px-3 py-2 text-xs ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="isRunning"
      />
    </div>

    <div class="flex items-center justify-between rounded-lg border p-3">
      <div>
        <Label>Deep Agent</Label>
        <p class="text-xs text-muted-foreground">Use advanced agent reasoning.</p>
      </div>
      <input 
        type="checkbox" 
        :checked="isDeepAgent" 
        @change="emit('update:isDeepAgent', ($event.target as HTMLInputElement).checked)"
        class="h-4 w-4" 
        :disabled="isRunning" 
      />
    </div>

    <div class="flex items-center justify-between rounded-lg border p-3">
      <div>
        <Label>RAG Support</Label>
        <p class="text-xs text-muted-foreground">Retrieve relevant context from documents.</p>
      </div>
      <input 
        type="checkbox" 
        :checked="enableRag" 
        @change="emit('update:enableRag', ($event.target as HTMLInputElement).checked)"
        class="h-4 w-4" 
        :disabled="isRunning" 
      />
    </div>

    <div class="space-y-2">
      <div class="flex items-center justify-between">
        <Label>Tools</Label>
        <Button variant="ghost" size="sm" class="h-8 px-2" @click="showTools = !showTools">
          <ChevronUp v-if="showTools" class="h-4 w-4" />
          <ChevronDown v-else class="h-4 w-4" />
        </Button>
      </div>
      <div v-if="showTools" class="space-y-2 pt-1 border-t animate-in fade-in slide-in-from-top-1">
        <div v-if="isToolsLoading" class="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 class="h-3 w-3 animate-spin" />
          Loading tools...
        </div>
        <div v-else-if="availableTools.length === 0" class="text-xs text-muted-foreground">
          No tools available.
        </div>
        <div v-else class="grid gap-2">
          <div v-for="tool in availableTools" :key="tool.name" class="flex items-start gap-2 group">
            <input
              type="checkbox"
              :id="`tool-${tool.name}`"
              :checked="selectedTools.includes(tool.name)"
              @change="emit('toggle-tool', tool.name)"
              :disabled="isRunning"
              class="h-4 w-4 mt-0.5"
            />
            <div class="grid gap-1.5 leading-none">
              <label
                :for="`tool-${tool.name}`"
                class="text-xs font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 group-hover:text-primary transition-colors cursor-pointer"
              >
                {{ tool.name }}
              </label>
              <p class="text-[10px] text-muted-foreground line-clamp-1 group-hover:line-clamp-none transition-all">
                {{ tool.description }}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="space-y-2">
      <div class="flex items-center justify-between">
        <Label>MCP Servers</Label>
        <Button variant="ghost" size="sm" class="h-8 px-2" @click="showMcp = !showMcp">
          <ChevronUp v-if="showMcp" class="h-4 w-4" />
          <ChevronDown v-else class="h-4 w-4" />
        </Button>
      </div>
      <div v-if="showMcp" class="space-y-2 pt-1 border-t animate-in fade-in slide-in-from-top-1">
        <div v-if="mcpServers.length === 0" class="text-xs text-muted-foreground">
          No enabled MCP servers.
        </div>
        <div v-else class="grid gap-2">
          <div v-for="server in mcpServers" :key="server.id" class="flex items-start gap-2 group">
            <input
              type="checkbox"
              :id="`mcp-${server.name}`"
              :checked="selectedMcpServers.includes(server.name)"
              @change="emit('toggle-mcp', server.name)"
              :disabled="isRunning"
              class="h-4 w-4 mt-0.5"
            />
            <div class="grid gap-1.5 leading-none">
              <label
                :for="`mcp-${server.name}`"
                class="text-xs font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 group-hover:text-primary transition-colors cursor-pointer"
              >
                {{ server.name }}
              </label>
              <p class="text-[10px] text-muted-foreground line-clamp-1 group-hover:line-clamp-none transition-all">
                {{ server.type === 'command' ? 'Stdio' : 'HTTP' }} · {{ server.type === 'command' ? server.command : server.url }}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="grid grid-cols-2 gap-4">
      <div class="space-y-2">
        <Label>Temperature</Label>
        <Input 
          type="number" 
          step="0.1" 
          min="0" 
          max="2" 
          v-model="temperatureModel"
          @focus="isEditingTemperature = true"
          @blur="normalizeTemperature"
          :disabled="isRunning" 
        />
      </div>
      <div class="space-y-2">
        <Label>Max Tokens</Label>
        <Input 
          type="number" 
          min="1" 
          v-model="maxTokensModel"
          @focus="isEditingMaxTokens = true"
          @blur="normalizeMaxTokens"
          :disabled="isRunning" 
        />
      </div>
    </div>

    <div class="flex items-center justify-between rounded-lg border p-3">
      <div>
        <Label>Enable 1M Context (Anthropic)</Label>
        <p class="text-xs text-muted-foreground">Use when your provider supports 1m context.</p>
      </div>
      <input 
        type="checkbox" 
        :checked="enable1mContext" 
        @change="emit('update:enable1mContext', ($event.target as HTMLInputElement).checked)"
        class="h-4 w-4" 
        :disabled="isRunning" 
      />
    </div>
  </CardContent>
</template>
