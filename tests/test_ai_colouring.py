"""REQ-050, DEC-084 (vector-detail-and-colour-control): the language model chooses a measured titanium colour for every source colour in a
style; it sees numbers only unless the operator allowed a reduced photograph for the work, every answer is checked before it is applied,
and the choice is stored in a variant that is never asked for again. No test calls the real service: a fake client stands in for it."""
import base64
import json
import re
import shutil
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from test_vector_work import BLUE, GREEN, PAPER, RED, YELLOW, by_rgb, colouring, job, routes_of, run_screen, work    # noqa: F401  (fixtures)
from titanium_platform import ai_colouring as ai, plans as pl, research, vector_job


def sent(call) -> dict:
    """The brief a call carried (its text part), as the model read it."""
    content = call["input"][0]["content"]
    text = content if isinstance(content, str) else next(p["text"] for p in content if p["type"] == "input_text")
    return json.loads(text)


def spread(brief: dict, reverse: bool = False) -> dict:
    """An answer that keeps the order of light and dark: the free colours, lightest last, get the palette's colours in the same order."""
    free = sorted(brief["free"], key=lambda s: (s["lab"][0], s["index"]))
    options = sorted(brief["palette"], key=lambda e: (e["lab"][0], str(e["id"])))
    picks = [options[round(i * (len(options) - 1) / max(1, len(free) - 1))] for i in range(len(free))]
    if reverse:
        picks = picks[::-1]
    return {"colours": {str(s["index"]): p["id"] for s, p in zip(free, picks)}, "note": "тёплые света, холодные тени"}


class Fake:
    """A stand-in for the model's client: every reply is a function of the brief (or a text, or an exception to raise)."""

    def __init__(self, *replies):
        self.replies, self.calls, self.responses = list(replies), [], self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if callable(reply):
            reply = reply(sent(kwargs))
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(output_text=reply if isinstance(reply, str) else json.dumps(reply), status="completed")


@pytest.fixture
def model(monkeypatch):
    def install(*replies, available=True):
        fake = Fake(*replies or [spread])
        monkeypatch.setattr(research, "ai_available", lambda: available)
        monkeypatch.setattr(research, "openai_client", lambda: fake)
        return fake
    return install


def ai_op(c, j, **op):
    return c["client"].post(f"/api/vector/{j['id']}/colouring", json={"op": "ai_colour", "style": "cubism", **op})


def refused(r, message):
    assert r.status_code == 422 and r.json()["error"] == message, r.text


def state_of(c, j):
    v = c["client"].get(f"/api/vector/{j['id']}").json()
    return v["colouring"], len(v["variants"]), v["undo"], v["redo"], [(x["entry_id"], x["how"]) for x in v["colours"]]


# -- a style gives a variant ------------------------------------------------------------------------------------------------------
def test_a_style_gives_one_variant_of_measured_colours_and_the_model_sees_only_numbers(work, job, model):
    c, j = work, job
    fake = model()
    before = state_of(c, j)
    r = ai_op(c, j)
    assert r.status_code == 200, r.text
    v = r.json()
    assert len(fake.calls) == 1 and v["colouring"]["mode"] == "ai" and v["colouring"]["variant"] == 2
    palette_ids = {e["id"] for e in c["client"].get(f"/api/vector-palette?device_id={c['w']['setup'][0]}&lens_id={c['w']['setup'][1]}"
                                                    f"&material_id={c['ti']}").json()["entries"]}
    assert all(col["entry_id"] in palette_ids and col["how"] == "ai" for col in v["colours"])           # a measured colour for every colour
    assert v["colouring"]["ai"] == {"style": "cubism", "text": None, "free_lightness": False, "photo": False, "note": "тёплые света, холодные тени"}
    variant = v["variants"][-1]
    assert variant["mode"] == "ai" and variant["ai"]["style"] == "cubism" and (v["undo"], v["redo"]) == (1, 0)
    brief = sent(fake.calls[0])                                                                         # numbers, no picture, no names
    assert set(brief) == {"wish", "lightness", "max_recipes", "free", "fixed", "touching", "palette"}
    assert isinstance(fake.calls[0]["input"][0]["content"], str) and "image" not in json.dumps(fake.calls[0]["input"])
    assert "Cubist" in brief["wish"] and brief["lightness"].startswith("lightness: keep the order") and brief["max_recipes"] == 29
    assert len(brief["free"]) == len(j["colours"]) and brief["fixed"] == {} and brief["touching"] and all(len(p) == 3 for p in brief["touching"])
    assert all(set(s) == {"index", "lab", "share"} for s in brief["free"]) and sum(s["share"] for s in brief["free"]) == pytest.approx(1, abs=0.01)
    assert {e["id"] for e in brief["palette"]} <= palette_ids and all(set(e) == {"id", "lab"} for e in brief["palette"])
    assert not any(name in json.dumps(brief) for name in ("Portrait", "photo.png", "svg")) and not re.search(r'"r\d+"', json.dumps(brief))   # no names, no region ids
    assert fake.calls[0]["store"] is False and "input_image" not in json.dumps(fake.calls[0])
    assert before[1] == 1 and before[0]["mode"] == "closest"                                            # the earlier colouring is one step back


@pytest.mark.parametrize("style, word", [("realistic", "Realistic"), ("artistic", "Artistic"), ("impressionism", "Impressionist")])
def test_every_style_of_the_list_is_told_to_the_model_in_its_own_words(work, job, model, style, word):
    fake = model()
    assert ai_op(work, job, style=style).status_code == 200
    assert word in sent(fake.calls[0])["wish"]


def test_an_own_description_is_the_wish_and_is_stored_with_the_variant(work, job, model):
    fake = model()
    r = ai_op(work, job, style="custom", text="  как витраж, много синего  ")
    assert r.status_code == 200, r.text
    assert "как витраж, много синего" in sent(fake.calls[0])["wish"]
    assert r.json()["variants"][-1]["ai"]["text"] == "как витраж, много синего" and r.json()["variants"][-1]["ai"]["style"] == "custom"


@pytest.mark.parametrize("op, message", [
    ({"style": "baroque"}, "choose a style for the AI colouring: realistic, artistic, impressionism, cubism or your own description"),
    ({"style": None}, "choose a style for the AI colouring: realistic, artistic, impressionism, cubism or your own description"),
    ({"style": "custom"}, "describe the look you want for the AI colouring"),
    ({"style": "custom", "text": "   "}, "describe the look you want for the AI colouring"),
    ({"style": "custom", "text": "x" * 401}, "the description may have at most 400 characters"),
    ({"free_lightness": "yes"}, "free lightness must be on or off"),
])
def test_a_request_without_a_style_or_with_a_bad_one_is_refused_before_the_model_is_asked(work, job, model, op, message):
    fake = model()
    before = state_of(work, job)
    refused(ai_op(work, job, **op), message)
    assert fake.calls == [] and state_of(work, job) == before


# -- the rules of the answer ---------------------------------------------------------------------------------------------------------
def test_the_order_of_light_and_dark_is_kept_unless_the_operator_allows_free_lightness(work, job, model):
    c, j = work, job
    backwards = lambda brief: spread(brief, reverse=True)       # noqa: E731
    fake = model(backwards)
    before = state_of(c, j)
    refused(ai_op(c, j), ai.ORDER_BROKEN)
    assert len(fake.calls) == 2 and state_of(c, j) == before                                          # asked again once, then refused: nothing changed
    assert fake.calls[1]["input"][1]["role"] == "assistant" and ai.ORDER_BROKEN in fake.calls[1]["input"][2]["content"]
    free = model(backwards)
    r = ai_op(c, j, free_lightness=True)
    assert r.status_code == 200 and len(free.calls) == 1 and r.json()["colouring"]["ai"]["free_lightness"] is True
    assert sent(free.calls[0])["lightness"] == ai.FREE_ORDER


def test_a_rejected_answer_is_sent_back_once_with_the_reason_and_a_good_second_answer_is_used(work, job, model):
    fake = model("not json at all", spread)
    r = ai_op(work, job)
    assert r.status_code == 200 and len(fake.calls) == 2 and r.json()["colouring"]["mode"] == "ai"
    assert ai.UNREADABLE in fake.calls[1]["input"][2]["content"] and fake.calls[1]["input"][1] == {"role": "assistant", "content": "not json at all"}


@pytest.mark.parametrize("bad, message", [
    (lambda b: {"colours": {**spread(b)["colours"], str(b["free"][0]["index"]): "no-such-colour"}}, ai.NOT_MEASURED),
    (lambda b: {"colours": {k: v for k, v in list(spread(b)["colours"].items())[1:]}}, ai.INCOMPLETE),
    (lambda b: {"colours": {**spread(b)["colours"], "x": b["palette"][0]["id"]}}, ai.UNREADABLE),
    (lambda b: {"colours": ["a"]}, ai.UNREADABLE),
    (lambda b: "{}", ai.INCOMPLETE if False else ai.UNREADABLE),
    ("the answer is in words, no braces", ai.UNREADABLE),
])
def test_an_answer_that_breaks_a_rule_is_refused_and_the_colouring_stays(work, job, model, bad, message):
    model(bad)
    before = state_of(work, job)
    refused(ai_op(work, job), message)
    assert state_of(work, job) == before


def test_an_answer_that_needs_more_layers_than_the_file_has_is_refused(work, job, model, monkeypatch):
    monkeypatch.setattr(vector_job, "photo_cap", lambda markers: 2)
    model(spread)
    refused(ai_op(work, job), "the AI chose 5 different colours but the file has 2 layers for them")


def test_the_service_failing_gives_one_message_that_never_carries_its_own_text(work, job, model):
    model(RuntimeError("Incorrect API key provided: sk-proj-SECRET123"))
    before = state_of(work, job)
    r = ai_op(work, job)
    refused(r, "the AI service did not answer: check the connection and the key, then try again")
    assert "SECRET" not in r.text and state_of(work, job) == before


def test_without_a_key_the_mode_is_off_and_says_why_while_the_other_modes_work(work, job, model):
    c, j = work, job
    fake = model(available=False)
    assert c["client"].get(f"/api/vector/{j['id']}").json()["ai"]["available"] is False
    refused(ai_op(c, j), "the AI colouring is off: no key for the language model is set (OPENAI_API_KEY)")
    assert fake.calls == []
    assert colouring(c, j, op="assign", mode="tonality")["colouring"]["mode"] == "tonality"


def test_the_operators_own_choices_stay_and_count_and_left_out_colours_are_not_shown_to_the_model(work, job, model):
    c, j = work, job
    blue, yellow, green = by_rgb(j, BLUE), by_rgb(j, YELLOW), by_rgb(j, GREEN)
    j = colouring(c, j, op="set_colour", colour=blue["index"], entry_id=green["entry_id"])
    j = colouring(c, j, op="exclude_colour", colour=yellow["index"])
    fake = model()
    v = ai_op(c, j).json()
    brief = sent(fake.calls[0])
    assert brief["fixed"] == {str(blue["index"]): green["entry_id"]}
    assert {s["index"] for s in brief["free"]} == {col["index"] for col in j["colours"]} - {blue["index"], yellow["index"]}
    now = {col["index"]: col for col in v["colours"]}
    assert now[blue["index"]]["entry_id"] == green["entry_id"] and now[blue["index"]]["status"] == "hand"       # the hand choice stayed
    assert now[yellow["index"]]["status"] == "excluded" and now[by_rgb(j, RED)["index"]]["how"] == "ai"
    assert all(now[s["index"]]["how"] == "ai" for s in brief["free"])


def test_with_every_colour_decided_by_hand_or_left_out_there_is_nothing_to_ask(work, job, model):
    c, j = work, job
    green = by_rgb(j, GREEN)["entry_id"]
    for col in j["colours"]:
        j = colouring(c, j, op="set_colour", colour=col["index"], entry_id=green)
    fake = model()
    refused(ai_op(c, j), "every colour of the picture is chosen by hand or left out: there is nothing for the AI to colour")
    assert fake.calls == []


# -- the variant, undo, and no second question ----------------------------------------------------------------------------------------
def test_a_variant_of_the_ai_is_restored_undone_and_kept_without_asking_the_model_again(work, job, model):
    c, j = work, job
    fake = model()
    first = state_of(c, j)
    v = ai_op(c, j).json()
    chosen = state_of(c, v)
    number = v["colouring"]["variant"]
    other = colouring(c, v, op="assign", mode="tonality")                                              # another mode in between
    assert other["colouring"]["mode"] == "tonality" and "ai" not in other["colouring"]
    back = colouring(c, other, op="restore", variant=number)
    assert state_of(c, back)[0]["mode"] == "ai" and state_of(c, back)[4] == chosen[4] and back["colouring"]["ai"]["style"] == "cubism"
    again = colouring(c, back, op="settings", tolerance_de=back["settings"]["tolerance_de"], max_time=None, include_as_shot=False)
    assert again["colouring"]["mode"] == "ai" and state_of(c, again)[4] == chosen[4]                    # new limits do not re-ask the model
    cleared = colouring(c, again, op="set_colour", colour=by_rgb(again, BLUE)["index"], entry_id=by_rgb(again, GREEN)["entry_id"])
    freed = colouring(c, cleared, op="set_colour", colour=by_rgb(again, BLUE)["index"], entry_id=None)  # back to the automatic choice: the AI's
    assert state_of(c, freed)[4] == chosen[4]
    assert len(fake.calls) == 1                                                                         # one question in the whole story
    j = freed
    while j["undo"]:
        j = colouring(c, j, op="undo")
    assert state_of(c, j)[0]["mode"] == first[0]["mode"] and state_of(c, j)[4] == first[4]


def test_a_new_split_leaves_the_ai_variants_behind_with_the_rest_of_the_colouring(work, job, model):
    c, j = work, job
    model()
    ai_op(c, j)
    r = c["client"].post(f"/api/vector/{j['id']}/split", json={"n_colors": 5})
    assert r.status_code == 200 and r.json()["colouring"]["mode"] == "closest" and "ai" not in r.json()["colouring"]
    assert [v["mode"] for v in r.json()["variants"]] == ["closest"]


# -- the photograph ------------------------------------------------------------------------------------------------------------------
def test_a_reduced_photograph_goes_with_the_numbers_only_after_the_operator_allowed_it_for_this_work(work, job, model):
    c, j = work, job
    view = c["client"].get(f"/api/vector/{j['id']}").json()
    assert view["ai"] == {"available": research.ai_available() and research.ai_library(), "missing": view["ai"]["missing"], "styles": list(ai.STYLES),
                          "photo_allowed": False, "photo_px": 512, "max_text": 400}
    assert view["ai"]["missing"] in (None, "key", "library") and view["ai"]["available"] is (view["ai"]["missing"] is None)
    fake = model()
    assert view["ai"]["photo_allowed"] is False and "ai_photo" not in view
    ai_op(c, j)
    assert isinstance(fake.calls[0]["input"][0]["content"], str)                                      # not allowed: numbers only
    allowed = c["client"].post(f"/api/vector/{j['id']}/ai-photo", json={"allowed": True})
    assert allowed.status_code == 200 and allowed.json()["ai"]["photo_allowed"] is True and "ai_photo" not in allowed.json()
    assert (allowed.json()["undo"], allowed.json()["redo"]) == (1, 0)                                    # not a step of undo
    assert pl.get_plan(work["store"], j["id"])["history"][-1]["op"] == {"op": "ai_photo", "allowed": True}
    v = ai_op(c, j, style="artistic").json()
    parts = fake.calls[1]["input"][0]["content"]
    assert [p["type"] for p in parts] == ["input_text", "input_image"] and v["variants"][-1]["ai"]["photo"] is True
    url = parts[1]["image_url"]
    assert url.startswith("data:image/jpeg;base64,")
    picture = cv2.imdecode(np.frombuffer(base64.b64decode(url.split(",", 1)[1]), np.uint8), cv2.IMREAD_COLOR)
    assert max(picture.shape[:2]) <= 512 and set(sent(fake.calls[1])) == set(sent(fake.calls[0]))      # a reduced copy beside the same numbers
    assert c["client"].get(f"/api/vector/{j['id']}").json()["ai"]["photo_allowed"] is True               # the work remembers it
    off = c["client"].post(f"/api/vector/{j['id']}/ai-photo", json={"allowed": False}).json()
    assert off["ai"]["photo_allowed"] is False
    ai_op(c, off, style="realistic")
    assert isinstance(fake.calls[2]["input"][0]["content"], str)


@pytest.mark.parametrize("body", [{}, {"allowed": "yes"}, {"allowed": 1}, {"allowed": None}])
def test_the_permission_must_be_on_or_off(work, job, body):
    refused(work["client"].post(f"/api/vector/{job['id']}/ai-photo", json=body), "the permission to send the photograph must be on or off")
    assert work["client"].get(f"/api/vector/{job['id']}").json()["ai"]["photo_allowed"] is False


def test_the_photograph_is_reduced_to_512_pixels_and_a_small_one_is_left_alone():
    big = cv2.imencode(".png", np.full((900, 1200, 3), 120, np.uint8))[1].tobytes()
    small = cv2.imencode(".png", np.full((200, 300, 3), 120, np.uint8))[1].tobytes()
    for data, expected in ((big, (384, 512)), (small, (200, 300))):
        url = ai.photo_data_url(data)
        picture = cv2.imdecode(np.frombuffer(base64.b64decode(url.split(",", 1)[1]), np.uint8), cv2.IMREAD_COLOR)
        assert picture.shape[:2] == expected


# -- the pieces ---------------------------------------------------------------------------------------------------------------------------
def test_the_touching_pairs_name_source_colours_with_their_share_of_the_borders(work, job):
    import json as _json
    from pathlib import Path
    document = _json.loads(Path(pl.get_plan(work["store"], job["id"])["document_path"]).read_text(encoding="utf-8"))
    pairs = ai.touching(document)
    indexes = {p["index"] for p in document["palette"]}
    assert pairs and all(a in indexes and b in indexes and a < b and 0 < share <= 1 for a, b, share in pairs)
    assert [share for _, _, share in pairs] == sorted((share for _, _, share in pairs), reverse=True)
    assert sum(share for _, _, share in pairs) == pytest.approx(1, abs=0.01)
    paper, red = by_rgb(job, PAPER)["index"], by_rgb(job, RED)["index"]
    assert [min(paper, red), max(paper, red)] in [p[:2] for p in pairs]                                   # the ring lies on the paper


def test_the_order_check_ignores_source_colours_of_the_same_lightness_and_the_operators_ones():
    palette = {"a": {"lab": [20, 0, 0]}, "b": {"lab": [50, 0, 0]}, "c": {"lab": [80, 0, 0]}}
    light = {1: 30.0, 2: 30.0, 3: 70.0}
    ok = {"colours": {"1": "b", "2": "a", "3": "c"}}                                                  # equal sources may swap
    assert ai.validate(ok, free={1, 2, 3}, palette=palette, lightness=light, keep_order=True, max_recipes=9, recipes=len) == {1: "b", 2: "a", 3: "c"}
    swapped = {"colours": {"1": "c", "2": "c", "3": "a"}}
    with pytest.raises(ai.Rejected, match="order of light and dark"):
        ai.validate(swapped, free={1, 2, 3}, palette=palette, lightness=light, keep_order=True, max_recipes=9, recipes=len)
    assert ai.validate(swapped, free={1, 2, 3}, palette=palette, lightness=light, keep_order=False, max_recipes=9, recipes=len)
    ignored = {"colours": {**ok["colours"], "9": "zzz"}}                                              # an index that is not free is theirs, not ours
    assert ai.validate(ignored, free={1, 2, 3}, palette=palette, lightness=light, keep_order=True, max_recipes=9, recipes=len)


# -- the screen ----------------------------------------------------------------------------------------------------------------------------
@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_screen_offers_the_styles_sends_the_choice_and_remembers_the_permission_for_the_photograph(work, job, model, tmp_path):
    c, j = work, job
    model()
    done = ai_op(c, j, style="custom", text="как витраж", free_lightness=True).json()          # a view with an AI variant, as the server gives it
    routes = routes_of(c, j)
    routes[f"/api/vector/{j['id']}"]["json"] = done
    routes[f"/api/vector/{j['id']}/colouring"] = {"status": 200, "json": done}
    permitted = {**done, "ai": {**done["ai"], "photo_allowed": True}}
    routes[f"/api/vector/{j['id']}/ai-photo"] = {"status": 200, "json": permitted}
    out = run_screen(tmp_path, j, routes, """
  const block = tree.querySelectorAll('div').find((d) => d.className === 'stack vw-ai');
  const select = block.querySelectorAll('select')[0];
  out.styles = select.options.map((o) => [o.value, o.textContent]);
  out.heading = block.querySelectorAll('h4')[0].textContent;
  const text = block.querySelectorAll('input').find((i) => i.getAttribute('aria-label') === 'Своё описание');
  const boxes = block.querySelectorAll('input').filter((i) => i.getAttribute('type') === 'checkbox');
  out.checked = boxes.map((b) => b.checked);
  const labels = block.querySelectorAll('label').map((l) => l.textContent);
  out.labels = labels;
  const go = byText(block, 'button', 'Раскрасить с помощью AI');
  out.disabled = go.disabled;
  out.current = block.querySelectorAll('p').map((p) => p.textContent).find((t) => t.startsWith('Сейчас раскрашено AI'));
  out.variants = tree.querySelectorAll('div').find((d) => d.classList.contains('vw-variants')).querySelectorAll('.lst-main').map((d) => d.textContent);   // a line each
  select.value = 'cubism'; await select.dispatch('change');
  out.hint = block.querySelectorAll('span').map((s) => s.textContent).find((t) => t.startsWith('Плоские грани'));
  boxes[0].checked = true;
  await go.dispatch('click');
  boxes[1].checked = true; await boxes[1].dispatch('change');
  out.posted = ctx.requests.filter((r) => r.method === 'POST').map((r) => [r.path, JSON.parse(r.body)]);
  out.photoAfter = block.querySelectorAll('input').filter((i) => i.getAttribute('type') === 'checkbox')[1].checked;
""")
    assert out["heading"] == "Раскраска с помощью AI"
    assert out["styles"] == [["realistic", "Реалистично"], ["artistic", "Артистично"], ["impressionism", "Импрессионизм"], ["cubism", "Кубизм"],
                             ["custom", "Своё описание"]]
    assert out["checked"] == [False, False] and out["disabled"] is False                          # free lightness off, no photograph, a key is set
    assert any("Свободная светлота" in label for label in out["labels"]) and any("до 512 px" in label for label in out["labels"])
    assert out["current"].startswith("Сейчас раскрашено AI: ") and "тёплые света, холодные тени" in out["current"] and "«как витраж»" in out["current"]
    assert out["variants"] and out["variants"][0].startswith("№ 2 · AI · «как витраж» · светлота свободна")        # the newest first
    assert out["hint"].startswith("Плоские грани земляной гаммы")
    ops = [(path, body) for path, body in out["posted"]]
    assert ops[0] == (f"/api/vector/{j['id']}/colouring", {"op": "ai_colour", "style": "cubism", "free_lightness": True})   # the choice, as typed
    assert ops[1] == (f"/api/vector/{j['id']}/ai-photo", {"allowed": True}) and out["photoAfter"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_without_a_key_the_button_is_off_and_the_screen_says_why(work, job, model, tmp_path):
    c, j = work, job
    model(available=False)
    routes = routes_of(c, j)
    out = run_screen(tmp_path, j, routes, """
  const block = tree.querySelectorAll('div').find((d) => d.className === 'stack vw-ai');
  out.disabled = byText(block, 'button', 'Раскрасить с помощью AI').disabled;
  out.alert = block.querySelectorAll('p').filter((p) => p.className === 'alert warn').map((p) => [p.hidden, p.textContent]);
  out.modes = tree.querySelectorAll('button').map((b) => b.textContent).filter((t) => ['Ближе к оригиналу', 'Сохранить тональность'].includes(t));
  out.modesDisabled = tree.querySelectorAll('button').filter((b) => b.textContent === 'Ближе к оригиналу').map((b) => !!b.disabled);
""")
    assert out["disabled"] is True and len(out["alert"]) == 1 and out["alert"][0][0] is False and "«Сеть»" in out["alert"][0][1]
    assert out["modes"] == ["Ближе к оригиналу", "Сохранить тональность"] and out["modesDisabled"] == [False]      # the other modes are unaffected


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_every_message_of_the_ai_colouring_has_a_russian_translation(tmp_path):
    from test_i18n_coverage import MARK, run_node
    messages = [ai.UNREADABLE, ai.NOT_MEASURED, ai.INCOMPLETE, ai.ORDER_BROKEN, "the AI chose 5 different colours but the file has 2 layers for them",
                "the AI service did not answer: check the connection and the key, then try again", "the AI answer was cut off: try again",
                "the AI could not be started on this computer: a library it needs is missing or broken, install the app's dependencies (see README)",
                "choose a style for the AI colouring: realistic, artistic, impressionism, cubism or your own description",
                "describe the look you want for the AI colouring", "the description may have at most 400 characters", "free lightness must be on or off",
                "the permission to send the photograph must be on or off", "the AI colouring is off: no key for the language model is set (OPENAI_API_KEY)",
                "no measured colour of this titanium may be chosen with the present limits: widen them to colour with AI",
                "every colour of the picture is chosen by hand or left out: there is nothing for the AI to colour"]
    left = run_node(tmp_path, messages, f"console.log(JSON.stringify(data.filter((s)=>tr(s).includes('{MARK}'))));\n")
    assert left == []
