"""Every message the server can raise for the operator has a Russian translation in the UI (DEC-034).

The messages are collected from the Python sources (every ``raise <UserError>(...)``), expanded for
f-strings with conditional parts, and each variant is run through the real translation tables with node.
A message with no rule would reach the operator in English, so this test fails when a new one is added
without a translation.
"""
import ast
import itertools
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src" / "titanium_platform"
UI = ROOT / "ui"
USER_ERRORS = {"ValidationError", "IngestError", "ConversionError", "DesignerError", "KnowledgeError", "ProtectedError", "PhotoError", "LightBurnError"}
# Messages also reach the screen as DATA, not only as raised errors. These are the sites that produce such text:
APPEND_TARGETS = {"problems", "notes", "limitations", "diffs", "missing", "why"}   # <name>.append(text) / <x>["name"].append(text)
RETURN_FUNCTIONS = {"attribution_note", "automatic_stage"}                       # return "text" or return (stage, "text")
NOTE_KEYS = {"note"}                                                              # row["note"] = "text" or {"note": "text"}
EVENT_REASON_ARG = 5                                                              # _event(store, id, type, from, to, REASON, ...)
TABLES = ["i18n.js", "i18n-more.js", "i18n-device.js", "i18n-rest.js", "i18n-photo.js", "i18n-data.js"]
PLACEHOLDER = "7"


def variants(node) -> list[str] | None:
    """All strings a message expression can produce; any dynamic part becomes a digit. None if it has no static text."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append([v.value])
            elif isinstance(v, ast.FormattedValue):
                inner = v.value
                if isinstance(inner, ast.IfExp):
                    parts.append((variants(inner.body) or [PLACEHOLDER]) + (variants(inner.orelse) or [PLACEHOLDER]))
                else:
                    parts.append([PLACEHOLDER])
            else:
                return None
        return ["".join(p) for p in itertools.product(*parts)]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = variants(node.left), variants(node.right)
        if left is None and right is None:
            return None
        return [a + b for a in (left or [PLACEHOLDER]) for b in (right or [PLACEHOLDER])]
    if isinstance(node, ast.BoolOp):
        out = [v for sub in node.values for v in (variants(sub) or [])]
        return out or None
    if isinstance(node, ast.IfExp):                       # "text a" if condition else "text b": both reach the screen
        out = (variants(node.body) or []) + (variants(node.orelse) or [])
        return out or None
    return None


def _target_name(value) -> str | None:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Subscript) and isinstance(value.slice, ast.Constant):
        return value.slice.value
    return None


def _is_message(text: str) -> bool:
    return " " in text.strip() or ":" in text   # a lone token such as a stage name is not a message


def raised_messages() -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []

    def add(path, node, expr):
        for text in variants(expr) or []:
            if _is_message(text):
                out.append((path.name, node.lineno, text))

    for path in sorted(ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in RETURN_FUNCTIONS]:
            for r in [n for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]:
                for elt in (r.value.elts if isinstance(r.value, ast.Tuple) else [r.value]):
                    add(path, r, elt)
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
                if getattr(node.exc.func, "id", getattr(node.exc.func, "attr", None)) in USER_ERRORS:
                    add(path, node, node.exc.args[0])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args:
                if node.func.attr == "append" and _target_name(node.func.value) in APPEND_TARGETS:
                    add(path, node, node.args[0])
                elif node.func.attr == "_event" or getattr(node.func, "id", "") == "_event":
                    pass
            elif isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_event" and len(node.args) > EVENT_REASON_ARG:
                add(path, node, node.args[EVENT_REASON_ARG])
            elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add) and isinstance(node.value, ast.ListComp):
                add(path, node, node.value.elt)
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 and _target_name(node.targets[0]) in NOTE_KEYS:
                add(path, node, node.value)
            elif isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value in NOTE_KEYS:
                        add(path, node, value)
            elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Tuple) and isinstance(node.value, ast.Tuple):
                # `rep["compatible"], rep["notes"] = False, ["text"]`: pair each target with its value
                for tgt, val in zip(node.targets[0].elts, node.value.elts):
                    if _target_name(tgt) in {"notes"} and isinstance(val, ast.List):
                        for item in val.elts:
                            add(path, node, item)
    return out


KNOWN_INNER = "a RAW photograph is required for measurement"


def with_known_inner(message: str) -> str:
    """A wrapper such as ``Photograph: {exc}`` ends in a fully dynamic part, which the collector shows as a digit.

    The inner messages are collected and checked on their own, so for the wrapper itself a known translatable
    inner message is substituted: that tests the wrapper rule and its recursion instead of excusing it.
    """
    return message[:-1] + KNOWN_INNER if message.endswith(f": {PLACEHOLDER}") else message


def test_wrapper_messages_are_recognised_and_given_a_translatable_inner_part():
    assert with_known_inner("Photograph: 7") == f"Photograph: {KNOWN_INNER}"
    assert with_known_inner("variance 7 exceeds 7") == "variance 7 exceeds 7"     # only a trailing dynamic part is replaced
    assert with_known_inner("plain message") == "plain message"


def test_the_collector_finds_the_messages_and_expands_conditional_fragments():
    msgs = {m for _, _, m in raised_messages()}
    assert "registration marker layer: not measured" not in msgs  # measured output layers are no longer discarded as service-only geometry
    assert "the plate has no marker definition" in msgs
    assert len(msgs) > 90
    assert "7 must be a finite positive number" in msgs and "7 must be a finite number" in msgs   # both branches of the f-string
    assert any("Reference chart not detected" in m for m in msgs)   # appended to the problems list, not raised
    assert any(m.startswith("variance 7 exceeds") for m in msgs) and any("no original plan" in m for m in msgs)  # data sites are covered too


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_every_raised_message_is_translated(tmp_path):
    msgs = [(f, l, with_known_inner(m)) for f, l, m in raised_messages()]
    (tmp_path / "msgs.json").write_text(json.dumps(msgs), encoding="utf-8")
    script = tmp_path / "run.js"
    script.write_text(
        "const fs=require('fs'),vm=require('vm');\n"
        f"const ui={json.dumps(str(UI) + '/')};\n"
        f"const code={json.dumps(TABLES)}.map(f=>fs.readFileSync(ui+f,'utf8')).join('\\n')+';globalThis.__I=I18N;';\n"
        "const ctx={};vm.createContext(ctx);vm.runInContext(code,ctx);\n"
        f"const msgs=JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'msgs.json'))},'utf8'));\n"
        "const gap=msgs.filter(([f,l,s])=>ctx.__I.tr(s).includes('без перевода')).map(([f,l,s])=>f+':'+l+'  '+s);\n"
        "console.log(JSON.stringify(gap));\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr[:400]
    untranslated = json.loads(run.stdout)
    assert untranslated == [], "server messages without a Russian translation:\n" + "\n".join(untranslated)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_translation_output_for_known_messages_is_russian_and_unknown_ones_are_marked(tmp_path):
    script = tmp_path / "t.js"
    script.write_text(
        "const fs=require('fs'),vm=require('vm');\n"
        f"const ui={json.dumps(str(UI) + '/')};\n"
        f"const code={json.dumps(TABLES)}.map(f=>fs.readFileSync(ui+f,'utf8')).join('\\n')+';globalThis.__I=I18N;';\n"
        "const ctx={};vm.createContext(ctx);vm.runInContext(code,ctx);\n"
        "console.log(JSON.stringify([ctx.__I.tr('A RAW photograph is required for measurement'),ctx.__I.tr('power must be a number'),\n"
        "ctx.__I.tr('some brand new server message'),ctx.__I.tr('')]));\n", encoding="utf-8")
    out = json.loads(subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60, check=True).stdout)
    assert out[0] == "Для измерения требуется фотография RAW" and out[1] == "Мощность — число"
    assert out[2] == "some brand new server message (сообщение сервера, без перевода)"   # a gap is visible, never hidden
    assert out[3] == "Неизвестная ошибка"
