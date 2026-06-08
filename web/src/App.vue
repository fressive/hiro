<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { RouterView } from 'vue-router'
import { AlertCircle, Bug, Save, Trash2, X } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
  SheetFooter,
} from '@/components/ui/sheet'
import { API_UNAVAILABLE_EVENT, API_UNAVAILABLE_MESSAGE, getApiBaseUrl, setApiBaseUrl } from '@/lib/api'

const debugApiUrl = ref('')
const isOpen = ref(false)
const serverErrorMessage = ref('')
let serverErrorTimer: ReturnType<typeof window.setTimeout> | null = null

const clearServerError = () => {
  serverErrorMessage.value = ''
  if (serverErrorTimer) {
    window.clearTimeout(serverErrorTimer)
    serverErrorTimer = null
  }
}

const showServerError = (event: Event) => {
  const { detail } = event as CustomEvent<{ message?: string }>
  serverErrorMessage.value = detail?.message || API_UNAVAILABLE_MESSAGE

  if (serverErrorTimer) {
    window.clearTimeout(serverErrorTimer)
  }

  serverErrorTimer = window.setTimeout(() => {
    serverErrorMessage.value = ''
    serverErrorTimer = null
  }, 5000)
}

const saveDebugSettings = () => {
  setApiBaseUrl(debugApiUrl.value)
  isOpen.value = false
  // Reload to ensure all components use the new base URL
  window.location.reload()
}

const clearDebugSettings = () => {
  debugApiUrl.value = ''
  setApiBaseUrl('')
  isOpen.value = false
  window.location.reload()
}

onMounted(() => {
  debugApiUrl.value = getApiBaseUrl()
  window.addEventListener(API_UNAVAILABLE_EVENT, showServerError)
})

onUnmounted(() => {
  window.removeEventListener(API_UNAVAILABLE_EVENT, showServerError)
  clearServerError()
})
</script>

<template>
  <div class="min-h-screen bg-background text-foreground relative">
    <RouterView />

    <Transition
      enter-active-class="transition duration-150 ease-out"
      enter-from-class="-translate-y-2 opacity-0"
      enter-to-class="translate-y-0 opacity-100"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="translate-y-0 opacity-100"
      leave-to-class="-translate-y-2 opacity-0"
    >
      <div
        v-if="serverErrorMessage"
        role="alert"
        class="fixed left-1/2 top-4 z-[60] flex w-[calc(100%-2rem)] max-w-md -translate-x-1/2 items-center gap-3 rounded-md border border-destructive/30 bg-background px-4 py-3 text-sm shadow-lg"
      >
        <AlertCircle class="h-5 w-5 shrink-0 text-destructive" />
        <p class="min-w-0 flex-1 text-destructive">
          {{ serverErrorMessage }}
        </p>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          class="h-7 w-7 shrink-0"
          aria-label="Dismiss server connection warning"
          @click="clearServerError"
        >
          <X class="h-4 w-4" />
        </Button>
      </div>
    </Transition>

    <!-- Debug Mode Toggle (Fixed Bottom Right) -->
    <div class="fixed bottom-4 right-4 z-50">
      <Sheet v-model:open="isOpen">
        <SheetTrigger as-child>
          <Button variant="outline" size="icon" class="rounded-full shadow-md border-primary/20 bg-background/80 backdrop-blur-sm">
            <Bug class="h-4 w-4 text-primary" />
          </Button>
        </SheetTrigger>
        <SheetContent side="left">
          <SheetHeader>
            <SheetTitle class="flex items-center gap-2">
              <Bug class="h-5 w-5 text-primary" />
              Debug Settings
            </SheetTitle>
            <SheetDescription>
              Configure alternative API endpoints for development and testing.
            </SheetDescription>
          </SheetHeader>

          <div class="grid gap-4 py-6 px-4">
            <div class="space-y-2">
              <Label for="debug-api-url">Alternative API Base URL</Label>
              <Input
                id="debug-api-url"
                v-model="debugApiUrl"
                placeholder="http://localhost:8000"
              />
              <p class="text-xs text-muted-foreground">
                Leave empty to use the default relative path (Vite proxy).
              </p>
            </div>
          </div>

          <SheetFooter class="flex-col sm:flex-col gap-2">
            <Button @click="saveDebugSettings" class="w-full">
              <Save class="mr-2 h-4 w-4" />
              Save and Reload
            </Button>
            <Button variant="ghost" @click="clearDebugSettings" class="w-full text-destructive hover:text-destructive hover:bg-destructive/10">
              <Trash2 class="mr-2 h-4 w-4" />
              Reset to Default
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </div>
  </div>
</template>
