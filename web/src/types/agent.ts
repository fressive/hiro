export type LLMConfig = {
  id: number
  name: string
  provider: string
  base_url?: string
  model: string
}

export type Tool = {
  name: string
  description: string
}

export type EventRecord = {
  id: string
  name: string
  status: 'running' | 'done'
  input?: string
  output?: string
}

export type AgentSession = {
  id: number
  title?: string | null
  config_id?: number | null
  system_prompt?: string | null
  temperature?: number | null
  max_tokens?: number | null
  enable_1m_context?: boolean | null
  is_deep_agent?: boolean | null
  enable_rag?: boolean | null
  tools?: string[] | null
  mcp_servers?: string[] | null
  created_at: string
  updated_at: string
}

export type MCPServer = {
  id: number
  name: string
  type: 'command' | 'sse' | 'streamable-http'
  command?: string
  args?: string[]
  env?: Record<string, string>
  url?: string
  enabled: boolean
  created_at: string
  updated_at: string
}

export type AgentMessage = {
  id: number
  session_id: number
  role: 'user' | 'assistant' | 'tool'
  content: string
  name?: string
  tool_call_id?: string
  tool_calls?: any[]
  extra_metadata?: {
    rag_sources?: string[]
  }
  input_tokens?: number
  output_tokens?: number
  model?: string
  created_at: string
}

export type SessionFile = {
  path: string
  size: number
  modified_at: string
  type: 'file' | 'directory'
}
