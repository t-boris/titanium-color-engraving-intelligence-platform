# Discussion — Vector work colour editor

### AI updated the requirements · 2026-10-19

DEC-001, DEC-075, DEC-076, DEC-077 written into REQ-049.

### AI asked, Boris Tsekinovsky answered · 2026-10-19

While implementing the feature, three points were put to the operator where a criterion and the code differed or the specification left a choice open (records checked: REQ-045, REQ-046, REQ-048, DEC-075, DEC-076, plan I-4, I-5, I-7). The answers are binding and are recorded as decisions:

1. REQ-046, "fewer than two colours": a titanium-colour merge needs two or more selected colours; one colour merged into another target is refused. DEC-078.
2. REQ-045, painting a source colour while some of its areas are excluded one by one: painting the source colour includes every area of it again. DEC-079.
3. REQ-048, "offered only for connected areas": the merge button is disabled unless the selected areas are connected through shared borders; the server refusal stays. DEC-080.

A fourth question was about the repository, not the specification: the untracked folder docs/features/vector-detail-and-colour-control/ (issue #32) is committed on the same branch in a commit of its own.
