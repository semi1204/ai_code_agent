"""Conversation history, pruning, loop detection, token estimate."""

import unittest
from collections import deque
from types import SimpleNamespace

from context import loop_detector as ld
from context import manager as cm
from utils.text import count_tokens


def session(context_window=100):
    return SimpleNamespace(messages=[], usage={}, last_usage={}, system_prompt="SYS",
                           config=SimpleNamespace(model=SimpleNamespace(context_window=context_window)),
                           history=deque(maxlen=ld.WINDOW))


class Messages(unittest.TestCase):
    def test_assistant_message_omits_empty_content(self):
        s = session()
        cm.add_assistant(s, None, [{"id": "1", "type": "function", "function": {"name": "x", "arguments": "{}"}}])
        self.assertNotIn("content", s.messages[0])
        cm.add_tool(s, "1", "out")
        self.assertEqual(cm.messages_for_api(s)[0], {"role": "system", "content": "SYS"})
        self.assertEqual(len(cm.messages_for_api(s)), 3)

    def test_usage_accumulates_and_drives_compaction(self):
        s = session(context_window=100)
        cm.add_user(s, "x" * 4000)
        self.assertTrue(cm.needs_compaction(s))  # estimate: 1000 tokens > 80
        cm.add_usage(s, {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
        cm.add_usage(s, {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
        self.assertEqual(s.usage, {"prompt_tokens": 11, "completion_tokens": 6, "total_tokens": 17})
        self.assertFalse(cm.needs_compaction(s))  # provider says 2 tokens


class Pruning(unittest.TestCase):
    def test_old_tool_outputs_are_cleared_but_ids_kept(self):
        s = session()
        cm.add_user(s, "a"); cm.add_tool(s, "1", "big " * 60000); cm.add_assistant(s, "ok")
        cm.add_user(s, "b"); cm.add_tool(s, "2", "small"); cm.add_assistant(s, "ok")
        self.assertEqual(cm.prune_tool_outputs(s), 1)
        self.assertEqual(s.messages[1], {"role": "tool", "tool_call_id": "1", "content": cm.PRUNED})
        self.assertEqual(s.messages[4]["content"], "small")
        self.assertEqual(cm.prune_tool_outputs(s), 0)

    def test_nothing_pruned_below_thresholds_or_in_first_turn(self):
        s = session()
        cm.add_user(s, "a"); cm.add_tool(s, "1", "big " * 60000)
        self.assertEqual(cm.prune_tool_outputs(s), 0)  # only one user message
        cm.add_user(s, "b"); s.messages[1]["content"] = "big " * 30000  # 30k tokens: inside the protected window
        self.assertEqual(cm.prune_tool_outputs(s), 0)


class LoopDetection(unittest.TestCase):
    def test_repeats_and_cycles(self):
        s = session()
        for _ in range(2):
            ld.record(s, "read_file", {"path": "a"})
        self.assertIsNone(ld.check(s))
        ld.record(s, "read_file", {"path": "a"})
        self.assertEqual(ld.check(s), "the same action was repeated 3 times")
        self.assertFalse(s.history)  # cleared so it fires once
        for name in ["grep", "read_file", "grep", "read_file"]:
            ld.record(s, name, {"x": 1})
        self.assertEqual(ld.check(s), "a repeating cycle of 2 actions")
        for name in ["a", "b", "c", "a", "b", "c"]:
            ld.record(s, name)
        self.assertEqual(ld.check(s), "a repeating cycle of 3 actions")
        for name in ["a", "b", "c", "d"]:
            ld.record(s, name)
        self.assertIsNone(ld.check(s))


class TokenEstimate(unittest.TestCase):
    def test_cjk_counts_more_than_ascii(self):
        self.assertEqual(count_tokens("abcdefgh"), 2)
        self.assertGreater(count_tokens("안녕하세요반갑습니다"), count_tokens("abcdefghij"))
        self.assertEqual(count_tokens(""), 1)


if __name__ == "__main__":
    unittest.main()
