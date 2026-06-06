<script setup lang="ts">
import { ref, computed } from 'vue'
import { 
  File, 
  Folder, 
  FolderOpen,
  ChevronRight, 
  ChevronDown,
  Download,
  Trash2,
  FileText,
  FileArchive,
  FileImage,
  FileCode
} from '@lucide/vue'
import { Button } from '@/components/ui/button'

interface TreeNode {
  name: string
  path: string
  type: 'file' | 'directory'
  children?: TreeNode[]
  size?: number
  modified_at?: string
}

const props = defineProps<{
  node: TreeNode
  depth: number
}>()

const emit = defineEmits<{
  (e: 'download', path: string): void
  (e: 'delete', path: string): void
}>()

const isOpen = ref(false)

const toggle = () => {
  if (props.node.type === 'directory') {
    isOpen.value = !isOpen.value
  }
}

const getFileIcon = (path: string) => {
  if (props.node.type === 'directory') {
    return isOpen.value ? FolderOpen : Folder
  }
  const ext = path.split('.').pop()?.toLowerCase()
  if (['zip', 'rar', '7z', 'tar', 'gz'].includes(ext || '')) return FileArchive
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext || '')) return FileImage
  if (['py', 'js', 'ts', 'html', 'css', 'json', 'md', 'sh'].includes(ext || '')) return FileCode
  if (['txt', 'pdf', 'doc', 'docx'].includes(ext || '')) return FileText
  return File
}

const sortedChildren = computed(() => {
  if (!props.node.children) return []
  return [...props.node.children].sort((a, b) => {
    if (a.type !== b.type) {
      return a.type === 'directory' ? -1 : 1
    }
    return a.name.localeCompare(b.name)
  })
})

const formatSize = (bytes?: number) => {
  if (bytes === undefined || bytes === 0) return ''
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}
</script>

<template>
  <div class="select-none">
    <div 
      class="group flex items-center py-1 px-2 hover:bg-muted/50 rounded-md cursor-pointer transition-colors"
      :style="{ paddingLeft: `${depth * 1.2 + 0.5}rem` }"
      @click="toggle"
    >
      <div class="flex items-center gap-1.5 flex-1 min-w-0">
        <div class="w-4 h-4 flex items-center justify-center">
          <template v-if="node.type === 'directory'">
            <ChevronDown v-if="isOpen" class="h-3 w-3 text-muted-foreground" />
            <ChevronRight v-else class="h-3 w-3 text-muted-foreground" />
          </template>
        </div>
        
        <component :is="getFileIcon(node.path)" class="h-4 w-4 shrink-0 text-muted-foreground" />
        
        <span class="text-sm truncate" :title="node.name">{{ node.name }}</span>
        
        <span v-if="node.type === 'file'" class="text-[10px] text-muted-foreground/60 font-mono ml-2">
          {{ formatSize(node.size) }}
        </span>
      </div>

      <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <Button 
          v-if="node.type === 'file'"
          variant="ghost" 
          size="icon" 
          class="h-7 w-7" 
          @click.stop="emit('download', node.path)"
        >
          <Download class="h-3.5 w-3.5" />
        </Button>
        <Button 
          variant="ghost" 
          size="icon" 
          class="h-7 w-7 text-destructive hover:bg-destructive/10" 
          @click.stop="emit('delete', node.path)"
        >
          <Trash2 class="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>

    <div v-if="isOpen && node.children && node.children.length > 0">
      <TreeItem 
        v-for="child in sortedChildren" 
        :key="child.path" 
        :node="child" 
        :depth="depth + 1"
        @download="(p) => emit('download', p)"
        @delete="(p) => emit('delete', p)"
      />
    </div>
  </div>
</template>
