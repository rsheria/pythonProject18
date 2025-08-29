#!/usr/bin/env python3
"""Dead code detector for the repository.

Recursively scans Python files, builds a very small symbol table and
usage index and reports unused definitions and unreachable code.

The implementation uses only the Python standard library.
"""

import argparse
import ast
import json
import os
import re
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

EXCLUDE_DIRS = {"venv", "__pycache__", "data", "dist", "build"}
PYQT_BASES = {"QThread", "QObject", "QAbstractItemModel"}
TEMPLATE_EXTS = {".tmpl", ".template", ".tpl", ".j2"}
TERMINATORS = (ast.Return, ast.Raise, ast.Break, ast.Continue)


def repo_root() -> str:
    """Return repository root (parent of tools directory)."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def scan_py_files(root: str) -> List[str]:
    files: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if fn.endswith('.py'):
                files.append(os.path.join(dirpath, fn))
    return files


def collect_template_names(root: str) -> Set[str]:
    names: Set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if any(fn.endswith(ext) for ext in TEMPLATE_EXTS):
                path = os.path.join(dirpath, fn)
                try:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                except Exception:
                    continue
                names.update(re.findall(r'[A-Za-z_][A-Za-z0-9_]*', content))
    return names


def load_allowlist(path: str) -> Set[Tuple[Optional[str], Optional[str]]]:
    allow: Set[Tuple[Optional[str], Optional[str]]] = set()
    if not os.path.exists(path):
        return allow
    entries: List[Dict[str, Optional[str]]] = []
    current: Optional[Dict[str, Optional[str]]] = None
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    continue
                if stripped.startswith('allowlist'):
                    continue
                if stripped.startswith('-'):
                    if current:
                        entries.append(current)
                    current = {}
                    stripped = stripped[1:].strip()
                    if stripped:
                        if ':' in stripped:
                            k, v = stripped.split(':', 1)
                            current[k.strip()] = v.strip().strip('"\'')
                    continue
                if current is not None and ':' in stripped:
                    k, v = stripped.split(':', 1)
                    current[k.strip()] = v.strip().strip('"\'')
            if current:
                entries.append(current)
    except Exception:
        return allow
    for item in entries:
        allow.add((item.get('file'), item.get('name')))
    return allow


def get_attr_chain(node: ast.AST) -> str:
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    parts.reverse()
    return '.'.join(parts)


def get_call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    elif isinstance(func, ast.Attribute):
        return get_attr_chain(func)
    return ''


def extract_callable_names(arg: ast.AST) -> List[str]:
    names: List[str] = []
    if isinstance(arg, ast.Name):
        names.append(arg.id)
    elif isinstance(arg, ast.Attribute):
        names.append(get_attr_chain(arg).split('.')[-1])
    elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        names.append(arg.value.split('.')[-1])
    return names


class UsageCollector(ast.NodeVisitor):
    def __init__(self):
        self.usage: Dict[str, List[int]] = defaultdict(list)

    # Basic names and attribute chains
    def visit_Name(self, node: ast.Name) -> None:
        self.usage[node.id].append(node.lineno)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        chain = get_attr_chain(node)
        self.usage[chain].append(node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Handle .connect
        if isinstance(node.func, ast.Attribute) and node.func.attr == 'connect':
            if node.args:
                for name in extract_callable_names(node.args[0]):
                    self.usage[name].append(node.args[0].lineno)
        # getattr/setattr/hasattr/delattr
        if isinstance(node.func, ast.Name) and node.func.id in {'getattr', 'setattr', 'hasattr', 'delattr'}:
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                self.usage[node.args[1].value].append(node.args[1].lineno)
        # importlib.import_module and __import__
        func_name = get_call_name(node)
        if func_name in {'importlib.import_module', '__import__'}:
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                mod = node.args[0].value.split('.')[-1]
                self.usage[mod].append(node.args[0].lineno)
        self.generic_visit(node)


class DefCollector(ast.NodeVisitor):
    def __init__(self):
        self.defs: List[Dict[str, object]] = []
        self.class_stack: List[str] = []
        self.dataclass_classes: Set[str] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = [get_attr_chain(b) for b in node.bases]
        entry = {
            'name': node.name,
            'kind': 'class',
            'line': node.lineno,
            'bases': bases,
            'node': node,
            'used': False,
        }
        self.defs.append(entry)
        # dataclass decorator?
        for dec in node.decorator_list:
            if get_attr_chain(dec) == 'dataclass':
                self.dataclass_classes.add(node.name)
        self.class_stack.append(node.name)
        for stmt in node.body:
            self.visit(stmt)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # includes methods
        if self.class_stack:
            name = f"{self.class_stack[-1]}.{node.name}"
            kind = 'method'
        else:
            name = node.name
            kind = 'function'
        entry = {
            'name': name,
            'kind': kind,
            'line': node.lineno,
            'node': node,
            'used': False,
        }
        # @pyqtSlot decorator => used
        for dec in node.decorator_list:
            if get_attr_chain(dec) == 'pyqtSlot':
                entry['used'] = True
        self.defs.append(entry)
        for stmt in node.body:
            self.visit(stmt)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign) -> None:
        if self.class_stack:
            class_name = self.class_stack[-1]
            # class attributes: mark pyqtSignal fields as used
            for target in node.targets:
                if isinstance(target, ast.Name):
                    attr_name = f"{class_name}.{target.id}"
                    used = False
                    if isinstance(node.value, ast.Call):
                        if get_call_name(node.value) == 'pyqtSignal':
                            used = True
                    entry = {
                        'name': attr_name,
                        'kind': 'attribute',
                        'line': node.lineno,
                        'node': node,
                        'used': used,
                    }
                    self.defs.append(entry)
        else:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name = target.id
                    if name.startswith('__') or name == '__all__':
                        continue
                    entry = {
                        'name': name,
                        'kind': 'var',
                        'line': node.lineno,
                        'node': node,
                        'used': False,
                    }
                    self.defs.append(entry)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if self.class_stack:
            class_name = self.class_stack[-1]
            if class_name in self.dataclass_classes:
                return  # dataclass field
            if isinstance(node.target, ast.Name):
                attr_name = f"{class_name}.{node.target.id}"
                used = False
                if isinstance(node.value, ast.Call) and get_call_name(node.value) == 'pyqtSignal':
                    used = True
                entry = {
                    'name': attr_name,
                    'kind': 'attribute',
                    'line': node.lineno,
                    'node': node,
                    'used': used,
                }
                self.defs.append(entry)
        else:
            if isinstance(node.target, ast.Name):
                name = node.target.id
                if name.startswith('__') or name == '__all__':
                    return
                entry = {
                    'name': name,
                    'kind': 'var',
                    'line': node.lineno,
                    'node': node,
                    'used': False,
                }
                self.defs.append(entry)


def collect_defs(tree: ast.AST) -> List[Dict[str, object]]:
    collector = DefCollector()
    collector.visit(tree)
    return collector.defs


def collect_usage(tree: ast.AST) -> Dict[str, List[int]]:
    uc = UsageCollector()
    uc.visit(tree)
    # Collect names from CLI entrypoints
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            if (
                isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == '__name__'
                and len(node.test.comparators) == 1
                and isinstance(node.test.comparators[0], ast.Constant)
                and node.test.comparators[0].value == '__main__'
            ):
                inner = UsageCollector()
                for stmt in node.body:
                    inner.visit(stmt)
                for k, v in inner.usage.items():
                    uc.usage[k].extend(v)
    return uc.usage


def find_unreachable(tree: ast.AST) -> List[Tuple[int, int]]:
    unreachable: List[Tuple[int, int]] = []

    def check(stmts: List[ast.stmt]) -> None:
        terminated = False
        for stmt in stmts:
            if terminated:
                start = stmt.lineno
                end = getattr(stmt, 'end_lineno', start)
                unreachable.append((start, end))
            else:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    check(stmt.body)
                elif isinstance(stmt, ast.ClassDef):
                    for s in stmt.body:
                        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match)):
                            check([s])
                elif isinstance(stmt, ast.If):
                    check(stmt.body)
                    check(stmt.orelse)
                elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
                    check(stmt.body)
                    check(stmt.orelse)
                elif isinstance(stmt, ast.Try):
                    check(stmt.body)
                    for h in stmt.handlers:
                        check(h.body)
                    check(stmt.orelse)
                    check(stmt.finalbody)
                elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                    check(stmt.body)
                elif isinstance(stmt, ast.Match):
                    for case in stmt.cases:
                        check(case.body)
                if isinstance(stmt, TERMINATORS):
                    terminated = True
    check(tree.body)
    return unreachable


def analyze_file(path: str, template_names: Set[str]) -> Tuple[List[Dict[str, object]], List[Tuple[int, int]]]:
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            source = fh.read()
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return [], []
    defs = collect_defs(tree)
    usage = collect_usage(tree)
    # Merge template names
    for name in template_names:
        usage.setdefault(name, []).append(0)
    # Mark used based on usage
    used_names = set(usage.keys())
    for d in defs:
        base_name = d['name'].split('.')[-1]
        if d['name'] in used_names or base_name in used_names:
            d['used'] = True
        if d['kind'] == 'class' and any(b.split('.')[-1] in PYQT_BASES for b in d.get('bases', [])):
            d['used'] = True
    # config.py constants
    if os.path.basename(path) == 'config.py':
        for d in defs:
            if d['kind'] == 'var' and d['name'].isupper():
                d['used'] = True
    unreachable = find_unreachable(tree)
    return defs, unreachable


def is_allowed(entry: Dict[str, object], allow: Set[Tuple[Optional[str], Optional[str]]]) -> bool:
    for f, n in allow:
        if (f is None or f == entry['file']) and (n is None or n == entry.get('name')):
            return True
    return False


def generate_reports(results: List[Dict[str, object]], root: str) -> None:
    md_path = os.path.join(root, 'dead_code_report.md')
    json_path = os.path.join(root, 'dead_code.json')
    # Markdown
    lines = ["# Dead Code Report", "", "| File | Line | Kind | Name | Reason |", "| --- | --- | --- | --- | --- |"]
    for r in results:
        line = f"| {r['file']} | {r['line']}{('-'+str(r['end_line'])) if r.get('end_line') else ''} | {r['kind']} | {r.get('name','')} | {r['reason']} |"
        lines.append(line)
    with open(md_path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')
    # JSON
    with open(json_path, 'w', encoding='utf-8') as fh:
        json.dump(results, fh, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect dead code")
    parser.add_argument('--strict', action='store_true', help='Fail if dead code found')
    args = parser.parse_args()

    root = repo_root()
    allowlist_path = os.path.join(root, 'tools', 'deadcode_allowlist.yml')
    allow = load_allowlist(allowlist_path)
    template_names = collect_template_names(root)

    results: List[Dict[str, object]] = []
    for file_path in scan_py_files(root):
        rel = os.path.relpath(file_path, root)
        defs, unreachable = analyze_file(file_path, template_names)
        for d in defs:
            if d['used']:
                continue
            entry = {
                'file': rel,
                'line': d['line'],
                'kind': d['kind'],
                'name': d['name'],
                'reason': 'unused',
                'references': [],
            }
            if not is_allowed(entry, allow):
                results.append(entry)
        for start, end in unreachable:
            entry = {
                'file': rel,
                'line': start,
                'end_line': end,
                'kind': 'unreachable',
                'name': '',
                'reason': 'unreachable code',
                'references': [],
            }
            if not is_allowed(entry, allow):
                results.append(entry)
    generate_reports(results, root)
    # Print table summary
    if results:
        print(f"Found {len(results)} dead code items. See dead_code_report.md for details.")
    else:
        print("No dead code detected.")
    if args.strict and results:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

