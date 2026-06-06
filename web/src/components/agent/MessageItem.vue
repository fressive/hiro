<script setup lang="ts">
import { Bot, Wrench, FileText } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import type { AgentMessage } from '@/types/agent'
import { isJsonBlocks, parseJsonBlocks } from '@/lib/agent-utils'

const props = defineProps<{
  message: AgentMessage
  isExpanded?: boolean
}>()

const emit = defineEmits<{
  (e: 'toggle-expand'): void
}>()
</script>

<template>
  <!-- Standard Message -->
  <div 
    v-if="message.role !== 'tool'"
    class="rounded-lg border p-3 text-sm shadow-sm"
    :class="message.role === 'assistant' ? 'bg-background' : 'bg-muted/10'"
  >
    <div class="text-xs font-semibold text-muted-foreground mb-2 flex items-center justify-between">
      <span>{{ message.role === 'user' ? 'User' : 'Assistant' }}</span>
      <div class="flex items-center gap-2">
        <span v-if="message.model" class="text-[9px] px-1 rounded bg-primary/10 text-primary border border-primary/20 font-medium">
          {{ message.model }}
        </span>
        <span v-if="message.input_tokens || message.output_tokens" class="text-[9px] px-1 rounded bg-muted font-mono opacity-80">
        <template v-if="message.input_tokens">in:{{ message.input_tokens }}</template>
          <template v-if="message.input_tokens && message.output_tokens">/</template>
          <template v-if="message.output_tokens">out:{{ message.output_tokens }}</template>
        </span>
        <span v-if="message.created_at" class="text-[10px] font-normal opacity-50">{{ new Date(message.created_at).toLocaleTimeString() }}</span>
      </div>
    </div>
    
    <!-- Multi-part Content Blocks (e.g. Thinking + Text) -->
    <template v-if="isJsonBlocks(message.content)">
      <div v-for="(block, idx) in parseJsonBlocks(message.content)" :key="idx">
        <div v-if="block.type === 'thinking'" class="text-[11px] italic text-muted-foreground bg-muted/40 p-2 mb-3 rounded border-l-2 border-primary/30">
          <p class="font-bold mb-1 opacity-70 flex items-center gap-1.5 uppercase tracking-tighter text-[9px]">
            <Bot class="h-3 w-3" />
            Thinking Process
          </p>
          <pre class="whitespace-pre-wrap font-sans">{{ block.thinking || block.reasoning || block.text }}</pre>
        </div>
        <pre v-else-if="block.text" class="whitespace-pre-wrap text-foreground font-sans mb-2">{{ block.text }}</pre>
        <pre v-else-if="block.type === 'tool_use'" class="whitespace-pre-wrap text-foreground font-sans mb-2 text-xs opacity-70 italic">Using tool: {{ block.name }}</pre>
      </div>
    </template>
    <pre v-else-if="message.content" class="whitespace-pre-wrap text-foreground font-sans">{{ message.content }}</pre>
    
    <!-- Inline Tool Calls (within Assistant message) -->
    <div v-if="message.tool_calls && message.tool_calls.length > 0" class="mt-2 space-y-2 border-t pt-2 border-dashed">
      <p class="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Initiating Tool Calls:</p>
      <div v-for="tc in message.tool_calls" :key="tc.id" class="text-xs bg-muted/40 p-2 rounded flex items-center gap-2">
        <Wrench class="h-3 w-3" />
        <span class="font-mono">{{ tc.name }}</span>
        <span class="opacity-50 text-[9px] truncate">({{ tc.args }})</span>
      </div>
    </div>

    <!-- RAG Sources (from extra_metadata) -->
    <div v-if="message.extra_metadata?.rag_sources?.length" class="mt-3 border-t pt-2 border-dashed">
      <p class="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1 flex items-center gap-1.5">
        <FileText class="h-3 w-3" />
        Sources used:
      </p>
      <div class="flex flex-wrap gap-1.5">
        <span 
          v-for="source in message.extra_metadata.rag_sources" 
          :key="source"
          class="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-[10px] font-medium border border-primary/20"
        >
          {{ source }}
        </span>
      </div>
    </div>
  </div>

  <!-- Tool Execution Result -->
  <div 
    v-else
    class="rounded-lg border border-dashed p-3 text-sm bg-muted/20 overflow-hidden"
  >
    <p class="text-xs font-semibold text-muted-foreground mb-2 flex items-center justify-between">
      <span class="flex items-center gap-1.5">
        <Wrench class="h-3 w-3" />
        Tool: {{ message.name || 'Result' }}
      </span>
      <span class="text-[10px] opacity-50 font-mono">{{ message.tool_call_id }}</span>
    </p>
    
    <div class="relative group">
      <pre 
        class="whitespace-pre-wrap text-foreground font-mono text-xs transition-all duration-300"
        :class="[!isExpanded && message.content.length > 500 ? 'max-h-[120px] overflow-hidden mask-fade' : '']"
      >{{ message.content }}</pre>
      
      <div 
        v-if="message.content.length > 500" 
        class="flex justify-center mt-2"
        :class="[!isExpanded ? 'absolute bottom-0 left-0 right-0 pt-8 pb-1 bg-gradient-to-t from-muted/30 to-transparent' : '']"
      >
        <Button 
          variant="ghost" 
          size="sm" 
          class="h-6 px-2 text-[10px] hover:bg-muted/50" 
          @click="emit('toggle-expand')"
        >
          {{ isExpanded ? 'Show Less' : 'Show More' }}
        </Button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mask-fade {
  mask-image: linear-gradient(to bottom, black 60%, transparent 100%);
}
</style>
