from langchain.tools import tool, ToolRuntime
from server.agent.runtime.context import SessionContext
from server.core.logger import logger

@tool(
    "log",
    description="Log what are you doing. Use when you do major operations.",
)
def log(message: str,
        runtime: ToolRuntime[SessionContext]) -> str:
    try:
        session_id = runtime.context.session_id
        logger.info("[log tool] [session_id: %d] %s", session_id, message)
        return f"Successfully logged: {message}"
    except Exception as e:
        return f"Error logging message: {str(e)}"
