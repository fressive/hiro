<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue'
import { Plus, Trash2, ShieldCheck, Loader2, Settings2, BarChart3 } from '@lucide/vue'
import { useForm } from 'vee-validate'
import { toTypedSchema } from '@vee-validate/zod'
import * as z from 'zod'

import { SidebarProvider, SidebarInset, SidebarTrigger } from '@/components/ui/sidebar'
import AppSidebar from '@/components/AppSidebar.vue'
import { Separator } from '@/components/ui/separator'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { 
  FormControl, 
  FormField, 
  FormItem, 
  FormLabel, 
  FormMessage 
} from '@/components/ui/form'
import { apiFetch } from '@/lib/api'
import { LineChart } from '@/components/ui/chart'

// --- Types ---
interface LLMConfig {
  id: number
  name: string
  provider: string
  base_url?: string
  model: string
}

interface UsageData {
  date: string
  tokens: number
}

// --- State ---
const currentTab = ref<'config' | 'stats'>('config')
const configs = ref<LLMConfig[]>([])
const isLoading = ref(true)
const isTesting = ref(false)
const isSaving = ref(false)
const testResult = ref<{ success: boolean; message: string } | null>(null)
const editingId = ref<number | null>(null)

const testingConfigs = reactive<Record<number, boolean>>({})
const existingTestResults = reactive<Record<number, { success: boolean; message: string } | null>>({})

const chartConfig = {
  tokens: {
    label: 'Tokens',
    color: 'var(--primary)',
  },
}

// Mock Stats Data
const statsData = ref<UsageData[]>([
  { date: '05-21', tokens: 1200 },
  { date: '05-22', tokens: 2100 },
  { date: '05-23', tokens: 800 },
  { date: '05-24', tokens: 1600 },
  { date: '05-25', tokens: 2400 },
  { date: '05-26', tokens: 3200 },
  { date: '05-27', tokens: 2800 },
])

// --- Form Setup ---
const formSchema = toTypedSchema(z.object({
  name: z.string().min(1, 'Name is required'),
  provider: z.string().min(1, 'Provider is required'),
  base_url: z.string().optional(),
  api_key: z.string().optional(), // Make optional for edit if user doesn't want to change it
  model: z.string().min(1, 'Model is required'),
  enable_1m_context: z.boolean().optional(),
}))

const form = useForm({
  validationSchema: formSchema,
  initialValues: {
    name: '',
    provider: 'openai',
    base_url: '',
    api_key: '',
    model: '',
    enable_1m_context: false,
  },
})

// --- Logic ---
const fetchConfigs = async () => {
  isLoading.value = true
  try {
    const response = await apiFetch('/api/v1/llm')
    if (response.ok) {
      configs.value = await response.json()
    }
  } catch (error) {
    console.error('Failed to fetch LLM configs:', error)
  } finally {
    isLoading.value = false
  }
}

const openEditForm = (config: LLMConfig) => {
  editingId.value = config.id
  form.setValues({
    name: config.name,
    provider: config.provider,
    base_url: config.base_url || '',
    model: config.model,
    api_key: '', // Don't pre-populate API key for security, keep it empty if unchanged
    enable_1m_context: (config as any).enable_1m_context || false,
  })
  testResult.value = null
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

const cancelEdit = () => {
  editingId.value = null
  form.resetForm()
  testResult.value = null
}

const onTest = async () => {
  const values = form.values
  if (!values.name || !values.model) return
  // api_key might be empty if editing and unchanged, we'll need to handle this in backend or here
  isTesting.value = true
  testResult.value = null
  try {
    const response = await apiFetch('/api/v1/llm/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...values,
        id: editingId.value // Pass ID so backend can use stored key if new key is empty
      }),
    })
    testResult.value = await response.json()
  } catch (error: any) {
    testResult.value = { success: false, message: error.message }
  } finally {
    isTesting.value = false
  }
}

const onTestExisting = async (id: number) => {
  testingConfigs[id] = true
  existingTestResults[id] = null
  try {
    const response = await apiFetch(`/api/v1/llm/${id}/test`, { method: 'POST' })
    existingTestResults[id] = await response.json()
  } catch (error: any) {
    existingTestResults[id] = { success: false, message: error.message }
  } finally {
    testingConfigs[id] = false
  }
}

const onSubmit = form.handleSubmit(async (values) => {
  isSaving.value = true
  try {
    const url = editingId.value ? `/api/v1/llm/${editingId.value}` : '/api/v1/llm'
    const method = editingId.value ? 'PUT' : 'POST'

    const response = await apiFetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    })
    if (response.ok) {
      cancelEdit()
      await fetchConfigs()
    }
  } catch (error) {
    console.error('Failed to save config:', error)
  } finally {
    isSaving.value = false
  }
})

const deleteConfig = async (id: number) => {
  if (!confirm('Are you sure you want to delete this configuration?')) return
  try {
    const response = await apiFetch(`/api/v1/llm/${id}`, { method: 'DELETE' })
    if (response.ok) await fetchConfigs()
  } catch (error) {
    console.error('Failed to delete config:', error)
  }
}

onMounted(fetchConfigs)
</script>

<template>
  <SidebarProvider>
    <AppSidebar />
    <SidebarInset class="flex h-screen flex-col overflow-hidden">
      <header class="flex h-16 shrink-0 items-center gap-2 border-b px-4">
        <SidebarTrigger class="-ml-1" />
        <Separator orientation="vertical" class="mr-2 h-4" />
        <h1 class="text-lg font-semibold">LLM Management</h1>
      </header>
      
      <main class="flex-1 p-6 space-y-6 overflow-auto">
        <!-- Tab Switcher -->
        <div class="flex items-center gap-1 p-1 bg-muted rounded-lg w-fit">
          <Button 
            variant="ghost" 
            size="sm" 
            :class="['gap-2', currentTab === 'config' && 'bg-background shadow-sm']"
            @click="currentTab = 'config'"
          >
            <Settings2 class="h-4 w-4" />
            Configuration
          </Button>
          <Button 
            variant="ghost" 
            size="sm" 
            :class="['gap-2', currentTab === 'stats' && 'bg-background shadow-sm']"
            @click="currentTab = 'stats'"
          >
            <BarChart3 class="h-4 w-4" />
            Statistics
          </Button>
        </div>

        <Separator />

        <!-- Subpage: Configuration -->
        <div v-if="currentTab === 'config'" class="grid gap-6 lg:grid-cols-2 animate-in fade-in slide-in-from-bottom-2 duration-300">
          <Card :class="[editingId && 'border-primary shadow-md']">
            <CardHeader>
              <CardTitle>{{ editingId ? 'Edit' : 'Add' }} Configuration</CardTitle>
              <CardDescription>{{ editingId ? 'Update your' : 'Configure a new' }} LLM provider and model.</CardDescription>
            </CardHeader>
            <CardContent>
              <form @submit="onSubmit" class="space-y-4">
                <FormField v-slot="{ componentField }" name="name">
                  <FormItem>
                    <FormLabel>Config Name</FormLabel>
                    <FormControl>
                      <Input placeholder="My OpenAI Config" v-bind="componentField" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                </FormField>

                <div class="grid grid-cols-2 gap-4">
                  <FormField v-slot="{ componentField }" name="provider">
                    <FormItem>
                      <FormLabel>Provider</FormLabel>
                      <FormControl>
                        <select 
                          v-bind="componentField"
                          class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          <option value="openai">OpenAI</option>
                          <option value="anthropic">Anthropic</option>
                        </select>
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  </FormField>

                  <FormField v-slot="{ componentField }" name="model">
                    <FormItem>
                      <FormLabel>Model</FormLabel>
                      <FormControl>
                        <Input placeholder="gpt-4o" v-bind="componentField" />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  </FormField>
                </div>

                <FormField v-slot="{ componentField }" name="base_url">
                  <FormItem>
                    <FormLabel>API Endpoint (Optional)</FormLabel>
                    <FormControl>
                      <Input placeholder="https://api.openai.com/v1" v-bind="componentField" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                </FormField>

                <FormField v-slot="{ componentField }" name="api_key">
                  <FormItem>
                    <FormLabel>API Token / Key {{ editingId ? '(Leave empty to keep current)' : '' }}</FormLabel>
                    <FormControl>
                      <Input type="password" placeholder="sk-..." v-bind="componentField" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                </FormField>

                <FormField v-slot="{ componentField }" name="enable_1m_context">
                  <FormItem class="flex items-center justify-between rounded-lg border p-3">
                    <div>
                      <FormLabel>Enable 1M Context</FormLabel>
                      <p class="text-xs text-muted-foreground">Use when your provider supports 1m context (e.g., Anthropic, Moonshot).</p>
                    </div>
                    <FormControl>
                      <input type="checkbox" class="h-4 w-4" v-bind="componentField" />
                    </FormControl>
                  </FormItem>
                </FormField>

                <div v-if="testResult" :class="['p-3 rounded-md text-sm', testResult.success ? 'bg-green-500/10 text-green-500' : 'bg-destructive/10 text-destructive']">
                  {{ testResult.message }}
                </div>

                <div class="flex gap-3 pt-2">
                  <Button type="button" variant="outline" class="flex-1" @click="onTest" :disabled="isTesting || isSaving">
                    <Loader2 v-if="isTesting" class="mr-2 h-4 w-4 animate-spin" />
                    <ShieldCheck v-else class="mr-2 h-4 w-4" />
                    Test Connection
                  </Button>
                  <Button v-if="editingId" type="button" variant="ghost" @click="cancelEdit">
                    Cancel
                  </Button>
                  <Button type="submit" class="flex-1" :disabled="isTesting || isSaving">
                    <Loader2 v-if="isSaving" class="mr-2 h-4 w-4 animate-spin" />
                    <component :is="editingId ? Settings2 : Plus" class="mr-2 h-4 w-4" />
                    {{ editingId ? 'Update' : 'Save' }} Config
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>

          <div class="space-y-6">
            <h2 class="text-xl font-bold">Existing Configurations</h2>
            <div v-if="isLoading" class="flex justify-center py-10">
              <Loader2 class="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
            <div v-else-if="configs.length === 0" class="text-center py-10 border-2 border-dashed rounded-lg border-muted">
              <p class="text-muted-foreground">No LLM configurations found.</p>
            </div>
            <div v-else class="grid gap-4">
              <Card v-for="config in configs" :key="config.id" :class="[editingId === config.id && 'ring-2 ring-primary border-primary']">
                <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-2">
                  <div class="space-y-1">
                    <CardTitle class="text-base">{{ config.name }}</CardTitle>
                    <CardDescription>{{ config.provider }} · {{ config.model }}</CardDescription>
                  </div>
                  <div class="flex gap-1">
                    <Button variant="ghost" size="icon" title="Test" @click="onTestExisting(config.id)" :disabled="testingConfigs[config.id]">
                      <Loader2 v-if="testingConfigs[config.id]" class="h-4 w-4 animate-spin" />
                      <ShieldCheck v-else class="h-4 w-4 text-emerald-500" />
                    </Button>
                    <Button variant="ghost" size="icon" title="Edit" @click="openEditForm(config)">
                      <Settings2 class="h-4 w-4 text-primary" />
                    </Button>
                    <Button variant="ghost" size="icon" title="Delete" class="text-destructive hover:text-destructive hover:bg-destructive/10" @click="deleteConfig(config.id)">
                      <Trash2 class="h-4 w-4" />
                    </Button>
                  </div>
                </CardHeader>
                <CardContent class="space-y-3">
                  <p v-if="config.base_url" class="text-xs text-muted-foreground truncate">{{ config.base_url }}</p>
                  <div v-if="existingTestResults[config.id]" :class="['p-2 rounded text-xs', existingTestResults[config.id]?.success ? 'bg-green-500/10 text-green-500' : 'bg-destructive/10 text-destructive']">
                    {{ existingTestResults[config.id]?.message }}
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>

        <!-- Subpage: Statistics -->
        <div v-else class="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
          <div class="grid gap-6 md:grid-cols-3">
            <Card>
              <CardHeader class="pb-2">
                <CardDescription>Total Tokens</CardDescription>
                <CardTitle class="text-3xl font-bold">13,900</CardTitle>
              </CardHeader>
              <CardContent>
                <p class="text-xs text-green-500 font-medium">+12% from last week</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader class="pb-2">
                <CardDescription>Average/Day</CardDescription>
                <CardTitle class="text-3xl font-bold">1,985</CardTitle>
              </CardHeader>
              <CardContent>
                <p class="text-xs text-muted-foreground">Last 7 days</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader class="pb-2">
                <CardDescription>Estimated Cost</CardDescription>
                <CardTitle class="text-3xl font-bold">$0.42</CardTitle>
              </CardHeader>
              <CardContent>
                <p class="text-xs text-muted-foreground">Based on gpt-4o pricing</p>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Token Usage Over Time</CardTitle>
              <CardDescription>Daily token consumption for the last 7 days.</CardDescription>
            </CardHeader>
            <CardContent>
              <div class="h-[300px] w-full pt-4">
                <LineChart
                  :data="statsData"
                  index="date"
                  :categories="['tokens']"
                  :config="chartConfig"
                  :show-x-axis="true"
                  :show-y-axis="true"
                  :show-tooltip="true"
                  class="h-full w-full"
                />
              </div>
            </CardContent>
          </Card>
        </div>
      </main>
    </SidebarInset>
  </SidebarProvider>
</template>

<style scoped>
.stop-primary {
  stop-color: var(--primary);
}
</style>
