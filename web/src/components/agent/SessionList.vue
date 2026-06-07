<script setup lang="ts">
import { nextTick, ref, type ComponentPublicInstance } from 'vue'
import { 
  MessageSquare, 
  Plus, 
  Calendar, 
  Clock,
  Trash2,
  ChevronRight,
  Pencil,
  Check,
  X
} from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card'
import type { AgentSession } from '@/types/agent'

const props = defineProps<{
  sessions: AgentSession[]
}>()

const emit = defineEmits<{
  (e: 'select-session', id: number): void
  (e: 'create-session'): void
  (e: 'delete-session', id: number): void
  (e: 'rename-session', id: number, title: string): void
}>()

const editingSessionId = ref<number | null>(null)
const editingTitle = ref('')
const editingInput = ref<HTMLInputElement | null>(null)

const setEditingInput = (el: Element | ComponentPublicInstance | null) => {
  editingInput.value = el instanceof HTMLInputElement ? el : null
}

const startRename = async (session: AgentSession) => {
  editingSessionId.value = session.id
  editingTitle.value = session.title || 'Untitled Session'
  await nextTick()
  editingInput.value?.focus()
  editingInput.value?.select()
}

const cancelRename = () => {
  editingSessionId.value = null
  editingTitle.value = ''
}

const submitRename = (session: AgentSession) => {
  const title = editingTitle.value.trim()
  if (!title) return
  if (title !== (session.title || '').trim()) {
    emit('rename-session', session.id, title)
  }
  cancelRename()
}

const formatDate = (dateStr: string) => {
  try {
    const date = new Date(dateStr)
    return new Intl.DateTimeFormat('en-US', {
      dateStyle: 'medium',
      timeStyle: 'short'
    }).format(date)
  } catch (e) {
    return dateStr
  }
}
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-2xl font-bold tracking-tight">Sessions</h2>
        <p class="text-muted-foreground">
          Manage your active agent sessions and conversations.
        </p>
      </div>
      <Button @click="emit('create-session')" class="gap-2">
        <Plus class="h-4 w-4" />
        New Session
      </Button>
    </div>

    <div v-if="sessions.length === 0" class="flex flex-col items-center justify-center rounded-lg border border-dashed p-12 text-center animate-in fade-in duration-500">
      <div class="flex h-20 w-20 items-center justify-center rounded-full bg-muted">
        <MessageSquare class="h-10 w-10 text-muted-foreground" />
      </div>
      <h3 class="mt-4 text-lg font-semibold">No sessions yet</h3>
      <p class="mb-4 mt-2 text-sm text-muted-foreground max-w-sm">
        Start your first conversation with the AI agent. You can configure tools, RAG, and more.
      </p>
      <Button @click="emit('create-session')" variant="outline" class="gap-2">
        <Plus class="h-4 w-4" />
        Create Session
      </Button>
    </div>

    <div v-else class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      <Card 
        v-for="session in sessions" 
        :key="session.id" 
        class="group relative flex flex-col hover:border-primary/50 transition-colors cursor-pointer"
        @click="emit('select-session', session.id)"
      >
        <CardHeader class="pb-3">
          <div class="flex items-start justify-between gap-2">
            <form
              v-if="editingSessionId === session.id"
              class="flex min-w-0 flex-1 items-center gap-1"
              @click.stop
              @submit.prevent.stop="submitRename(session)"
            >
              <input
                :ref="setEditingInput"
                v-model="editingTitle"
                class="h-8 min-w-0 flex-1 rounded-md border bg-background px-2 text-sm font-medium outline-none ring-offset-background focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                @keydown.esc.prevent="cancelRename"
              />
              <Button
                type="submit"
                variant="ghost"
                size="icon"
                class="h-8 w-8 text-muted-foreground hover:text-primary"
                :disabled="!editingTitle.trim()"
              >
                <Check class="h-4 w-4" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                class="h-8 w-8 text-muted-foreground"
                @click="cancelRename"
              >
                <X class="h-4 w-4" />
              </Button>
            </form>
            <template v-else>
              <CardTitle class="line-clamp-1 min-w-0 flex-1 text-base group-hover:text-primary transition-colors">
                {{ session.title || 'Untitled Session' }}
              </CardTitle>
              <div class="-mt-1 -mr-1 flex shrink-0 items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  title="Rename"
                  class="h-8 w-8 text-muted-foreground"
                  @click.stop="startRename(session)"
                >
                  <Pencil class="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  title="Delete"
                  class="h-8 w-8 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                  @click.stop="emit('delete-session', session.id)"
                >
                  <Trash2 class="h-4 w-4" />
                </Button>
              </div>
            </template>
          </div>
          <CardDescription class="flex items-center gap-1.5 text-xs">
            <Calendar class="h-3 w-3" />
            {{ formatDate(session.created_at) }}
          </CardDescription>
        </CardHeader>
        <CardContent class="flex-1 pb-3">
          <div class="flex flex-wrap gap-2">
            <div v-if="session.enable_rag" class="inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold transition-colors bg-secondary text-secondary-foreground border-transparent">
              RAG
            </div>
            <div class="inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold transition-colors border-muted text-muted-foreground">
              {{ session.tools?.length || 0 }} Tools
            </div>
          </div>
        </CardContent>
        <CardFooter class="pt-0 border-t bg-muted/30 py-3 flex items-center justify-between text-xs text-muted-foreground">
          <div class="flex items-center gap-1">
            <Clock class="h-3 w-3" />
            Updated {{ formatDate(session.updated_at) }}
          </div>
          <ChevronRight class="h-4 w-4 opacity-0 group-hover:opacity-100 transition-opacity" />
        </CardFooter>
      </Card>
    </div>
  </div>
</template>
