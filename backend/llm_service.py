"""
LLM Service Module
Orchestrates conversations with external LLM providers (Google Gemini and OpenAI)
and bridges tool calls with the local MCP Client.
"""

import os
import json
import logging
import re
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

from backend.mcp_client import mcp_client

# Reload env to pick up any changes
load_dotenv()

logger = logging.getLogger("llm_service")
logger.setLevel(logging.INFO)

SYSTEM_INSTRUCTION = (
    "You are a helpful, intelligent assistant equipped with Model Context Protocol (MCP) external tools. "
    "When a user asks a question that requires real-time information (e.g. current time, local database records, "
    "reading files, or performing precise math calculations), always call the appropriate MCP tool to fetch context "
    "before formulating your response. Ground your answers accurately using the tool outputs."
)


def _convert_mcp_to_openai_tools(mcp_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Converts MCP tool definitions to OpenAI tool format."""
    openai_tools = []
    for tool in mcp_tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}})
            }
        })
    return openai_tools


def _convert_mcp_to_gemini_declarations(mcp_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Converts MCP tool definitions to Gemini function declarations."""
    declarations = []
    for tool in mcp_tools:
        schema = tool.get("input_schema", {})
        # Ensure schema structure conforms to OpenAPI/Gemini standard
        clean_schema = {
            "type": "OBJECT",
            "properties": schema.get("properties", {}),
            "required": schema.get("required", [])
        }
        declarations.append({
            "name": tool["name"],
            "description": tool["description"],
            "parameters": clean_schema
        })
    return declarations


class LLMService:
    """Manages LLM generation and tool-calling execution loops."""

    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "gemini").lower().strip()
        self.gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash").strip()
        self.openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
        self.openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()

    def reload_config(self):
        """Reload configuration from environment."""
        load_dotenv(override=True)
        self.provider = os.getenv("LLM_PROVIDER", "gemini").lower().strip()
        self.gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash").strip()
        self.openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
        self.openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()

    async def generate_response(
        self,
        user_message: str,
        chat_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Main entry point for generating chat responses with MCP tool execution.
        Returns a dict containing the final reply, tool executions, and provider info.
        """
        self.reload_config()
        history = chat_history or []

        # Determine effective provider
        effective_provider = self.provider
        if effective_provider == "gemini" and not self.gemini_key:
            if self.openai_key:
                effective_provider = "openai"
            else:
                effective_provider = "mock"
        elif effective_provider == "openai" and not self.openai_key:
            if self.gemini_key:
                effective_provider = "gemini"
            else:
                effective_provider = "mock"

        # Fetch available MCP tools
        mcp_tools = await mcp_client.list_tools()

        executed_tools: List[Dict[str, Any]] = []

        try:
            if effective_provider == "gemini":
                return await self._generate_gemini(user_message, history, mcp_tools, executed_tools)
            elif effective_provider == "openai":
                return await self._generate_openai(user_message, history, mcp_tools, executed_tools)
            else:
                return await self._generate_mock_agent(user_message, history, mcp_tools, executed_tools)
        except Exception as e:
            logger.error(f"Error during LLM generation ({effective_provider}): {e}", exc_info=True)
            # Fallback to mock agent with note if external provider failed
            fallback_res = await self._generate_mock_agent(user_message, history, mcp_tools, executed_tools)
            fallback_res["reply"] = (
                f"> **Notice**: External LLM call ({effective_provider}) encountered an issue: `{str(e)}`. "
                f"Falling back to local tool-calling processor.\n\n"
                + fallback_res["reply"]
            )
            return fallback_res

    async def _generate_openai(
        self,
        user_message: str,
        history: List[Dict[str, str]],
        mcp_tools: List[Dict[str, Any]],
        executed_tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Handles OpenAI chat completion with MCP tool calls."""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.openai_key, base_url=self.openai_base_url)
        openai_tools = _convert_mcp_to_openai_tools(mcp_tools) if mcp_tools else None

        messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_INSTRUCTION}]
        for msg in history[-10:]:  # Keep recent history
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
        messages.append({"role": "user", "content": user_message})

        kwargs: Dict[str, Any] = {
            "model": self.openai_model,
            "messages": messages,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools
            kwargs["tool_choice"] = "auto"

        response = await client.chat.completions.create(**kwargs)
        response_msg = response.choices[0].message

        # Check if the model decided to call tools
        if response_msg.tool_calls:
            # Append assistant's tool-call request to message history
            messages.append(response_msg)

            for tool_call in response_msg.tool_calls:
                func_name = tool_call.function.name
                try:
                    func_args = json.loads(tool_call.function.arguments or "{}")
                except Exception:
                    func_args = {}

                # Execute through MCP Client
                tool_res = await mcp_client.call_tool(func_name, func_args)
                executed_tools.append(tool_res)

                # Append tool result to context for final synthesis
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": func_name,
                    "content": tool_res.get("result", "")
                })

            # Call OpenAI again with the tool output to generate grounded natural language response
            final_res = await client.chat.completions.create(
                model=self.openai_model,
                messages=messages
            )
            final_text = final_res.choices[0].message.content or ""
            return {
                "reply": final_text,
                "tool_calls": executed_tools,
                "provider": f"openai ({self.openai_model})"
            }

        return {
            "reply": response_msg.content or "",
            "tool_calls": executed_tools,
            "provider": f"openai ({self.openai_model})"
        }

    async def _generate_gemini(
        self,
        user_message: str,
        history: List[Dict[str, str]],
        mcp_tools: List[Dict[str, Any]],
        executed_tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Handles Google Gemini chat generation with MCP function calling."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.gemini_key)

        # Build contents from history
        contents = []
        for msg in history[-10:]:
            role = "user" if msg.get("role") == "user" else "model"
            contents.append(types.Content(
                role=role,
                parts=[types.Part.from_text(text=msg.get("content", ""))]
            ))
        contents.append(types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_message)]
        ))

        # Build tool declarations if MCP tools exist
        config_tools = []
        if mcp_tools:
            # Map tools into function declarations
            func_decls = []
            for t in mcp_tools:
                func_decls.append(types.FunctionDeclaration(
                    name=t["name"],
                    description=t["description"],
                    parameters=t.get("input_schema")
                ))
            config_tools.append(types.Tool(function_declarations=func_decls))

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            tools=config_tools if config_tools else None,
            temperature=0.7,
        )

        response = client.models.generate_content(
            model=self.gemini_model,
            contents=contents,
            config=config
        )

        # Check for function calls in candidates
        function_calls = []
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    function_calls.append(part.function_call)

        if function_calls:
            # Append model turn with function calls
            contents.append(response.candidates[0].content)

            tool_response_parts = []
            for call in function_calls:
                func_name = call.name
                func_args = dict(call.args) if call.args else {}

                # Execute via MCP Client
                tool_res = await mcp_client.call_tool(func_name, func_args)
                executed_tools.append(tool_res)

                # Format function response part for Gemini
                tool_response_parts.append(
                    types.Part.from_function_response(
                        name=func_name,
                        response={"result": tool_res.get("result", "")}
                    )
                )

            # Send function responses back to Gemini
            contents.append(types.Content(role="user", parts=tool_response_parts))

            final_response = client.models.generate_content(
                model=self.gemini_model,
                contents=contents,
                config=config
            )
            return {
                "reply": final_response.text or "Completed tool execution.",
                "tool_calls": executed_tools,
                "provider": f"gemini ({self.gemini_model})"
            }

        return {
            "reply": response.text or "",
            "tool_calls": executed_tools,
            "provider": f"gemini ({self.gemini_model})"
        }

    async def _generate_mock_agent(
        self,
        user_message: str,
        history: List[Dict[str, str]],
        mcp_tools: List[Dict[str, Any]],
        executed_tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Intelligent local agentic engine that executes real MCP tools and synthesizes responses
        when external API keys are not configured.
        """
        lower_msg = user_message.lower().strip()

        # 1. Intent: Time / Date
        if any(w in lower_msg for w in ["time", "date", "clock", "today", "day", "current time", "what time"]):
            tool_res = await mcp_client.call_tool("get_current_time", {"timezone": "Local/UTC"})
            executed_tools.append(tool_res)
            return {
                "reply": (
                    f"According to the MCP Time Service tool:\n\n"
                    f"```text\n{tool_res.get('result')}\n```\n\n"
                    f"The current system time has been retrieved live via the Model Context Protocol."
                ),
                "tool_calls": executed_tools,
                "provider": "agentic-mcp-engine (local)"
            }

        # 2. Intent: Database Query (Products / System Status)
        if any(w in lower_msg for w in ["product", "stock", "catalog", "inventory", "price", "status", "system status", "service", "database", "sqlite"]):
            if "status" in lower_msg or "system" in lower_msg or "service" in lower_msg:
                table = "system_status"
                search = ""
            else:
                table = "products"
                # Extract potential search term
                search = ""
                for word in ["quantum", "neural", "vectordb", "fastapi", "cable", "sensor"]:
                    if word in lower_msg:
                        search = word
                        break
            
            tool_res = await mcp_client.call_tool("query_database", {"table": table, "search": search})
            executed_tools.append(tool_res)
            return {
                "reply": (
                    f"I queried the local SQLite database via the MCP Database Tool. Here are the retrieved records:\n\n"
                    f"{tool_res.get('result')}\n\n"
                    f"Let me know if you would like me to filter or inspect specific records further!"
                ),
                "tool_calls": executed_tools,
                "provider": "agentic-mcp-engine (local)"
            }

        # 3. Intent: Math Calculation
        # Check if the query contains math patterns (e.g. 15 * 8, 25 + 50, calculate ...)
        math_match = re.search(r"(\d+[\s\+\-\*\/\^\%]+[\d\s\+\-\*\/\^\%\(\)\.]+)", lower_msg)
        if ("calculate" in lower_msg or "compute" in lower_msg or "what is" in lower_msg or "math" in lower_msg) and math_match:
            expr = math_match.group(1).strip()
            tool_res = await mcp_client.call_tool("calculate_math", {"expression": expr})
            executed_tools.append(tool_res)
            return {
                "reply": (
                    f"I computed your mathematical expression using the MCP Math Calculator:\n\n"
                    f"**{tool_res.get('result')}**\n\n"
                    f"Computation executed securely and verified."
                ),
                "tool_calls": executed_tools,
                "provider": "agentic-mcp-engine (local)"
            }

        # 4. Intent: File Reading
        if any(w in lower_msg for w in ["read file", "read readme", "read note", "show readme", "show file", "file content"]):
            file_path = "README.md"
            if "requirements" in lower_msg:
                file_path = "backend/requirements.txt"
            elif "main.py" in lower_msg:
                file_path = "backend/main.py"

            tool_res = await mcp_client.call_tool("read_local_file", {"file_path": file_path})
            executed_tools.append(tool_res)
            return {
                "reply": (
                    f"I read `{file_path}` using the MCP File Reader tool. Here is the file content:\n\n"
                    f"```text\n{tool_res.get('result')[:1500]}\n```"
                ),
                "tool_calls": executed_tools,
                "provider": "agentic-mcp-engine (local)"
            }

        # 5. General response / guidance
        tools_list = ", ".join([f"`{t['name']}`" for t in mcp_tools]) if mcp_tools else "none"
        return {
            "reply": (
                f"Hello! I am your AI Assistant powered by FastAPI and the Model Context Protocol (MCP).\n\n"
                f"Currently connected MCP tools: {tools_list}\n\n"
                f"You can ask me to:\n"
                f"- **Check the time**: *'What is the current time?'*\n"
                f"- **Query the database**: *'Show me all products in the database'* or *'Check system status'*\n"
                f"- **Calculate math**: *'Calculate 250 * 1.18 + 45'*\n"
                f"- **Read project files**: *'Read the README.md file'*\n\n"
                f"> **Tip**: To enable external LLMs like Google Gemini or OpenAI, add your `GEMINI_API_KEY` or `OPENAI_API_KEY` to `backend/.env`."
            ),
            "tool_calls": executed_tools,
            "provider": "agentic-mcp-engine (local)"
        }


# Singleton LLM Service instance
llm_service = LLMService()
