import asyncio
import json

import requests

from eam_qea_tool import Tools as QEATools


# Config
BASE_URL = "" # URL of the OpenWebUI instance, e.g. "http://localhost:3000"
TOKEN = "" # Your OpenWebUI API token
MODEL = "" # Model name (can check using get_model_list() function)
QEA_PATH = "" # Path to your QEA file for local tool calls
SYSTEM_PROMPT = "You can call local QEA tools when needed."
MAX_TOOL_ROUNDS = 8
RAG_FILES = [""] # Name of files to use for RAG
FILES_MAX_PAGES = 5


TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "list_available_qea_files",
            "description": "List all QEA files found in the configured search directories (newest first).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_qea_statistics",
            "description": "Get model statistics from QEA: element/package/connector counts, element types and stereotypes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "qea_path": {"type": "string", "description": "Optional path to the .qea file; auto-discovers the most recently modified file when omitted."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_elements_in_qea",
            "description": "Find elements by name, type, stereotype, or package. All filters optional.",
            "parameters": {
                "type": "object",
                "properties": {
                    "qea_path": {"type": "string"},
                    "name": {"type": "string"},
                    "object_type": {"type": "string"},
                    "stereotype": {"type": "string"},
                    "package_id": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_element_detail_from_qea",
            "description": "Get full detail for one element by Object_ID: attributes, operations, relationships, tagged values, diagrams.",
            "parameters": {
                "type": "object",
                "properties": {
                    "qea_path": {"type": "string"},
                    "element_id": {"type": "integer"},
                },
                "required": ["element_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_relationships_from_qea",
            "description": "Get relationships/connectors, optionally filtered by element, type, or stereotype.",
            "parameters": {
                "type": "object",
                "properties": {
                    "qea_path": {"type": "string"},
                    "element_id": {"type": "integer"},
                    "connector_type": {"type": "string"},
                    "stereotype": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_qea_elements",
            "description": "Full-text search across element names and notes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "qea_path": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_package_tree_from_qea",
            "description": "Get the complete package/folder hierarchy tree.",
            "parameters": {
                "type": "object",
                "properties": {
                    "qea_path": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_elements_by_tagged_value",
            "description": "Find elements by tagged value name and/or value. Essential for NAF metadata.",
            "parameters": {
                "type": "object",
                "properties": {
                    "qea_path": {"type": "string"},
                    "tag_name": {"type": "string"},
                    "tag_value": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_qea_diagrams",
            "description": "List all diagrams with their element counts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "qea_path": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_naf_view_elements_from_qea",
            "description": "Get elements belonging to a NAF view (NAF-2 through NAF-7).",
            "parameters": {
                "type": "object",
                "properties": {
                    "qea_path": {"type": "string"},
                    "view_type": {"type": "string", "enum": ["NAF-2", "NAF-3", "NAF-4", "NAF-5", "NAF-6", "NAF-7"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_process_packages_and_activities",
            "description": "Discover packages and Activity elements for process extraction. Call before extracting graphs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "qea_path": {"type": "string"},
                    "package_path": {"type": "string"},
                    "include_subpackages": {"type": "boolean"},
                    "include_empty_packages": {"type": "boolean"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_extracted_activity_graphs",
            "description": "Get compact summaries of all extractable process graphs from Activity diagrams.",
            "parameters": {
                "type": "object",
                "properties": {
                    "qea_path": {"type": "string"},
                    "package_path": {"type": "string"},
                    "include_subpackages": {"type": "boolean"},
                    "max_items": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_activity_diagram_process_graph",
            "description": "Extract a detailed BPMN-like process graph for one Activity diagram. Requires activity_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "qea_path": {"type": "string"},
                    "activity_id": {"type": "integer"},
                    "package_path": {"type": "string"},
                    "include_subpackages": {"type": "boolean"},
                    "max_nodes": {"type": "integer"},
                    "max_edges": {"type": "integer"},
                },
                "required": ["activity_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_qea_sql",
            "description": "Execute a read-only SQL query against the QEA database. Only SELECT allowed; result is always capped.",
            "parameters": {
                "type": "object",
                "properties": {
                    "qea_path": {"type": "string"},
                    "sql": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_qea_table_schema",
            "description": "Inspect database schema: list all tables, or get columns for a specific table.",
            "parameters": {
                "type": "object",
                "properties": {
                    "qea_path": {"type": "string"},
                    "table_name": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_qea_element_report",
            "description": "Generate a comprehensive report for a named element: details, relationships, tagged values, diagrams.",
            "parameters": {
                "type": "object",
                "properties": {
                    "qea_path": {"type": "string"},
                    "element_name": {"type": "string"},
                },
                "required": ["element_name"],
            },
        },
    },
]


def chat_with_model(token, data):
    url = f"{BASE_URL}/api/chat/completions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    response = requests.post(url, headers=headers, json=data, timeout=300)
    try:
        response.raise_for_status()
    except requests.HTTPError as e:
        raise requests.HTTPError(f"{e} | body={response.text}") from e
    return response.json()

def get_files(token, page=1):
    url = f"{BASE_URL}/api/v1/files/"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"

    }
    params={"content": False, "page": page}
    response = requests.get(url, headers=headers, params=params)
    return response.json()

def get_model_list(token):
    url = f"{BASE_URL}/api/models"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    response = requests.get(url, headers=headers)
    return response.json()


def _resolve_model_id(token, configured_model):
    models = (get_model_list(token) or {}).get("data") or []
    if not models:
        return configured_model
    ids = [m.get("id") for m in models if m.get("id")]
    cfg = (configured_model or "").strip()
    if cfg in ids:
        return cfg
    cfg_l = cfg.lower()
    for mid in ids:
        if str(mid).lower() == cfg_l:
            return mid
    for m in models:
        if str(m.get("name", "")).lower() == cfg_l and m.get("id"):
            return m["id"]
    return ids[0]


def _get_tool_calls(msg):
    tool_calls = msg.get("tool_calls") or []
    fc = msg.get("function_call")
    if fc and not tool_calls:
        return [{"type": "function", "function": fc}], True
    return tool_calls, False


def _resolve_payload_files(token, wanted_names):
    wanted = {str(n).strip().lower() for n in (wanted_names or []) if str(n).strip()}
    if not wanted:
        return []

    matched = {}
    for page in range(1, max(1, int(FILES_MAX_PAGES)) + 1):
        data = get_files(token, page=page)

        rows = data.get("items") or []

        if not rows:
            break
        for row in rows:
            fid = row.get("id")
            name = row.get("name") or row.get("filename") or ""
            key = str(name).strip().lower()

            if fid and key in wanted:
                matched[key] = {"type": "file", "id": fid}
        if len(matched) == len(wanted):
            break

    missing = sorted(wanted - set(matched.keys()))
    if missing:
        print("Missing Open WebUI files:", ", ".join(missing))
    return list(matched.values())


async def _run_local_tool(tools_obj, name, args):
    fn = getattr(tools_obj, name, None)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    args = args or {}
    if "qea_path" in fn.__code__.co_varnames and not args.get("qea_path"):
        args["qea_path"] = QEA_PATH
    try:
        return await fn(**args)
    except Exception as e:
        return json.dumps({"error": str(e), "tool": name, "args": args})


def run_tool_chat_loop(token):
    tools_obj = QEATools()
    model_id = _resolve_model_id(token, MODEL)
    payload_files = _resolve_payload_files(token, RAG_FILES)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    print("Type 'exit' to quit.")

    while True:
        user_text = input("You> ").strip()
        if user_text.lower() in {"exit", "quit"}:
            break
        if not user_text:
            continue

        messages.append({"role": "user", "content": user_text})

        for _ in range(MAX_TOOL_ROUNDS):
            payload = {
                "model": model_id,
                "messages": messages,
                "tools": TOOL_DEFS,
            }
            if payload_files:
                payload["files"] = payload_files
            out = chat_with_model(token, payload)
            msg = ((out.get("choices") or [{}])[0]).get("message") or {}
            assistant_msg = {
                "role": "assistant",
                "content": msg.get("content") or "",
            }
            if msg.get("tool_calls"):
                assistant_msg["tool_calls"] = msg["tool_calls"]
            if msg.get("function_call"):
                assistant_msg["function_call"] = msg["function_call"]
            messages.append(assistant_msg)

            tool_calls, is_legacy_fc = _get_tool_calls(msg)
            if not tool_calls:
                print("Assistant>", msg.get("content", ""))
                break

            for call in tool_calls:
                fn = (call.get("function") or {}).get("name")
                raw_args = (call.get("function") or {}).get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    args = {}

                result = asyncio.run(_run_local_tool(tools_obj, fn, args))
                print(f"Tool> {fn}({args})")

                if is_legacy_fc:
                    tool_msg = {
                        "role": "function",
                        "name": fn,
                        "content": result,
                    }
                else:
                    tool_msg = {
                        "role": "tool",
                        "name": fn,
                        "content": result,
                    }
                    if call.get("id"):
                        tool_msg["tool_call_id"] = call["id"]
                messages.append(tool_msg)
        else:
            print("Assistant> Stopped after MAX_TOOL_ROUNDS without final answer.")

if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("Set TOKEN at the top of this script.")
    run_tool_chat_loop(TOKEN)