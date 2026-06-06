<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { 
  SidebarProvider, 
  SidebarInset, 
  SidebarTrigger 
} from '@/components/ui/sidebar'
import AppSidebar from '@/components/AppSidebar.vue'
import { 
  Separator 
} from '@/components/ui/separator'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { apiFetch } from '@/lib/api'
import { BarChart3, Loader2 } from '@lucide/vue'
import { LineChart } from '@/components/ui/chart'

const stats = ref<any>(null)
const isLoading = ref(true)

const chartConfig = {
  tokens: {
    label: 'Tokens',
    color: 'var(--primary)',
  },
  input_tokens: {
    label: 'Input',
    color: 'var(--vis-color-0)',
  },
  cached_input_tokens: {
    label: 'Cached',
    color: 'var(--vis-color-1)',
  },
  output_tokens: {
    label: 'Output',
    color: 'var(--vis-color-2)',
  },
}

const fetchGlobalStats = async () => {
  isLoading.value = true
  try {
    const response = await apiFetch('/api/v1/agent/stats')
    if (response.ok) {
      stats.value = await response.json()
    }
  } finally {
    isLoading.value = false
  }
}

onMounted(fetchGlobalStats)
</script>

<template>
  <SidebarProvider>
    <AppSidebar />
    <SidebarInset class="flex h-screen flex-col overflow-hidden">
      <header class="flex h-16 shrink-0 items-center gap-2 border-b px-4">
        <SidebarTrigger class="-ml-1" />
        <Separator orientation="vertical" class="mr-2 h-4" />
        <h1 class="text-lg font-semibold">Dashboard</h1>
      </header>
      
      <main class="flex-1 p-6 space-y-6 overflow-auto">
        <div class="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          <Card>
            <CardHeader>
              <CardTitle>Welcome to Hiro</CardTitle>
            </CardHeader>
            <CardContent>
              <p class="text-sm text-muted-foreground">
                This is your new dashboard. You can manage your agents, tools, and configurations from here.
              </p>
              <Button class="mt-4 w-full" variant="outline">Learn More</Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Token Usage</CardTitle>
              <CardDescription>Total consumption across all sessions</CardDescription>
            </CardHeader>
            <CardContent>
              <div v-if="isLoading" class="flex items-center justify-center h-24">
                <Loader2 class="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
              <div v-else-if="stats" class="space-y-4">
                <div class="flex items-end justify-between">
                  <span class="text-3xl font-bold">{{ stats.total_tokens.toLocaleString() }}</span>
                  <BarChart3 class="h-8 w-8 text-primary opacity-20" />
                </div>
                <div class="grid grid-cols-3 gap-2 text-xs">
                  <div class="flex flex-col border-r pr-2">
                    <span class="text-muted-foreground">Input</span>
                    <span class="font-semibold text-blue-500">{{ stats.total_input_tokens.toLocaleString() }}</span>
                  </div>
                  <div class="flex flex-col border-r pr-2 pl-2">
                    <span class="text-muted-foreground">Cached</span>
                    <span class="font-semibold text-cyan-500">{{ (stats.total_cached_input_tokens || 0).toLocaleString() }}</span>
                  </div>
                  <div class="flex flex-col pl-2">
                    <span class="text-muted-foreground">Output</span>
                    <span class="font-semibold text-green-500">{{ stats.total_output_tokens.toLocaleString() }}</span>
                  </div>
                </div>

                <div v-if="stats.usage_over_time && stats.usage_over_time.length > 0" class="h-[60px] w-full pt-2">
                  <LineChart
                    :data="stats.usage_over_time"
                    index="date"
                    :categories="['tokens']"
                    :config="chartConfig"
                    :show-x-axis="false"
                    :show-y-axis="false"
                    :show-tooltip="true"
                    class="h-full w-full"
                  />
                </div>
                
                <div v-if="stats.model_usage && Object.keys(stats.model_usage).length > 0" class="pt-4 border-t space-y-2">
                  <p class="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Usage by Model</p>
                  <div v-for="(usage, model) in stats.model_usage" :key="model" class="flex items-center justify-between text-xs">
                    <span class="truncate max-w-[150px]" :title="String(model)">{{ model }}</span>
                    <span class="font-mono bg-muted px-1.5 py-0.5 rounded">{{ usage.total.toLocaleString() }}</span>
                  </div>
                </div>
              </div>
              <div v-else class="flex items-center justify-center h-24 border-2 border-dashed rounded-lg">
                <p class="text-sm text-muted-foreground">No data available</p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>System Status</CardTitle>
            </CardHeader>
            <CardContent>
              <ul class="space-y-2">
                <li class="flex items-center justify-between text-sm">
                  <span>Backend</span>
                  <span class="text-green-500 font-medium">Online</span>
                </li>
                <li class="flex items-center justify-between text-sm">
                  <span>Database</span>
                  <span class="text-green-500 font-medium">Connected</span>
                </li>
              </ul>
            </CardContent>
          </Card>
        </div>
      </main>
    </SidebarInset>
  </SidebarProvider>
</template>
