<script setup lang="ts">
import { Terminal, ExternalLink, Power, PowerOff, Settings2, Trash2, Play, Loader2, CheckCircle2, XCircle } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import type { MCPServer } from '@/types/agent'

const props = defineProps<{
  server: MCPServer
  isTesting: boolean
  testResult?: { success: boolean; message: string; tools?: string[] }
}>()

const emit = defineEmits<{
  (e: 'toggle-enabled', server: MCPServer): void
  (e: 'edit', server: MCPServer): void
  (e: 'delete', id: number): void
  (e: 'test', server: MCPServer): void
}>()
</script>

<template>
  <Card :class="[!server.enabled && 'opacity-60']">
    <CardContent class="py-3 px-4">
      <div class="flex flex-col gap-2.5 sm:flex-row sm:items-start sm:justify-between">
        <div class="space-y-2">
          <div class="flex items-center gap-2">
            <h3 class="font-bold text-base leading-tight">{{ server.name }}</h3>
            <span 
              class="text-[10px] uppercase font-bold px-2 py-0.5 rounded-full border"
              :class="server.type === 'command' ? 'bg-blue-50 text-blue-700 border-blue-200' : 'bg-purple-50 text-purple-700 border-purple-200'"
            >
              {{ server.type }}
            </span>
          </div>
          
          <div v-if="server.type === 'command'" class="flex items-center gap-2 text-xs text-muted-foreground font-mono bg-muted/50 px-2 py-0.5 rounded">
            <Terminal class="h-3 w-3" />
            <span class="truncate max-w-[300px]">{{ server.command }} {{ server.args?.join(' ') }}</span>
          </div>
          
          <div v-if="server.type === 'sse' || server.type === 'streamable-http'" class="flex items-center gap-2 text-xs text-muted-foreground">
            <ExternalLink class="h-3 w-3" />
            <span class="underline truncate max-w-[300px]">{{ server.url }}</span>
          </div>
        </div>

        <div class="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            class="h-7 w-7"
            title="Test Connection"
            @click="emit('test', server)"
            :disabled="isTesting"
          >
            <Loader2 v-if="isTesting" class="h-3.5 w-3.5 animate-spin" />
            <Play v-else class="h-3.5 w-3.5 text-blue-500" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            class="h-7 w-7"
            :title="server.enabled ? 'Disable' : 'Enable'"
            @click="emit('toggle-enabled', server)"
          >
            <Power v-if="server.enabled" class="h-3.5 w-3.5 text-emerald-500" />
            <PowerOff v-else class="h-3.5 w-3.5 text-rose-500" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            class="h-7 w-7"
            title="Edit"
            @click="emit('edit', server)"
          >
            <Settings2 class="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            class="h-7 w-7"
            title="Delete"
            @click="emit('delete', server.id)"
          >
            <Trash2 class="h-3.5 w-3.5 text-rose-500" />
          </Button>
        </div>
      </div>

      <div v-if="server.env && Object.keys(server.env).length > 0" class="mt-2.5 pt-2.5 border-t border-dashed">
        <p class="text-[9px] font-bold text-muted-foreground mb-1 uppercase tracking-tight">Environment Variables</p>
        <div class="flex flex-wrap gap-1">
          <span v-for="(_, key) in server.env" :key="key" class="text-[9px] bg-muted px-1 py-0.5 rounded border">
            {{ key }}=***
          </span>
        </div>
      </div>

      <div v-if="testResult" class="mt-2.5 rounded-md border p-2 text-xs animate-in zoom-in-95 duration-200" :class="testResult.success ? 'bg-emerald-50 border-emerald-200 text-emerald-800' : 'bg-rose-50 border-rose-200 text-rose-800'">
        <div class="flex items-center gap-1.5 font-bold mb-0.5">
          <CheckCircle2 v-if="testResult.success" class="h-3 w-3" />
          <XCircle v-else class="h-3 w-3" />
          <span class="text-[11px]">{{ testResult.success ? 'Success' : 'Failed' }}</span>
        </div>
        <p class="text-[10px] opacity-90 leading-tight">{{ testResult.message }}</p>
        <div v-if="testResult.tools && testResult.tools.length > 0" class="mt-1">
          <div class="flex flex-wrap gap-1">
            <span v-for="tool in testResult.tools" :key="tool" class="bg-emerald-100/50 border border-emerald-300/50 px-1 py-0 rounded text-[9px] font-mono">
              {{ tool }}
            </span>
          </div>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
