"""
MCP Client Module
Handles connection to the Model Context Protocol (MCP) server over stdio transport.
Provides tool discovery, execution, health checking, and error resilience.
"""

import sys
import os
import asyncio
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

# Load environment variables
load_dotenv()

logger = logging.getLogger("mcp_client")
logger.setLevel(logging.INFO)

# Configurable timeout
MCP_TIMEOUT = float(os.getenv("MCP_TIMEOUT_SECONDS", "10.0"))


class MCPClientManager:
    """Manages MCP Server process lifecycle and JSON-RPC tool invocations."""

    def __init__(self):
        # Default to launching backend/mcp_server.py with current Python interpreter
        default_server_path = str(Path(__file__).parent / "mcp_server.py")
        custom_command = os.getenv("MCP_SERVER_COMMAND", "").strip()

        if custom_command:
            parts = custom_command.split()
            self.command = parts[0]
            self.args = parts[1:]
        else:
            self.command = sys.executable
            self.args = [default_server_path]

        self.server_params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=os.environ.copy()
        )

    def _get_server_params(self) -> StdioServerParameters:
        return StdioServerParameters(
            command=self.command,
            args=self.args,
            env=os.environ.copy()
        )

    async def list_tools(self) -> List[Dict[str, Any]]:
        """
        Discovers all available tools exposed by the MCP server.
        Returns a list of dicts with name, description, and input_schema.
        """
        try:
            async with asyncio.timeout(MCP_TIMEOUT):
                async with stdio_client(self._get_server_params()) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tool_list = await session.list_tools()
                        
                        tools = []
                        for t in tool_list.tools:
                            tools.append({
                                "name": t.name,
                                "description": t.description or "",
                                "input_schema": t.inputSchema if hasattr(t, "inputSchema") and t.inputSchema else {
                                    "type": "object",
                                    "properties": {},
                                    "required": []
                                }
                            })
                        return tools
        except TimeoutError:
            logger.error(f"MCP server timeout while listing tools (limit: {MCP_TIMEOUT}s)")
            return []
        except Exception as e:
            logger.error(f"Failed to list tools from MCP server: {e}")
            return []

    async def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Executes a named tool on the MCP server with given arguments.
        Returns a dictionary with result, success status, and error details if any.
        """
        args = arguments or {}
        try:
            async with asyncio.timeout(MCP_TIMEOUT):
                async with stdio_client(self._get_server_params()) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool(tool_name, args)
                        
                        # Extract content from result
                        content_texts = []
                        if hasattr(result, "content") and result.content:
                            for c in result.content:
                                if hasattr(c, "text"):
                                    content_texts.append(c.text)
                                else:
                                    content_texts.append(str(c))
                        
                        output = "\n".join(content_texts) if content_texts else "Tool executed successfully (no output)."
                        is_error = getattr(result, "isError", False)

                        return {
                            "success": not is_error,
                            "tool_name": tool_name,
                            "arguments": args,
                            "result": output,
                            "error": output if is_error else None
                        }
        except TimeoutError:
            err_msg = f"MCP server timed out after {MCP_TIMEOUT}s while executing '{tool_name}'"
            logger.error(err_msg)
            return {
                "success": False,
                "tool_name": tool_name,
                "arguments": args,
                "result": f"Error: {err_msg}",
                "error": err_msg
            }
        except Exception as e:
            err_msg = f"MCP tool execution failed for '{tool_name}': {str(e)}"
            logger.error(err_msg)
            return {
                "success": False,
                "tool_name": tool_name,
                "arguments": args,
                "result": f"Error: {err_msg}",
                "error": err_msg
            }

    async def check_health(self) -> Dict[str, Any]:
        """Checks if the MCP server process can be initialized and lists tools."""
        try:
            tools = await self.list_tools()
            return {
                "status": "healthy" if tools else "degraded",
                "tool_count": len(tools),
                "tools": [t["name"] for t in tools]
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "tool_count": 0,
                "tools": []
            }


# Singleton instance for application usage
mcp_client = MCPClientManager()
