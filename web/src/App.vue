<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { RouterView } from 'vue-router'
import { Bug, Save, Trash2 } from '@lucide/vue'
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
import { getApiBaseUrl, setApiBaseUrl } from '@/lib/api'

const debugApiUrl = ref('')
const isOpen = ref(false)

onMounted(() => {
  debugApiUrl.value = getApiBaseUrl()
})

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
</script>

<template>
  <div class="min-h-screen bg-background text-foreground relative">
    <RouterView />

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
