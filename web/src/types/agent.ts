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
  status: 'running' | 'done' | 'error'
  input?: string
  output?: string
  agent?: string
  agent_path?: string
}

export type SubagentEventRecord = {
  id: string
  name?: string | null
  path: string
  status: 'running' | 'done' | 'error' | 'completed' | 'failed' | 'cancelled' | string
  input?: string | null
  error?: string | null
}

export type AgentSession = {
  id: number
  title?: string | null
  config_id?: number | null
  system_prompt?: string | null
  temperature?: number | null
  max_tokens?: number | null
  enable_1m_context?: boolean | null
  enable_rag?: boolean | null
  tools?: string[] | null
  mcp_servers?: string[] | null
  agent_configs?: Record<string, number | null> | null
  created_at: string
  updated_at: string
}

export type AgentSessionTemplate = {
  id: number
  name: string
  config_id?: number | null
  system_prompt?: string | null
  temperature?: number | null
  max_tokens?: number | null
  enable_1m_context?: boolean | null
  enable_rag?: boolean | null
  tools?: string[] | null
  mcp_servers?: string[] | null
  agent_configs?: Record<string, number | null> | null
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
    tool_events?: EventRecord[]
    mcp_events?: EventRecord[]
    subagent_events?: SubagentEventRecord[]
  }
  input_tokens?: number
  cached_input_tokens?: number
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
