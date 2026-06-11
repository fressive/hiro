<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { 
  Save, Trash2, Loader2, ChevronUp, ChevronDown
} from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { CardContent } from '@/components/ui/card'
import type { LLMConfig, AgentSessionTemplate, Tool, SubAgent, MCPServer } from '@/types/agent'

const props = defineProps<{
  templates: AgentSessionTemplate[]
  canSaveTemplate: boolean
  configs: LLMConfig[]
  availableTools: Tool[]
  availableSubagents: SubAgent[]
  selectedTools: string[]
  mcpServers: MCPServer[]
  selectedMcpServers: string[]
  agentConfigs: Record<string, number | null>
  agentMcpServers: Record<string, string[] | null>
  systemPrompt: string
  temperature: number
  maxTokens: number
  enable1mContext: boolean
  enableRag: boolean
  isLoading: boolean
  isToolsLoading: boolean
  isSubagentsLoading: boolean
  isRunning: boolean
  selectedConfigId: number | null
}>()

const emit = defineEmits<{
  (e: 'update:selectedConfigId', val: number | null): void
  (e: 'update:systemPrompt', val: string): void
  (e: 'update:temperature', val: number): void
  (e: 'update:maxTokens', val: number): void
  (e: 'update:enable1mContext', val: boolean): void
  (e: 'update:enableRag', val: boolean): void
  (e: 'update:agentConfigs', val: Record<string, number | null>): void
  (e: 'update:agentMcpServers', val: Record<string, string[] | null>): void
  (e: 'save-template'): void
  (e: 'apply-template', templateId: number): void
  (e: 'delete-template', templateId: number): void
  (e: 'toggle-tool', toolName: string): void
  (e: 'toggle-mcp', serverName: string): void
}>()

const showTools = ref(false)
const showMcp = ref(false)
const showSubagents = ref(false)
const selectedTemplateId = ref<number | null>(null)
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

const onConfigChange = (e: Event) => {
  const target = e.target as HTMLSelectElement
  emit('update:selectedConfigId', target.value ? Number(target.value) : null)
}

const mainModelLabel = computed(() => {
  const config = props.configs.find((item) => item.id === props.selectedConfigId)
  if (!config) return 'main model'
  return `${config.name} · ${config.model}`
})

const subagentConfigValue = (agentName: string) => {
  const value = props.agentConfigs?.[agentName]
  return typeof value === 'number' ? String(value) : ''
}

const subagentMcpServerNames = (agentName: string) => (
  props.agentMcpServers?.[agentName]?.filter(Boolean) || []
)

const formatSubagentName = (name: string) => (
  name
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
)

const onSubagentConfigChange = (agentName: string, e: Event) => {
  const target = e.target as HTMLSelectElement
  const nextConfigs = { ...(props.agentConfigs || {}) }
  if (!target.value) {
    delete nextConfigs[agentName]
  } else {
    nextConfigs[agentName] = Number(target.value)
  }
  emit('update:agentConfigs', nextConfigs)
}

const toggleSubagentMcpServer = (agentName: string, serverName: string) => {
  const nextServers = { ...(props.agentMcpServers || {}) }
  const current = [...subagentMcpServerNames(agentName)]
  const index = current.indexOf(serverName)
  if (index >= 0) {
    current.splice(index, 1)
  } else {
    current.push(serverName)
  }

  if (current.length === 0) {
    delete nextServers[agentName]
  } else {
    nextServers[agentName] = current
  }
  emit('update:agentMcpServers', nextServers)
}

watch(
  () => props.templates,
  (templates) => {
    if (
      selectedTemplateId.value
      && !templates.some((template) => template.id === selectedTemplateId.value)
    ) {
      selectedTemplateId.value = null
    }
  },
  { deep: true },
)

const onTemplateChange = (e: Event) => {
  const target = e.target as HTMLSelectElement
  const templateId = target.value ? Number(target.value) : null
  selectedTemplateId.value = templateId
  if (templateId) {
    emit('apply-template', templateId)
  }
}

const deleteSelectedTemplate = () => {
  if (!selectedTemplateId.value) return
  emit('delete-template', selectedTemplateId.value)
}
</script>

<template>
  <CardContent class="space-y-4 p-4">
    <div class="space-y-2">
      <Label>Templates</Label>
      <div class="flex gap-2">
        <select
          :value="selectedTemplateId"
          @change="onTemplateChange"
          class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="isRunning"
        >
          <option :value="''">No template selected</option>
          <option v-for="template in templates" :key="template.id" :value="template.id">
            {{ template.name }}
          </option>
        </select>
        <div class="flex gap-1">
          <Button type="button" variant="outline" size="icon" @click="emit('save-template')" :disabled="isRunning || !canSaveTemplate" title="Save Template">
            <Save class="h-4 w-4" />
          </Button>
          <Button type="button" variant="outline" size="icon" class="text-destructive hover:text-destructive hover:bg-destructive/10" @click="deleteSelectedTemplate" :disabled="isRunning || !selectedTemplateId" title="Delete Template">
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
      <div class="flex items-center justify-between">
        <Label>Subagents</Label>
        <Button variant="ghost" size="sm" class="h-8 px-2" @click="showSubagents = !showSubagents">
          <ChevronUp v-if="showSubagents" class="h-4 w-4" />
          <ChevronDown v-else class="h-4 w-4" />
        </Button>
      </div>
      <div v-if="showSubagents" class="space-y-3 border-t pt-3 animate-in fade-in slide-in-from-top-1">
        <div v-if="isSubagentsLoading" class="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 class="h-3 w-3 animate-spin" />
          Loading subagents...
        </div>
        <div v-else-if="availableSubagents.length === 0" class="text-xs text-muted-foreground">
          No specialized subagents available.
        </div>
        <div v-else class="grid gap-3">
          <div v-for="subagent in availableSubagents" :key="subagent.name" class="space-y-1.5">
            <div class="flex min-w-0 items-center justify-between gap-2">
              <Label :for="`subagent-model-${subagent.name}`" class="min-w-0 truncate text-xs">
                {{ formatSubagentName(subagent.name) }}
              </Label>
            </div>
            <select
              :id="`subagent-model-${subagent.name}`"
              :value="subagentConfigValue(subagent.name)"
              @change="onSubagentConfigChange(subagent.name, $event)"
              class="flex h-9 w-full rounded-md border border-input bg-background px-3 py-2 text-xs ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="configs.length === 0 || isRunning"
            >
              <option :value="''">Use main model · {{ mainModelLabel }}</option>
              <option v-for="config in configs" :key="config.id" :value="config.id">
                {{ config.name }} · {{ config.model }}
              </option>
            </select>
            <div class="space-y-1.5">
              <div class="text-[10px] font-medium uppercase text-muted-foreground">
                MCP Servers
              </div>
              <div v-if="mcpServers.length === 0" class="text-[10px] text-muted-foreground">
                No enabled MCP servers.
              </div>
              <div v-else class="grid gap-1.5">
                <label
                  v-for="server in mcpServers"
                  :key="`${subagent.name}-${server.id}`"
                  :for="`subagent-mcp-${subagent.name}-${server.name}`"
                  class="flex min-w-0 items-center gap-2 text-[11px]"
                >
                  <input
                    type="checkbox"
                    :id="`subagent-mcp-${subagent.name}-${server.name}`"
                    :checked="subagentMcpServerNames(subagent.name).includes(server.name)"
                    @change="toggleSubagentMcpServer(subagent.name, server.name)"
                    :disabled="isRunning"
                    class="h-3.5 w-3.5"
                  />
                  <span class="min-w-0 truncate">{{ server.name }}</span>
                </label>
              </div>
            </div>
            <p class="line-clamp-2 text-[10px] text-muted-foreground">
              {{ subagent.description }}
            </p>
          </div>
        </div>
      </div>
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
        <Label>Main Agent MCP Servers</Label>
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
