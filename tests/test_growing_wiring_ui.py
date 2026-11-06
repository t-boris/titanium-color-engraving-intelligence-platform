"""The screens that place the catalogue and the selector (feature ux-growing-collections-p0, REQ-001): the «Titanium» tab of the settings
screen is the paged catalogue, and the start of a research session chooses its stock record in the selector instead of a drop-down of all.
Run in node over a small DOM against the real server."""
from growing_ui import fill_materials, node, run_node, serving
from titanium_platform import devices

pytestmark = node


def test_the_titanium_tab_of_the_settings_screen_is_the_paged_catalogue(tmp_path):
    with serving(tmp_path / "data") as (app, port):
        fill_materials(app.state.store, 60)
        out = run_node(tmp_path, port, ["screens/material-catalog.js", "screens/setup.js"], """
          const screen = ctx.__screens.setup;
          const box = mount(await screen.render({query: {tab: 'material', material: '5'}}));
          out.screen = {title: q(box, 'h2').textContent, tabs: qa(box, '[role]').filter((n) => n.getAttribute('role') === 'tab').map((n) => n.textContent),
            pressed: qa(box, '[role]').filter((n) => n.hasAttribute('aria-selected')).map((n) => n.textContent),
            rows: rows(box).length, count: count(box), editor: q(box, '.mat-editor').getAttribute('aria-label'),
            unbounded: requests('/api/materials').filter((x) => (x.url === '/api/materials' || x.url.startsWith('/api/materials?')) && !x.url.includes('limit=')).length};
        """, ("MaterialCatalog",))
    assert out["screen"] == {"title": "Settings", "tabs": ["Stock", "Capture", "Repeatability", "Photo markers", "Display"], "pressed": ["Stock"], "rows": 20,
                             "count": "showing 20 of 60", "editor": "Material #5", "unbounded": 0}


def test_a_research_session_is_started_with_a_record_chosen_in_the_selector(tmp_path):
    with serving(tmp_path / "data") as (app, port):
        store = app.state.store
        devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
        fill_materials(store, 300)
        out = run_node(tmp_path, port, ["markdown.js", "screens/material-picker.js", "screens/research.js"], """
          stub('/research/sessions', {status: 200, json: {id: 77}}, 'POST');
          const box = mount(await ctx.__screens.research.render({arg: null, query: {}}));
          const picker = q(box, '.matpick');
          await picker.ready;
          const start = button(box, 'Start research');
          out.start = {label: q(picker, '.matpick-label').textContent, value: picker.value, disabled: start.disabled,
            lists: requests('/api/materials').map((x) => x.url), fieldLabel: qa(box, 'label').some((l) => l.textContent.startsWith('Material and stock'))};
          picker.value = '';
          await start.dispatch('click');
          const stock = qa(box, '.f').find((l) => l.textContent.startsWith('Material and stock'));        // the refusal stands beside the field, not in a toast
          out.empty = {toast: [stock.errorText()], posts: requests('/research/sessions').filter((x) => x.method === 'POST').length, toasts: qa(doc.body, '.toast.bad').length};
          picker.value = '41';
          await until(() => picker.record !== null);
          qa(box, 'textarea')[0].value = 'Legible text on Grade 2';
          await start.dispatch('click');
          const posts = requests('/research/sessions').filter((x) => x.method === 'POST');
          out.sent = {count: posts.length, body: JSON.parse(posts[0].body), went: ctx.__went};
        """, ("MaterialPicker",))
    assert out["start"]["value"] == "300" and out["start"]["label"].startswith("Sheet 300 · ") and out["start"]["disabled"] is False        # nothing used yet: the newest record
    assert out["start"]["lists"] == ["/api/materials?limit=1", "/api/materials?limit=1&sort=recent"] and out["start"]["fieldLabel"]            # no list of three hundred
    assert out["empty"] == {"toast": ["Select stock: a specific batch or sheet"], "posts": 0, "toasts": 0}
    assert out["sent"]["count"] == 1 and out["sent"]["body"]["material_id"] == 41 and out["sent"]["body"]["target"] == "Legible text on Grade 2"
    assert out["sent"]["went"] == "/research/77"


def test_a_research_session_cannot_be_started_without_any_stock_record(tmp_path):
    with serving(tmp_path / "data") as (app, port):
        devices.create_from_template(app.state.store, "jpt-ydflp-e-60-m7-m-r")
        out = run_node(tmp_path, port, ["markdown.js", "screens/material-picker.js", "screens/research.js"], """
          const box = mount(await ctx.__screens.research.render({arg: null, query: {}}));
          const picker = q(box, '.matpick');
          await picker.ready;
          out.start = {disabled: button(box, 'Start research').disabled, label: q(picker, '.matpick-label').textContent, value: picker.value};
        """, ("MaterialPicker",))
    assert out["start"] == {"disabled": True, "label": "No stock selected", "value": ""}


def test_a_source_of_a_colour_with_many_photographs_is_a_count_with_a_list_and_a_short_one_stays_in_the_line(tmp_path):
    """The block «How we know this color» (shared by the colour map and the vector picker): a few analysis links stay in the line, many
    become a count with a list of every link."""
    out = run_node(tmp_path, 0, ["screens/source-refs.js"], """
      const source = (pairs, photos) => ({title: 'Plate', origin: 'work', experiment: 'e1', work_id: null, provisional: false, lab: [50, 0, 0], date: '2026-10-20T10:00:00',
        pair_ids: Array.from({length: pairs}, (_, i) => 100 + i), photos: Array.from({length: photos}, (_, i) => 'IMG_' + i + '.CR3'), layers: ['C01'],
        measurement: 'calibrated', agrees: true, delta_e: 1});
      const few = mount(App.sourcesBlock([source(2, 2)], {limit: 5}, [50, 0, 0]));
      out.few = {links: qa(few, 'a').map((a) => a.textContent), blocks: qa(few, '.srefs').length, text: q(few, 'ul').textContent.includes('photos IMG_0.CR3, IMG_1.CR3')};
      const many = mount(App.sourcesBlock([source(12, 8)], {limit: 5}, [50, 0, 0]));
      out.many = {blocks: qa(many, '.srefs').map((b) => [q(b, '.srefs-label').textContent, q(b, '.srefs-count').textContent]), links: qa(many, 'a').map((a) => a.textContent),
        inline: q(many, 'ul').textContent.includes('photos IMG_0')};
      await qa(many, '.srefs-toggle')[0].dispatch('click');
      await until(() => qa(many, 'a').length === 13);
      out.opened = qa(q(many, '.srefs-list'), 'a').map((a) => a.getAttribute('href'));
    """, ("SourceRefs",))
    assert out["few"] == {"links": ["experiment", "review #100", "review #101"], "blocks": 0, "text": True}
    assert out["many"]["blocks"] == [["Photo reviews: ", "12"], ["Photos: ", "8"]] and out["many"]["links"] == ["experiment"] and out["many"]["inline"] is False
    assert out["opened"] == [f"#/analysis/{100 + i}" for i in range(12)]


def test_the_designer_chooses_its_stock_in_the_selector_and_means_all_measured_stocks_by_default(tmp_path):
    with serving(tmp_path / "data") as (app, port):
        devices.create_from_template(app.state.store, "jpt-ydflp-e-60-m7-m-r")
        fill_materials(app.state.store, 300)
        out = run_node(tmp_path, port, ["hardware.js", "tasks.js", "screens/material-picker.js", "screens/designer.js"], """
          stub('/designer/propose', {status: 200, json: {id: 9}}, 'POST');
          const box = mount(await ctx.__screens.designer.render({query: {}}));
          const picker = q(box, '.matpick');
          await picker.ready;
          out.start = {label: q(picker, '.matpick-label').textContent, value: picker.value, clear: q(picker, '.matpick-clear').textContent,
            lists: requests('/api/materials').map((x) => x.url)};
          const propose = button(box, 'Propose plate');
          await propose.dispatch('click');
          picker.value = '41';
          await until(() => picker.record !== null);
          await propose.dispatch('click');
          out.sent = requests('/designer/propose').map((x) => JSON.parse(x.body).material_id);
        """, ("MaterialPicker",))
    assert out["start"] == {"label": "all measured stocks", "value": "", "clear": "All stocks", "lists": []}          # no list of three hundred is read
    assert out["sent"] == [None, 41]


def test_the_designer_refuses_a_wrong_count_seed_or_step_beside_its_box_keeps_it_and_sends_nothing(tmp_path):
    """ux-save-feedback-p0, REQ-003: the count of sets is a whole number from 1 to 40 and the seed a whole number (designer.propose)."""
    with serving(tmp_path / "data") as (app, port):
        devices.create_from_template(app.state.store, "jpt-ydflp-e-60-m7-m-r")
        out = run_node(tmp_path, port, ["hardware.js", "tasks.js", "screens/material-picker.js", "screens/designer.js"], """
          stub('/designer/propose', {status: 200, json: {id: 9}}, 'POST');
          const box = mount(await ctx.__screens.designer.render({query: {}}));
          const labelled = (text) => qa(box, 'label').find((l) => (l.querySelector('span') || {}).textContent === text);
          const proposals = () => requests('/designer/propose').length;
          const size = labelled('Number of sets').firstControl(), seed = labelled('Seed').firstControl(), step = labelled('Line interval').firstControl();
          size.value = '41'; seed.value = '1.5'; step.value = '0';
          await button(box, 'Propose plate').dispatch('click');
          out.wrong = [proposals(), labelled('Number of sets').errorText(), labelled('Seed').errorText(), labelled('Line interval').errorText(),
            size.value, seed.value, step.value, size.getAttribute('aria-invalid')];
          size.value = '6'; seed.value = '1729'; step.value = '0.025';
          await button(box, 'Propose plate').dispatch('click');
          out.right = [proposals(), JSON.parse(requests('/designer/propose')[0].body)];
        """, ("MaterialPicker",))
    assert out["wrong"][0] == 0
    assert "Entered: 41" in out["wrong"][1] and "from 1 to 40" in out["wrong"][1] and "whole number" in out["wrong"][2] and "Entered: 0" in out["wrong"][3]
    assert out["wrong"][4:] == ["41", "1.5", "0", "true"]
    assert out["right"][0] == 1 and out["right"][1]["seed"] == 1729 and out["right"][1]["size"] == 6 and out["right"][1]["line_interval"] == 0.025
