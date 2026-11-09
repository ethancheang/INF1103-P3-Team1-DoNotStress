"""Automated checks for the module's coding requirements.

* one class per .py file, and the file is named after its class;
* no procedural code: no module-level functions in the application;
* test doubles live in tests/, never in the application;
* the four manager responsibilities stay identifiable.

They run in CI, so a change that breaks a rule fails the build.
"""

from __future__ import annotations

import ast
import importlib
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY_POINTS = {"main.py", "gui.py"}  # thin scripts: they build the app object and start it
SKIPPED_FOLDERS = {"tests", "venv", "env", "site-packages", "node_modules", "build", "dist", "__pycache__"}


def is_project_folder(folder):
    """False for tests, hidden folders (.venv, .git) and any virtual environment, whatever its name."""
    return not (folder.name.startswith(".") or folder.name in SKIPPED_FOLDERS or (folder / "pyvenv.cfg").exists())


def application_files():
    for current, folders, files in os.walk(ROOT):
        folders[:] = sorted(name for name in folders if is_project_folder(Path(current) / name))
        for name in sorted(files):
            if name.endswith(".py"):
                path = Path(current) / name
                yield path.relative_to(ROOT), ast.parse(path.read_text(encoding="utf-8"))


def snake_case(name):
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name).lower()


class CodingRequirementTests(unittest.TestCase):
    def test_one_class_per_file_named_after_the_class(self):
        for relative, tree in application_files():
            classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
            with self.subTest(file=str(relative)):
                self.assertLessEqual(len(classes), 1, classes)
                if classes and relative.name not in ENTRY_POINTS:
                    self.assertEqual(relative.stem, snake_case(classes[0]))

    def test_no_module_level_functions_in_the_application(self):
        for relative, tree in application_files():
            functions = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
            with self.subTest(file=str(relative)):
                self.assertEqual(functions, [])

    def test_test_doubles_are_not_in_the_application(self):
        for relative, tree in application_files():
            names = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
            with self.subTest(file=str(relative)):
                self.assertFalse([n for n in names if n.startswith(("Mock", "Fake", "InMemory", "Recording", "Scripted", "Demo"))])

    def test_test_doubles_also_follow_one_class_per_file(self):
        for path in sorted((ROOT / "tests" / "doubles").glob("*.py")):
            classes = [n.name for n in ast.parse(path.read_text(encoding="utf-8")).body if isinstance(n, ast.ClassDef)]
            with self.subTest(file=path.name):
                self.assertLessEqual(len(classes), 1)

    def test_the_four_managers_are_identifiable(self):
        managers = {
            "io_manager": "StudentIO",
            "ai_manager": "GeminiAIManager",
            "logic_manager": "LogicManager",
            "data_manager": "JsonRecordRepository",
        }
        for package, class_name in managers.items():
            with self.subTest(manager=package):
                self.assertTrue(hasattr(importlib.import_module(package), class_name))


if __name__ == "__main__":
    unittest.main()
