"""
MCP Server providing utility and data-access tools for the LLM.
Implements Model Context Protocol (MCP) using the official MCP Python SDK.
"""

import sys
import os
import sqlite3
import datetime
import ast
import operator
from pathlib import Path
from mcp.server.mcpserver import MCPServer

# Initialize MCP Server instance
server = MCPServer("modular-mcp-server")

# Path to local SQLite database
DB_PATH = Path(__file__).parent / "context_database.sqlite"


def init_sample_database():
    """Initializes a local sample SQLite database with demo tables."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create products table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER NOT NULL
        )
    """)
    
    # Create system_status table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_name TEXT NOT NULL,
            status TEXT NOT NULL,
            uptime_pct REAL NOT NULL,
            last_checked TEXT NOT NULL
        )
    """)

    # Seed data if empty
    cursor.execute("SELECT COUNT(*) FROM products")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("""
            INSERT INTO products (name, category, price, stock) VALUES (?, ?, ?, ?)
        """, [
            ("Quantum Processor X1", "Hardware", 899.99, 14),
            ("Neural Edge Accelerator", "Hardware", 449.50, 28),
            ("VectorDB Enterprise License", "Software", 1200.00, 100),
            ("FastAPI Agent Starter Kit", "Software", 49.99, 500),
            ("Cybernetic Sensor Hub", "IoT", 185.00, 42),
            ("High-Bandwidth Interconnect Cable", "Accessories", 29.95, 250)
        ])

    cursor.execute("SELECT COUNT(*) FROM system_status")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("""
            INSERT INTO system_status (service_name, status, uptime_pct, last_checked) VALUES (?, ?, ?, ?)
        """, [
            ("API Gateway", "Operational", 99.98, "2026-08-26 00:00:00"),
            ("FastAPI Backend", "Operational", 99.99, "2026-08-26 00:00:00"),
            ("MCP Stdio Daemon", "Operational", 100.0, "2026-08-26 00:00:00"),
            ("Vector Database Engine", "Operational", 99.95, "2026-08-26 00:00:00")
        ])
    
    conn.commit()
    conn.close()


# Initialize database on module import
init_sample_database()


@server.tool(
    name="get_current_time",
    description="Retrieves the current date, time, day of the week, and timezone information."
)
def get_current_time(timezone: str = "UTC") -> str:
    """Returns current timestamp and system date."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return (
        f"Current UTC Time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"Day of Week: {now.strftime('%A')}\n"
        f"Requested Timezone: {timezone}"
    )


@server.tool(
    name="read_local_file",
    description="Reads the contents of a local project text/markdown file to provide relevant context."
)
def read_local_file(file_path: str) -> str:
    """Safely reads a local file within the project directory."""
    try:
        # Base allowed directory is the project root (parent of backend)
        base_dir = Path(__file__).parent.parent.resolve()
        target_file = (base_dir / file_path).resolve()

        # Prevent directory traversal outside project root
        if not str(target_file).startswith(str(base_dir)):
            return f"Error: Access denied. Cannot read files outside project root: {file_path}"

        if not target_file.exists():
            return f"Error: File not found: {file_path}"

        if target_file.is_dir():
            return f"Error: Target path is a directory, not a file: {file_path}"

        # Limit max file read size to 100KB for safety
        content = target_file.read_text(encoding="utf-8", errors="replace")
        if len(content) > 100000:
            content = content[:100000] + "\n... [Content truncated at 100KB]"
        return content
    except Exception as e:
        return f"Error reading file '{file_path}': {str(e)}"


@server.tool(
    name="query_database",
    description="Queries the local SQLite database for context on products, stock, pricing, or system status."
)
def query_database(table: str = "products", search: str = "") -> str:
    """Queries product catalog or system status from SQLite."""
    try:
        table_clean = table.strip().lower()
        if table_clean not in ["products", "system_status"]:
            return f"Error: Table '{table}' not supported. Allowed tables: 'products', 'system_status'"

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if table_clean == "products":
            if search:
                cursor.execute(
                    "SELECT id, name, category, price, stock FROM products WHERE name LIKE ? OR category LIKE ?",
                    (f"%{search}%", f"%{search}%")
                )
            else:
                cursor.execute("SELECT id, name, category, price, stock FROM products LIMIT 20")
            
            rows = cursor.fetchall()
            conn.close()
            if not rows:
                return f"No products found matching query '{search}'."
            
            result = ["Products Catalog:"]
            for r in rows:
                result.append(f"- ID {r['id']}: {r['name']} | Category: {r['category']} | Price: ${r['price']:.2f} | Stock: {r['stock']} units")
            return "\n".join(result)

        elif table_clean == "system_status":
            cursor.execute("SELECT service_name, status, uptime_pct, last_checked FROM system_status")
            rows = cursor.fetchall()
            conn.close()
            result = ["System Status:"]
            for r in rows:
                result.append(f"- {r['service_name']}: Status={r['status']}, Uptime={r['uptime_pct']}%, Last Checked={r['last_checked']}")
            return "\n".join(result)

    except Exception as e:
        return f"Database query error: {str(e)}"


# Safe mathematical evaluation using AST
SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_expr(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    elif isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in SAFE_OPERATORS:
            raise ValueError(f"Unsupported operator: {op_type.__name__}")
        left = _eval_expr(node.left)
        right = _eval_expr(node.right)
        return SAFE_OPERATORS[op_type](left, right)
    elif isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in SAFE_OPERATORS:
            raise ValueError(f"Unsupported operator: {op_type.__name__}")
        operand = _eval_expr(node.operand)
        return SAFE_OPERATORS[op_type](operand)
    else:
        raise ValueError("Invalid mathematical expression syntax")


@server.tool(
    name="calculate_math",
    description="Safely computes mathematical expressions (e.g. arithmetic, percentages, powers)."
)
def calculate_math(expression: str) -> str:
    """Evaluates mathematical expression safely."""
    try:
        expr_clean = expression.strip().replace("^", "**")
        parsed = ast.parse(expr_clean, mode="eval")
        result = _eval_expr(parsed.body)
        return f"Result of `{expression}` = {result}"
    except Exception as e:
        return f"Calculation error for '{expression}': {str(e)}"


if __name__ == "__main__":
    # Run the server over stdio transport
    server.run("stdio")
