import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langchain.chat_models import init_chat_model
from langchain_anthropic import ChatAnthropic
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from server.agent.sandboxed_backend import SessionSandboxedBackend
from server.agent.tools import agent_tools
from server.agent.context import SessionContext
from langchain_core.callbacks import get_usage_metadata_callback, BaseCallbackHandler
from langchain_core.outputs import LLMResult
from typing import Any, List, Dict

class LogAllLLMOutputHandler(BaseCallbackHandler):
    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """当任何一个 LLM 节点执行结束时触发"""
        for generations in response.generations:
            for generation in generations:
                # 打印文本内容
                print(f"LLM: {generation}")
        
def test_llm_activation():
    api_key = os.getenv("API_KEY")
    if not api_key:
        print("Skipping live model test: API_KEY is not set.")
        return

    
    # llm = init_chat_model(
    #     model="claude-opus-4-8",
    #     model_provider='anthropic',
    #     base_url='https://anyrouter.top',
    #     api_key=api_key,
    #     default_headers={
	# 		"anthropic-beta": "context-1m-2025-08-07"
	# 	})
    
    llm = ChatAnthropic(
        model_name="claude-haiku-4-5-20251001",
        base_url='https://anyrouter.top',
        api_key=api_key,
        default_headers={
            "User-Agent": "claude-code/1.0.0 (official-cli)",
            "anthropic-version": "2023-06-01",
            "Anthropic-Beta": "context-1m-2025-08-07"
        }
    )
    
    backend = SessionSandboxedBackend(session_id=1)
    log_handler = LogAllLLMOutputHandler()
    agent = create_deep_agent(
        llm, 
        tools=agent_tools,
        context_schema=SessionContext,
        backend=backend,
        skills=["./skills"],
        system_prompt="""You are a web security researcher requested to do penetration tests on some websites. 
## Regulations
1. Your working directory is `./data/{session_id}`, as session_id is passed in through the context
""")

    while True:
        prompt = input("Prompt: ")
        
        if prompt == "/quit":
            break
        
        with get_usage_metadata_callback() as cb:
            ai_msg1 = agent.invoke(
                {"messages": [{"role": "user", "content": prompt}]}, 
                config={"callbacks": [log_handler]},
                context=SessionContext(1))
            
            print(ai_msg1["messages"][-1].content_blocks)
            print(f"总 Token 消耗: {cb.usage_metadata}")
        
if __name__ == "__main__":
    test_llm_activation()