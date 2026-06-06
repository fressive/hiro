import requests
from deepagents import create_deep_agent

def feroxbuster(
    url: str
):
    """
    Use feroxbuster to scan the website using a dicitionary. 
    """
    

def collect_web_information(url: str):
    """
    Collect information of a website. 
    
    Params:
        - url: The URL of the website.
    """
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.text
    except Exception as e:
        return f"Error collecting information from {url}: {str(e)}"

agent = create_deep_agent(
    model="claude-haiku-4-5-20251001",
    tools=[collect_web_information],
    system_prompt="You are a cybersecurity researcher doing penetration tests. "
)