"""Agent package.

Implementation modules are grouped by responsibility:

- events: streaming callbacks and session event hubs.
- persistence: message storage and token usage helpers.
- runtime: LLM construction, MCP loading, execution context, and sandboxes.
- subagents: specialized agents such as writeup generation.
- trace: tool and MCP trace metadata.
- utils: small shared utilities.
"""
