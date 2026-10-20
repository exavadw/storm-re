import http.client
import json
import threading
import unittest
from unittest import mock

from support import ROOT  # noqa: F401

from storm_re import mcp_server


class ToolSchemaTests(unittest.TestCase):
    def test_tool_count(self):
        names = [t["name"] for t in mcp_server.TOOLS]
        self.assertEqual(len(names), 22)
        self.assertEqual(len(set(names)), 22)
        self.assertIn("storm_show", names)
        self.assertIn("storm_symbolize", names)
        self.assertIn("storm_state_surface", names)
        self.assertIn("storm_write_sites", names)
        self.assertIn("storm_input_path", names)
        self.assertIn("storm_frame_tick", names)
        self.assertIn("storm_net_session", names)
        self.assertIn("storm_scene_dispatch", names)
        self.assertIn("storm_patch_diff", names)
        self.assertIn("storm_export", names)
        self.assertIn("storm_explain", names)
        self.assertIn("storm_batch", names)
        for tool in mcp_server.TOOLS:
            self.assertTrue(tool["description"])
            self.assertEqual(tool["inputSchema"]["type"], "object")

    def test_initialize(self):
        resp = mcp_server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(resp["result"]["protocolVersion"], mcp_server.PROTOCOL)
        self.assertIn("tools", resp["result"]["capabilities"])
        self.assertIn("resources", resp["result"]["capabilities"])
        self.assertIn("prompts", resp["result"]["capabilities"])
        self.assertTrue(resp["result"]["instructions"])

    def test_protocol_negotiation(self):
        resp = mcp_server.handle_request({
            "jsonrpc": "2.0", "id": 9, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        })
        self.assertEqual(resp["result"]["protocolVersion"], "2024-11-05")

    def test_tool_annotations(self):
        for tool in mcp_server.TOOLS:
            self.assertIn("title", tool)
            self.assertIn("annotations", tool)
            self.assertIn("outputSchema", tool)
            if tool["name"] != "storm_export":
                self.assertTrue(tool["annotations"]["readOnlyHint"])
        export = next(t for t in mcp_server.TOOLS if t["name"] == "storm_export")
        self.assertFalse(export["annotations"]["readOnlyHint"])

    def test_resources_and_prompts(self):
        res = mcp_server.handle_request({"jsonrpc": "2.0", "id": 10, "method": "resources/list"})
        self.assertIn("storm-re://builds", [r["uri"] for r in res["result"]["resources"]])
        tpl = mcp_server.handle_request({"jsonrpc": "2.0", "id": 11, "method": "resources/templates/list"})
        self.assertTrue(tpl["result"]["resourceTemplates"])
        prompts = mcp_server.handle_request({"jsonrpc": "2.0", "id": 12, "method": "prompts/list"})
        self.assertEqual(len(prompts["result"]["prompts"]), 4)
        got = mcp_server.handle_request({
            "jsonrpc": "2.0", "id": 13, "method": "prompts/get",
            "params": {"name": "rollback_audit", "arguments": {"root": "ccPlayer"}},
        })
        self.assertIn("storm_state_surface", got["result"]["messages"][0]["content"]["text"])

    def test_tools_list(self):
        resp = mcp_server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(len(resp["result"]["tools"]), 22)

    def test_unknown_tool(self):
        resp = mcp_server.handle_request(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "nope"}}
        )
        self.assertEqual(resp["error"]["code"], -32601)

    def test_missing_argument(self):
        resp = mcp_server.handle_request(
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "storm_resolve", "arguments": {}}}
        )
        self.assertEqual(resp["error"]["code"], -32602)

    def test_notification_has_no_response(self):
        self.assertIsNone(
            mcp_server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )


class ArgvTests(unittest.TestCase):
    def test_resolve(self):
        argv = mcp_server.build_argv(
            "storm_resolve", {"target": "ccPlayer::ChangeAction", "build": "s4-debug"}, "db", "http://x"
        )
        self.assertEqual(argv[:4], ["resolve", "ccPlayer::ChangeAction", "-b", "s4-debug"])
        self.assertIn("--db", argv)
        self.assertIn("--mcp", argv)

    def test_decomp_options(self):
        argv = mcp_server.build_argv(
            "storm_decomp",
            {"target": "0x7ab468", "detail": "sig", "max_bytes": 100, "head": 3, "refresh": True},
            None, None,
        )
        self.assertIn("--detail", argv)
        self.assertIn("sig", argv)
        self.assertIn("--max-bytes", argv)
        self.assertIn("--refresh", argv)

    def test_diff_map(self):
        argv = mcp_server.build_argv(
            "storm_diff", {"target": "x", "from_build": "s4", "to_build": "s4-debug", "use_map": True},
            None, None,
        )
        self.assertIn("--map", argv)

    def test_export(self):
        argv = mcp_server.build_argv(
            "storm_export", {"topic": "input", "out": "-", "limit": 5}, None, None
        )
        self.assertEqual(argv[0], "export")
        self.assertIn("--out", argv)

    def test_patch_diff(self):
        argv = mcp_server.build_argv(
            "storm_patch_diff", {"from_build": "s4", "to_build": "s4-debug", "limit": 5},
            None, None,
        )
        self.assertEqual(argv[0], "patch_diff")
        self.assertIn("--from", argv)

    def test_scene_dispatch(self):
        argv = mcp_server.build_argv("storm_scene_dispatch", {"build": "s4", "limit": 5}, None, None)
        self.assertEqual(argv[0], "scene_dispatch")
        self.assertIn("--limit", argv)

    def test_net_session(self):
        argv = mcp_server.build_argv("storm_net_session", {"build": "s4", "limit": 5}, None, None)
        self.assertEqual(argv[0], "net_session")
        self.assertIn("--limit", argv)

    def test_frame_tick(self):
        argv = mcp_server.build_argv("storm_frame_tick", {"build": "s4", "limit": 5}, None, None)
        self.assertEqual(argv[0], "frame_tick")
        self.assertIn("--limit", argv)

    def test_input_path(self):
        argv = mcp_server.build_argv(
            "storm_input_path", {"build": "s4", "depth": 2, "limit": 10}, None, None
        )
        self.assertEqual(argv[0], "input_path")
        self.assertIn("--depth", argv)

    def test_write_sites(self):
        argv = mcp_server.build_argv(
            "storm_write_sites",
            {"target": "ccPlayer", "offset": "0xCC0", "build": "s4", "include_reads": True},
            None, None,
        )
        self.assertEqual(argv[0], "write_sites")
        self.assertIn("--offset", argv)
        self.assertIn("--include-reads", argv)

    def test_state_surface(self):
        argv = mcp_server.build_argv(
            "storm_state_surface",
            {"root": "ccPlayer", "build": "s4", "limit": 5, "max_offset": 0x1000, "seeds": "a,b"},
            None, None,
        )
        self.assertEqual(argv[0], "state_surface")
        self.assertIn("--max-offset", argv)
        self.assertIn("--seeds", argv)

    def test_symbolize(self):
        argv = mcp_server.build_argv(
            "storm_symbolize", {"target": "0x7ab468", "build": "s4", "max_bytes": 100}, None, None
        )
        self.assertEqual(argv[0], "symbolize")
        self.assertIn("--max-bytes", argv)

    def test_show(self):
        argv = mcp_server.build_argv("storm_show", {"query": "input", "build": "s4", "limit": 5}, None, None)
        self.assertEqual(argv[0], "show")
        self.assertIn("--build", argv)


class DispatchTests(unittest.TestCase):
    @mock.patch.object(mcp_server, "call_cli", return_value={"ok": True, "rva": "0x1"})
    def test_call_success(self, _call):
        resp = mcp_server.handle_request(
            {
                "jsonrpc": "2.0", "id": 5, "method": "tools/call",
                "params": {"name": "storm_resolve", "arguments": {"target": "x"}},
            }
        )
        self.assertFalse(resp["result"]["isError"])
        self.assertEqual(resp["result"]["structuredContent"]["rva"], "0x1")
        self.assertEqual(json.loads(resp["result"]["content"][0]["text"])["rva"], "0x1")

    @mock.patch.object(mcp_server, "call_cli", return_value={"ok": False, "error": "nope", "code": 2})
    def test_call_error(self, _call):
        resp = mcp_server.handle_request(
            {
                "jsonrpc": "2.0", "id": 6, "method": "tools/call",
                "params": {"name": "storm_resolve", "arguments": {"target": "x"}},
            }
        )
        self.assertTrue(resp["result"]["isError"])

    @mock.patch.object(mcp_server, "call_cli", return_value={"ok": True})
    def test_batch(self, _call):
        resp = mcp_server.handle_request({
            "jsonrpc": "2.0", "id": 14, "method": "tools/call",
            "params": {"name": "storm_batch", "arguments": {"calls": [
                {"tool": "storm_resolve", "arguments": {"target": "x"}},
                {"tool": "storm_stat", "arguments": {}},
            ]}},
        })
        self.assertFalse(resp["result"]["isError"])
        self.assertEqual(len(resp["result"]["structuredContent"]["results"]), 2)

    def test_http_initialize(self):
        server = mcp_server.create_http_server("127.0.0.1", 0, None, None)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                               "params": {"protocolVersion": "2025-06-18"}})
            conn.request("POST", "/mcp", body, {"Content-Type": "application/json"})
            resp = conn.getresponse()
            data = json.loads(resp.read())
            self.assertEqual(resp.status, 200)
            self.assertIn("instructions", data["result"])
            conn.close()
        finally:
            server.shutdown()
            server.server_close()

    @mock.patch.object(mcp_server, "call_cli", return_value={"ok": True, "rva": "0x1"})
    def test_http_tool_call_and_auth(self, _call):
        server = mcp_server.create_http_server("127.0.0.1", 0, None, None, token="t")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": "storm_resolve", "arguments": {"target": "x"}}})
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("POST", "/mcp", body, {"Content-Type": "application/json"})
            self.assertEqual(conn.getresponse().status, 401)
            conn.close()
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("POST", "/mcp", body, {"Content-Type": "application/json",
                                                "Authorization": "Bearer t"})
            resp = conn.getresponse()
            data = json.loads(resp.read())
            self.assertEqual(resp.status, 200)
            self.assertEqual(data["result"]["structuredContent"]["rva"], "0x1")
            conn.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_http_refuses_public_bind_without_token(self):
        with self.assertRaises(ValueError):
            mcp_server.create_http_server("0.0.0.0", 0, None, None)

    def test_cap_response(self):
        big = {"ok": True, "text": "a" * (mcp_server.MAX_CHARS * 2)}
        capped = mcp_server.cap_response(big)
        self.assertTrue(capped.get("truncated"))
        self.assertLessEqual(len(json.dumps(capped)), mcp_server.MAX_CHARS)

    def test_cap_fallback(self):
        big = {"ok": True, "items": ["x" * 1000] * 200}
        capped = mcp_server.cap_response(big)
        self.assertTrue(capped.get("truncated"))
        self.assertEqual(capped["code"], 3)


if __name__ == "__main__":
    unittest.main()
