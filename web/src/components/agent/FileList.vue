<script setup lang="ts">
import { ref, onMounted, watch, computed } from 'vue'
import { 
  File, 
  Upload, 
  Loader2,
  RefreshCcw,
  Search
} from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { apiFetch } from '@/lib/api'
import type { SessionFile } from '@/types/agent'
import TreeItem from './TreeItem.vue'

const props = defineProps<{
  sessionId: number
}>()

const files = ref<SessionFile[]>([])
const isLoading = ref(false)
const isUploading = ref(false)
const searchQuery = ref('')
const fileInput = ref<HTMLInputElement | null>(null)

const fetchFiles = async () => {
  if (!props.sessionId) return
  isLoading.value = true
  try {
    const response = await apiFetch(`/api/v1/agent/sessions/${props.sessionId}/files`)
    if (response.ok) {
      files.value = await response.json()
    }
  } catch (error) {
    console.error('Failed to fetch files:', error)
  } finally {
    isLoading.value = false
  }
}

interface TreeNode {
  name: string
  path: string
  type: 'file' | 'directory'
  children?: TreeNode[]
  size?: number
  modified_at?: string
}

const fileTree = computed(() => {
  const root: TreeNode[] = []
  const map: Record<string, TreeNode> = {}

  // Filter files by search query if any
  const filteredFiles = searchQuery.value 
    ? files.value.filter(f => f.path.toLowerCase().includes(searchQuery.value.toLowerCase()))
    : files.value

  filteredFiles.forEach(file => {
    const parts = file.path.split('/')
    let currentPath = ''
    
    parts.forEach((part, index) => {
      const isLast = index === parts.length - 1
      const parentPath = currentPath
      currentPath = currentPath ? `${currentPath}/${part}` : part
      
      if (!map[currentPath]) {
        const node: TreeNode = {
          name: part,
          path: currentPath,
          type: isLast ? file.type : 'directory',
          size: isLast ? file.size : undefined,
          modified_at: isLast ? file.modified_at : undefined
        }
        
        if (node.type === 'directory') {
          node.children = []
        }
        
        map[currentPath] = node
        
        if (!parentPath) {
          root.push(node)
        } else {
          map[parentPath].children?.push(node)
        }
      }
    })
  })

  // Sort: Directories first, then alphabetically
  const sortNodes = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => {
      if (a.type !== b.type) return a.type === 'directory' ? -1 : 1
      return a.name.localeCompare(b.name)
    })
    nodes.forEach(node => {
      if (node.children) sortNodes(node.children)
    })
  }
  
  sortNodes(root)
  return root
})

const handleFileUpload = async (event: Event) => {
  const target = event.target as HTMLInputElement
  if (!target.files || target.files.length === 0) return

  const file = target.files[0]
  const formData = new FormData()
  formData.append('file', file)

  isUploading.value = true
  try {
    const response = await apiFetch(`/api/v1/agent/sessions/${props.sessionId}/files/upload`, {
      method: 'POST',
      body: formData,
    })
    if (response.ok) {
      await fetchFiles()
    }
  } catch (error) {
    console.error('Failed to upload file:', error)
  } finally {
    isUploading.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

const downloadFile = async (path: string) => {
  try {
    const response = await apiFetch(`/api/v1/agent/sessions/${props.sessionId}/files/download?path=${encodeURIComponent(path)}`)
    if (response.ok) {
      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = path.split('/').pop() || 'download'
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    }
  } catch (error) {
    console.error('Failed to download file:', error)
  }
}

const deleteFile = async (path: string) => {
  if (!confirm(`Are you sure you want to delete ${path}?`)) return
  try {
    const response = await apiFetch(`/api/v1/agent/sessions/${props.sessionId}/files?path=${encodeURIComponent(path)}`, {
      method: 'DELETE'
    })
    if (response.ok) {
      await fetchFiles()
    }
  } catch (error) {
    console.error('Failed to delete file:', error)
  }
}

onMounted(fetchFiles)
watch(() => props.sessionId, fetchFiles)

const triggerUpload = () => {
  fileInput.value?.click()
}
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between gap-4">
      <div class="relative flex-1 max-w-sm">
        <Search class="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          v-model="searchQuery"
          type="search"
          placeholder="Search files..."
          class="pl-8 h-9"
        />
      </div>
      
      <div class="flex items-center gap-2">
        <Button variant="outline" size="sm" @click="fetchFiles" :disabled="isLoading">
          <RefreshCcw :class="['h-4 w-4 mr-2', isLoading && 'animate-spin']" />
          Refresh
        </Button>
        <input 
          ref="fileInput"
          type="file" 
          class="hidden" 
          @change="handleFileUpload"
        />
        <Button size="sm" @click="triggerUpload" :disabled="isUploading">
          <Loader2 v-if="isUploading" class="h-4 w-4 mr-2 animate-spin" />
          <Upload v-else class="h-4 w-4 mr-2" />
          Upload
        </Button>
      </div>
    </div>

    <Card class="flex flex-col min-h-0 overflow-hidden">
      <CardHeader class="pb-3">
        <CardTitle class="text-lg">Session Workspace</CardTitle>
        <CardDescription>
          Explore and manage files in the agent's sandboxed environment.
        </CardDescription>
      </CardHeader>
      <CardContent class="flex-1 overflow-auto">
        <div v-if="files.length === 0 && !isLoading" class="flex flex-col items-center justify-center py-12 text-muted-foreground italic">
          <File class="h-12 w-12 mb-2 opacity-20" />
          <p>No files in this session yet.</p>
        </div>
        
        <div v-else class="space-y-1">
          <TreeItem 
            v-for="node in fileTree" 
            :key="node.path" 
            :node="node" 
            :depth="0"
            @download="downloadFile"
            @delete="deleteFile"
          />
        </div>
      </CardContent>
    </Card>
  </div>
</template>
