"""Tool infrastructure, builtins and batching."""

import asyncio
import contextlib
import io
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import tools.builtin  # noqa: F401  (registers the builtins)
from agent.suggest import _clean
from tools.base import TOOLS, make_schema, run_tool, tool
from tools.parallel import batches


@tool("_t_echo", "test", {"text": "string", "times": "integer?", "ratio": "number?"})
def _echo(args, s):
    return args["text"] * args.get("times", 1)


@tool("_t_boom", "test", {})
def _boom(args, s):
    raise ValueError("kaboom")


@tool("_t_sleep", "test", {})
def _sleep(args, s):
    time.sleep(0.3)
    return "slept"


@tool("_t_async", "test", {})
async def _async(args, s):
    await asyncio.sleep(0)
    return "async"


def run(coro):
    return asyncio.run(coro)


class Schema(unittest.TestCase):
    def test_compact_schema(self):
        schema = make_schema("_t_echo")
        self.assertEqual(schema["parameters"]["required"], ["text"])
        self.assertEqual(schema["parameters"]["properties"]["times"], {"type": "integer"})
        self.assertEqual(schema["parameters"]["properties"]["ratio"], {"type": "number"})

    def test_full_json_schema_passes_through(self):
        full = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        tool("_t_full", "test", full)(lambda args, s: "ok")
        self.assertEqual(make_schema("_t_full")["parameters"], full)


class RunTool(unittest.TestCase):
    def test_runs_and_reports_errors_as_strings(self):
        self.assertEqual(run(run_tool("_t_echo", {"text": "ab", "times": 2}, None)), "abab")
        self.assertEqual(run(run_tool("_t_echo", {}, None)), "error: missing parameters: text")
        self.assertEqual(run(run_tool("_t_boom", {}, None)), "error: kaboom")
        self.assertEqual(run(run_tool("_t_async", {}, None)), "async")

    def test_sync_tools_overlap_in_a_batch(self):
        async def both():
            t0 = time.time()
            out = await asyncio.gather(run_tool("_t_sleep", {}, None), run_tool("_t_sleep", {}, None))
            return out, time.time() - t0
        out, elapsed = run(both())
        self.assertEqual(out, ["slept", "slept"])
        self.assertLess(elapsed, 0.55)


class Batches(unittest.TestCase):
    def names(self, calls, enabled=True, limit=5):
        return [[c["name"] for c in b] for b in batches([{"name": n} for n in calls], enabled, limit)]

    def test_only_consecutive_read_only_calls_share_a_batch(self):
        self.assertEqual(self.names(["read_file", "grep", "write_file", "glob", "glob", "shell", "read_file"]),
                         [["read_file", "grep"], ["write_file"], ["glob", "glob"], ["shell"], ["read_file"]])
        self.assertEqual(self.names(["read_file"] * 4, limit=2), [["read_file", "read_file"], ["read_file", "read_file"]])
        self.assertEqual(self.names(["read_file", "grep"], enabled=False), [["read_file"], ["grep"]])
        self.assertEqual(self.names([]), [])


class EditTool(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.s = SimpleNamespace(config=SimpleNamespace(cwd=self.dir), undo=[], pending=[])

    def edit(self, **args):
        with contextlib.redirect_stdout(io.StringIO()):
            return run(run_tool("edit", args, self.s))

    def test_unique_match_replace_all_and_hints(self):
        (self.dir / "m.txt").write_text("x x x\n")
        self.assertIn("appears 3 times", self.edit(path="m.txt", old_string="x", new_string="y"))
        self.assertIn("replaced 3", self.edit(path="m.txt", old_string="x", new_string="y", replace_all=True))
        self.assertEqual((self.dir / "m.txt").read_text(), "y y y\n")
        self.assertIn("Similar lines", self.edit(path="m.txt", old_string="y q", new_string="q"))
        self.assertIn("not found", self.edit(path="m.txt", old_string="zz", new_string="q"))
        self.assertTrue(self.edit(path="m.txt", old_string="y", new_string="y", replace_all=True).startswith("error: no change"))

    def test_create_and_snapshot_for_undo(self):
        self.assertTrue(self.edit(path="new.txt", new_string="hi\n").startswith("Created"))
        self.assertEqual(self.s.pending, [(self.dir.resolve() / "new.txt", None)])
        self.assertIn("does not exist", self.edit(path="ghost.txt", old_string="a", new_string="b"))


class SuggestionCleaning(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(_clean('  "hello.txt의 world를 there로 바꿔줘"  \n\nextra'), "hello.txt의 world를 there로 바꿔줘")
        self.assertEqual(_clean("\n`git status 실행해`\n"), "git status 실행해")
        self.assertIsNone(_clean(""))
        self.assertIsNone(_clean("x" * 200))


if __name__ == "__main__":
    unittest.main()
