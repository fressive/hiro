<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Blocks, Loader2, Plus, XCircle } from '@lucide/vue'

import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import AppSidebar from '@/components/AppSidebar.vue'
import { Separator } from '@/components/ui/separator'
import { Button } from '@/components/ui/button'
import { apiFetch } from '@/lib/api'

import type { MCPServer } from '@/types/agent'
import MCPServerForm from '@/components/mcp/MCPServerForm.vue'
import MCPServerCard from '@/components/mcp/MCPServerCard.vue'

const servers = ref<MCPServer[]>([])
const isLoading = ref(false)
const isSaving = ref(false)
const isTesting = ref(false)
const error = ref('')
const testResult = ref<{ success: boolean; message: string; tools?: string[] } | null>(null)
const serverTestResults = ref<Record<number, { success: boolean; message: string; tools?: string[] }>>({})

const showForm = ref(false)
const editingId = ref<number | null>(null)
const editingData = ref<Partial<MCPServer> | undefined>(undefined)

const fetchServers = async () => {
  isLoading.value = true
  error.value = ''
  try {
    const response = await apiFetch('/api/v1/mcp/')
    if (!response.ok) throw new Error('Failed to fetch MCP servers')
    servers.value = await response.json()
  } catch (err: any) {
    error.value = err.message || 'Unable to load MCP servers.'
  } finally {
    isLoading.value = false
  }
}

const resetForm = () => {
  editingId.value = null
  editingData.value = undefined
  showForm.value = false
  testResult.value = null
}

const openAddForm = () => {
  resetForm()
  showForm.value = true
}

const openEditForm = (server: MCPServer) => {
  editingId.value = server.id
  editingData.value = { ...server }
  showForm.value = true
  testResult.value = null
}

const handleTest = async (payload: any) => {
  isTesting.value = true
  testResult.value = null
  error.value = ''

  try {
    const response = await apiFetch('/api/v1/mcp/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })

    if (!response.ok) {
      const data = await response.json()
      throw new Error(data.detail || 'Test failed')
    }

    testResult.value = await response.json()
  } catch (err: any) {
    testResult.value = {
      success: false,
      message: err.message || 'Unable to test MCP server.'
    }
  } finally {
    isTesting.value = false
  }
}

const testExistingServer = async (server: MCPServer) => {
  isTesting.value = true
  serverTestResults.value[server.id] = undefined as any // Clear previous result
  
  const payload = {
    name: server.name,
    type: server.type,
    command: server.command,
    args: server.args,
    env: server.env,
    url: server.url,
  }

  try {
    const response = await apiFetch('/api/v1/mcp/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const result = await response.json()
    serverTestResults.value[server.id] = result
  } catch (err: any) {
    serverTestResults.value[server.id] = {
      success: false,
      message: err.message || 'Unable to test MCP server.'
    }
  } finally {
    isTesting.value = false
  }
}

const handleSave = async (payload: any) => {
  isSaving.value = true
  error.value = ''

  try {
    const url = editingId.value ? `/api/v1/mcp/${editingId.value}` : '/api/v1/mcp/'
    const method = editingId.value ? 'PUT' : 'POST'

    const response = await apiFetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })

    if (!response.ok) {
      const data = await response.json()
      throw new Error(data.detail || 'Failed to save MCP server')
    }

    await fetchServers()
    resetForm()
  } catch (err: any) {
    error.value = err.message || 'Unable to save MCP server.'
  } finally {
    isSaving.value = false
  }
}

const deleteServer = async (id: number) => {
  if (!confirm('Are you sure you want to delete this MCP server?')) return

  try {
    const response = await apiFetch(`/api/v1/mcp/${id}`, { method: 'DELETE' })
    if (!response.ok) throw new Error('Failed to delete MCP server')
    await fetchServers()
  } catch (err: any) {
    error.value = err.message || 'Unable to delete MCP server.'
  }
}

const toggleEnabled = async (server: MCPServer) => {
  try {
    const response = await apiFetch(`/api/v1/mcp/${server.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !server.enabled }),
    })
    if (!response.ok) throw new Error('Failed to toggle MCP server status')
    await fetchServers()
  } catch (err: any) {
    error.value = err.message || 'Unable to toggle status.'
  }
}

onMounted(fetchServers)
</script>

<template>
  <SidebarProvider>
    <AppSidebar />
    <SidebarInset class="flex h-screen flex-col overflow-hidden">
      <header class="flex h-16 shrink-0 items-center gap-2 border-b px-4">
        <SidebarTrigger class="-ml-1" />
        <Separator orientation="vertical" class="mr-2 h-4" />
        <div class="flex flex-col">
          <h1 class="text-lg font-semibold mcp-title">MCP Servers</h1>
          <span class="text-xs text-muted-foreground">Manage Model Context Protocol servers</span>
        </div>
      </header>

      <main class="flex-1 p-6 space-y-6 overflow-auto">
        <div class="flex justify-between items-center">
          <p class="text-sm text-muted-foreground">
            Connect external tools and resources to your agents using the Model Context Protocol.
          </p>
          <Button v-if="!showForm" @click="openAddForm" class="gap-2">
            <Plus class="h-4 w-4" />
            Add Server
          </Button>
          <Button v-else @click="showForm = false" variant="outline" class="gap-2">
            Cancel
          </Button>
        </div>

        <Separator />

        <!-- Form Section -->
        <MCPServerForm
          v-if="showForm"
          :editing-id="editingId"
          :initial-data="editingData"
          :is-saving="isSaving"
          :is-testing="isTesting"
          :test-result="testResult"
          @save="handleSave"
          @test="handleTest"
          @cancel="resetForm"
        />

        <!-- List Section -->
        <div v-if="isLoading" class="flex justify-center p-12">
          <Loader2 class="h-8 w-8 animate-spin text-muted-foreground" />
        </div>

        <div v-else-if="servers.length === 0 && !showForm" class="rounded-lg border border-dashed p-12 text-center space-y-3">
          <div class="inline-flex h-12 w-12 items-center justify-center rounded-full bg-muted">
            <Blocks class="h-6 w-6 text-muted-foreground" />
          </div>
          <h3 class="text-lg font-medium">No MCP servers configured</h3>
          <p class="text-sm text-muted-foreground max-w-sm mx-auto">
            Add your first MCP server to extend your agent's capabilities with custom tools and resources.
          </p>
          <Button @click="openAddForm" variant="outline" class="gap-2">
            <Plus class="h-4 w-4" />
            Add Server
          </Button>
        </div>

        <div v-else class="grid gap-4">
          <MCPServerCard
            v-for="server in servers"
            :key="server.id"
            :server="server"
            :is-testing="isTesting"
            :test-result="serverTestResults[server.id]"
            @toggle-enabled="toggleEnabled"
            @edit="openEditForm"
            @delete="deleteServer"
            @test="testExistingServer"
          />
        </div>

        <div v-if="error" class="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive flex items-center gap-2">
          <XCircle class="h-4 w-4" />
          {{ error }}
        </div>
      </main>
    </SidebarInset>
  </SidebarProvider>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&display=swap');

.mcp-title {
  font-family: 'Space Grotesk', sans-serif;
  letter-spacing: -0.02em;
}
</style>
