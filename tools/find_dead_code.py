#!/usr/bin/env python3

"""Simple dead code detector with PyQt and dynamic heuristics.

This script indexes definitions and usages across a project and reports
potentially unused symbols.  It is a best-effort static analysis tool and
is not perfect, but it aims to reduce false positives for common patterns
used in this repository such as Qt signals/slots and cross module calls.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Iterable

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - PyYAML may not be installed
    yaml = None  # fallback, allow running without allowlist support

EXCLUDE_DIRS = {"venv", "__pycache__", "data", "dist", "build"}
EXCLUDE_PATTERN = re.compile(r".*(old|legacy|bak).*", re.IGNORECASE)

PYQT_BASES = {
    "QObject",
    "QThread",
    "QAbstractItemModel",
    "QAbstractListModel",
    "QAbstractTableModel",
}

@dataclass
class Definition:
    name: str
    kind: str
    file: str
    start: int
    end: int
    used: bool = False

    def to_dead_item(self) -> Dict[str, object]:
        return {
            "file": self.file,
            "kind": self.kind,
            "name": self.name,
            "start": self.start,
            "end": self.end,
            "reason": "unused",
            "references": [],
            "confidence": 0.5,
        }

@dataclass
class Unreachable:
    file: str
    name: str
    start: int
    end: int

    def to_dead_item(self) -> Dict[str, object]:
        return {
            "file": self.file,
            "kind": "code",
            "name": self.name,
            "start": self.start,
            "end": self.end,
            "reason": "unreachable",
            "references": [],
            "confidence": 0.9,
        }

# Helpers ------------------------------------------------------------------

def path_to_module(path: str, root: str) -> str:
    rel = os.path.relpath(path, root)
    rel = rel.replace(os.sep, "/")
    parts = rel.split("/")
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]  # strip .py
    return ".".join(p for p in parts if p)

def iter_py_files(root: str, include_tests: bool) -> Iterable[str]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in EXCLUDE_DIRS and not EXCLUDE_PATTERN.match(d)
        ]
        if not include_tests and "tests" in dirpath.split(os.sep):
            continue
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            if EXCLUDE_PATTERN.match(filename):
                continue
            yield os.path.join(dirpath, filename)

def get_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = get_name(node.value)
        if base:
            return f"{base}.{node.attr}"
        return node.attr
    return None

# Definition collection -----------------------------------------------------

def find_unreachable(body: List[ast.stmt]) -> List[ast.stmt]:
    unreachable: List[ast.stmt] = []
    reachable = True
    for stmt in body:
        if not reachable:
            unreachable.append(stmt)
        if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
            reachable = False
    return unreachable

def collect_definitions(path: str, root: str,
                        definitions: Dict[str, Definition],
                        local_defs: Dict[str, Dict[str, str]],
                        class_members: Dict[str, Dict[str, Dict[str, str]]],
                        unreachables: List[Unreachable]) -> None:
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return
    module = path_to_module(path, root)
    rel = os.path.relpath(path, root)
    definitions[module] = Definition(module, "module", rel, 1, len(source.splitlines()))
    local_defs[rel] = {}
    class_members[rel] = {}

    def register(name: str, kind: str, node: ast.AST) -> None:
        definitions[name] = Definition(
            name=name,
            kind=kind,
            file=rel,
            start=getattr(node, "lineno", 1),
            end=getattr(node, "end_lineno", getattr(node, "lineno", 1)),
        )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qname = f"{module}.{node.name}"
            register(qname, "function", node)
            local_defs[rel][node.name] = qname
            if any((get_name(d) or "").split(".")[-1] == "pyqtSlot" for d in node.decorator_list):
                definitions[qname].used = True
            for stmt in find_unreachable(node.body):
                unreachables.append(
                    Unreachable(rel, qname, stmt.lineno, getattr(stmt, "end_lineno", stmt.lineno))
                )
        elif isinstance(node, ast.ClassDef):
            qclass = f"{module}.{node.name}"
            register(qclass, "class", node)
            local_defs[rel][node.name] = qclass
            class_members[rel][node.name] = {}
            for base in node.bases:
                base_name = get_name(base)
                if base_name:
                    base_name = base_name.split(".")[-1]
                    if base_name in PYQT_BASES or base_name.endswith("Model"):
                        definitions[qclass].used = True
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    mname = f"{qclass}.{item.name}"
                    register(mname, "method", item)
                    class_members[rel][node.name][item.name] = mname
                    if any((get_name(d) or "").split(".")[-1] == "pyqtSlot" for d in item.decorator_list):
                        definitions[mname].used = True
                    for stmt in find_unreachable(item.body):
                        unreachables.append(
                            Unreachable(rel, mname, stmt.lineno, getattr(stmt, "end_lineno", stmt.lineno))
                        )
                elif isinstance(item, (ast.Assign, ast.AnnAssign)):
                    targets: List[ast.expr] = []
                    if isinstance(item, ast.Assign):
                        targets = item.targets
                        value = item.value
                    else:
                        targets = [item.target]
                        value = item.value
                    for t in targets:
                        if isinstance(t, ast.Name):
                            attr_qname = f"{qclass}.{t.id}"
                            register(attr_qname, "attribute", item)
                            class_members[rel][node.name][t.id] = attr_qname
                            if isinstance(value, ast.Call):
                                fname = get_name(value.func)
                                if fname and fname.split(".")[-1] == "pyqtSignal":
                                    definitions[attr_qname].used = True
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets: List[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            else:
                targets = [node.target]
                value = node.value
            for t in targets:
                if isinstance(t, ast.Name):
                    qname = f"{module}.{t.id}"
                    register(qname, "variable", node)
                    local_defs[rel][t.id] = qname
                    if isinstance(value, ast.Call):
                        fname = get_name(value.func)
                        if fname and fname.split(".")[-1] == "pyqtSignal":
                            definitions[qname].used = True

# Usage analysis ------------------------------------------------------------

def is_main_check(test: ast.AST) -> bool:
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq):
        left, right = test.left, test.comparators[0]
        if isinstance(left, ast.Name) and left.id == "__name__" and isinstance(right, ast.Constant):
            return str(right.value) == "__main__"
        if isinstance(right, ast.Name) and right.id == "__name__" and isinstance(left, ast.Constant):
            return str(left.value) == "__main__"
    return False

def gather_names(nodes: List[ast.stmt]) -> List[object]:
    items: List[object] = []
    class NV(ast.NodeVisitor):
        def visit_Name(self, n: ast.Name) -> None:
            items.append(n.id)
        def visit_Attribute(self, n: ast.Attribute) -> None:
            if isinstance(n.value, ast.Name):
                items.append((n.value.id, n.attr))
            self.generic_visit(n)
    v = NV()
    for n in nodes:
        v.visit(n)
    return items

class UsageVisitor(ast.NodeVisitor):
    def __init__(self, module: str, rel: str, definitions: Dict[str, Definition],
                 local_defs: Dict[str, str],
                 class_members: Dict[str, Dict[str, str]]):
        self.module = module
        self.rel = rel
        self.definitions = definitions
        self.local_defs = local_defs
        self.class_members = class_members
        self.imports: Dict[str, str] = {}
        self.current_class: Optional[str] = None

    def mark(self, name: str) -> None:
        if name in self.definitions:
            self.definitions[name].used = True
    def mark_name(self, name: str) -> None:
        if name in self.imports:
            self.mark(self.imports[name])
        elif self.current_class and name in self.class_members.get(self.current_class, {}):
            self.mark(self.class_members[self.current_class][name])
        elif name in self.local_defs:
            self.mark(self.local_defs[name])
        else:
            for n in self.definitions:
                if n.split(".")[-1] == name:
                    self.definitions[n].used = True
    def resolve_attr(self, node: ast.Attribute) -> Optional[str]:
        if isinstance(node.value, ast.Name):
            base = node.value.id
            if base in ("self", "cls") and self.current_class:
                return f"{self.module}.{self.current_class}.{node.attr}"
            if base in self.imports:
                return f"{self.imports[base]}.{node.attr}"
            if base in self.local_defs:
                return f"{self.local_defs[base]}.{node.attr}"
        elif isinstance(node.value, ast.Attribute):
            base = self.resolve_attr(node.value)
            if base:
                return f"{base}.{node.attr}"
        return None

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports[alias.asname or alias.name.split(".")[-1]] = alias.name
            self.mark(alias.name)
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            if alias.name == "*":
                self.mark(module)
                continue
            full = f"{module}.{alias.name}" if module else alias.name
            self.imports[alias.asname or alias.name] = full
            self.mark(module)
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        prev = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = prev
    def visit_Name(self, node: ast.Name) -> None:
        self.mark_name(node.id)
    def visit_Attribute(self, node: ast.Attribute) -> None:
        qname = self.resolve_attr(node)
        if qname:
            self.mark(qname)
        self.generic_visit(node)
    def visit_Call(self, node: ast.Call) -> None:
        fname = get_name(node.func) or ""
        if fname.endswith("getattr") and len(node.args) >= 2:
            arg = node.args[1]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                target = arg.value
                if self.current_class and target in self.class_members.get(self.current_class, {}):
                    self.mark(self.class_members[self.current_class][target])
                else:
                    self.mark(f"{self.module}.{target}")
        if fname.endswith("import_module") and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                self.mark(arg.value)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "connect":
            for arg in node.args:
                if isinstance(arg, ast.Name):
                    self.mark_name(arg.id)
                elif isinstance(arg, ast.Attribute):
                    qname = self.resolve_attr(arg)
                    if qname:
                        self.mark(qname)
                elif isinstance(arg, ast.Constant) and isinstance(arg.value, str) and self.current_class:
                    member_map = self.class_members.get(self.current_class, {})
                    if arg.value in member_map:
                        self.mark(member_map[arg.value])
        self.generic_visit(node)
    def visit_If(self, node: ast.If) -> None:
        if is_main_check(node.test):
            for ref in gather_names(node.body):
                if isinstance(ref, tuple):
                    base, attr = ref
                    if base in ("self", "cls") and self.current_class:
                        self.mark(f"{self.module}.{self.current_class}.{attr}")
                    elif base in self.imports:
                        self.mark(f"{self.imports[base]}.{attr}")
                    elif base in self.local_defs:
                        self.mark(f"{self.local_defs[base]}.{attr}")
                    else:
                        for n in self.definitions:
                            if n.split(".")[-1] == attr:
                                self.definitions[n].used = True
                else:
                    self.mark_name(ref)
        self.generic_visit(node)

# Allowlist -----------------------------------------------------------------

def load_allowlist(path: Optional[str]) -> Dict[str, List[str]]:
    data = {"names": [], "regex": []}
    if not path or not os.path.exists(path) or not yaml:
        return data
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        if isinstance(raw, dict):
            data["names"] = list(raw.get("names", []))
            data["regex"] = list(raw.get("regex", []))
    except Exception:
        pass
    return data

def allowlisted(name: str, allow: Dict[str, List[str]]) -> bool:
    if name in allow.get("names", []):
        return True
    for pattern in allow.get("regex", []):
        try:
            if re.search(pattern, name):
                return True
        except re.error:
            continue
    return False

# Main ----------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Find dead code")
    parser.add_argument("paths", nargs="*", default=["."], help="Root paths to scan")
    parser.add_argument("--strict", action="store_true", help="Exit with 1 if dead code found")
    parser.add_argument("--allowlist", default=None, help="Path to allowlist YAML")
    parser.add_argument("--include-tests", action="store_true", help="Include test files")
    args = parser.parse_args()

    roots = [os.path.abspath(p) for p in args.paths]
    definitions: Dict[str, Definition] = {}
    local_defs: Dict[str, Dict[str, str]] = {}
    class_members: Dict[str, Dict[str, Dict[str, str]]] = {}
    unreachables: List[Unreachable] = []

    for root in roots:
        for path in iter_py_files(root, args.include_tests):
            collect_definitions(path, root, definitions, local_defs, class_members, unreachables)
    for root in roots:
        for path in iter_py_files(root, args.include_tests):
            rel = os.path.relpath(path, root)
            module = path_to_module(path, root)
            visitor = UsageVisitor(module, rel, definitions,
                                   local_defs.get(rel, {}),
                                   class_members.get(rel, {}))
            with open(path, "r", encoding="utf-8") as f:
                try:
                    tree = ast.parse(f.read(), filename=path)
                except SyntaxError:
                    continue
            visitor.visit(tree)

    allow = load_allowlist(args.allowlist)
    dead_items = []
    for name, info in definitions.items():
        if not info.used and not allowlisted(name, allow):
            dead_items.append(info.to_dead_item())
    for ur in unreachables:
        if not allowlisted(ur.name, allow):
            dead_items.append(ur.to_dead_item())

    with open("dead_code.json", "w", encoding="utf-8") as f:
        json.dump(dead_items, f, indent=2)
    with open("dead_code_report.md", "w", encoding="utf-8") as f:
        f.write("# Dead Code Report\n\n")
        if not dead_items:
            f.write("No dead code found.\n")
        else:
            for item in dead_items:
                f.write(
                    f"- {item['file']}:{item['start']}-{item['end']} {item['kind']} {item['name']} ({item['reason']})\n"
                )

    if args.strict and dead_items:
        return 1
    return 0

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
