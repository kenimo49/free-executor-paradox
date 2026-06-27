"""Tool definitions + executors for the agent loop.

Two tools:
  - str_replace_editor: view / create / str_replace / insert (Anthropic-style file editor)
  - bash:               run a shell command in the repo cwd

All paths are resolved relative to a fixed repo_root passed to ToolExecutor.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

TOOL_SCHEMAS = [
    {
        "name": "str_replace_editor",
        "description": (
            "Edit files. Commands: 'view' (cat with line numbers), 'create' (new file), "
            "'str_replace' (exact string replacement), 'insert' (insert at line). "
            "All paths must be repo-relative."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "enum": ["view", "create", "str_replace", "insert"],
                },
                "path": {"type": "string", "description": "repo-relative path"},
                "file_text": {"type": "string", "description": "for 'create'"},
                "old_str": {"type": "string", "description": "for 'str_replace'"},
                "new_str": {"type": "string", "description": "for 'str_replace'"},
                "insert_line": {"type": "integer", "description": "for 'insert' (0 = top)"},
                "view_range": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "for 'view', e.g. [1, 50]",
                },
            },
            "required": ["command", "path"],
        },
    },
    {
        "name": "bash",
        "description": (
            "Run a shell command in the repo root. Timeout 120s. "
            "Use for: ls, grep, running harness.sh, running tests, etc. "
            "Avoid network commands."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string"},
            },
            "required": ["cmd"],
        },
    },
]


@dataclass
class ToolExecutor:
    repo_root: Path
    bash_timeout: int = 120
    max_output_chars: int = 8000

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        """Returns (output, is_error)."""
        try:
            if name == "str_replace_editor":
                return self._editor(args)
            if name == "bash":
                return self._bash(args)
            return (f"unknown tool: {name}", True)
        except Exception as e:
            return (f"tool exception: {type(e).__name__}: {e}", True)

    def _truncate(self, s: str) -> str:
        if len(s) <= self.max_output_chars:
            return s
        keep = self.max_output_chars // 2 - 100
        return s[:keep] + f"\n\n[... {len(s) - 2*keep} chars truncated ...]\n\n" + s[-keep:]

    def _resolve(self, path: str) -> Path:
        p = (self.repo_root / path).resolve()
        if self.repo_root.resolve() not in p.parents and p != self.repo_root.resolve():
            raise ValueError(f"path escapes repo_root: {path}")
        return p

    def _editor(self, args: dict) -> tuple[str, bool]:
        cmd = args["command"]
        p = self._resolve(args["path"])
        if cmd == "view":
            if not p.exists():
                return (f"file not found: {args['path']}", True)
            if p.is_dir():
                listing = "\n".join(sorted(x.name for x in p.iterdir()))
                return (self._truncate(f"directory {args['path']}:\n{listing}"), False)
            text = p.read_text()
            lines = text.splitlines()
            vr = args.get("view_range")
            if vr:
                lo, hi = vr[0], vr[1] if vr[1] != -1 else len(lines)
                lines = lines[lo - 1 : hi]
                offset = lo
            else:
                offset = 1
            numbered = "\n".join(f"{i+offset:5d}  {l}" for i, l in enumerate(lines))
            return (self._truncate(numbered), False)
        if cmd == "create":
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args.get("file_text", ""))
            return (f"created {args['path']} ({len(args.get('file_text', ''))} chars)", False)
        if cmd == "str_replace":
            if not p.exists():
                return (f"file not found: {args['path']}", True)
            text = p.read_text()
            old = args["old_str"]
            new = args["new_str"]
            count = text.count(old)
            if count == 0:
                return (f"old_str not found in {args['path']}", True)
            if count > 1:
                return (
                    f"old_str matches {count} times in {args['path']}; make it unique",
                    True,
                )
            p.write_text(text.replace(old, new, 1))
            return (f"replaced 1 occurrence in {args['path']}", False)
        if cmd == "insert":
            if not p.exists():
                return (f"file not found: {args['path']}", True)
            lines = p.read_text().splitlines(keepends=True)
            n = args.get("insert_line", 0)
            new = args.get("new_str", args.get("file_text", ""))
            if not new.endswith("\n"):
                new += "\n"
            lines.insert(n, new)
            p.write_text("".join(lines))
            return (f"inserted at line {n} in {args['path']}", False)
        return (f"unknown editor command: {cmd}", True)

    def _bash(self, args: dict) -> tuple[str, bool]:
        cmd = args["cmd"]
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=self.bash_timeout,
        )
        out = ""
        if proc.stdout:
            out += proc.stdout
        if proc.stderr:
            out += ("\n--- stderr ---\n" if out else "") + proc.stderr
        out += f"\n[exit={proc.returncode}]"
        return (self._truncate(out), proc.returncode != 0)
