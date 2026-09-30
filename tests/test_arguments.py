"""Windows 参数解析及 subprocess 参数序列的实际传递。"""

import itertools
import json
import subprocess
import sys
import unittest

from script_chainer.utils.arguments import parse_arguments


class TestArguments(unittest.TestCase):
    def test_windows_quoting_examples(self):
        for text, expected in (
            ('--profile "中文 空格"', ["--profile", "中文 空格"]),
            ('"" "a b" c', ["", "a b", "c"]),
            ('ab" cd"ef', ["ab cdef"]),
            ('"a""b"', ['a"b']),
            (r'"C:\Game Folder\\"', ["C:\\Game Folder\\"]),
            (r"a\"b", ['a"b']),
            ("  \t ", []),
            ('"open ended', ["open ended"]),
            ("'a b' & %PATH%", ["'a", "b'", "&", "%PATH%"]),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_arguments(text), expected)

    def test_round_trip_subprocess_windows_escaping(self):
        values = ["", "中文", "a b", "a\tb", 'a"b', "a\\", 'a\\"b', "C:\\Game Folder\\"]
        for arguments in itertools.product(values, repeat=2):
            with self.subTest(arguments=arguments):
                self.assertEqual(
                    parse_arguments(subprocess.list2cmdline(arguments)), list(arguments)
                )

    def test_child_receives_empty_quoted_and_trailing_backslash_arguments(self):
        expected = ["", "中文 空格", 'a"b', "C:\\Game Folder\\", "a&b"]
        parsed = parse_arguments(subprocess.list2cmdline(expected))
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json,sys;print(json.dumps(sys.argv[1:]))",
                *parsed,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(json.loads(result.stdout), expected)

    def test_invalid_argument_text(self):
        for value in (None, 123, "a\0b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_arguments(value)
