#!/usr/bin/env python3
"""
Fixture tests for tools/unwrap-prose.py — the one-paragraph-per-line fixer the
prose kit vendors into every fleet repository.

Guards the contract each repo's markdown-oneline gate relies on:

  * a wrapped prose paragraph becomes one line; structure (headings, fences,
    tables, quotes, front matter, hard breaks) is left byte-identical;
  * a list item's wrapped, indented continuation joins the item line (a
    flush-left line after it stays its own line), and a later indented
    paragraph of the item keeps its indent, so no text ever leaves the list
    it belongs to (the pre-0.4 tool de-indented an item's second paragraph
    out of its list);
  * nested items, indented code inside an item, and hard breaks stay as written;
  * the transform is idempotent.

Stdlib only:

    python3 tools/test_unwrap_prose.py
"""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("unwrap_prose", Path(__file__).with_name("unwrap-prose.py"))
up = importlib.util.module_from_spec(spec)
spec.loader.exec_module(up)


def t(text: str) -> str:
    out = up.transform(text)
    assert up.transform(out) == out, "not idempotent:\n" + out
    return out


class Prose(unittest.TestCase):
    def test_paragraph_joins(self):
        self.assertEqual(t("one\ntwo\nthree.\n"), "one two three.\n")

    def test_structure_is_untouched(self):
        doc = ("---\ntitle: x\ntags:\n  - a\n---\n# H\n\n| a | b |\n| - | - |\n\n> quote\n> more\n\n"
               "```\ncode\nline\n```\n\nhard  \nbreak\n")
        self.assertEqual(t(doc), doc)


class Lists(unittest.TestCase):
    def test_indented_continuation_joins_the_item(self):
        self.assertEqual(t("- item one\n  continues here\n- item two\n"), "- item one continues here\n- item two\n")

    def test_a_flush_left_line_after_an_item_stays_its_own_line(self):
        # In a raw-read prompt this is a new instruction, not a continuation.
        doc = "3. residual risks needing a human\nNever approve baseline updates yourself.\n"
        self.assertEqual(t(doc), doc)

    def test_a_later_paragraph_keeps_its_indent(self):
        doc = "- item\n\n  second paragraph\n  wrapped\n\nTop level\nprose.\n"
        self.assertEqual(t(doc), "- item\n\n  second paragraph wrapped\n\nTop level prose.\n")

    def test_nested_items_and_code_stay_inside(self):
        doc = "- a\n  b\n  - nested\n    more\n\n      code one\n      code two\n"
        self.assertEqual(t(doc), "- a b\n  - nested more\n\n      code one\n      code two\n")

    def test_a_table_or_fence_in_an_item_is_left_alone(self):
        doc = "- item\n\n  | a | b |\n  | - | - |\n\n  ```\n  x\n  y\n  ```\n"
        self.assertEqual(t(doc), doc)

    def test_hard_break_inside_an_item_is_kept(self):
        doc = "- line ends hard  \n  next\n"
        self.assertEqual(t(doc), doc)

    def test_the_list_ends_at_flush_left_text_after_a_blank(self):
        self.assertEqual(t("- item\n\nafter the\nlist.\n"), "- item\n\nafter the list.\n")


if __name__ == "__main__":
    unittest.main(verbosity=1)
