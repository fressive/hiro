"""Agent package.

Implementation modules are grouped by responsibility:

- events: streaming callbacks and session event hubs.
- graph: LangGraph execution graph construction and node handlers.
- persistence: message storage and token usage helpers.
- runtime: LLM construction, MCP loading, execution context, and sandboxes.
- subagents: specialized agents such as writeup generation.
- trace: execution graph metadata.
- utils: small shared utilities.
"""
