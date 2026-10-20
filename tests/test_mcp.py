import unittest

from support import ROOT  # noqa: F401

from storm_re.mcp import MCPError, _parse_events, _unwrap


class MCPParsingTests(unittest.TestCase):
    def test_sse(self):
        body = (
            'event: message\n'
            'data: {"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"{\\"a\\":1}"}]}}\n'
        )
        events = _parse_events(body)
        self.assertEqual(len(events), 1)
        self.assertEqual(_unwrap(events[0]), {"a": 1})

    def test_plain_json(self):
        events = _parse_events('{"jsonrpc":"2.0","id":1,"result":{"x":2}}')
        self.assertEqual(_unwrap(events[0]), {"x": 2})

    def test_structured_content(self):
        event = {"result": {"structuredContent": {"programs": []}}}
        self.assertEqual(_unwrap(event), {"programs": []})

    def test_tool_error(self):
        event = {"result": {"isError": True, "content": [{"type": "text", "text": "boom"}]}}
        with self.assertRaises(MCPError):
            _unwrap(event)

    def test_rpc_error(self):
        with self.assertRaises(MCPError):
            _unwrap({"error": {"message": "nope"}})

    def test_plain_text(self):
        event = {"result": {"content": [{"type": "text", "text": "hello"}]}}
        self.assertEqual(_unwrap(event), {"text": "hello"})

    def test_text_wins_over_result_wrapper(self):
        event = {
            "result": {
                "content": [{"type": "text", "text": '{"code":"real","signature":"s"}'}],
                "structuredContent": {"result": {"code": "", "signature": ""}},
                "isError": False,
            }
        }
        self.assertEqual(_unwrap(event)["code"], "real")

    def test_structured_result_wrapper(self):
        event = {"result": {"structuredContent": {"result": {"a": 1}}}}
        self.assertEqual(_unwrap(event), {"a": 1})

    def test_structured_direct(self):
        event = {"result": {"structuredContent": {"programs": []}}}
        self.assertEqual(_unwrap(event), {"programs": []})


if __name__ == "__main__":
    unittest.main()
