"""Main entry point for the FastAPI application."""

import uvicorn
from server.app import create_app

# Create app instance for uvicorn
app = create_app()

if __name__ == "__main__":
    # Run with uvicorn
    # Usage: python main.py
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False,  # Set to True for development with auto-reload
    )
