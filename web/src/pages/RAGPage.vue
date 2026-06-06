<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  CheckCircle2,
  Database,
  FileText,
  Loader2,
  Plus,
  Save,
  Sparkles,
  Trash2,
  XCircle,
  Upload,
  Eye,
  RefreshCw,
} from '@lucide/vue'

import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from '@/components/ui/sidebar'
import AppSidebar from '@/components/AppSidebar.vue'
import { Separator } from '@/components/ui/separator'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { apiFetch } from '@/lib/api'

type DocumentStatus = 'indexed' | 'queued' | 'error'

interface DocumentItem {
  id: number
  title: string
  source: string
  status: DocumentStatus
  chunks: number
  updated: string
  tags: string[]
}

const currentTab = ref<'documents' | 'embedding'>('documents')
const searchQuery = ref('')

const newDocument = reactive({
  title: '',
  source: '',
  tags: '',
})

const documents = ref<DocumentItem[]>([])
const isDocumentsLoading = ref(false)
const isDocumentSaving = ref(false)
const isUploading = ref(false)
const deletingDocuments = reactive<Record<number, boolean>>({})
const reindexingDocuments = reactive<Record<number, boolean>>({})
const documentsError = ref('')
const uploadInput = ref<HTMLInputElement | null>(null)

// Document View state
const selectedDoc = ref<DocumentItem | null>(null)
const isSheetOpen = ref(false)
const docChunks = ref<any[]>([])
const isChunksLoading = ref(false)

const filteredDocuments = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return documents.value

  return documents.value.filter((doc) => {
    const haystack = [doc.title, doc.source, ...doc.tags].join(' ').toLowerCase()
    return haystack.includes(query)
  })
})

const addDocument = async () => {
  if (!newDocument.title.trim() || !newDocument.source.trim()) return

  const tags = newDocument.tags
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean)

  isDocumentSaving.value = true
  documentsError.value = ''

  try {
    const response = await apiFetch('/api/v1/rag/documents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: newDocument.title.trim(),
        source: newDocument.source.trim(),
        tags,
      }),
    })

    if (!response.ok) {
      const data = await response.json().catch(() => null)
      throw new Error(data?.detail || 'Failed to create document')
    }

    const created = await response.json()
    documents.value.unshift({
      id: created.id,
      title: created.title,
      source: created.source,
      status: created.status,
      chunks: created.chunks,
      updated: formatDate(created.updated_at),
      tags: created.tags || [],
    })

    newDocument.title = ''
    newDocument.source = ''
    newDocument.tags = ''
  } catch (error: any) {
    documentsError.value = error.message || 'Unable to add document.'
  } finally {
    isDocumentSaving.value = false
  }
}

const handleFileUpload = async (event: Event) => {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return

  isUploading.value = true
  documentsError.value = ''

  const formData = new FormData()
  formData.append('file', file)
  formData.append('tags', newDocument.tags)

  try {
    const response = await apiFetch('/api/v1/rag/upload', {
      method: 'POST',
      body: formData,
    })

    if (!response.ok) {
      const data = await response.json().catch(() => null)
      throw new Error(data?.detail || 'Failed to upload file')
    }

    const created = await response.json()
    documents.value.unshift({
      id: created.id,
      title: created.title,
      source: created.source,
      status: created.status,
      chunks: created.chunks,
      updated: formatDate(created.updated_at),
      tags: created.tags || [],
    })
    
    if (uploadInput.value) uploadInput.value.value = ''
  } catch (error: any) {
    documentsError.value = error.message || 'Unable to upload file.'
  } finally {
    isUploading.value = false
  }
}

const viewDocument = async (doc: DocumentItem) => {
  selectedDoc.value = doc
  isSheetOpen.value = true
  isChunksLoading.value = true
  docChunks.value = []
  
  try {
    const response = await apiFetch(`/api/v1/rag/documents/${doc.id}/chunks`)
    if (response.ok) {
      docChunks.value = await response.json()
    }
  } catch (error) {
    console.error('Failed to fetch chunks:', error)
  } finally {
    isChunksLoading.value = false
  }
}

const reindexDocument = async (id: number) => {
  reindexingDocuments[id] = true
  try {
    const response = await apiFetch(`/api/v1/rag/documents/${id}/reindex`, {
      method: 'POST',
    })
    if (response.ok) {
      const updated = await response.json()
      const idx = documents.value.findIndex(d => d.id === id)
      if (idx !== -1) {
        documents.value[idx].status = updated.status
      }
    }
  } catch (error) {
    console.error('Failed to reindex:', error)
  } finally {
    reindexingDocuments[id] = false
  }
}

const removeDocument = async (id: number) => {
  deletingDocuments[id] = true
  documentsError.value = ''
  try {
    const response = await apiFetch(`/api/v1/rag/documents/${id}`, {
      method: 'DELETE',
    })

    if (!response.ok) {
      const data = await response.json().catch(() => null)
      throw new Error(data?.detail || 'Failed to delete document')
    }

    documents.value = documents.value.filter((doc) => doc.id !== id)
  } catch (error: any) {
    documentsError.value = error.message || 'Unable to delete document.'
  } finally {
    deletingDocuments[id] = false
  }
}

const embeddingConfig = reactive({
  provider: 'openai',
  apiEndpoint: 'https://api.openai.com/v1',
  apiToken: '',
  model: 'text-embedding-3-large',
  dimensions: '3072',
  chunkSize: '800',
  chunkOverlap: '160',
  batchSize: '64',
  normalize: 'true',
})

const vectorStoreConfig = reactive({
  provider: 'milvus',
  dataSource: 'local',
  endpoint: '',
  token: '',
  dbName: '',
  collectionName: '',
})

const hasStoredToken = ref(false)
const isConfigLoading = ref(false)
const isConfigSaving = ref(false)
const isTesting = ref(false)
const configError = ref('')
const testResult = ref<{ success: boolean; message: string } | null>(null)
const lastSavedAt = ref('')

const isVectorConfigLoading = ref(false)
const isVectorConfigSaving = ref(false)
const vectorConfigError = ref('')
const vectorSavedAt = ref('')
const vectorHasStoredToken = ref(false)
const isVectorTesting = ref(false)
const vectorTestResult = ref<{ success: boolean; message: string } | null>(null)

const fetchEmbeddingConfig = async () => {
  isConfigLoading.value = true
  configError.value = ''

  try {
    const response = await apiFetch('/api/v1/rag/embedding-config')
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      throw new Error(data?.detail || 'Failed to load embedding config')
    }

    const data = await response.json()
    embeddingConfig.provider = data.provider
    embeddingConfig.apiEndpoint = data.api_endpoint
    embeddingConfig.apiToken = ''
    embeddingConfig.model = data.model
    embeddingConfig.dimensions = String(data.dimensions)
    embeddingConfig.chunkSize = String(data.chunk_size)
    embeddingConfig.chunkOverlap = String(data.chunk_overlap)
    embeddingConfig.batchSize = String(data.batch_size)
    embeddingConfig.normalize = data.normalize ? 'true' : 'false'
    hasStoredToken.value = Boolean(data.has_token)
  } catch (error: any) {
    configError.value = error.message || 'Unable to load embedding configuration.'
  } finally {
    isConfigLoading.value = false
  }
}

const fetchVectorStoreConfig = async () => {
  isVectorConfigLoading.value = true
  vectorConfigError.value = ''

  try {
    const response = await apiFetch('/api/v1/rag/vector-store-config')
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      throw new Error(data?.detail || 'Failed to load vector store config')
    }

    const data = await response.json()
    vectorStoreConfig.provider = data.provider
    vectorStoreConfig.dataSource = data.data_source
    vectorStoreConfig.endpoint = data.endpoint || ''
    vectorStoreConfig.token = ''
    vectorStoreConfig.dbName = data.db_name || ''
    vectorStoreConfig.collectionName = data.collection_name || ''
    vectorHasStoredToken.value = Boolean(data.has_token)
  } catch (error: any) {
    vectorConfigError.value = error.message || 'Unable to load vector store configuration.'
  } finally {
    isVectorConfigLoading.value = false
  }
}

const saveEmbeddingConfig = async () => {
  isConfigSaving.value = true
  configError.value = ''
  testResult.value = null

  const payload: Record<string, unknown> = {
    provider: embeddingConfig.provider,
    api_endpoint: embeddingConfig.apiEndpoint,
    model: embeddingConfig.model,
    dimensions: Number(embeddingConfig.dimensions) || 0,
    chunk_size: Number(embeddingConfig.chunkSize) || 0,
    chunk_overlap: Number(embeddingConfig.chunkOverlap) || 0,
    batch_size: Number(embeddingConfig.batchSize) || 0,
    normalize: embeddingConfig.normalize === 'true',
  }

  if (embeddingConfig.apiToken.trim()) {
    payload.api_token = embeddingConfig.apiToken.trim()
  }

  try {
    const response = await apiFetch('/api/v1/rag/embedding-config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })

    if (!response.ok) {
      const data = await response.json().catch(() => null)
      throw new Error(data?.detail || 'Failed to save embedding config')
    }

    const data = await response.json()
    embeddingConfig.apiToken = ''
    hasStoredToken.value = Boolean(data.has_token)
    lastSavedAt.value = new Date().toLocaleString()
  } catch (error: any) {
    configError.value = error.message || 'Unable to save embedding configuration.'
  } finally {
    isConfigSaving.value = false
  }
}

const saveVectorStoreConfig = async () => {
  isVectorConfigSaving.value = true
  vectorConfigError.value = ''
  vectorTestResult.value = null

  const payload: Record<string, unknown> = {
    provider: vectorStoreConfig.provider,
    data_source: vectorStoreConfig.dataSource,
  }

  if (vectorStoreConfig.endpoint.trim()) {
    payload.endpoint = vectorStoreConfig.endpoint.trim()
  }

  if (vectorStoreConfig.dbName.trim()) {
    payload.db_name = vectorStoreConfig.dbName.trim()
  }

  if (vectorStoreConfig.collectionName.trim()) {
    payload.collection_name = vectorStoreConfig.collectionName.trim()
  }

  if (vectorStoreConfig.token.trim()) {
    payload.token = vectorStoreConfig.token.trim()
  }

  try {
    const response = await apiFetch('/api/v1/rag/vector-store-config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })

    if (!response.ok) {
      const data = await response.json().catch(() => null)
      throw new Error(data?.detail || 'Failed to save vector store config')
    }

    const data = await response.json()
    vectorStoreConfig.token = ''
    vectorHasStoredToken.value = Boolean(data.has_token)
    vectorSavedAt.value = new Date().toLocaleString()
  } catch (error: any) {
    vectorConfigError.value = error.message || 'Unable to save vector store configuration.'
  } finally {
    isVectorConfigSaving.value = false
  }
}

const testVectorStoreConfig = async () => {
  isVectorTesting.value = true
  vectorConfigError.value = ''
  vectorTestResult.value = null

  const payload: Record<string, unknown> = {
    provider: vectorStoreConfig.provider,
    data_source: vectorStoreConfig.dataSource,
    db_name: vectorStoreConfig.dbName,
    collection_name: vectorStoreConfig.collectionName,
  }

  if (vectorStoreConfig.endpoint.trim()) {
    payload.endpoint = vectorStoreConfig.endpoint.trim()
  }

  if (vectorStoreConfig.token.trim()) {
    payload.token = vectorStoreConfig.token.trim()
  }

  try {
    const response = await apiFetch('/api/v1/rag/vector-store-config/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })

    if (!response.ok) {
      const data = await response.json().catch(() => null)
      throw new Error(data?.detail || 'Failed to test vector store')
    }

    vectorTestResult.value = await response.json()
  } catch (error: any) {
    vectorTestResult.value = {
      success: false,
      message: error.message || 'Unable to test vector store configuration.',
    }
  } finally {
    isVectorTesting.value = false
  }
}

const testEmbeddingConfig = async () => {
  isTesting.value = true
  configError.value = ''
  testResult.value = null

  const payload: Record<string, unknown> = {
    provider: embeddingConfig.provider,
    api_endpoint: embeddingConfig.apiEndpoint,
    model: embeddingConfig.model,
  }

  if (embeddingConfig.apiToken.trim()) {
    payload.api_token = embeddingConfig.apiToken.trim()
  }

  try {
    const response = await apiFetch('/api/v1/rag/embedding-config/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })

    if (!response.ok) {
      const data = await response.json().catch(() => null)
      throw new Error(data?.detail || 'Failed to test embedding model')
    }

    testResult.value = await response.json()
  } catch (error: any) {
    testResult.value = {
      success: false,
      message: error.message || 'Unable to test embedding configuration.',
    }
  } finally {
    isTesting.value = false
  }
}

const formatDate = (value?: string) => {
  if (!value) return 'Unknown'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString()
}

const fetchDocuments = async () => {
  isDocumentsLoading.value = true
  documentsError.value = ''
  try {
    const response = await apiFetch('/api/v1/rag/documents')
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      throw new Error(data?.detail || 'Failed to load documents')
    }

    const data = await response.json()
    documents.value = data.map((doc: any) => ({
      id: doc.id,
      title: doc.title,
      source: doc.source,
      status: doc.status,
      chunks: doc.chunks,
      updated: formatDate(doc.updated_at),
      tags: doc.tags || [],
    }))
  } catch (error: any) {
    documentsError.value = error.message || 'Unable to load documents.'
  } finally {
    isDocumentsLoading.value = false
  }
}

onMounted(() => {
  fetchDocuments()
  fetchEmbeddingConfig()
  fetchVectorStoreConfig()
})

const chunkPreview = computed(() => {
  const chunkSize = Math.max(Number(embeddingConfig.chunkSize) || 1, 1)
  const overlap = Math.max(Number(embeddingConfig.chunkOverlap) || 0, 0)
  const effective = Math.max(chunkSize - overlap, 1)
  const sampleTokens = 3200
  const chunks = Math.ceil(sampleTokens / effective)

  return {
    sampleTokens,
    effective,
    chunks,
  }
})
</script>

<template>
  <SidebarProvider>
    <AppSidebar />
    <SidebarInset class="flex h-screen flex-col overflow-hidden">
      <header class="flex h-16 shrink-0 items-center gap-2 border-b px-4">
        <SidebarTrigger class="-ml-1" />
        <Separator orientation="vertical" class="mr-2 h-4" />
        <div class="flex flex-col">
          <h1 class="text-lg font-semibold rag-title">RAG Studio</h1>
          <span class="text-xs text-muted-foreground">Documents and embeddings for retrieval</span>
        </div>
      </header>

      <main class="flex-1 p-6 space-y-6 overflow-auto">

        <div class="flex items-center gap-1 rounded-lg bg-muted p-1 w-fit">
          <Button
            variant="ghost"
            size="sm"
            :class="['gap-2', currentTab === 'documents' && 'bg-background shadow-sm']"
            @click="currentTab = 'documents'"
          >
            <FileText class="h-4 w-4" />
            Documents
          </Button>
          <Button
            variant="ghost"
            size="sm"
            :class="['gap-2', currentTab === 'embedding' && 'bg-background shadow-sm']"
            @click="currentTab = 'embedding'"
          >
            <Database class="h-4 w-4" />
            Embeddings
          </Button>
        </div>

        <Separator />

        <section v-if="currentTab === 'documents'" class="grid gap-6 lg:grid-cols-[1.1fr_1.6fr] animate-in fade-in slide-in-from-bottom-2 duration-300">
          <Card>
            <CardHeader>
              <CardTitle>Add Document</CardTitle>
              <CardDescription>Register sources to sync into your vector store.</CardDescription>
            </CardHeader>
            <CardContent>
              <form class="space-y-4" @submit.prevent="addDocument">
                <div class="space-y-2">
                  <Label for="doc-title">Title</Label>
                  <Input id="doc-title" v-model="newDocument.title" placeholder="Support Playbook" :disabled="isDocumentSaving" />
                </div>
                <div class="space-y-2">
                  <Label for="doc-source">Source URL or URI</Label>
                  <Input id="doc-source" v-model="newDocument.source" placeholder="https://... or s3://..." :disabled="isDocumentSaving" />
                </div>
                <div class="space-y-2">
                  <Label for="doc-tags">Tags</Label>
                  <Input id="doc-tags" v-model="newDocument.tags" placeholder="ops, policy" :disabled="isDocumentSaving" />
                </div>
                <Button type="submit" class="w-full gap-2" :disabled="isDocumentSaving">
                  <Loader2 v-if="isDocumentSaving" class="h-4 w-4 animate-spin" />
                  <Plus v-else class="h-4 w-4" />
                  Queue document
                </Button>
                
                <div class="relative">
                  <div class="absolute inset-0 flex items-center">
                    <span class="w-full border-t" />
                  </div>
                  <div class="relative flex justify-center text-xs uppercase">
                    <span class="bg-card px-2 text-muted-foreground">Or upload local file</span>
                  </div>
                </div>

                <div class="space-y-2">
                  <input
                    type="file"
                    ref="uploadInput"
                    class="hidden"
                    accept=".pdf,.txt,.md,.mhtml,.docx"
                    @change="handleFileUpload"
                    :disabled="isUploading"
                  />
                  <Button 
                    type="button" 
                    variant="outline" 
                    class="w-full gap-2" 
                    :disabled="isUploading"
                    @click="uploadInput?.click()"
                  >
                    <Loader2 v-if="isUploading" class="h-4 w-4 animate-spin" />
                    <Upload v-else class="h-4 w-4" />
                    Upload file
                  </Button>
                  <p class="text-[10px] text-center text-muted-foreground">
                    PDF, TXT, MD, MHTML, or DOCX supported.
                  </p>
                </div>

                <p v-if="documentsError" class="text-sm text-destructive">
                  {{ documentsError }}
                </p>
              </form>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <CardTitle>Document Library</CardTitle>
                  <CardDescription>Track ingestion status and recent updates.</CardDescription>
                </div>
                <div class="w-full sm:w-64">
                  <Input v-model="searchQuery" placeholder="Search title, source, tags" />
                </div>
              </div>
            </CardHeader>
            <CardContent class="space-y-3">
              <div v-if="isDocumentsLoading" class="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
                Loading documents...
              </div>
              <div v-else-if="filteredDocuments.length === 0" class="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
                No documents match your filters yet.
              </div>
              <div
                v-for="doc in filteredDocuments"
                :key="doc.id"
                v-if="!isDocumentsLoading"
                class="flex flex-col gap-3 rounded-lg border p-4 transition hover:border-primary/40"
              >
                <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div class="space-y-1">
                    <div class="flex flex-wrap items-center gap-2">
                      <p class="font-semibold">{{ doc.title }}</p>
                      <span
                        class="rounded-full px-2 py-0.5 text-xs font-medium"
                        :class="{
                          'bg-emerald-100 text-emerald-700': doc.status === 'indexed',
                          'bg-amber-100 text-amber-700': doc.status === 'queued',
                          'bg-rose-100 text-rose-700': doc.status === 'error',
                        }"
                      >
                        {{ doc.status }}
                      </span>
                    </div>
                    <p class="text-xs text-muted-foreground break-all">{{ doc.source }}</p>
                  </div>
                  <div class="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="icon"
                      title="View indexed chunks"
                      @click="viewDocument(doc)"
                    >
                      <Eye class="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      title="Re-index document"
                      :disabled="reindexingDocuments[doc.id]"
                      @click="reindexDocument(doc.id)"
                    >
                      <Loader2 v-if="reindexingDocuments[doc.id]" class="h-4 w-4 animate-spin" />
                      <RefreshCw v-else class="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      :disabled="deletingDocuments[doc.id]"
                      @click="removeDocument(doc.id)"
                    >
                      <Loader2 v-if="deletingDocuments[doc.id]" class="h-4 w-4 animate-spin" />
                      <Trash2 v-else class="h-4 w-4" />
                    </Button>
                  </div>
                </div>

                <div class="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                  <span>{{ doc.chunks }} chunks</span>
                  <span>Updated {{ doc.updated }}</span>
                  <span v-if="doc.tags.length">Tags: {{ doc.tags.join(', ') }}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </section>

        <section v-else class="grid gap-6 lg:grid-cols-[1.2fr_1fr] animate-in fade-in slide-in-from-bottom-2 duration-300">
          <Card>
            <CardHeader>
              <CardTitle>Embedding Model</CardTitle>
              <CardDescription>Pick the provider and tune the retrieval settings.</CardDescription>
            </CardHeader>
            <CardContent class="space-y-4">
              <div v-if="isConfigLoading" class="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                Loading embedding configuration...
              </div>
              <div class="grid gap-4 sm:grid-cols-2">
                <div class="space-y-2">
                  <Label for="embedding-provider">Provider</Label>
                  <select
                    id="embedding-provider"
                    v-model="embeddingConfig.provider"
                    class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                    :disabled="isConfigLoading || isConfigSaving"
                  >
                    <option value="openai">OpenAI</option>
                    <option value="cohere">Cohere</option>
                    <option value="ollama">Ollama</option>
                  </select>
                </div>
                <div class="space-y-2">
                  <Label for="embedding-model">Model</Label>
                  <Input id="embedding-model" v-model="embeddingConfig.model" placeholder="text-embedding-3-large" :disabled="isConfigLoading || isConfigSaving" />
                </div>
              </div>

              <div class="grid gap-4 sm:grid-cols-2">
                <div class="space-y-2">
                  <Label for="embedding-endpoint">API endpoint</Label>
                  <Input id="embedding-endpoint" v-model="embeddingConfig.apiEndpoint" placeholder="https://api.openai.com/v1" :disabled="isConfigLoading || isConfigSaving" />
                </div>
                <div class="space-y-2">
                  <Label for="embedding-token">API token</Label>
                  <Input id="embedding-token" v-model="embeddingConfig.apiToken" type="password" placeholder="sk-..." :disabled="isConfigLoading || isConfigSaving" />
                  <p class="text-xs text-muted-foreground">
                    {{ hasStoredToken ? 'Token stored. Leave blank to keep it.' : 'No token stored yet.' }}
                  </p>
                </div>
              </div>

              <div class="grid gap-4 sm:grid-cols-2">
                <div class="space-y-2">
                  <Label for="embedding-dim">Dimensions</Label>
                  <Input id="embedding-dim" v-model="embeddingConfig.dimensions" placeholder="3072" :disabled="isConfigLoading || isConfigSaving" />
                </div>
                <div class="space-y-2">
                  <Label for="embedding-batch">Batch size</Label>
                  <Input id="embedding-batch" v-model="embeddingConfig.batchSize" placeholder="64" :disabled="isConfigLoading || isConfigSaving" />
                </div>
              </div>

              <div class="grid gap-4 sm:grid-cols-2">
                <div class="space-y-2">
                  <Label for="chunk-size">Chunk size (tokens)</Label>
                  <Input id="chunk-size" v-model="embeddingConfig.chunkSize" placeholder="800" :disabled="isConfigLoading || isConfigSaving" />
                </div>
                <div class="space-y-2">
                  <Label for="chunk-overlap">Chunk overlap</Label>
                  <Input id="chunk-overlap" v-model="embeddingConfig.chunkOverlap" placeholder="160" :disabled="isConfigLoading || isConfigSaving" />
                </div>
              </div>

              <div class="grid gap-4 sm:grid-cols-2">
                <div class="space-y-2">
                  <Label for="normalize">Normalize vectors</Label>
                  <select
                    id="normalize"
                    v-model="embeddingConfig.normalize"
                    class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                    :disabled="isConfigLoading || isConfigSaving"
                  >
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </select>
                </div>
              </div>

              <div class="flex flex-wrap items-center gap-3">
                <Button class="gap-2" :disabled="isConfigSaving || isConfigLoading" @click="saveEmbeddingConfig">
                  <Loader2 v-if="isConfigSaving" class="h-4 w-4 animate-spin" />
                  <Save v-else class="h-4 w-4" />
                  Save configuration
                </Button>
                <Button variant="outline" class="gap-2" :disabled="isTesting || isConfigLoading" @click="testEmbeddingConfig">
                  <Loader2 v-if="isTesting" class="h-4 w-4 animate-spin" />
                  <Sparkles v-else class="h-4 w-4" />
                  Test model
                </Button>
                <span v-if="lastSavedAt" class="text-xs text-muted-foreground">
                  Last saved {{ lastSavedAt }}
                </span>
              </div>
              <div v-if="configError" class="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                {{ configError }}
              </div>
              <div v-if="testResult" class="rounded-lg border p-3 text-sm" :class="testResult.success ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-rose-200 bg-rose-50 text-rose-700'">
                <div class="flex items-center gap-2">
                  <CheckCircle2 v-if="testResult.success" class="h-4 w-4" />
                  <XCircle v-else class="h-4 w-4" />
                  <span>{{ testResult.message }}</span>
                </div>
              </div>
            </CardContent>
          </Card>
          <div class="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Vector Store</CardTitle>
                <CardDescription>Configure Milvus storage for retrieved chunks.</CardDescription>
              </CardHeader>
              <CardContent class="space-y-4">
                <div v-if="isVectorConfigLoading" class="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                  Loading vector store configuration...
                </div>
                <div class="grid gap-4 sm:grid-cols-2">
                  <div class="space-y-2">
                    <Label for="vector-provider">Provider</Label>
                    <select
                      id="vector-provider"
                      v-model="vectorStoreConfig.provider"
                      class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                      :disabled="isVectorConfigLoading || isVectorConfigSaving"
                    >
                      <option value="milvus">Milvus</option>
                    </select>
                  </div>
                  <div class="space-y-2">
                    <Label for="vector-source">Data source</Label>
                    <select
                      id="vector-source"
                      v-model="vectorStoreConfig.dataSource"
                      class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                      :disabled="isVectorConfigLoading || isVectorConfigSaving"
                    >
                      <option value="local">Local</option>
                      <option value="remote">Remote</option>
                    </select>
                  </div>
                </div>

                <div v-if="vectorStoreConfig.dataSource === 'remote'" class="grid gap-4">
                  <div class="space-y-2">
                    <Label for="vector-endpoint">Endpoint</Label>
                    <Input id="vector-endpoint" v-model="vectorStoreConfig.endpoint" placeholder="http://localhost:19530" :disabled="isVectorConfigLoading || isVectorConfigSaving" />
                  </div>
                  <div class="space-y-2">
                    <Label for="vector-db">Database name</Label>
                    <Input id="vector-db" v-model="vectorStoreConfig.dbName" placeholder="hiro" :disabled="isVectorConfigLoading || isVectorConfigSaving" />
                  </div>
                  <div class="space-y-2">
                    <Label for="vector-token">Token</Label>
                    <Input id="vector-token" v-model="vectorStoreConfig.token" type="password" placeholder="root:Milvus" :disabled="isVectorConfigLoading || isVectorConfigSaving" />
                    <p class="text-xs text-muted-foreground">
                      {{ vectorHasStoredToken ? 'Token stored. Leave blank to keep it.' : 'No token stored yet.' }}
                    </p>
                  </div>
                </div>

                <div class="space-y-2">
                  <Label for="vector-collection">Collection name</Label>
                  <Input id="vector-collection" v-model="vectorStoreConfig.collectionName" placeholder="hiro_documents" :disabled="isVectorConfigLoading || isVectorConfigSaving" />
                </div>

                <div class="flex flex-wrap items-center gap-3">
                  <Button class="gap-2" :disabled="isVectorConfigSaving || isVectorConfigLoading" @click="saveVectorStoreConfig">
                    <Loader2 v-if="isVectorConfigSaving" class="h-4 w-4 animate-spin" />
                    <Save v-else class="h-4 w-4" />
                    Save vector store
                  </Button>
                  <Button variant="outline" class="gap-2" :disabled="isVectorTesting || isVectorConfigLoading" @click="testVectorStoreConfig">
                    <Loader2 v-if="isVectorTesting" class="h-4 w-4 animate-spin" />
                    <Sparkles v-else class="h-4 w-4" />
                    Test Milvus
                  </Button>
                  <span v-if="vectorSavedAt" class="text-xs text-muted-foreground">
                    Last saved {{ vectorSavedAt }}
                  </span>
                </div>
                <div v-if="vectorConfigError" class="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                  {{ vectorConfigError }}
                </div>
                <div v-if="vectorTestResult" class="rounded-lg border p-3 text-sm" :class="vectorTestResult.success ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-rose-200 bg-rose-50 text-rose-700'">
                  <div class="flex items-center gap-2">
                    <CheckCircle2 v-if="vectorTestResult.success" class="h-4 w-4" />
                    <XCircle v-else class="h-4 w-4" />
                    <span>{{ vectorTestResult.message }}</span>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Chunking Preview</CardTitle>
                <CardDescription>Estimate split count for a 3.2k token sample.</CardDescription>
              </CardHeader>
              <CardContent class="space-y-4">
                <div class="rounded-lg border bg-muted/30 p-4">
                  <div class="flex items-center justify-between text-sm">
                    <span>Effective chunk size</span>
                    <span class="font-semibold">{{ chunkPreview.effective }}</span>
                  </div>
                  <div class="mt-3 flex items-center justify-between text-sm">
                    <span>Estimated chunks</span>
                    <span class="font-semibold">{{ chunkPreview.chunks }}</span>
                  </div>
                  <div class="mt-3 flex items-center justify-between text-sm">
                    <span>Sample tokens</span>
                    <span class="font-semibold">{{ chunkPreview.sampleTokens }}</span>
                  </div>
                </div>

                <div class="space-y-3 text-sm text-muted-foreground">
                  <p>
                    Keep overlap under 25% of chunk size to reduce redundant context and index cost.
                  </p>
                  <div class="rounded-lg border border-dashed p-3">
                    Tip: Re-run embedding jobs after changing dimensions or provider.
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </section>
      </main>
    </SidebarInset>

        <!-- Document Preview Sheet -->
        <Sheet v-model:open="isSheetOpen">
        <SheetContent class="sm:max-w-xl flex flex-col h-full">
        <SheetHeader>
          <SheetTitle>{{ selectedDoc?.title }}</SheetTitle>
          <SheetDescription class="break-all">
            {{ selectedDoc?.source }}
          </SheetDescription>
        </SheetHeader>

        <Separator class="my-4" />

        <div class="flex-1 overflow-auto space-y-4 px-4 pr-2">
          <div v-if="isChunksLoading" class="flex flex-col items-center justify-center h-40 gap-2 text-muted-foreground">
            <Loader2 class="h-6 w-6 animate-spin" />
            <span>Loading indexed chunks...</span>
          </div>
          <div v-else-if="docChunks.length === 0" class="flex flex-col items-center justify-center h-40 text-muted-foreground italic text-sm">
            No chunks found for this document.
          </div>
          <div 
            v-for="(chunk, idx) in docChunks" 
            :key="idx"
            class="rounded-lg border bg-muted/30 p-4 text-xs font-mono relative group"
          >
            <span class="absolute top-2 right-2 text-[9px] text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity">
              Chunk #{{ idx + 1 }}
            </span>
            <pre class="whitespace-pre-wrap font-sans text-foreground">{{ chunk.text }}</pre>
            <div v-if="chunk.metadata" class="mt-3 pt-2 border-t border-dashed text-[10px] text-muted-foreground">
              <span class="font-bold uppercase tracking-tighter mr-2">Metadata:</span>
              {{ JSON.stringify(chunk.metadata) }}
            </div>
          </div>
        </div>
        </SheetContent>
        </Sheet>
        </SidebarProvider>
        </template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&display=swap');

.rag-title {
  font-family: 'Space Grotesk', sans-serif;
  letter-spacing: -0.02em;
}
</style>
