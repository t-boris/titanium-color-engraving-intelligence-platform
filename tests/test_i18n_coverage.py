"""Every message the server can show the operator has a Russian translation in the UI (DEC-034).

The messages are collected from the Python sources of the package and of its API (every ``raise <UserError>(...)``,
including the ``KeyError`` of a record that is not found and the ``HTTPException`` of an upload, and the data sites listed
below), expanded for f-strings with conditional parts, and each variant is run through the real translation tables with
node. A message with no rule would reach the operator in English, so this test fails when a new one is added without a
translation.

A *wrapper* embeds another server message: ``f"Photograph: {exc}"`` in a handler of PhotoError, ``"...: " + "; ".join(x)``
of a list of messages, ``[f"...: {m}" for m in problems]``. The collector follows the embedded part to the messages it can be
(raised with the caught classes, appended to the joined list, returned by the function the list comes from), and every
wrapper is translated with each of those real inner messages and with all of them joined: the translation must contain
the inner message's own translation (it translates recursively) and nothing may stay untranslated.
"""
import ast
import itertools
import json
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src" / "titanium_platform"
UI = ROOT / "ui"
SOURCES = sorted(ROOT.rglob("*.py"))                  # the package and its api/ routes
USER_ERRORS = {"ValidationError", "IngestError", "ConversionError", "DesignerError", "KnowledgeError", "ProtectedError", "PhotoError", "LightBurnError",
               "VectorizeError", "PredictionError", "ResearchError", "ImmutableError", "ZoneError", "FontError", "LabImportError",
               "KeyError",                             # a record that is not found: the API answers 404 with its message
               "CloudError"}                           # the cloud of laboratories refused, is off or unreachable (cloud_http.py, 422)
HTTP_ERRORS = {"HTTPException"}                        # HTTPException(status, {"error": text, ...}) or HTTPException(status, text)
# Messages also reach the screen as DATA, not only as raised errors. These are the sites that produce such text:
APPEND_TARGETS = {"problems", "notes", "limitations", "diffs", "missing", "why", "questions", "worth",
                  "warnings"}                                                    # <name>.append(text) / <x>["name"].append(text)
RETURN_FUNCTIONS = {"attribution_note", "automatic_stage", "supported_stage", "removal_doubt",
                    "_kinetics_note", "_blocker_photo", "_why_not_engraved", "text_blocker"}   # return "text" or (stage, "text")
NOTE_KEYS = {"note", "statement", "rationale",                                   # row["note"] = "text" or {"note": "text"}; findings, proposals
             "measurement", "refused"}                                           # how a layer was sampled; why an anchoring was refused
REASON_ARGS = {"_event": 5, "_record": 3,          # _event(store, id, type, from, to, REASON, ...), _record(store, id, to, REASON, ...)
               "refuse": 0}                        # anchoring's refuse(REASON)
TABLES = ["i18n.js", "i18n-more.js", "i18n-device.js", "i18n-rest.js", "i18n-photo.js", "i18n-tasks.js", "i18n-data.js", "i18n-findings.js",
          "i18n-palette.js", "i18n-lettering.js", "i18n-labs.js", "i18n-workshop.js", "i18n-lan.js", "i18n-cloud.js", "i18n-gaps.js"]
PLACEHOLDER = "7"
HOLE = "\x00"                                      # where a wrapper embeds another server message
LIST_SEPARATOR = "; "                              # several server messages in one are joined with it
JOINED = ("joined",)                               # a source mark: the embedded part is a list of such messages joined
# Wrappers whose embedded message travels through a stored record, where the AST cannot follow it: the text before the
# embedded part, and where that part comes from (the reasons of a questioned knowledge entry, kept in its doubt).
INNER_OF = {
    "this knowledge entry is questioned: ": (("listed", "_breaks_thresholds"), ("returned", "removal_doubt")),
    "flag cleared by the operator: ": (("listed", "_breaks_thresholds"), ("returned", "removal_doubt")),
    "a removed photograph took away the evidence of this stage: what remains supports only 7: ": (
        ("returned", "supported_stage"), ("returned", "automatic_stage")),
    # why a photo zone of a vector work cannot be engraved: the message of its scale's curve, kept in the zone's row (REQ-073)
    "photo zone 7 cannot be engraved: ": (("raised", "PredictionError"),),
    # why an inscription cannot be engraved: its font is gone or unreadable (fonts.FontError), or a reason of lettering._why_not_engraved,
    # kept in its row
    "inscription 7 cannot be engraved: ": (("raised", "FontError"), ("returned", "_why_not_engraved")),
}
# Messages that end in a dynamic part after a colon which is data, not a server message: it is shown as it is.
DATA_TAILS = {
    "plate cells not found in the LightBurn file: ": "the names of the plate cells",
    "cannot decode RAW file: ": "the RAW library's own error text",
    "unknown engraving task: ": "the task key that was sent",
    "settings unknown to this version are kept with the recipe but not interpreted: ": "the LightBurn setting tags of the layer",
    "Google Fonts could not be reached: ": "the network library's own error text",
    "the release cannot be written: ": "the release format's own description of the value it refuses (lab_format.FormatError)",
    "the font 7 could not be downloaded from Google Fonts: ": "the network library's own error text",
    "the cloud could not be reached: ": "the network library's own error text (cloud_http.py)",
    "the sign-in service could not be reached: ": "the network library's own error text (cloud_http.py)",
    "the cloud refused the request: ": "the cloud service's own message (cloud/titanium_cloud, translated by i18n-cloud.js when known) or its HTTP status",
    "the sign-in service refused the request: ": "the sign-in service's own message or its HTTP status",
}
# A handler that passes on the whole message of a caught exception that is not a user error: (file, function) -> the
# module and class whose raised messages reach the operator through it.
PASSTHROUGH = {("ingest.py", "update_matrix"): ("matrix.py", "ValueError"), ("photo_state.py", "rules_in"): ("picture_rules.py", "RuleError")}


class Scope(NamedTuple):
    function: ast.FunctionDef | None
    handlers: dict                     # exception variable -> the class names its handler catches
    comprehensions: dict               # comprehension variable -> the iterated expression
    constants: dict                    # a variable that takes one of a few known texts -> those texts


class Site(NamedTuple):
    file: str
    line: int
    expr: ast.AST
    scope: Scope


def _is_message(text: str) -> bool:
    return " " in text.strip() or ":" in text   # a lone token such as a stage name is not a message


def _target_name(value) -> str | None:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Subscript) and isinstance(value.slice, ast.Constant):
        return value.slice.value
    if isinstance(value, ast.Attribute):
        return value.attr
    return None


def _call_name(node) -> str | None:
    return getattr(node.func, "id", getattr(node.func, "attr", None)) if isinstance(node, ast.Call) else None


def _caught(handler: ast.ExceptHandler) -> frozenset:
    nodes = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return frozenset(getattr(n, "attr", getattr(n, "id", "BaseException")) for n in nodes if n is not None) or frozenset({"BaseException"})


def _texts(node) -> list[str] | None:
    """The texts of a literal tuple or list of strings, or of a ``Literal["a", "b"]`` annotation; None for anything else."""
    if isinstance(node, ast.Subscript) and getattr(node.value, "id", getattr(node.value, "attr", None)) == "Literal":
        node = node.slice if isinstance(node.slice, ast.Tuple) else ast.Tuple([node.slice])
    if isinstance(node, (ast.Tuple, ast.List)) and node.elts and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts):
        return [e.value for e in node.elts]
    return None


def _walk(node, scope: Scope):
    """Every node with the function, exception handlers, comprehension variables and known texts it sits in: a parameter
    annotated ``Literal[...]``, a loop over a literal tuple of texts."""
    yield node, scope
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        params = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        scope = Scope(node, {}, {}, {a.arg: _texts(a.annotation) for a in params if a.annotation is not None and _texts(a.annotation)})
    elif isinstance(node, ast.For) and isinstance(node.target, ast.Name) and _texts(node.iter):
        scope = scope._replace(constants={**scope.constants, node.target.id: _texts(node.iter)})
    elif isinstance(node, ast.ExceptHandler) and node.name:
        scope = scope._replace(handlers={**scope.handlers, node.name: _caught(node)})
    elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
        bound = {g.target.id: g.iter for g in node.generators if isinstance(g.target, ast.Name)}
        scope = scope._replace(comprehensions={**scope.comprehensions, **bound})
    for child in ast.iter_child_nodes(node):
        yield from _walk(child, scope)


class Sources:
    """The Python sources read once: every site that can produce text, and what each list, function and class holds."""

    def __init__(self):
        self.sites: list[Site] = []                       # every place whose text reaches the screen
        self.held: dict[tuple, list[Site]] = {}           # ("raised", class) / ("raised_in", file, class) / ("listed", name) /
                                                          # ("local", function, name) / ("returned", function) -> texts
        self.assigned: dict[tuple, str] = {}              # (function, name) -> the function a local list is returned by
        self.names: dict[tuple[str, str], list[str]] = {}   # (file, NAME) -> the values of a module table of names
        for path in SOURCES:
            self._read(path)

    def _hold(self, key, site: Site) -> None:
        self.held.setdefault(key, []).append(site)

    def _read(self, path: Path) -> None:
        name = str(path.relative_to(ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:             # LABELS = {"power": "Power", ...}: a part such as LABELS[p] is one of its names
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                    and isinstance(node.value, ast.Dict) and node.value.values \
                    and all(isinstance(v, ast.Constant) and isinstance(v.value, str) for v in node.value.values):
                self.names[(name, node.targets[0].id)] = sorted({v.value for v in node.value.values})
        for node, scope in _walk(tree, Scope(None, {}, {}, {})):
            site = lambda expr: Site(name, getattr(node, "lineno", 0), expr, scope)
            fn = scope.function
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
                cls = _call_name(node.exc)
                if cls in HTTP_ERRORS and len(node.exc.args) > 1:
                    detail = node.exc.args[1]
                    if isinstance(detail, ast.Dict):
                        detail = next((v for k, v in zip(detail.keys, detail.values) if isinstance(k, ast.Constant) and k.value == "error"), None)
                    if detail is not None:
                        self.sites.append(site(detail))
                    continue
                self._hold(("raised", cls), site(node.exc.args[0]))
                self._hold(("raised_in", name, cls), site(node.exc.args[0]))
                if cls in USER_ERRORS:
                    self.sites.append(site(node.exc.args[0]))
            elif isinstance(node, ast.Return) and node.value is not None and fn is not None:
                for elt in (node.value.elts if isinstance(node.value, ast.Tuple) else [node.value]):
                    self._hold(("returned", fn.name), site(elt))
                    if fn.name in RETURN_FUNCTIONS:
                        self.sites.append(site(elt))
                if isinstance(node.value, ast.Name):            # a function that returns a list it appended messages to
                    for appended in self.held.get(("local", id(fn), node.value.id), []):
                        self._hold(("listed", fn.name), appended)
            elif isinstance(node, ast.Call) and _call_name(node) == "append" and isinstance(node.func, ast.Attribute) and node.args:
                target = _target_name(node.func.value)
                self._hold(("listed", target), site(node.args[0]))
                if isinstance(node.func.value, ast.Name) and fn is not None:
                    self._hold(("local", id(fn), target), site(node.args[0]))
                if target in APPEND_TARGETS:
                    self.sites.append(site(node.args[0]))
            elif isinstance(node, ast.Call) and _call_name(node) in REASON_ARGS and isinstance(node.func, ast.Name) \
                    and len(node.args) > REASON_ARGS[node.func.id]:
                self.sites.append(site(node.args[REASON_ARGS[node.func.id]]))
            elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add) and isinstance(node.value, ast.ListComp):
                # `notes += [f"...: {m}" for m in problems]`: the element is read with the comprehension's variables
                bound = {g.target.id: g.iter for g in node.value.generators if isinstance(g.target, ast.Name)}
                element = Site(name, node.lineno, node.value.elt,
                               scope._replace(comprehensions={**scope.comprehensions, **bound}))
                self._hold(("listed", _target_name(node.target)), element)
                if fn is not None and isinstance(node.target, ast.Name):
                    self._hold(("local", id(fn), node.target.id), element)
                if _target_name(node.target) in APPEND_TARGETS:
                    self.sites.append(element)
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 and _target_name(node.targets[0]) in NOTE_KEYS:
                self.sites.append(site(node.value))
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                    and fn is not None and isinstance(node.value, ast.Call) and _call_name(node.value):
                self.assigned[(id(fn), node.targets[0].id)] = _call_name(node.value)
            elif isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value in NOTE_KEYS:
                        self.sites.append(site(value))
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Tuple) and isinstance(node.value, ast.Tuple):
                # `rep["compatible"], rep["notes"] = False, ["text"]`: pair each target with its value
                for tgt, val in zip(node.targets[0].elts, node.value.elts):
                    if _target_name(tgt) in {"notes"} and isinstance(val, ast.List):
                        for item in val.elts:
                            self.sites.append(site(item))

    # -- what an embedded part can be ----------------------------------------------------------------------------------
    def _list_source(self, expr, scope: Scope):
        if isinstance(expr, ast.Call) and _call_name(expr) in ("fromkeys", "sorted", "list") and expr.args:
            return self._list_source(expr.args[0], scope)
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):     # rep["notes"] + [...]
            return self._list_source(expr.left, scope)
        if isinstance(expr, ast.Name):
            fn = scope.function
            if fn is not None and ("local", id(fn), expr.id) in self.held:
                return (("local", id(fn), expr.id),)
            called = self.assigned.get((id(fn), expr.id)) if fn is not None else None
            return (("listed", called),) if called and ("listed", called) in self.held else None
        name = _target_name(expr)
        return (("listed", name),) if name and ("listed", name) in self.held else None

    def source(self, expr, site: Site):
        """Where an embedded server message comes from, or None when the part is data."""
        scope = site.scope
        target = expr.args[0] if _call_name(expr) == "str" and len(expr.args) == 1 else expr
        if isinstance(target, ast.Name) and target.id in scope.handlers:
            caught = scope.handlers[target.id]
            if caught & USER_ERRORS:
                return tuple(("raised", c) for c in sorted(caught & USER_ERRORS))
            through = PASSTHROUGH.get((site.file, scope.function.name if scope.function else None))
            return (("raised_in", *through),) if through else None
        if _call_name(expr) == "join" and isinstance(expr.func, ast.Attribute) and isinstance(expr.func.value, ast.Constant) \
                and expr.func.value.value == LIST_SEPARATOR and len(expr.args) == 1:
            listed = self._list_source(expr.args[0], scope)
            return (JOINED, *listed) if listed else None
        if isinstance(expr, ast.Name) and expr.id in scope.comprehensions:
            return self._list_source(scope.comprehensions[expr.id], scope)
        return None

    def expand(self, site: Site) -> list[tuple[str, tuple | None]]:
        """The texts one site can produce: (text, None), or (template with HOLE, the sources of the embedded part)."""
        found = []

        def part(node):
            src = self.source(node, site)
            if src:
                found.append(src)
                return [HOLE]
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
                return self.names.get((site.file, node.value.id))
            if isinstance(node, ast.Name):
                return site.scope.constants.get(node.id)
            return None

        out = []
        for text in variants(site.expr, part) or []:
            if HOLE in text:
                out.append((text, found[0]))
                continue
            prefix = next((p for p in INNER_OF if text == p + PLACEHOLDER), None)
            out.append((prefix + HOLE, INNER_OF[prefix]) if prefix else (text, None))
        return out

    def inner(self, sources: tuple, depth: int = 0) -> list[str]:
        """Every message the embedded part of a wrapper can be; an inner wrapper is expanded with its own inner messages."""
        out: list[str] = []
        for key in sources:
            for site in self.held.get(key, []):
                for text, nested in self.expand(site):
                    if nested is None:
                        out.append(text)
                    elif depth < 2:
                        out += [text.replace(HOLE, m) for m in self.inner(nested, depth + 1)]
        return sorted({t for t in out if _is_message(t)})


def variants(node, part=None) -> list[str] | None:
    """All strings a message expression can produce; any dynamic part becomes a digit, unless ``part`` knows it: an embedded
    server message becomes HOLE, a value of a fixed table of names (``LABELS[p]``) each of its names. None if it has no
    static text."""
    known = part(node) if part is not None and not isinstance(node, (ast.Constant, ast.JoinedStr)) else None
    if known is not None:
        return known
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append([v.value])
            elif isinstance(v, ast.FormattedValue):
                inner = v.value
                known = part(inner) if part is not None else None
                if known is not None:
                    parts.append(known)
                elif isinstance(inner, ast.IfExp):
                    parts.append((variants(inner.body) or [PLACEHOLDER]) + (variants(inner.orelse) or [PLACEHOLDER]))
                else:
                    parts.append([PLACEHOLDER])
            else:
                return None
        return ["".join(p) for p in itertools.product(*parts)]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = variants(node.left, part), variants(node.right, part)
        if left is None and right is None:
            return None
        return [a + b for a in (left or [PLACEHOLDER]) for b in (right or [PLACEHOLDER])]
    if isinstance(node, ast.BoolOp):
        out = [v for sub in node.values for v in (variants(sub, part) or [])]
        return out or None
    if isinstance(node, ast.IfExp):                       # "text a" if condition else "text b": both reach the screen
        out = (variants(node.body, part) or []) + (variants(node.orelse, part) or [])
        return out or None
    return None


_SOURCES: Sources | None = None


def sources() -> Sources:
    global _SOURCES
    if _SOURCES is None:
        _SOURCES = Sources()
    return _SOURCES


def raised_messages() -> list[tuple[str, int, str]]:
    """Every message as it reaches the screen with no other server message embedded in it: (file, line, text)."""
    out = []
    for site in sources().sites:
        for text, nested in sources().expand(site):
            if nested is None and _is_message(text):
                out.append((site.file, site.line, text))
    return out


def wrappers() -> list[tuple[str, int, str, tuple]]:
    """Every message that embeds another server message: (file, line, template with HOLE, where the embedded part comes from)."""
    out = []
    for site in sources().sites:
        for text, nested in sources().expand(site):
            if nested is not None:
                out.append((site.file, site.line, text, nested))
    return out


def wrapped_cases() -> list[tuple[str, int, str, list[str]]]:
    """Each wrapper filled with each real inner message, and with all of them joined as a list: (file, line, message, the
    inner messages it holds). A wrapper with nothing but the embedded part passes on a message that is checked on its own,
    unless it is a list or a class that is not a user error."""
    out = []
    for file, line, template, nested in wrappers():
        inner = sources().inner(nested)
        joined = JOINED in nested or any(source == ("listed", "_breaks_thresholds") for source in nested)   # a doubt's reasons
        whole = template == HOLE and not joined and not any(kind == "raised_in" for kind, *_ in nested)
        if whole:
            continue
        out += [(file, line, template.replace(HOLE, m), [m]) for m in inner]
        if joined and len(inner) > 1:
            out.append((file, line, template.replace(HOLE, LIST_SEPARATOR.join(inner)), inner))
        if not inner:
            out.append((file, line, template, []))           # nothing found to embed: reported by the test
    return out


MARK = "без перевода"
NODE = "const fs=require('fs'),vm=require('vm');\n" \
       f"const ui={json.dumps(str(UI) + '/')};\n" \
       f"const code={json.dumps(TABLES)}.map(f=>fs.readFileSync(ui+f,'utf8')).join('\\n')+';globalThis.__I=I18N;';\n" \
       "const ctx={};vm.createContext(ctx);vm.runInContext(code,ctx);const tr=ctx.__I.tr;\n"


def run_node(tmp_path, data, body: str):
    """Run ``body`` (JavaScript with ``tr`` and ``data``) against the real translation tables; its printed JSON is returned."""
    (tmp_path / "data.json").write_text(json.dumps(data), encoding="utf-8")
    script = tmp_path / "run.js"
    script.write_text(NODE + f"const data=JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'data.json'))},'utf8'));\n" + body,
                      encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[:400]
    return json.loads(run.stdout)


def test_the_collector_finds_the_messages_and_expands_conditional_fragments():
    msgs = {m for _, _, m in raised_messages()}
    assert "registration marker layer: not measured" not in msgs  # measured output layers are no longer discarded as service-only geometry
    assert "the plate has no marker definition" in msgs
    assert len(msgs) > 90
    assert "7 must be a finite positive number" in msgs and "7 must be a finite number" in msgs   # both branches of the f-string
    assert any("Reference chart not detected" in m for m in msgs)   # appended to the problems list, not raised
    assert any(m.startswith("variance 7 exceeds") for m in msgs) and any("no original plan" in m for m in msgs)  # data sites are covered too


def test_records_not_found_and_the_api_routes_are_collected():
    found = {(f, m) for f, _, m in raised_messages()}
    assert ("plans.py", "plan 7 not found") in found and ("designer.py", "proposal 7 not found") in found        # KeyError: 404
    assert ("api/routes_plans.py", "active input pairs are linked to this plan; delete those pairs first") in found  # ProtectedError
    assert ("api/routes_vector.py", "the palette must be a JSON list of sRGB colours") in found                      # in api/
    assert ("api/common.py", "choose the 7 file") in found                                                          # HTTPException
    assert ("db.py", "observation 7 is immutable; model-derived values are stored separately") in found            # ImmutableError


def test_wrappers_are_followed_to_the_real_messages_they_embed():
    found: dict[tuple[str, str], list[str]] = {}
    for f, _, t, n in wrappers():
        found.setdefault((f, t), []).extend(sources().inner(n))
    assert "pulse width is missing from this LightBurn layer" in found[("ingest.py", f"not comparable within this laser and lens: {HOLE}")]
    assert "a RAW photograph is required for measurement" in found[("ingest.py", f"Photograph: {HOLE}")]
    assert "the setting along the columns is not known" in found[("ingest.py", f"the matrix settings are incomplete: {HOLE}")]
    assert any(m.startswith("Reference chart not detected") for m in found[("ingest.py", f"resolve the problems found by the check: {HOLE}")])
    assert "power 7 % is outside 0-100" in found[("plans.py", f"the saved marker layer settings are not offered by this laser: {HOLE}")]
    assert "unknown setting 7" in found[("ingest.py", HOLE)]                                   # matrix.py passes through update_matrix
    assert "variance 7 exceeds 7" in found[("findings.py", f"this knowledge entry is questioned: {HOLE}")]
    assert all(found.values()), [key for key, inner in found.items() if not inner]          # every wrapper embeds something real


def test_every_message_that_ends_in_a_dynamic_part_is_a_wrapper_or_named_data():
    """A new ``"...: {x}"`` is either followed to the server messages it embeds or declared data here, never left unknown."""
    tails = sorted({m for _, _, m in raised_messages() if m.endswith(f": {PLACEHOLDER}") and not any("\u0400" <= c <= "\u04ff" for c in m)})
    unknown = [m for m in tails if not any(m.startswith(prefix) for prefix in DATA_TAILS)]
    assert unknown == [], "classify these in INNER_OF (it embeds a server message) or DATA_TAILS (it ends in data):\n" + "\n".join(unknown)
    templates = [t for _, _, t, _ in wrappers()]
    assert all(any(t == prefix + HOLE for t in templates) for prefix in INNER_OF)          # no stale entry
    assert all(any(m.startswith(prefix) for m in tails) for prefix in DATA_TAILS)


def test_a_message_passed_on_whole_comes_from_a_user_error_or_is_named():
    """``raise IngestError(str(exc))`` shows the caught message itself: a class that is not a user error must say here which
    module's messages pass, so they are collected too."""
    loose = []
    for site in sources().sites:
        target = site.expr.args[0] if _call_name(site.expr) == "str" and len(site.expr.args) == 1 else site.expr
        if isinstance(target, ast.Name) and target.id in site.scope.handlers and not site.scope.handlers[target.id] & USER_ERRORS:
            if (site.file, site.scope.function.name if site.scope.function else None) not in PASSTHROUGH:
                loose.append(f"{site.file}:{site.line}")
    assert loose == [], "name the module whose messages pass here in PASSTHROUGH: " + ", ".join(loose)
    passed = {key for _, _, t, nested in wrappers() for key in nested if t == HOLE and key[0] == "raised_in"}
    assert passed == {("raised_in", *through) for through in PASSTHROUGH.values()}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_every_raised_message_is_translated(tmp_path):
    untranslated = run_node(tmp_path, raised_messages(),
                            f"console.log(JSON.stringify(data.filter(([f,l,s])=>tr(s).includes('{MARK}')).map(([f,l,s])=>f+':'+l+'  '+s)));\n")
    assert untranslated == [], "server messages without a Russian translation:\n" + "\n".join(untranslated)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_every_wrapper_translates_the_real_messages_it_embeds(tmp_path):
    """Each wrapper with each inner message it can carry (and all of them as one list): no part stays untranslated and the
    inner message reads as its own translation inside the wrapper's."""
    cases = wrapped_cases()
    assert len(cases) > 200
    failed = run_node(tmp_path, cases, (
        "const low=(s)=>s.toLowerCase();\n"
        "console.log(JSON.stringify(data.filter(([f,l,s,inner])=>{const out=tr(s);\n"
        f"  return out.includes('{MARK}')||inner.some((m)=>tr(m).includes('{MARK}')||!low(out).includes(low(tr(m))));}})\n"
        "  .map(([f,l,s])=>f+':'+l+'  '+s+'  ->  '+tr(s))));\n"))
    assert failed == [], f"{len(failed)} wrapped messages do not translate what they embed:\n" + "\n".join(failed[:60])


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_findings_and_proposal_texts_read_in_russian_with_their_numbers_and_nested_reasons(tmp_path):
    """REQ-022 texts are data: a finding's statement, a questioned entry's joined reasons, a proposal's reason for a set."""
    script = tmp_path / "t.js"
    cases = ["no accepted evidence for line on this titanium with this laser and lens",
             "this knowledge entry is questioned: variance 3.20 exceeds 2; deviation 5.00 exceeds 4",
             "aimed at target colour 3: the model predicts 1.9 ΔE from it at these settings",
             "Which settings reproduce target colour 1 (L 70.0, a -5.0, b 20.0)?"]
    script.write_text(
        "const fs=require('fs'),vm=require('vm');\n"
        f"const ui={json.dumps(str(UI) + '/')};\n"
        f"const code={json.dumps(TABLES)}.map(f=>fs.readFileSync(ui+f,'utf8')).join('\\n')+';globalThis.__I=I18N;';\n"
        "const ctx={};vm.createContext(ctx);vm.runInContext(code,ctx);\n"
        f"console.log(JSON.stringify({json.dumps(cases)}.map((s)=>ctx.__I.tr(s))));\n", encoding="utf-8")
    out = json.loads(subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60, check=True).stdout)
    assert out[0] == "Нет принятых данных для задачи «линии» на этой заготовке титана с этим лазером и этой линзой"
    assert out[1] == "Запись знания под вопросом: дисперсия 3.20 превышает порог 2; отклонение 5.00 превышает допуск 4"
    assert out[2] == "Нацелен на целевой цвет № 3: модель прогнозирует 1.9 ΔE от него при этих настройках"
    assert out[3] == "Какие настройки воспроизводят целевой цвет № 1 (L 70.0, a -5.0, b 20.0)?"


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


# -- server vocabulary the screens print as data (DEC-034 audit of 2026-10-18) ------------------------------------------------
def test_the_screens_print_the_servers_english_vocabulary_through_a_translation():
    """Fields that are not messages but English words of the server: the kind of an experiment (a plan mode), a designer plate's
    name, the status of a pair, the role of a layer, a research goal, a guide plate's test type, a waveform without a title, a
    dither mode, the default reason of a demotion."""
    screen = lambda name: (UI / "screens" / name).read_text(encoding="utf-8")
    assert "I18N.name(e.kind)" in screen("experiment-cards.js") and "I18N.name(e.title)" in screen("experiment-cards.js")
    assert "I18N.name(exp.kind)" in screen("experiment.js") and "I18N.name(exp.plate.mode)" in screen("experiment.js")
    assert "I18N.name(p.name)" in screen("plan.js") and "PAIR_STATUS[set.status]" in screen("colors.js")
    assert "ROLE[l.role]" in screen("ingest-dialogs.js") and "goalNames[c.purpose]" in screen("findings.js")
    assert "PLATE_TYPE[guide.plate.test_type]" in screen("experiments.js") and "PhotoModes.label(layer.dither)" in screen("photo-preview.js")
    assert "I18N.name(w.title)" in screen("device-report.js") and "I18N.name(w.title)" in screen("device-plots.js")
    assert "I18N.known(e.reason) ?? e.reason" in screen("knowledge.js") and "I18N.name(r.name)" in screen("ingest-upload.js")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_plan_modes_designer_plates_and_server_lists_read_in_russian(tmp_path):
    names = ["Calibration plate", "Tonal photo engraving", "Plate TCE-0A1B2C3D (speed 900)", "waveform", "Photo capture (no rig)", "Мой тест"]
    texts = ["manual demotion", "моё основание", "power 7 % is outside 0-100; frequency 3 kHz is outside 1-4",
             "resolve the problems found by the check: Alignment: only 2 registration markers detected; at least three are needed; "
             "Reference chart not detected: no observations will be created.",
             "plan 12 not found", "experiment plate-3 not found",
             "not comparable to this hardware/search setup: pulse width is missing from this LightBurn layer"]   # stored by older versions
    out = run_node(tmp_path, {"names": names, "texts": texts},
                   "console.log(JSON.stringify([data.names.map((n)=>ctx.__I.name(n)), data.texts.map((s)=>ctx.__I.known(s)), "
                   "data.texts.map((s)=>tr(s))]));\n")
    assert out[0] == ["Калибровочная матрица", "Тональная фотогравировка", "Плата TCE-0A1B2C3D (скорость 900 мм/с)", "Форма импульса",
                      "Съёмка без установки (ранние фотографии)", "Мой тест"]
    assert out[1][0] == "ручное понижение" and out[1][1] is None                     # the operator's own words are not a message
    assert out[2][2] == "Мощность 7 % вне диапазона лазера 0–100; Частота 3 kHz вне диапазона лазера 1–4"
    assert out[2][3] == ("Устраните проблемы, найденные проверкой: Распознано меток: 2. Для надёжного совмещения нужны минимум три; "
                         "Эталонная карта не обнаружена. Наблюдения не будут созданы.")
    assert out[2][4:] == ["План № 12 не найден", "Эксперимент plate-3 не найден",
                          "Не сопоставим в пределах этого лазера и линзы: В этом слое LightBurn не задан Q-Pulse"]
