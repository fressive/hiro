<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { 
  Key, 
  Plus, 
  Trash2, 
  Copy, 
  Check, 
  Loader2,
  Calendar,
  Clock,
  ShieldCheck
} from '@lucide/vue'
import { SidebarProvider, SidebarInset, SidebarTrigger } from '@/components/ui/sidebar'
import AppSidebar from '@/components/AppSidebar.vue'
import { Separator } from '@/components/ui/separator'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardDescription, CardFooter } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { 
  Sheet, 
  SheetContent, 
  SheetHeader, 
  SheetTitle, 
  SheetDescription,
  SheetFooter,
  SheetClose
} from '@/components/ui/sheet'
import { apiFetch } from '@/lib/api'

type APIToken = {
  id: number
  name: string
  token: string
  created_at: string
  last_used_at: string | null
}

const tokens = ref<APIToken[]>([])
const isLoading = ref(false)
const isCreating = ref(false)
const newTokenName = ref('')
const showCreateSheet = ref(false)
const newlyCreatedToken = ref<APIToken | null>(null)
const copiedTokenId = ref<number | null>(null)

const fetchTokens = async () => {
  isLoading.value = true
  try {
    const response = await apiFetch('/api/v1/tokens')
    if (response.ok) {
      tokens.value = await response.json()
    }
  } catch (error) {
    console.error('Failed to fetch tokens:', error)
  } finally {
    isLoading.value = false
  }
}

const createToken = async () => {
  if (!newTokenName.value.trim()) return
  
  isCreating.value = true
  try {
    const response = await apiFetch('/api/v1/tokens', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newTokenName.value.trim() }),
    })
    
    if (response.ok) {
      const created = await response.json()
      tokens.value.unshift(created)
      newlyCreatedToken.value = created
      newTokenName.value = ''
      // Don't close sheet yet, show the token
    }
  } catch (error) {
    console.error('Failed to create token:', error)
  } finally {
    isCreating.value = false
  }
}

const deleteToken = async (id: number) => {
  if (!confirm('Are you sure you want to delete this API token? Any applications using it will no longer be able to authenticate.')) return
  
  try {
    const response = await apiFetch(`/api/v1/tokens/${id}`, {
      method: 'DELETE',
    })
    
    if (response.ok) {
      tokens.value = tokens.value.filter(t => t.id !== id)
    }
  } catch (error) {
    console.error('Failed to delete token:', error)
  }
}

const copyToClipboard = (text: string, id: number) => {
  navigator.clipboard.writeText(text)
  copiedTokenId.value = id
  setTimeout(() => {
    copiedTokenId.value = null
  }, 2000)
}

const formatDate = (dateStr: string) => {
  try {
    return new Intl.DateTimeFormat('en-US', {
      dateStyle: 'medium',
      timeStyle: 'short'
    }).format(new Date(dateStr))
  } catch (e) {
    return dateStr
  }
}

onMounted(fetchTokens)
</script>

<template>
  <SidebarProvider>
    <AppSidebar />
    <SidebarInset class="flex h-screen flex-col overflow-hidden">
      <header class="flex h-16 shrink-0 items-center gap-2 border-b px-4">
        <SidebarTrigger class="-ml-1" />
        <Separator orientation="vertical" class="mr-2 h-4" />
        <h1 class="text-lg font-semibold">API Tokens</h1>
      </header>

      <main class="flex-1 p-6 space-y-6 overflow-auto">
        <div class="flex items-center justify-between">
          <div>
            <h2 class="text-2xl font-bold tracking-tight">API Tokens</h2>
            <p class="text-muted-foreground">
              Manage personal access tokens to access the Hiro API.
            </p>
          </div>
          <Button @click="showCreateSheet = true" class="gap-2">
            <Plus class="h-4 w-4" />
            Generate New Token
          </Button>
        </div>

        <div v-if="isLoading" class="flex flex-col items-center justify-center py-20">
          <Loader2 class="h-8 w-8 animate-spin text-primary" />
          <p class="mt-2 text-sm text-muted-foreground">Loading tokens...</p>
        </div>

        <div v-else-if="tokens.length === 0" class="flex flex-col items-center justify-center rounded-lg border border-dashed p-12 text-center animate-in fade-in duration-500">
          <div class="flex h-20 w-20 items-center justify-center rounded-full bg-muted">
            <ShieldCheck class="h-10 w-10 text-muted-foreground" />
          </div>
          <h3 class="mt-4 text-lg font-semibold">No API tokens yet</h3>
          <p class="mb-4 mt-2 text-sm text-muted-foreground max-w-sm">
            Create a token to authenticate your requests to the Hiro API from external tools or scripts.
          </p>
          <Button @click="showCreateSheet = true" variant="outline" class="gap-2">
            <Plus class="h-4 w-4" />
            Generate Token
          </Button>
        </div>

        <div v-else class="grid gap-4">
          <Card v-for="token in tokens" :key="token.id" class="overflow-hidden">
            <CardHeader class="pb-3">
              <div class="flex items-start justify-between">
                <div class="space-y-1">
                  <CardTitle class="text-base flex items-center gap-2">
                    <Key class="h-4 w-4 text-primary" />
                    {{ token.name }}
                  </CardTitle>
                  <CardDescription class="text-xs font-mono bg-muted px-2 py-1 rounded inline-block">
                    hiro_••••••••••••••••
                  </CardDescription>
                </div>
                <Button 
                  variant="ghost" 
                  size="icon" 
                  class="h-8 w-8 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                  @click="deleteToken(token.id)"
                >
                  <Trash2 class="h-4 w-4" />
                </Button>
              </div>
            </CardHeader>
            <CardFooter class="bg-muted/30 py-3 flex items-center gap-6 text-xs text-muted-foreground border-t">
              <div class="flex items-center gap-1.5">
                <Calendar class="h-3.5 w-3.5" />
                Created {{ formatDate(token.created_at) }}
              </div>
              <div class="flex items-center gap-1.5">
                <Clock class="h-3.5 w-3.5" />
                Last used {{ token.last_used_at ? formatDate(token.last_used_at) : 'Never' }}
              </div>
            </CardFooter>
          </Card>
        </div>
      </main>
      <!-- Create Token Sheet -->
      <Sheet :open="showCreateSheet" @update:open="(v) => { if(!v) { showCreateSheet = false; newlyCreatedToken = null; } }">
        <SheetContent>
          <SheetHeader>
            <SheetTitle>Generate API Token</SheetTitle>
            <SheetDescription>
              Give your token a descriptive name to remember what it's used for.
            </SheetDescription>
          </SheetHeader>

          <div class="p-4 space-y-4 py-6">
            <div v-if="!newlyCreatedToken" class="space-y-2">
              <Label for="token-name">Token Name</Label>
              <Input 
                id="token-name" 
                v-model="newTokenName" 
                placeholder="e.g. My Script, GitHub Action" 
                @keydown.enter="createToken"
              />
            </div>

            <div v-else class="space-y-4 rounded-lg bg-primary/5 border border-primary/20 p-4 animate-in zoom-in-95 duration-300">
              <div class="flex items-center gap-2 text-primary font-semibold text-sm">
                <Check class="h-4 w-4" />
                Token generated successfully!
              </div>
              <p class="text-xs text-muted-foreground">
                Make sure to copy your API token now. You won't be able to see it again!
              </p>
              <div class="relative group">
                <div class="bg-background border rounded-md p-3 pr-12 font-mono text-sm break-all leading-relaxed">
                  {{ newlyCreatedToken.token }}
                </div>
                <Button 
                  size="icon" 
                  variant="ghost" 
                  class="absolute right-2 top-2 h-8 w-8"
                  @click="copyToClipboard(newlyCreatedToken.token, newlyCreatedToken.id)"
                >
                  <Check v-if="copiedTokenId === newlyCreatedToken.id" class="h-4 w-4 text-green-500" />
                  <Copy v-else class="h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>

          <SheetFooter>
            <Button v-if="!newlyCreatedToken" @click="createToken" :disabled="!newTokenName.trim() || isCreating" class="w-full">
              <Loader2 v-if="isCreating" class="mr-2 h-4 w-4 animate-spin" />
              Generate Token
            </Button>
            <SheetClose v-else as-child>
              <Button variant="outline" class="w-full">Done</Button>
            </SheetClose>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </SidebarInset>
  </SidebarProvider>
</template>
