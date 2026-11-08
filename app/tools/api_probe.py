"""Runs under the project's Python and inspects the libraries its code imports.

  python api_probe.py check <project> <file.py>   names a file uses that its libraries do not have
  python api_probe.py inspect <project> <name> [match]   what a module, class or object really offers

The last line printed is "@@RESULT@@" and a JSON string, because libraries print their own banners on import.
"""
import ast
import builtins
import difflib
import importlib
import inspect
import json
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
SKIP = {"this", "antigravity", "idlelib", "turtle"}
LIMIT = 10
LISTED = 90


def is_local(name, root):
    top = name.split(".")[0]
    return os.path.exists(os.path.join(root, top + ".py")) or os.path.isdir(os.path.join(root, top))


def public(obj):
    try:
        names = list(getattr(obj, "__all__", None) or dir(obj))
    except Exception:
        return []
    return [name for name in names if not name.startswith("_")]


def close(name, options):
    found = difflib.get_close_matches(name, [str(item) for item in options], n=4, cutoff=0.6)
    return f" Did you mean: {', '.join(found)}?" if found else ""


def check(root, path):
    source = open(path, encoding="utf-8", errors="replace").read()
    tree = ast.parse(source)
    findings, ns, unresolved_star, origin = [], {}, False, {}
    imported = set()

    def bring(name):
        if name.split(".")[0] in SKIP or is_local(name, root):
            return None
        try:
            return importlib.import_module(name)
        except ModuleNotFoundError as error:
            top = name.split(".")[0]
            if error.name and error.name.split(".")[0] == top:
                findings.append(f"Module {name} is not installed ({error}). Install it into the project's .venv with pip, or use something else.")
            return None
        except BaseException as error:
            findings.append(f"Importing {name} fails: {type(error).__name__}: {error}")
            return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = bring(alias.name)
                bound = alias.asname or alias.name.split(".")[0]
                imported.add(bound)
                origin[bound] = alias.name if alias.asname else bound
                if module is not None:
                    ns[bound] = module if alias.asname else sys.modules.get(alias.name.split(".")[0], module)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            module = bring(node.module)
            for alias in node.names:
                if alias.name == "*":
                    if module is None:
                        unresolved_star = True
                    else:
                        for name in public(module):
                            if name not in ns:
                                ns[name] = getattr(module, name, None)
                                origin[name] = f"{node.module}.{name}"
                    continue
                bound = alias.asname or alias.name
                imported.add(bound)
                origin[bound] = f"{node.module}.{alias.name}"
                if module is None:
                    continue
                if hasattr(module, alias.name):
                    ns[bound] = getattr(module, alias.name)
                else:
                    try:
                        ns[bound] = importlib.import_module(f"{node.module}.{alias.name}")
                    except Exception:
                        findings.append(f"line {node.lineno}: cannot import {alias.name} from {node.module}.{close(alias.name, public(module))}")
    rebound = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            rebound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            rebound.add(node.name)
            if not isinstance(node, ast.ClassDef):
                args = node.args
                for arg in args.posonlyargs + args.args + args.kwonlyargs + [item for item in (args.vararg, args.kwarg) if item]:
                    rebound.add(arg.arg)
        elif isinstance(node, ast.Lambda):
            args = node.args
            for arg in args.posonlyargs + args.args + args.kwonlyargs + [item for item in (args.vararg, args.kwarg) if item]:
                rebound.add(arg.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            rebound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            rebound.update(node.names)
        elif isinstance(node, ast.MatchAs) and node.name:
            rebound.add(node.name)
    seen = set()
    for node in ast.walk(tree):
        if len(findings) >= LIMIT:
            break
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            chain, current = [], node
            while isinstance(current, ast.Attribute):
                chain.append(current.attr)
                current = current.value
            if not isinstance(current, ast.Name) or current.id not in ns or current.id in rebound:
                continue
            chain.reverse()
            obj, prefix = ns[current.id], current.id
            for attr in chain:
                if inspect.isclass(obj) or hasattr(type(obj), "__getattr__"):
                    break
                try:
                    exists = hasattr(obj, attr)
                except Exception:
                    break
                if not exists:
                    key = (prefix, attr)
                    if key not in seen:
                        seen.add(key)
                        findings.append(f"line {node.lineno}: {prefix} has no attribute {attr}.{close(attr, public(obj))} Look at inspect_api name={origin[current.id] + prefix[len(current.id):]!r}.")
                    break
                try:
                    obj = getattr(obj, attr)
                except Exception:
                    break
                prefix += "." + attr
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            name = node.id
            if name in ns or name in rebound or name in imported or hasattr(builtins, name) or name in ("__file__", "__name__", "__doc__", "__spec__", "__builtins__") or unresolved_star:
                continue
            if ("name", name) not in seen:
                seen.add(("name", name))
                findings.append(f"line {node.lineno}: name {name} is not defined.{close(name, list(ns) + list(rebound))}")
    return findings[:LIMIT]


def describe(obj, name, match):
    parts = [f"{name}: {type(obj).__module__}.{type(obj).__name__}"]
    try:
        parts.append("signature: " + name.split(".")[-1] + str(inspect.signature(obj)))
    except (TypeError, ValueError):
        pass
    doc = inspect.getdoc(obj) or ""
    if doc:
        parts.append(doc[:700])
    rows = []
    for attr in public(obj):
        if match and match.lower() not in attr.lower():
            continue
        try:
            value = inspect.getattr_static(obj, attr)
        except Exception:
            continue
        kind = "class" if inspect.isclass(value) else "method" if callable(value) or isinstance(value, (staticmethod, classmethod)) else "property" if isinstance(value, property) else "value"
        shown = attr
        if kind in ("method", "class"):
            try:
                target = value.__func__ if isinstance(value, (staticmethod, classmethod)) else value
                shown += str(inspect.signature(target))[:90]
            except (TypeError, ValueError):
                shown += "(...)"
        rows.append(f"  {shown}  [{kind}]")
    if rows:
        more = len(rows) - LISTED
        parts.append("names" + (f" matching {match!r}" if match else "") + ":\n" + "\n".join(rows[:LISTED]) + (f"\n  ... {more} more: pass match to narrow it" if more > 0 else ""))
    elif match:
        parts.append(f"nothing here matches {match!r}. All names: " + ", ".join(public(obj)[:LISTED]))
    return "\n".join(parts)


def inspect_name(root, name, match):
    pieces = name.strip().split(".")
    if is_local(pieces[0], root):
        return f"{pieces[0]} is a file of the project: read it with read_file or outline."
    try:
        obj = importlib.import_module(pieces[0])
    except ModuleNotFoundError as error:
        return f"Module {pieces[0]} is not installed ({error}). Install it into the project's .venv with pip."
    except BaseException as error:
        return f"Importing {pieces[0]} fails: {type(error).__name__}: {error}"
    walked = pieces[0]
    for attr in pieces[1:]:
        # An exported name wins over a submodule: ursina.mouse is an object.
        if hasattr(obj, attr):
            obj = getattr(obj, attr)
        else:
            try:
                obj = importlib.import_module(f"{walked}.{attr}")
            except Exception:
                return f"{walked} has no attribute {attr}.{close(attr, public(obj))}\n" + describe(obj, walked, attr[:3])
        walked += "." + attr
    return describe(obj, name, match)


def main():
    mode, root = sys.argv[1], os.path.abspath(sys.argv[2])
    os.chdir(root)
    sys.argv[0] = os.path.join(root, "main.py")
    try:
        if mode == "check":
            result = json.dumps(check(root, sys.argv[3]), ensure_ascii=False)
        else:
            result = json.dumps(inspect_name(root, sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else ""), ensure_ascii=False)
    except SyntaxError as error:
        result = json.dumps([f"Syntax error at line {error.lineno}: {error.msg}"] if mode == "check" else "Syntax error", ensure_ascii=False)
    sys.stdout.flush()
    sys.stdout.buffer.write(b"\n@@RESULT@@" + result.encode("utf-8") + b"\n")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
