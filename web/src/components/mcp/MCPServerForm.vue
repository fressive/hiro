<script setup lang="ts">
import { reactive, watch } from 'vue'
import { Loader2, Save, Wrench } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { CheckCircle2, XCircle } from '@lucide/vue'
import type { MCPServer } from '@/types/agent'

const props = defineProps<{
  editingId: number | null
  initialData?: Partial<MCPServer>
  isSaving: boolean
  isTesting: boolean
  testResult: { success: boolean; message: string; tools?: string[] } | null
}>()

const emit = defineEmits<{
  (e: 'save', data: any): void
  (e: 'test', data: any): void
  (e: 'cancel'): void
}>()

const form = reactive({
  name: '',
  type: 'command' as 'command' | 'sse' | 'streamable-http',
  command: '',
  args: '',
  env: '',
  url: '',
  enabled: true,
})

watch(() => props.initialData, (newVal) => {
  if (newVal) {
    form.name = newVal.name || ''
    form.type = newVal.type || 'command'
    form.command = newVal.command || ''
    form.args = newVal.args ? newVal.args.join(' ') : ''
    form.env = newVal.env ? JSON.stringify(newVal.env, null, 2) : ''
    form.url = newVal.url || ''
    form.enabled = newVal.enabled !== false
  }
}, { immediate: true })

const handleSubmit = () => {
  let envParsed = null
  if (form.env.trim()) {
    try {
      envParsed = JSON.parse(form.env)
    } catch (e) {
      alert('Invalid JSON in Environment Variables')
      return
    }
  }

  const payload = {
    name: form.name,
    type: form.type,
    command: form.type === 'command' ? form.command : null,
    args: form.type === 'command' ? form.args.split(' ').filter(a => a.trim()) : null,
    env: envParsed,
    url: (form.type === 'sse' || form.type === 'streamable-http') ? form.url : null,
    enabled: form.enabled,
  }
  emit('save', payload)
}

const handleTest = () => {
    let envParsed = null
  if (form.env.trim()) {
    try {
      envParsed = JSON.parse(form.env)
    } catch (e) {
      alert('Invalid JSON in Environment Variables')
      return
    }
  }

  const payload = {
    name: form.name,
    type: form.type,
    command: form.type === 'command' ? form.command : null,
    args: form.type === 'command' ? form.args.split(' ').filter(a => a.trim()) : null,
    env: envParsed,
    url: (form.type === 'sse' || form.type === 'streamable-http') ? form.url : null,
  }
  emit('test', payload)
}
</script>

<template>
  <Card class="animate-in fade-in slide-in-from-top-2 duration-300 border-primary/50 bg-primary/5">
    <CardHeader>
      <CardTitle>{{ editingId ? 'Edit' : 'Add' }} MCP Server</CardTitle>
      <CardDescription>Configure how to connect to this MCP server.</CardDescription>
    </CardHeader>
    <CardContent>
      <form @submit.prevent="handleSubmit" class="space-y-4">
        <div class="grid gap-4 md:grid-cols-2">
          <div class="space-y-2">
            <Label for="mcp-name">Name</Label>
            <Input id="mcp-name" v-model="form.name" placeholder="my-mcp-server" required />
          </div>
          <div class="space-y-2">
            <Label for="mcp-type">Transport Type</Label>
            <select
              id="mcp-type"
              v-model="form.type"
              class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              <option value="command">Command (Stdio)</option>
              <option value="sse">SSE (HTTP)</option>
              <option value="streamable-http">Streamable HTTP</option>
            </select>
          </div>
        </div>

        <div v-if="form.type === 'command'" class="grid gap-4 md:grid-cols-2">
          <div class="space-y-2">
            <Label for="mcp-command">Command</Label>
            <Input id="mcp-command" v-model="form.command" placeholder="npx" required />
          </div>
          <div class="space-y-2">
            <Label for="mcp-args">Arguments (space separated)</Label>
            <Input id="mcp-args" v-model="form.args" placeholder="@modelcontextprotocol/server-everything" />
          </div>
        </div>

        <div v-if="form.type === 'sse' || form.type === 'streamable-http'" class="space-y-2">
          <Label for="mcp-url">{{ form.type === 'sse' ? 'SSE' : 'Streamable HTTP' }} URL</Label>
          <Input id="mcp-url" v-model="form.url" :placeholder="form.type === 'sse' ? 'http://localhost:3000/sse' : 'http://localhost:3000/stream'" required />
        </div>

        <div class="space-y-2">
          <Label for="mcp-env">Environment Variables (JSON Object)</Label>
          <textarea
            id="mcp-env"
            v-model="form.env"
            rows="4"
            placeholder='{ "API_KEY": "secret" }'
            class="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          ></textarea>
        </div>

        <div class="flex items-center gap-2">
          <input type="checkbox" id="mcp-enabled" v-model="form.enabled" />
          <Label for="mcp-enabled">Enabled</Label>
        </div>

        <div v-if="testResult" class="rounded-md border p-3 text-sm animate-in zoom-in-95 duration-200" :class="testResult.success ? 'bg-emerald-50 border-emerald-200 text-emerald-800' : 'bg-rose-50 border-rose-200 text-rose-800'">
          <div class="flex items-center gap-2 font-bold mb-1">
            <CheckCircle2 v-if="testResult.success" class="h-4 w-4" />
            <XCircle v-else class="h-4 w-4" />
            {{ testResult.success ? 'Test Successful' : 'Test Failed' }}
          </div>
          <p class="text-xs opacity-90">{{ testResult.message }}</p>
          <div v-if="testResult.tools && testResult.tools.length > 0" class="mt-2">
            <p class="text-[10px] font-bold uppercase tracking-wider mb-1 opacity-70">Tools Found:</p>
            <div class="flex flex-wrap gap-1">
              <span v-for="tool in testResult.tools" :key="tool" class="bg-emerald-100 border border-emerald-300 px-1.5 py-0.5 rounded text-[10px] font-mono">
                {{ tool }}
              </span>
            </div>
          </div>
        </div>

        <div class="flex justify-between items-center">
          <Button type="button" variant="outline" size="sm" @click="handleTest" :disabled="isTesting || isSaving" class="gap-2">
            <Loader2 v-if="isTesting" class="h-4 w-4 animate-spin" />
            <Wrench v-else class="h-4 w-4" />
            Test Connection
          </Button>
          <div class="flex gap-3">
            <Button type="button" variant="ghost" @click="emit('cancel')">Cancel</Button>
            <Button type="submit" :disabled="isSaving || isTesting" class="gap-2">
              <Loader2 v-if="isSaving" class="h-4 w-4 animate-spin" />
              <Save v-else class="h-4 w-4" />
              {{ editingId ? 'Update' : 'Create' }} Server
            </Button>
          </div>
        </div>
      </form>
    </CardContent>
  </Card>
</template>
