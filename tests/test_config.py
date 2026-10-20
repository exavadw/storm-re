"""Config file: lets a fresh install point at its own Ghidra project without code edits."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

PROBE = """
import json
from storm_re import config
print(json.dumps({"mcp": config.mcp_url(), "program": config.BUILDS["s4"]["program"],
                  "host": config.host_label(), "win": config.assets_win_root()}))
"""


def probe(toml: str, **env) -> dict:
    with tempfile.TemporaryDirectory() as d:
        cfg = Path(d) / "config.toml"
        cfg.write_text(toml)
        clean = {k: v for k, v in os.environ.items() if not k.startswith("STORM_RE_")}
        clean.update(PYTHONPATH=SRC, STORM_RE_CONFIG=str(cfg), **env)
        out = subprocess.run([sys.executable, "-c", PROBE], env=clean,
                             capture_output=True, text=True, check=True)
        return json.loads(out.stdout)


class ConfigFileTest(unittest.TestCase):
    def test_defaults_are_local_and_private_free(self):
        got = probe("")
        self.assertEqual(got["mcp"], "http://127.0.0.1:8770/mcp")
        self.assertEqual(got["host"], "local")
        self.assertEqual(got["win"], "")

    def test_file_overrides_defaults_and_build_program(self):
        got = probe('mcp_url = "http://ghidra:9000/mcp"\nhost = "box"\n'
                    '[builds.s4]\nprogram = "/MyImport.exe-123abc"\n')
        self.assertEqual(got["mcp"], "http://ghidra:9000/mcp")
        self.assertEqual(got["host"], "box")
        self.assertEqual(got["program"], "/MyImport.exe-123abc")

    def test_env_beats_file(self):
        got = probe('mcp_url = "http://from-file/mcp"\n', STORM_RE_MCP="http://from-env/mcp")
        self.assertEqual(got["mcp"], "http://from-env/mcp")


if __name__ == "__main__":
    unittest.main()
