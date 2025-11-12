#!/usr/bin/env python3
"""
Production-ready server startup script with proper import handling
"""

import sys
import os
import uvicorn
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set working directory to project root
os.chdir(project_root)

# Import and configure the FastAPI app
from api.main import app

def start_server(host="127.0.0.1", port=8000, reload=False):
    """Start the FastAPI server with proper configuration"""
    print(f"🚀 Starting VouchLink AI API Server on http://{host}:{port}")
    print(f"📁 Working directory: {os.getcwd()}")
    print(f"🐍 Python path: {sys.path[0]}")
    
    # Configure uvicorn
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload,
        access_log=True,
        log_level="info"
    )

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Start VouchLink AI API Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    
    args = parser.parse_args()
    start_server(host=args.host, port=args.port, reload=args.reload)