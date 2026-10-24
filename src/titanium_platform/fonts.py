"""The fonts an inscription is set in (feature inscriptions-in-works, REQ-001, DEC-001, DEC-002).

Three sources make one catalogue:

* ``mac``: the fonts installed on this Mac (``MAC_DIRS``), read where they are and never copied;
* ``own``: font files the operator added (TTF, OTF, TTC), kept in the data folder (``fonts/own``);
* ``google``: Google Fonts. Every family is listed from Google's public metadata (its category, scripts and popularity) and the files of
  its folder in Google's repository (``index.json``, fetched once and again on request); a family is downloaded into ``fonts/google/<its
  folder>`` the first time it is shown or chosen, or many at once in the background (:func:`start_download`).

A face is one style of a family: a font of a file (a collection holds several), or a named instance of a variable font (its axes set to
the instance's coordinates). It is known by an id made from its source, its path inside the source and its index or instance, so it stays
the same while the file does; an inscription also keeps the family and style names, so a font that moved is found again by them
(:func:`resolve`). What a face covers (``scripts``) is read from its character map; its kind (serif, sans serif, handwriting, display,
monospace, symbol) from Google's category, else from the font's PANOSE and family class.

Reading every file takes seconds (about 3 s for the Mac's 470 files), so what was read is kept in ``fonts/catalogue.json`` with each
file's size and modification time: a listing reads only files that are new or changed. HarfBuzz fonts (:func:`hb_font`) are kept for the
faces used last.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import urllib.request
from collections import OrderedDict
from pathlib import Path

import uharfbuzz as hb
from fontTools.ttLib import TTCollection, TTFont

from . import setup as su

logging.getLogger("fontTools").setLevel(logging.ERROR)        # the Mac's own fonts trip harmless warnings ("extra bytes in post")

MAC, OWN, GOOGLE = "mac", "own", "google"
SOURCES = (MAC, OWN, GOOGLE)
MAC_DIRS = ("/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts", "~/Library/Fonts")
SUFFIXES = (".ttf", ".otf", ".ttc")
MAX_OWN_BYTES = 64 * 1024 * 1024
# a script is covered when every one of its sample letters is in the font
SCRIPTS = {"latin": "AaZz", "cyrillic": "АаЯяЖж", "greek": "ΑαΩω", "hebrew": "אבשת", "arabic": "ابتج", "armenian": "Աաֆ",
           "georgian": "აბგ", "devanagari": "कखग", "thai": "กขค", "japanese": "あア", "korean": "한국", "chinese": "中文"}
KINDS = ("serif", "sans", "handwriting", "display", "monospace", "symbol", "other")
GOOGLE_KINDS = {"Serif": "serif", "Sans Serif": "sans", "Handwriting": "handwriting", "Display": "display", "Monospace": "monospace"}
# Google's subsets as our scripts
GOOGLE_SCRIPTS = {"latin": "latin", "cyrillic": "cyrillic", "greek": "greek", "hebrew": "hebrew", "arabic": "arabic", "armenian": "armenian",
                  "georgian": "georgian", "devanagari": "devanagari", "thai": "thai", "japanese": "japanese", "korean": "korean",
                  "chinese-simplified": "chinese", "chinese-traditional": "chinese", "chinese-hongkong": "chinese"}
GOOGLE_METADATA = "https://fonts.google.com/metadata/fonts"
GOOGLE_TREE = "https://api.github.com/repos/google/fonts/git/trees/main?recursive=1"
GOOGLE_RAW = "https://raw.githubusercontent.com/google/fonts/main/"
GOOGLE_LICENCES = ("ofl", "apache", "ufl")
TIMEOUT_S = 60
FRESH_S = 5.0                     # a listing made this long ago is used again unless a font was added or downloaded since
KEEP_FONTS = 48                   # HarfBuzz fonts kept for the faces used last
CATALOGUE_VERSION = 2               # 2: a cap height a font does not state is read as unknown (it was -1 for some Mac fonts)

_lock = threading.RLock()
_listed: dict = {}                # data folder -> {"at": time, "faces": {...}, "families": [...]}
_fonts: OrderedDict = OrderedDict()
_download = {"running": False, "done": 0, "total": 0, "failed": [], "current": None, "error": None}


# -- where fonts are ---------------------------------------------------------------------------------------------------------------
def _root(data_dir: Path) -> Path:
    return Path(data_dir) / "fonts"


def own_dir(data_dir: Path) -> Path:
    return _root(data_dir) / "own"


def google_dir(data_dir: Path) -> Path:
    return _root(data_dir) / "google"


def _font_files(folder: Path, recursive: bool = False) -> list[Path]:
    if not folder.is_dir():
        return []
    found = folder.rglob("*") if recursive else folder.iterdir()
    return sorted(p for p in found if p.is_file() and p.suffix.lower() in SUFFIXES)


def _files(data_dir: Path) -> list[tuple[str, Path, Path]]:
    """Every font file with its source and the folder its id is relative to."""
    out = []
    for folder in MAC_DIRS:
        root = Path(os.path.expanduser(folder))
        out += [(MAC, root, p) for p in _font_files(root)]
    out += [(OWN, own_dir(data_dir), p) for p in _font_files(own_dir(data_dir))]
    out += [(GOOGLE, google_dir(data_dir), p) for p in _font_files(google_dir(data_dir), recursive=True)]
    return out


def _stamp(path: Path) -> list[int]:
    st = path.stat()
    return [st.st_size, st.st_mtime_ns]


# -- reading one file ----------------------------------------------------------------------------------------------------------------
def _name(font: TTFont, *ids: int) -> str:
    table = font["name"]
    for i in ids:
        value = table.getDebugName(i)
        if value:
            return value.strip()
    return ""


def _kind(font: TTFont, family: str) -> str:
    """Serif, sans serif, handwriting, display, monospace or symbol, from the font's own classification (PANOSE, the IBM family class), else
    from its name."""
    os2 = font["OS/2"] if "OS/2" in font else None
    if "post" in font and font["post"].isFixedPitch:
        return "monospace"
    if os2 is not None:
        panose = os2.panose
        if panose.bProportion == 9 and panose.bFamilyType == 2:
            return "monospace"
        if panose.bFamilyType == 3:
            return "handwriting"
        if panose.bFamilyType == 4:
            return "display"
        if panose.bFamilyType == 5:
            return "symbol"
        cls = (os2.sFamilyClass >> 8) & 0xFF
        if cls in (1, 2, 3, 4, 5, 7):
            return "serif"
        if cls == 8:
            return "sans"
        if cls == 9:
            return "display"
        if cls == 10:
            return "handwriting"
        if cls == 12:
            return "symbol"
        if panose.bFamilyType == 2:
            return "sans" if panose.bSerifStyle in (11, 12, 13, 14, 15) else "serif" if 2 <= panose.bSerifStyle <= 10 else _named_kind(family)
    return _named_kind(family)


def _named_kind(family: str) -> str:
    low = family.lower()
    for words, kind in ((("mono", "code", "courier"), "monospace"), (("sans", "gothic", "grotesk", "helvetica", "arial"), "sans"),
                        (("serif", "roman", "times", "garamond"), "serif"), (("script", "hand", "brush", "chancery", "cursive"), "handwriting"),
                        (("symbol", "dings", "emoji"), "symbol")):
        if any(w in low for w in words):
            return kind
    return "other"


def _metrics(font: TTFont) -> dict:
    """The face's units per em, cap height and line height (ascender - descender + line gap), in font units; a cap height the font does
    not state (0, or -1 as some Mac fonts write) is None: the letters measure it."""
    upem = font["head"].unitsPerEm
    os2 = font["OS/2"] if "OS/2" in font else None
    hhea = font["hhea"] if "hhea" in font else None
    cap = getattr(os2, "sCapHeight", 0) if os2 is not None and os2.version >= 2 else 0
    if hhea is not None and hhea.ascent - hhea.descent > 0:
        line = hhea.ascent - hhea.descent + hhea.lineGap
    elif os2 is not None:
        line = os2.sTypoAscender - os2.sTypoDescender + os2.sTypoLineGap
    else:
        line = upem * 1.2
    return {"upem": upem, "cap": cap if cap > 0 else None, "line": line if line > 0 else upem * 1.2}


def _faces_of(source: str, root: Path, path: Path) -> list[dict]:
    """The faces of one font file: every font of a collection, every named instance of a variable font. Hidden system fonts (a name that
    starts with a dot), fonts without outlines (bitmap or colour emoji) and fonts that cannot be read are left out."""
    try:
        count = len(TTCollection(str(path), lazy=True).fonts) if path.suffix.lower() == ".ttc" else 1
    except Exception:
        return []
    rel = str(path.relative_to(root))
    out = []
    for index in range(count):
        try:
            font = TTFont(str(path), fontNumber=index, lazy=True)
            family, style = _name(font, 16, 1), _name(font, 17, 2) or "Regular"
            if not family or family.startswith(".") or family == "LastResort":
                continue
            if not ("glyf" in font or "CFF " in font or "CFF2" in font):
                continue
            cmap = font.getBestCmap() or {}
            if not cmap:
                continue
            scripts = [name for name, sample in SCRIPTS.items() if all(ord(c) in cmap for c in sample)]
            os2 = font["OS/2"] if "OS/2" in font else None
            weight = int(getattr(os2, "usWeightClass", 400) or 400)
            italic = bool(getattr(os2, "fsSelection", 0) & 1) or "italic" in style.lower() or "oblique" in style.lower()
            common = {"source": source, "path": str(path), "rel": rel, "index": index, "family": family, "kind": _kind(font, family),
                      "scripts": scripts, **_metrics(font)}
            instances = []
            if "fvar" in font:
                fvar = font["fvar"]
                for inst in fvar.instances:
                    name = _instance_name(font, inst.subfamilyNameID) or style
                    coords = {k: round(float(v), 3) for k, v in inst.coordinates.items()}
                    instances.append((name, coords))
            if instances:
                for name, coords in instances:
                    out.append({**common, "id": _id(source, rel, index, name), "style": name, "coords": coords,
                                "weight": int(round(coords.get("wght", weight))),
                                "italic": italic or coords.get("ital", 0) >= 1 or coords.get("slnt", 0) < 0 or "italic" in name.lower()})
            else:
                out.append({**common, "id": _id(source, rel, index, ""), "style": style, "coords": None, "weight": weight, "italic": italic})
        except Exception:
            continue
    seen, unique = set(), []
    for face in out:                       # a variable font may name one instance twice
        if face["id"] not in seen:
            seen.add(face["id"])
            unique.append(face)
    return unique


def _instance_name(font: TTFont, name_id: int) -> str:
    value = font["name"].getDebugName(name_id) if name_id else None
    return value.strip() if value else ""


def _id(source: str, rel: str, index: int, instance: str) -> str:
    return hashlib.sha1(f"{source}|{rel}|{index}|{instance}".encode("utf-8")).hexdigest()[:16]


# -- the catalogue ---------------------------------------------------------------------------------------------------------------
def _cache_path(data_dir: Path) -> Path:
    return _root(data_dir) / "catalogue.json"


def _read_cache(data_dir: Path) -> dict:
    try:
        cached = json.loads(_cache_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return cached.get("files", {}) if cached.get("version") == CATALOGUE_VERSION else {}


def _write_cache(data_dir: Path, files: dict) -> None:
    path = _cache_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": CATALOGUE_VERSION, "files": files}), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass                                 # a catalogue that cannot be kept is read again next time


def _forget(data_dir: Path) -> None:
    with _lock:
        _listed.pop(str(Path(data_dir)), None)


def faces(data_dir: Path) -> dict[str, dict]:
    """Every face of every source by its id (:func:`_faces_of`), read from the files that changed since the last listing."""
    return _listing(data_dir)["faces"]


def _listing(data_dir: Path) -> dict:
    key = str(Path(data_dir))
    with _lock:
        known = _listed.get(key)
        if known and time.monotonic() - known["at"] < FRESH_S:
            return known
        cached = _read_cache(data_dir)
        files, changed = {}, False
        for source, root, path in _files(data_dir):
            try:
                stamp = _stamp(path)
            except OSError:
                continue
            entry = cached.get(str(path))
            if entry is None or entry.get("stamp") != stamp:
                entry = {"stamp": stamp, "faces": _faces_of(source, root, path)}
                changed = True
            files[str(path)] = entry
        if changed or set(files) != set(cached):
            _write_cache(data_dir, files)
        by_id = {face["id"]: face for entry in files.values() for face in entry["faces"]}
        listing = {"at": time.monotonic(), "faces": by_id}
        _listed[key] = listing
        return listing


class FontError(su.ValidationError):
    """The font an inscription needs is not on this computer or cannot be read: the inscription says so and is not engraved."""


def face(data_dir: Path, face_id: str) -> dict:
    """One face by its id; KeyError when no font has it."""
    found = faces(data_dir).get(face_id)
    if found is None:
        raise KeyError(f"there is no font {face_id!r}")
    return found


def resolve(data_dir: Path, wanted) -> dict:
    """The face an inscription names (``{"face", "family", "style"}``): by its id, else by its family and style (the font moved or was
    downloaded again), else the family's regular style; FontError when no font of that family is here."""
    if not isinstance(wanted, dict):
        raise FontError("choose the font of the inscription")
    known = faces(data_dir)
    found = known.get(wanted.get("face")) if isinstance(wanted.get("face"), str) else None
    if found is not None:
        return found
    family, style = wanted.get("family"), wanted.get("style")
    same = [f for f in known.values() if f["family"] == family]
    if not same:
        raise FontError(f"the font {family or wanted.get('face')!r} is not on this computer any more: choose another font")
    return next((f for f in same if f["style"] == style), None) or _regular(same)


def _regular(same: list[dict]) -> dict:
    return min(same, key=lambda f: (f["italic"], abs(f["weight"] - 400), f["style"] != "Regular", f["style"]))


def described(face_: dict) -> dict:
    """A face as the screen and an inscription name it."""
    return {"face": face_["id"], "family": face_["family"], "style": face_["style"]}


def families(data_dir: Path) -> dict:
    """The catalogue as the font window shows it: every family of every source with its faces (lightest upright first), the face it opens
    on (``regular``), kind, scripts and source, and each Google family not downloaded yet (``downloaded`` false, no faces) from the Google
    index when it was fetched."""
    grouped: dict[tuple[str, str], list[dict]] = {}
    for f in faces(data_dir).values():
        grouped.setdefault((f["source"], f["family"]), []).append(f)
    index = google_index(data_dir, fetch=False)
    meta = index["families"] if index else {}
    out = []
    for (source, family), members in grouped.items():
        members.sort(key=lambda f: (f["italic"], f["weight"], f["style"]))
        scripts = sorted({s for f in members for s in f["scripts"]}, key=list(SCRIPTS).index)
        info = meta.get(family) if source == GOOGLE else None
        out.append({"family": family, "source": source, "kind": GOOGLE_KINDS.get(info["category"], members[0]["kind"]) if info else members[0]["kind"],
                    "scripts": scripts, "downloaded": True, "popularity": info["popularity"] if info else None,
                    "faces": [{"id": f["id"], "style": f["style"], "weight": f["weight"], "italic": f["italic"]} for f in members],
                    "regular": _regular(members)["id"]})
    present = {family for source, family in grouped if source == GOOGLE}
    for family, info in meta.items():
        if family not in present:
            out.append({"family": family, "source": GOOGLE, "kind": GOOGLE_KINDS.get(info["category"], "other"), "scripts": info["scripts"],
                        "downloaded": False, "popularity": info["popularity"], "faces": [], "size": sum(s for _, s in info["files"])})
    out.sort(key=lambda f: (f["family"].lower(), SOURCES.index(f["source"])))
    with _lock:
        status = dict(_download, failed=list(_download["failed"]))
    return {"families": out, "scripts": list(SCRIPTS), "kinds": list(KINDS), "sources": list(SOURCES),
            "google": {"listed": index is not None, "fetched_at": index["fetched_at"] if index else None, "families": len(meta),
                       "downloaded": len(present), "download": status}}


# -- the operator's own fonts --------------------------------------------------------------------------------------------------------
def add_own(data_dir: Path, file_name: str, data: bytes) -> list[dict]:
    """Keep an uploaded font file among the operator's fonts; its faces as :func:`described` names them. ValidationError when it is not a
    font with outlines."""
    suffix = Path(file_name or "").suffix.lower()
    if suffix not in SUFFIXES:
        raise su.ValidationError("a font file must be TTF, OTF or TTC")
    if len(data) > MAX_OWN_BYTES:
        raise su.ValidationError(f"the font file is larger than {MAX_OWN_BYTES // (1024 * 1024)} MB")
    stem = re.sub(r"[^\w.-]+", "-", Path(file_name).stem).strip("-.") or "font"
    folder = own_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stem}{suffix}"
    n = 1
    while path.exists() and path.read_bytes() != data:
        n += 1
        path = folder / f"{stem}-{n}{suffix}"
    path.write_bytes(data)
    found = _faces_of(OWN, folder, path)
    if not found:
        path.unlink(missing_ok=True)
        raise su.ValidationError("this file is not a font that can be engraved: it has no outlines or cannot be read")
    _forget(data_dir)
    return [described(f) for f in found]


def remove_own(data_dir: Path, face_id: str) -> None:
    """Take the operator's font file of this face away (every face of that file goes with it)."""
    found = face(data_dir, face_id)
    if found["source"] != OWN:
        raise su.ValidationError("only a font you added can be removed here")
    Path(found["path"]).unlink(missing_ok=True)
    _forget(data_dir)


# -- Google Fonts --------------------------------------------------------------------------------------------------------------------
def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "titanium-platform"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:           # noqa: S310 - fixed https addresses
        return response.read()


def _index_path(data_dir: Path) -> Path:
    return google_dir(data_dir) / "index.json"


def google_index(data_dir: Path, fetch: bool = True, refresh: bool = False) -> dict | None:
    """Google's families (category, our scripts, popularity, the repository folder and its font files with their sizes), fetched once and
    kept in ``fonts/google/index.json``; None when it was never fetched and ``fetch`` is false. ValidationError when Google cannot be
    reached."""
    path = _index_path(data_dir)
    if not refresh:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            if not fetch:
                return None
    try:
        raw = _get(GOOGLE_METADATA).decode("utf-8")
        meta = json.loads(raw[raw.index("{"):])["familyMetadataList"]
        tree = json.loads(_get(GOOGLE_TREE).decode("utf-8"))["tree"]
    except Exception as exc:
        raise su.ValidationError(f"Google Fonts could not be reached: {type(exc).__name__}") from None
    folders: dict[str, list] = {}
    for item in tree:
        parts = item["path"].split("/")
        if item["type"] == "blob" and len(parts) == 3 and parts[0] in GOOGLE_LICENCES and parts[2].lower().endswith((".ttf", ".otf")):
            folders.setdefault(parts[1], []).append([item["path"], int(item.get("size") or 0)])
    out = {}
    for f in meta:
        folder = re.sub(r"[^a-z0-9]", "", f["family"].lower())
        if folder not in folders:
            continue
        scripts = sorted({GOOGLE_SCRIPTS[s] for s in f.get("subsets", []) if s in GOOGLE_SCRIPTS}, key=list(SCRIPTS).index)
        out[f["family"]] = {"category": f.get("category"), "scripts": scripts, "popularity": f.get("popularity"), "folder": folder,
                            "files": folders[folder]}
    index = {"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "families": out}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(index), encoding="utf-8")
    tmp.replace(path)
    return index


def download(data_dir: Path, family: str) -> list[dict]:
    """Download one Google family (every file of its folder) unless it is here already; its faces (:func:`described`)."""
    index = google_index(data_dir)
    info = index["families"].get(family)
    if info is None:
        raise su.ValidationError(f"Google Fonts has no family {family!r}")
    folder = google_dir(data_dir) / info["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    for repo_path, size in info["files"]:
        target = folder / repo_path.split("/")[-1]
        if target.exists() and (not size or target.stat().st_size == size):
            continue
        try:
            data = _get(GOOGLE_RAW + urllib.request.quote(repo_path))
        except Exception as exc:
            raise su.ValidationError(f"the font {family!r} could not be downloaded from Google Fonts: {type(exc).__name__}") from None
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(target)
    _forget(data_dir)
    return [described(f) for f in faces(data_dir).values() if f["source"] == GOOGLE and f["family"] == family]


def google_faces(data_dir: Path, family: str) -> list[dict]:
    """The faces of a Google family, downloaded first when they are not here yet."""
    if not isinstance(family, str) or not family:
        raise su.ValidationError("say which Google family to download")
    here = [f for f in faces(data_dir).values() if f["source"] == GOOGLE and f["family"] == family]
    if here:
        return [described(f) for f in here]
    return download(data_dir, family)


def start_download(data_dir: Path, wanted: dict) -> dict:
    """Download many Google families in the background: the families named (``families``), or every family of a script (``script``) and/or
    kind (``kind``) not downloaded yet; the progress is :func:`download_status`. Only one such download runs at a time."""
    index = google_index(data_dir)
    if not isinstance(wanted, dict):
        raise su.ValidationError("say which Google families to download")
    names = wanted.get("families")
    if names is not None:
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise su.ValidationError("say which Google families to download")
        chosen = [n for n in names if n in index["families"]]
    else:
        script, kind = wanted.get("script"), wanted.get("kind")
        if script is not None and script not in SCRIPTS:
            raise su.ValidationError(f"unknown script {script!r}")
        if kind is not None and kind not in KINDS:
            raise su.ValidationError(f"unknown kind of font {kind!r}")
        chosen = [n for n, info in index["families"].items() if (script is None or script in info["scripts"])
                  and (kind is None or GOOGLE_KINDS.get(info["category"]) == kind)]
    present = {f["family"] for f in faces(data_dir).values() if f["source"] == GOOGLE}
    chosen = [n for n in chosen if n not in present]
    with _lock:
        if _download["running"]:
            raise su.ValidationError("Google fonts are being downloaded already: wait until it ends")
        _download.update(running=True, done=0, total=len(chosen), failed=[], current=None, error=None)

    def work():
        for name in chosen:
            with _lock:
                _download["current"] = name
            try:
                download(data_dir, name)
            except Exception:
                with _lock:
                    _download["failed"].append(name)
            with _lock:
                _download["done"] += 1
        with _lock:
            _download.update(running=False, current=None)
        _forget(data_dir)
    threading.Thread(target=work, name="google-fonts", daemon=True).start()
    return download_status()


def download_status() -> dict:
    with _lock:
        return dict(_download, failed=list(_download["failed"]))


# -- HarfBuzz --------------------------------------------------------------------------------------------------------------------------
def hb_font(face_: dict) -> hb.Font:
    """The HarfBuzz font of a face, its variable axes set to the face's coordinates, kept for the faces used last."""
    key = (face_["path"], face_["index"], json.dumps(face_.get("coords"), sort_keys=True))
    with _lock:
        if key in _fonts:
            _fonts.move_to_end(key)
            return _fonts[key]
    try:
        font = hb.Font(hb.Face(hb.Blob.from_file_path(face_["path"]), face_["index"]))
    except Exception:
        raise FontError(f"the font file of {face_['family']} cannot be read any more: choose another font") from None
    if face_.get("coords"):
        font.set_variations(face_["coords"])
    with _lock:
        _fonts[key] = font
        while len(_fonts) > KEEP_FONTS:
            _fonts.popitem(last=False)
    return font
