"""Connect the ps5 MCP server to an agent app, using this checkout's paths.

    python tools\\connect_agents.py json      # print an mcpServers config block (Claude Desktop, Cursor, others)
    python tools\\connect_agents.py claude    # print the Claude Code command (add --apply to run it)
    python tools\\connect_agents.py dsh       # write a DeepSeek Harness bundle to dsh-bundle\\

Run it with the project's venv Python so the generated config points at it.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = Path(sys.executable)
SERVER = ROOT / "mcp_server.py"

ICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <path d="M18 20h28c7 0 12 6 13 14l2 12c1 5-5 8-9 4l-6-6H18l-6 6c-4 4-10 1-9-4l2-12c1-8 6-14 13-14z" fill="#2f6bff"/>
  <path d="M19 27v10m-5-5h10" stroke="#fff" stroke-width="3.5" stroke-linecap="round"/>
  <circle cx="45" cy="28" r="2.6" fill="#44d6b2"/>
  <circle cx="51" cy="33" r="2.6" fill="#ff6f7d"/>
  <circle cx="39" cy="33" r="2.6" fill="#e58bd8"/>
  <circle cx="45" cy="38" r="2.6" fill="#7aa7ff"/>
</svg>
"""


def do_json() -> None:
    print(json.dumps({"mcpServers": {"ps5": {"command": str(PY), "args": [str(SERVER)]}}}, indent=2))


def do_claude(apply: bool) -> None:
    cmd = ["claude", "mcp", "add", "-s", "user", "ps5", "--", str(PY), str(SERVER)]
    print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
    if apply:
        exe = shutil.which("claude")
        if not exe:
            sys.exit("The claude command is not on PATH. Install Claude Code first.")
        subprocess.run([exe, *cmd[1:]], check=True)


def do_dsh() -> None:
    out = ROOT / "dsh-bundle"
    (out / "locale").mkdir(parents=True, exist_ok=True)
    (out / "package.json").write_text(json.dumps({
        "name": "@local/ps5-remote-mcp",
        "version": "1.0.0",
        "private": True,
        "type": "module",
        "exports": {"./locale/*.json": "./locale/*.json", "./icon": "./icon.svg"},
        "files": ["cordis.patch.yml", "locale/*.json", "icon.svg"],
        "dsh": {"bundle": {"patch": "./cordis.patch.yml"}},
    }, indent=2) + "\n", encoding="utf-8")
    (out / "cordis.patch.yml").write_text(
        "- insert:\n"
        "    - id: ps5-remote-mcp\n"
        "      name: '@deepseek-ai/dsh-mcp-client'\n"
        "      config:\n"
        "        serverName: ps5\n"
        "        transport: stdio\n"
        f"        command: {PY}\n"
        "        args:\n"
        f"          - {SERVER}\n"
        f"        cwd: {ROOT}\n"
        "        failOnStartupError: true\n",
        encoding="utf-8",
    )
    (out / "locale" / "en.json").write_text(json.dumps({"meta": {
        "title": "PS5 Remote",
        "description": "Lets the agent see the PS5 screen, press controller buttons, type, and search the PlayStation library and store.",
    }}, indent=2) + "\n", encoding="utf-8")
    (out / "icon.svg").write_text(ICON, encoding="utf-8")
    print(f"Wrote {out}")
    print("In DeepSeek Harness, ask the agent: install the plugin bundle at this folder (plugin_manager install_bundle).")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", choices=["json", "claude", "dsh"])
    ap.add_argument("--apply", action="store_true", help="for claude: run the command")
    a = ap.parse_args()
    if a.target == "json":
        do_json()
    elif a.target == "claude":
        do_claude(a.apply)
    else:
        do_dsh()


if __name__ == "__main__":
    main()
