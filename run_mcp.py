#!/usr/bin/env python3
from app.mcp_server import mcp

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
