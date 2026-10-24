"""What makes an upload a release (REQ-087, DEC-058): the chunks are streamed through the same reader the desktop uses, and the release
is accepted only when the file is complete, its hashes hold, its schema and limits hold, and it is the release that was reserved for this
laboratory by its owner. Nothing is kept of a publication that fails here."""
from __future__ import annotations

from typing import Iterable, Mapping

from . import _lab_format as lf
from .chunks import ChunkStream
from .errors import Invalid


def validate(chunks: Iterable[bytes], publication: Mapping, lab: Mapping, declared: Mapping,
             policy: lf.ResourcePolicy = lf.DEFAULT_POLICY) -> dict:
    """Read the publication's chunks as one file and return what the release row needs (manifest, the lab record, counts, sizes);
    ``declared`` is what the client says of its file (``file_sha256``, ``byte_size``, ``chunk_count``); raise :class:`Invalid` with a
    code naming the first problem."""
    stream = ChunkStream(chunks)
    manifest = lab_record = None
    try:
        for kind, value in lf.read(stream, policy=policy):
            if kind == "manifest":
                manifest = value
                if manifest["origin_lab_id"] != lab["origin_lab_id"]:
                    raise Invalid("the release is not of this laboratory: its origin laboratory id differs", "lab_mismatch")
                if manifest["release_id"] != publication["release_id"]:
                    raise Invalid("the release id is not the one reserved for this publication", "release_id")
                if manifest.get("release_number") != publication["release_number"]:
                    raise Invalid(f"the release number must be {publication['release_number']}, the one reserved", "release_number")
                if manifest["attribution"]["name"] != lab["author"]:
                    raise Invalid("the release names another author than the laboratory's", "author")
            elif kind == "lab":
                lab_record = value
                if value["name"] != lab["name"]:
                    raise Invalid("the release names the laboratory differently from the catalogue", "lab_name")
            elif kind == "end":
                manifest = value
    except lf.FormatError as exc:
        raise Invalid(f"the release is not acceptable: {exc}", exc.code) from None
    stream.drain()
    if stream.size != declared["byte_size"]:
        raise Invalid(f"the chunks hold {stream.size} bytes, the publication declared {declared['byte_size']}", "size")
    if stream.sha256 != declared["file_sha256"]:
        raise Invalid("the uploaded bytes do not match the declared file hash", "file_hash")
    return {"manifest": manifest, "lab": lab_record, "counts": manifest["counts"], "content_sha256": manifest["content_sha256"],
            "terms": manifest["usage_terms"]["id"], "byte_size": stream.size, "file_sha256": stream.sha256, "chunk_count": declared["chunk_count"]}
