#!/usr/bin/env python3
"""Scoped stdio MCP client for the protected Linux broker, without shared state.

Configure the socket and expected broker UID in the protected launch artifact.
The broker derives sender/session/root from kernel credentials and its binding,
not these arguments, cwd, environment or a role the agent claims to represent.
"""
import argparse
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from relay_core.broker_wire import client_request
from relay_core.identity import Denied, MAX_FRAME, strict_json


TOOLS = [
    {"name": "whoami", "description": "Show the kernel-authenticated role and session binding.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "list_sessions", "description": "List registered peer sessions; registration is not readiness.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]


def run(socket_path, broker_uid, input_stream=sys.stdin, output_stream=sys.stdout, transport=client_request):
    while True:
        line = input_stream.readline(MAX_FRAME + 1)
        if not line:
            return
        if len(line) > MAX_FRAME or not line.endswith("\n"):
            raise Denied("oversized or incomplete MCP input; refusing truncated framing")
        request = strict_json(line)
        if type(request) is not dict:
            raise Denied("MCP request object required")
        rid = request.get("id")
        if rid is None:
            continue
        try:
            params = request.get("params") or {}
            if type(params) is not dict:
                raise Denied("MCP parameters must be an object")
            if request.get("method") == "initialize":
                result = {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                          "capabilities": {"tools": {}}, "serverInfo": {"name": "ccrelay-broker", "version": "0.2"}}
            elif request.get("method") == "ping":
                result = {}
            elif request.get("method") == "tools/list":
                result = {"tools": TOOLS}
            elif request.get("method") == "tools/call":
                name = params.get("name")
                if name not in {tool["name"] for tool in TOOLS}:
                    raise Denied("MCP operation not enabled yet")
                out = transport(socket_path, {"schema": "ccrelay.broker_request.v1", "request_id": uuid.uuid4().hex,
                                               "method": name, "args": params.get("arguments", {})}, broker_uid=broker_uid)
                result = {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                          "isError": out.get("ok") is False}
            else:
                raise Denied("unsupported MCP operation")
            response = {"jsonrpc": "2.0", "id": rid, "result": result}
        except (Denied, ValueError, OSError):
            response = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": "broker operation unavailable or denied"}}
        output_stream.write(json.dumps(response, ensure_ascii=False) + "\n")
        output_stream.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--broker-uid", type=int, required=True)
    args = parser.parse_args()
    if args.broker_uid <= 0:
        parser.error("a non-root protected broker UID is required")
    run(args.socket, args.broker_uid)


if __name__ == "__main__":
    main()
