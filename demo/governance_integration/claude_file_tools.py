"""Claude Agent SDK向けの自作ファイルTool。

Claude Agent SDKではPython関数をインプロセスMCP Serverとして公開する。
このFactoryを使うことで、OpenAI版と同じread/write/delete ToolをClaudeへ渡せる。
"""

from __future__ import annotations

from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

from common import safe_file


SERVER_NAME = "files"
READ_TOOL = f"mcp__{SERVER_NAME}__read_file"
WRITE_TOOL = f"mcp__{SERVER_NAME}__write_file"
DELETE_TOOL = f"mcp__{SERVER_NAME}__delete_file"
TOOL_NAMES = [READ_TOOL, WRITE_TOOL, DELETE_TOOL]


def build_file_server(workspace: Path):
    """指定Workspaceだけを操作できる3つのMCP Toolを生成する。"""

    @tool("read_file", "UTF-8ファイルを読み込む", {"filename": str})
    async def read_file(args: dict) -> dict:
        """ファイル内容をMCPのtext contentとして返す。"""
        filename = str(args["filename"])
        content = safe_file(workspace, filename).read_text(encoding="utf-8")
        return {"content": [{"type": "text", "text": content}]}

    @tool(
        "write_file",
        "UTF-8ファイルを上書きする",
        {"filename": str, "content": str},
    )
    async def write_file(args: dict) -> dict:
        """指定された内容でファイルを上書きする。"""
        filename = str(args["filename"])
        safe_file(workspace, filename).write_text(str(args["content"]), encoding="utf-8")
        return {"content": [{"type": "text", "text": f"wrote {filename}"}]}

    @tool("delete_file", "ファイルを削除する", {"filename": str})
    async def delete_file(args: dict) -> dict:
        """指定されたファイルを削除する。"""
        filename = str(args["filename"])
        safe_file(workspace, filename).unlink()
        return {"content": [{"type": "text", "text": f"deleted {filename}"}]}

    return create_sdk_mcp_server(
        name=SERVER_NAME,
        version="1.0.0",
        tools=[read_file, write_file, delete_file],
    )

