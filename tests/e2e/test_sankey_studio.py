"""
Sankey Studio: node placement, priority/first-match routing, generating
with unplaced catalog items still present, save/reload persistence, the
in-canvas toolbar layout, per-node color overrides, target-colored edges
in the generated chart, snap-to-grid, line-shaping anchors, viewport-aware
node spawn positioning, auto-pan while dragging a connection, and the
custom hover tooltip.

Dragging on an SVG canvas is unreliable under Selenium's synthetic mouse
events (confirmed manually: even a native browser drag needs real
mousedown/mouseup dispatch to land on the right element), so node
placement/wiring here drives the same public methods the pointer handlers
call (`_place`, `_tryConnect`, `_addAnchorAt`, `_deleteAnchor`, ...) via
execute_script, then asserts against the rendered DOM/generated chart,
i.e. what the user actually sees, not just the JS object graph.

Run with (live stack required):
    pytest tests/e2e/test_sankey_studio.py -v | tee logfile.log
"""
import time

from selenium.webdriver.common.by import By

from bhelpers import _confirm
from helpers import _url, cleanup_user, run_cmd, setup_user

SANKEY_URL = _url("/budget/sankey/")


def _create_expense(email: str, category: str, tag: str, value: int, date_due: str,
                     txn_type: str = "TransactionType.EXPENSE") -> None:
    run_cmd(
        "shell", "-c",
        "from feusers.models import FeUser\n"
        "from budget.models import Category, Tag\n"
        "from budget.expense_factory import create_expense\n"
        "from budget.models.base import TransactionType\n"
        "from datetime import date\n"
        f"feuser = FeUser.objects.get(email='{email}')\n"
        f"cat = Category.objects.get(owning_feuser=feuser, title='{category}')\n"
        f"tag = Tag.objects.get(owning_feuser=feuser, title='{tag}')\n"
        "exp = create_expense(owning_feuser=feuser, title='Sankey e2e expense', "
        f"value={value}, type={txn_type}, "
        f"date_due=date.fromisoformat('{date_due}'), category=cat)\n"
        "exp.tags.set([tag])\n",
    )


class TestSankeyStudioNav:
    def test_nav_link_present_and_loads(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(_url("/budget/"))
            time.sleep(1)
            link = driver.find_element(By.LINK_TEXT, "Sankey Studio")
            link.click()
            time.sleep(1)
            assert "/budget/sankey/" in driver.current_url
            assert "Sankey Studio" in driver.page_source
        finally:
            cleanup_user(ctx["email"])


class TestSankeyStudioGenerate:
    def test_generate_succeeds_with_unplaced_catalog_items(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            _create_expense(ctx["email"], "Salary", "Food", 250, "2026-07-10")

            driver.get(SANKEY_URL)
            time.sleep(1)
            driver.execute_script("window._sankeyEditor.generate();")
            time.sleep(1)
            assert driver.find_element(By.ID, "sankey-error").text == ""
            chart = driver.execute_script("return window._sankeyEditor.chart;")
            assert chart == {"nodes": [], "links": []}
        finally:
            cleanup_user(ctx["email"])

    def test_unplaced_node_is_excluded_from_generated_chart(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            _create_expense(ctx["email"], "Salary", "Food", 250, "2026-07-10")

            driver.get(SANKEY_URL)
            time.sleep(1)
            result = driver.execute_script(
                """
                const ed = window._sankeyEditor;
                let sourceKey = null;
                Object.entries(ed.catalog).forEach(([key, info]) => {
                    if (info.title === 'Salary') sourceKey = key;
                });
                ed._place(sourceKey);
                ed.render();
                return {sourceKey};
                """
            )
            assert result["sourceKey"], "Default 'Salary' category must exist from create_defaults"

            driver.find_element(By.ID, "sankey-generate").click()
            time.sleep(2)

            assert driver.find_element(By.ID, "sankey-error").text == ""
            chart = driver.execute_script("return window._sankeyEditor.chart;")
            titles = [n["title"] for n in chart["nodes"]]
            assert titles == ["Salary"]
            assert chart["nodes"][0]["value"] == 250
            assert chart["links"] == []
        finally:
            cleanup_user(ctx["email"])

    def test_generate_computes_real_expense_value_through_the_edge(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            _create_expense(ctx["email"], "Salary", "Food", 250, "2026-07-10")

            driver.get(SANKEY_URL)
            time.sleep(1)

            result = driver.execute_script(
                """
                const ed = window._sankeyEditor;
                let sourceKey = null, targetKey = null;
                Object.entries(ed.catalog).forEach(([key, info]) => {
                    if (info.title === 'Salary') sourceKey = key;
                    if (info.title === 'Food') targetKey = key;
                });
                Object.keys(ed.catalog).forEach((key) => {
                    if (!(key in ed.nodes)) ed._place(key);
                });
                Object.entries(ed.nodes).forEach(([key, n]) => {
                    if (key !== sourceKey && key !== targetKey) n.disabled = true;
                });
                ed._tryConnect(sourceKey, targetKey);
                ed.render();
                return {sourceKey, targetKey};
                """
            )
            assert result["sourceKey"] and result["targetKey"], \
                "Default 'Salary' category and 'Food' tag must exist from create_defaults"

            driver.find_element(By.ID, "sankey-generate").click()
            time.sleep(2)

            chart = driver.execute_script("return window._sankeyEditor.chart;")
            assert chart is not None
            values_by_title = {n["title"]: n["value"] for n in chart["nodes"]}
            assert values_by_title.get("Salary") == 250
            assert values_by_title.get("Food") == 250
            assert chart["links"] == [
                {"source": result["sourceKey"], "target": result["targetKey"], "value": 250}
            ]

            # UI-level assertion: the generated chart's own SVG actually
            # renders these nodes, not just the JS state.
            chart_svg_text = driver.find_element(By.ID, "sankey-chart").text
            assert "Salary" in chart_svg_text
            assert "Food" in chart_svg_text
        finally:
            cleanup_user(ctx["email"])

    def test_generate_excludes_non_expense_transaction_types(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            _create_expense(ctx["email"], "Salary", "Food", 250, "2026-07-10")
            _create_expense(ctx["email"], "Salary", "Food", 999, "2026-07-11",
                             txn_type="TransactionType.INCOME")
            _create_expense(ctx["email"], "Salary", "Food", 999, "2026-07-12",
                             txn_type="TransactionType.SAVINGS_DEPOSIT")

            driver.get(SANKEY_URL)
            time.sleep(1)
            result = driver.execute_script(
                """
                const ed = window._sankeyEditor;
                let sourceKey = null, targetKey = null;
                Object.entries(ed.catalog).forEach(([key, info]) => {
                    if (info.title === 'Salary') sourceKey = key;
                    if (info.title === 'Food') targetKey = key;
                });
                ed._place(sourceKey);
                ed._place(targetKey);
                ed._tryConnect(sourceKey, targetKey);
                ed.render();
                return {sourceKey, targetKey};
                """
            )
            assert result["sourceKey"] and result["targetKey"]

            driver.find_element(By.ID, "sankey-generate").click()
            time.sleep(2)

            assert driver.find_element(By.ID, "sankey-error").text == ""
            chart = driver.execute_script("return window._sankeyEditor.chart;")
            values_by_title = {n["title"]: n["value"] for n in chart["nodes"]}
            # Only the type=expense expense (250) counts -- the income
            # (999) and savings deposit (999) expenses must be excluded.
            assert values_by_title.get("Salary") == 250
            assert values_by_title.get("Food") == 250
        finally:
            cleanup_user(ctx["email"])

    def test_save_persists_graph_across_reload(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(SANKEY_URL)
            time.sleep(1)
            driver.execute_script(
                """
                const ed = window._sankeyEditor;
                let key = null;
                Object.entries(ed.catalog).forEach(([k, info]) => {
                    if (info.title === 'Salary') key = k;
                });
                ed._place(key);
                ed.render();
                """
            )
            driver.find_element(By.ID, "sankey-save").click()
            time.sleep(1)

            driver.get(SANKEY_URL)
            time.sleep(1)
            placed_titles = driver.execute_script(
                "return Object.keys(window._sankeyEditor.nodes).map("
                "k => window._sankeyEditor._nodeTitle(k));"
            )
            assert "Salary" in placed_titles
        finally:
            cleanup_user(ctx["email"])

    def test_reset_clears_nodes_and_edges(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(SANKEY_URL)
            time.sleep(1)
            driver.execute_script(
                """
                const ed = window._sankeyEditor;
                let sourceKey = null, targetKey = null;
                Object.entries(ed.catalog).forEach(([key, info]) => {
                    if (info.title === 'Salary') sourceKey = key;
                    if (info.title === 'Food') targetKey = key;
                });
                ed._place(sourceKey);
                ed._place(targetKey);
                ed._tryConnect(sourceKey, targetKey);
                ed.render();
                """
            )
            before = driver.execute_script(
                "return {nodes: Object.keys(window._sankeyEditor.nodes).length, "
                "edges: window._sankeyEditor.edges.length};"
            )
            assert before["nodes"] == 2 and before["edges"] == 1

            driver.find_element(By.ID, "sankey-reset").click()
            _confirm(driver)

            after = driver.execute_script(
                "return {nodes: Object.keys(window._sankeyEditor.nodes).length, "
                "edges: window._sankeyEditor.edges.length};"
            )
            assert after == {"nodes": 0, "edges": 0}
        finally:
            cleanup_user(ctx["email"])

    def test_connector_node_routes_real_values(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            _create_expense(ctx["email"], "Salary", "Food", 100, "2026-07-10")
            _create_expense(ctx["email"], "Sales", "Health", 50, "2026-07-11")

            driver.get(SANKEY_URL)
            time.sleep(1)
            driver.find_element(By.ID, "sankey-add-connector").click()

            result = driver.execute_script(
                """
                const ed = window._sankeyEditor;
                const connectorKey = Object.keys(ed.nodes).find(k => k.startsWith('connector:'));
                let salaryKey = null, salesKey = null, foodKey = null, healthKey = null;
                Object.entries(ed.catalog).forEach(([k, info]) => {
                    if (info.title === 'Salary') salaryKey = k;
                    if (info.title === 'Sales') salesKey = k;
                    if (info.title === 'Food') foodKey = k;
                    if (info.title === 'Health') healthKey = k;
                });
                Object.keys(ed.catalog).forEach((key) => { if (!(key in ed.nodes)) ed._place(key); });
                Object.entries(ed.nodes).forEach(([key, n]) => {
                    const type = ed._nodeType(key);
                    if (type === 'connector') return;
                    const title = ed.catalog[key] ? ed.catalog[key].title : '';
                    n.disabled = !['Salary', 'Sales', 'Food', 'Health'].includes(title);
                });
                ed._tryConnect(salaryKey, connectorKey);
                ed._tryConnect(salesKey, connectorKey);
                ed._tryConnect(connectorKey, foodKey);
                ed._tryConnect(connectorKey, healthKey);
                ed.render();
                return {connectorType: ed._nodeType(connectorKey), edgeCount: ed.edges.length};
                """
            )
            assert result["connectorType"] == "connector"
            assert result["edgeCount"] == 4  # 2 in + 2 out, not 2*2 direct

            driver.find_element(By.ID, "sankey-generate").click()
            time.sleep(2)

            chart = driver.execute_script("return window._sankeyEditor.chart;")
            values_by_title = {n["title"]: n["value"] for n in chart["nodes"]}
            assert values_by_title.get("Connector") == 150
            assert values_by_title.get("Food") == 100
            assert values_by_title.get("Health") == 50
        finally:
            cleanup_user(ctx["email"])

    def test_category_to_category_edge_is_rejected(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(SANKEY_URL)
            time.sleep(1)
            error_text = driver.execute_script(
                """
                const ed = window._sankeyEditor;
                let salaryKey = null, salesKey = null;
                Object.entries(ed.catalog).forEach(([k, info]) => {
                    if (info.title === 'Salary') salaryKey = k;
                    if (info.title === 'Sales') salesKey = k;
                });
                ed._place(salaryKey);
                ed._place(salesKey);
                ed._tryConnect(salaryKey, salesKey);
                return ed.error;
                """
            )
            assert "never co-occur" in error_text
            edge_count = driver.execute_script("return window._sankeyEditor.edges.length;")
            assert edge_count == 0
        finally:
            cleanup_user(ctx["email"])


class TestSankeyStudioToolbar:
    def test_canvas_toolbar_holds_graph_actions_and_generate_moved_below(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(SANKEY_URL)
            time.sleep(1)
            layout = driver.execute_script(
                """
                const toolbar = document.getElementById('sankey-canvas-toolbar');
                const canvasWrap = document.getElementById('sankey-canvas-wrap');
                const generateBtn = document.getElementById('sankey-generate');
                return {
                    toolbarInsideCanvasWrap: canvasWrap.contains(toolbar),
                    hasConnectorBtn: !!toolbar.querySelector('#sankey-add-connector'),
                    hasSaveBtn: !!toolbar.querySelector('#sankey-save'),
                    hasResetBtn: !!toolbar.querySelector('#sankey-reset'),
                    hasSnapCheckbox: !!toolbar.querySelector('#sankey-snap-grid'),
                    hasZoomButtons: !!toolbar.querySelector('#sankey-zoom-in') && !!toolbar.querySelector('#sankey-zoom-out'),
                    generateOutsideCanvasWrap: !canvasWrap.contains(generateBtn),
                };
                """
            )
            assert layout == {
                "toolbarInsideCanvasWrap": True,
                "hasConnectorBtn": True,
                "hasSaveBtn": True,
                "hasResetBtn": True,
                "hasSnapCheckbox": True,
                "hasZoomButtons": True,
                "generateOutsideCanvasWrap": True,
            }
        finally:
            cleanup_user(ctx["email"])


class TestSankeyStudioColorOverride:
    def test_color_override_persists_through_generate(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            _create_expense(ctx["email"], "Salary", "Food", 250, "2026-07-10")

            driver.get(SANKEY_URL)
            time.sleep(1)
            driver.execute_script(
                """
                const ed = window._sankeyEditor;
                let salaryKey = null, foodKey = null;
                Object.entries(ed.catalog).forEach(([k, info]) => {
                    if (info.title === 'Salary') salaryKey = k;
                    if (info.title === 'Food') foodKey = k;
                });
                ed._place(salaryKey);
                ed._place(foodKey);
                ed.nodes[salaryKey].color = '#e15759';
                ed._tryConnect(salaryKey, foodKey);
                ed.render();
                window._salaryKey = salaryKey;
                window._foodKey = foodKey;
                """
            )
            driver.find_element(By.ID, "sankey-generate").click()
            time.sleep(2)

            chart = driver.execute_script("return window._sankeyEditor.chart;")
            colors_by_title = {n["title"]: n["color"] for n in chart["nodes"]}
            assert colors_by_title["Salary"] == "#e15759"

            # The link is stroked with the *target's* color (Food's default
            # green), not the source's overridden red -- see
            # build/js/sankey_editor.js's _drawChart module comment.
            link_stroke = driver.execute_script(
                "return document.querySelector('#sankey-chart g g path').getAttribute('stroke');"
            )
            assert link_stroke == "#59a14f"
        finally:
            cleanup_user(ctx["email"])

    def test_color_picker_popover_applies_preset_and_hex(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(SANKEY_URL)
            time.sleep(1)
            result = driver.execute_script(
                """
                const ed = window._sankeyEditor;
                let key = null;
                Object.entries(ed.catalog).forEach(([k, info]) => {
                    if (info.title === 'Salary') key = k;
                });
                ed._place(key);
                ed._openColorPicker(key, 100, 100);
                const popover = document.querySelector('.sankey-color-popover');
                popover.querySelectorAll('.sankey-color-swatch')[0].click();
                const afterPreset = ed.nodes[key].color;

                ed._openColorPicker(key, 100, 100);
                const popover2 = document.querySelector('.sankey-color-popover');
                const hexInput = popover2.querySelector('.sankey-color-hex');
                hexInput.value = '#123abc';
                hexInput.dispatchEvent(new Event('change', {bubbles: true}));
                const afterHex = ed.nodes[key].color;
                return {afterPreset, afterHex, popoverGoneAfterHex: !document.querySelector('.sankey-color-popover')};
                """
            )
            # First preset is the first of the 32-color palette (blue),
            # not the old 8-color palette's first entry (red).
            assert result["afterPreset"] == "#2a78d6"
            assert result["afterHex"] == "#123abc"
            assert result["popoverGoneAfterHex"] is True
        finally:
            cleanup_user(ctx["email"])

    def test_color_popover_offers_32_unique_presets(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(SANKEY_URL)
            time.sleep(1)
            result = driver.execute_script(
                """
                const ed = window._sankeyEditor;
                let key = null;
                Object.entries(ed.catalog).forEach(([k, info]) => {
                    if (info.title === 'Salary') key = k;
                });
                ed._place(key);
                ed._openColorPicker(key, 100, 100);
                const swatches = [...document.querySelectorAll('.sankey-color-swatch')];
                return {
                    count: swatches.length,
                    uniqueCount: new Set(swatches.map((s) => s.style.background)).size,
                };
                """
            )
            assert result == {"count": 32, "uniqueCount": 32}
        finally:
            cleanup_user(ctx["email"])


class TestSankeyStudioSnapToGrid:
    def test_snap_checkbox_defaults_on_and_toggles_off(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(SANKEY_URL)
            time.sleep(1)
            # Snap to grid defaults to enabled -- both the editor flag and
            # the checkbox itself must agree on that.
            before = driver.execute_script(
                "return {snapToGrid: window._sankeyEditor.snapToGrid, "
                "checkboxChecked: document.getElementById('sankey-snap-grid').checked};"
            )
            assert before == {"snapToGrid": True, "checkboxChecked": True}

            cb = driver.find_element(By.ID, "sankey-snap-grid")
            driver.execute_script(
                "arguments[0].checked = false; arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                cb,
            )
            after = driver.execute_script("return window._sankeyEditor.snapToGrid;")
            assert after is False
        finally:
            cleanup_user(ctx["email"])

    def test_snap_only_rounds_while_enabled_and_never_moves_existing_nodes(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(SANKEY_URL)
            time.sleep(1)
            result = driver.execute_script(
                """
                const ed = window._sankeyEditor;
                ed.snapToGrid = false;
                const off = ed._applySnap(37, 53);

                let key = null;
                Object.entries(ed.catalog).forEach(([k, info]) => {
                    if (info.title === 'Salary') key = k;
                });
                ed._place(key);
                ed.nodes[key].x = 37;
                ed.nodes[key].y = 53;

                // Enabling snap-to-grid must not retroactively move the
                // node that's already sitting at an off-grid position.
                ed.snapToGrid = true;
                const posAfterEnabling = {x: ed.nodes[key].x, y: ed.nodes[key].y};
                const on = ed._applySnap(37, 53);
                return {off, on, posAfterEnabling};
                """
            )
            assert result["off"] == {"x": 37, "y": 53}
            assert result["on"] == {"x": 40, "y": 60}
            assert result["posAfterEnabling"] == {"x": 37, "y": 53}
        finally:
            cleanup_user(ctx["email"])


class TestSankeyStudioAnchors:
    def test_right_click_adds_anchor_left_click_removes_it(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(SANKEY_URL)
            time.sleep(1)
            result = driver.execute_script(
                """
                const ed = window._sankeyEditor;
                let salaryKey = null, foodKey = null;
                Object.entries(ed.catalog).forEach(([k, info]) => {
                    if (info.title === 'Salary') salaryKey = k;
                    if (info.title === 'Food') foodKey = k;
                });
                ed._place(salaryKey);
                ed._place(foodKey);
                ed._tryConnect(salaryKey, foodKey);
                const edge = ed.edges[0];

                ed._addAnchorAt(edge, 400, 100);
                ed.render();
                const afterAdd = {
                    anchorCount: edge.anchors.length,
                    diamondCount: document.querySelectorAll('.sankey-anchor-diamond').length,
                };

                const anchorEl = document.querySelector('.sankey-anchor');
                anchorEl.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                const afterDelete = {
                    anchorCount: edge.anchors.length,
                    diamondCount: document.querySelectorAll('.sankey-anchor-diamond').length,
                    edgeStillExists: ed.edges.includes(edge),
                };
                return {afterAdd, afterDelete};
                """
            )
            assert result["afterAdd"] == {"anchorCount": 1, "diamondCount": 1}
            assert result["afterDelete"] == {"anchorCount": 0, "diamondCount": 0, "edgeStillExists": True}
        finally:
            cleanup_user(ctx["email"])

    def test_right_click_on_anchor_itself_does_nothing(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(SANKEY_URL)
            time.sleep(1)
            result = driver.execute_script(
                """
                const ed = window._sankeyEditor;
                let salaryKey = null, foodKey = null;
                Object.entries(ed.catalog).forEach(([k, info]) => {
                    if (info.title === 'Salary') salaryKey = k;
                    if (info.title === 'Food') foodKey = k;
                });
                ed._place(salaryKey);
                ed._place(foodKey);
                ed._tryConnect(salaryKey, foodKey);
                const edge = ed.edges[0];
                ed._addAnchorAt(edge, 400, 100);
                ed.render();

                const anchorEl = document.querySelector('.sankey-anchor');
                const evt = new MouseEvent('contextmenu', {bubbles: true, cancelable: true});
                anchorEl.dispatchEvent(evt);
                return {anchorCount: edge.anchors.length, defaultPrevented: evt.defaultPrevented};
                """
            )
            assert result == {"anchorCount": 1, "defaultPrevented": True}
        finally:
            cleanup_user(ctx["email"])

    def test_deleting_edge_deletes_its_anchors_too(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(SANKEY_URL)
            time.sleep(1)
            result = driver.execute_script(
                """
                const ed = window._sankeyEditor;
                let salaryKey = null, foodKey = null;
                Object.entries(ed.catalog).forEach(([k, info]) => {
                    if (info.title === 'Salary') salaryKey = k;
                    if (info.title === 'Food') foodKey = k;
                });
                ed._place(salaryKey);
                ed._place(foodKey);
                ed._tryConnect(salaryKey, foodKey);
                const edge = ed.edges[0];
                ed._addAnchorAt(edge, 400, 100);
                ed.render();

                // A left click on the plain line (not the anchor) deletes
                // the whole connection, anchors and all.
                const pathEl = document.querySelector('.sankey-edge');
                pathEl.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                return {
                    edgeCount: ed.edges.length,
                    diamondCount: document.querySelectorAll('.sankey-anchor-diamond').length,
                };
                """
            )
            assert result == {"edgeCount": 0, "diamondCount": 0}
        finally:
            cleanup_user(ctx["email"])

    def test_shaped_line_stays_smooth_through_anchors(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(SANKEY_URL)
            time.sleep(1)
            # Anchors must reshape the line with a smooth, tangent-continuous
            # curve (all cubic-bezier "C" segments), the same rounded feel as
            # an unshaped connection -- never sharp straight-line "L" joints.
            d = driver.execute_script(
                """
                const ed = window._sankeyEditor;
                let salaryKey = null, foodKey = null;
                Object.entries(ed.catalog).forEach(([k, info]) => {
                    if (info.title === 'Salary') salaryKey = k;
                    if (info.title === 'Food') foodKey = k;
                });
                ed._place(salaryKey);
                ed._place(foodKey);
                ed._tryConnect(salaryKey, foodKey);
                const edge = ed.edges[0];
                ed._addAnchorAt(edge, 400, 500);
                ed._addAnchorAt(edge, 600, 100);
                ed.render();
                return document.querySelector('.sankey-edge').getAttribute('d');
                """
            )
            assert d.count("C") == 3  # source->anchor1, anchor1->anchor2, anchor2->target
            assert "L" not in d
        finally:
            cleanup_user(ctx["email"])


class TestSankeyStudioTooltip:
    def test_hovering_editor_edge_and_anchor_shows_instant_tooltip(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(SANKEY_URL)
            time.sleep(1)
            result = driver.execute_script(
                """
                const ed = window._sankeyEditor;
                let salaryKey = null, foodKey = null;
                Object.entries(ed.catalog).forEach(([k, info]) => {
                    if (info.title === 'Salary') salaryKey = k;
                    if (info.title === 'Food') foodKey = k;
                });
                ed._place(salaryKey);
                ed._place(foodKey);
                ed._tryConnect(salaryKey, foodKey);
                const edge = ed.edges[0];
                ed._addAnchorAt(edge, 400, 100);
                ed.render();

                const tooltip = document.getElementById('sankey-tooltip');
                const initiallyHidden = tooltip.style.display === 'none';

                const pathEl = document.querySelector('.sankey-edge');
                pathEl.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true, clientX: 10, clientY: 10}));
                const edgeTooltipText = tooltip.textContent;
                const edgeTooltipVisible = tooltip.style.display === 'block';
                pathEl.dispatchEvent(new MouseEvent('mouseleave', {bubbles: true}));
                const hiddenAfterLeave = tooltip.style.display === 'none';

                const anchorEl = document.querySelector('.sankey-anchor');
                anchorEl.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true, clientX: 20, clientY: 20}));
                const anchorTooltipText = tooltip.textContent;

                return {
                    initiallyHidden, edgeTooltipText, edgeTooltipVisible,
                    hiddenAfterLeave, anchorTooltipText,
                };
                """
            )
            assert result["initiallyHidden"] is True
            assert result["edgeTooltipText"] == "Left click: delete connection · Right click: add anchor"
            assert result["edgeTooltipVisible"] is True
            assert result["hiddenAfterLeave"] is True
            assert result["anchorTooltipText"] == "Left click: delete anchor · Right click: does nothing"
        finally:
            cleanup_user(ctx["email"])

    def test_generated_chart_uses_custom_tooltip_not_native_title(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            _create_expense(ctx["email"], "Salary", "Food", 250, "2026-07-10")

            driver.get(SANKEY_URL)
            time.sleep(1)
            driver.execute_script(
                """
                const ed = window._sankeyEditor;
                let salaryKey = null, foodKey = null;
                Object.entries(ed.catalog).forEach(([k, info]) => {
                    if (info.title === 'Salary') salaryKey = k;
                    if (info.title === 'Food') foodKey = k;
                });
                ed._place(salaryKey);
                ed._place(foodKey);
                ed._tryConnect(salaryKey, foodKey);
                ed.render();
                """
            )
            driver.find_element(By.ID, "sankey-generate").click()
            time.sleep(2)

            result = driver.execute_script(
                """
                const chartSvg = document.getElementById('sankey-chart');
                const nativeTitleCount = chartSvg.querySelectorAll('title').length;
                const rect = chartSvg.querySelector('g rect');
                rect.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true, clientX: 30, clientY: 30}));
                const tooltip = document.getElementById('sankey-tooltip');
                return {nativeTitleCount, tooltipText: tooltip.textContent, tooltipVisible: tooltip.style.display === 'block'};
                """
            )
            assert result["nativeTitleCount"] == 0
            assert result["tooltipText"] in ("Salary: 250.00", "Food: 250.00")
            assert result["tooltipVisible"] is True
        finally:
            cleanup_user(ctx["email"])


class TestSankeyStudioChartHeight:
    def test_chart_height_scales_with_a_crowded_column(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(SANKEY_URL)
            time.sleep(1)
            # 12 nodes all feeding one target used to be squeezed into a flat
            # 480px budget; height must now scale with the most crowded
            # column instead of being capped there.
            height = driver.execute_script(
                """
                const ed = window._sankeyEditor;
                const nodes = [];
                const links = [];
                for (let i = 0; i < 12; i++) {
                    nodes.push({key: `n${i}`, title: `N${i}`, value: 10, color: null});
                    links.push({source: `n${i}`, target: 'target', value: 10});
                }
                nodes.push({key: 'target', title: 'Target', value: 120, color: null});
                ed.chart = {nodes, links};
                ed._renderChart();
                return parseInt(document.getElementById('sankey-chart').getAttribute('height'), 10);
                """
            )
            assert height > 480
        finally:
            cleanup_user(ctx["email"])

    def test_chart_height_accounts_for_sinks_merged_by_justify_alignment(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(SANKEY_URL)
            time.sleep(1)
            # Root -> 8 direct leaves (naive longest-path depth 1) plus
            # Root -> Mid -> 8 more leaves (naive depth 2). d3-sankey's
            # default "justify" alignment pushes every *sink* node (no
            # outgoing links) to the same rightmost column regardless of its
            # natural depth, so all 16 leaves actually share one column --
            # a naive per-depth count (or reading the pre-alignment
            # `node.depth` instead of the post-alignment `node.layer`)
            # would only see 8 or 9 and undersize the chart.
            height = driver.execute_script(
                """
                const ed = window._sankeyEditor;
                const nodes = [
                    {key: 'root', title: 'Root', value: 160, color: null},
                    {key: 'mid', title: 'Mid', value: 80, color: null},
                ];
                const links = [];
                for (let i = 0; i < 8; i++) {
                    nodes.push({key: `leafA${i}`, title: `LeafA${i}`, value: 10, color: null});
                    links.push({source: 'root', target: `leafA${i}`, value: 10});
                }
                links.push({source: 'root', target: 'mid', value: 80});
                for (let i = 0; i < 8; i++) {
                    nodes.push({key: `leafB${i}`, title: `LeafB${i}`, value: 10, color: null});
                    links.push({source: 'mid', target: `leafB${i}`, value: 10});
                }
                ed.chart = {nodes, links};
                ed._renderChart();
                return parseInt(document.getElementById('sankey-chart').getAttribute('height'), 10);
                """
            )
            # 16 leaves sharing one column at 46px/node -> 736; a naive
            # per-depth count would have wrongly stopped at 480 (the old
            # floor) since no single *depth* has more than 9 nodes.
            assert height >= 700
        finally:
            cleanup_user(ctx["email"])


class TestSankeyStudioNodeSpawn:
    def test_new_node_spawns_inside_the_current_viewport_after_panning(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(SANKEY_URL)
            time.sleep(1)
            # Pan far away from the origin -- the old fixed-grid spawn logic
            # placed every new node starting at world (30, 30) regardless of
            # pan/zoom, which could land far outside a panned-away
            # viewport. A new node must now land inside whatever's actually
            # visible.
            result = driver.execute_script(
                """
                const ed = window._sankeyEditor;
                ed.pan = {x: -3000, y: -2000};
                ed.zoom = 1;
                ed.render();
                const rect = ed._viewportWorldRect();

                ed._addPassthrough();
                const key = Object.keys(ed.nodes).find((k) => k.startsWith('connector:'));
                const pos = ed.nodes[key];
                const withinViewport = pos.x >= rect.x0 && pos.x <= rect.x0 + rect.w
                    && pos.y >= rect.y0 && pos.y <= rect.y0 + rect.h;
                return {rect, pos: {x: pos.x, y: pos.y}, withinViewport};
                """
            )
            assert result["withinViewport"] is True
        finally:
            cleanup_user(ctx["email"])

    def test_repeated_spawns_in_a_small_zoomed_in_viewport_dont_stack_exactly(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(SANKEY_URL)
            time.sleep(1)
            # A heavily zoomed-in viewport only fits a couple of grid slots;
            # once they're used up, further adds must cascade with a small
            # offset instead of landing exactly on top of earlier nodes.
            result = driver.execute_script(
                """
                const ed = window._sankeyEditor;
                ed.pan = {x: -1000, y: -800};
                ed.zoom = 2.2;
                ed.render();

                const keys = Object.keys(ed.catalog).slice(0, 6);
                keys.forEach((k) => ed._place(k));
                const positions = keys.map((k) => `${ed.nodes[k].x.toFixed(1)},${ed.nodes[k].y.toFixed(1)}`);
                return {positionCount: positions.length, uniqueCount: new Set(positions).size};
                """
            )
            assert result["positionCount"] == 6
            assert result["uniqueCount"] == 6
        finally:
            cleanup_user(ctx["email"])


class TestSankeyStudioConnectAutoPan:
    def test_cursor_near_edge_while_connecting_auto_pans_toward_it(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(SANKEY_URL)
            time.sleep(1)
            # Two nodes far apart wouldn't both fit in the viewport, making
            # them impossible to wire together without panning manually
            # first -- dragging a connection with the cursor held near the
            # viewport's right edge must auto-pan the canvas toward it.
            # _autoPanTick is driven directly (deterministic, not dependent
            # on real requestAnimationFrame timing/tab visibility) the same
            # way _startAutoPanLoop's own rAF callback would drive it.
            result = driver.execute_script(
                """
                const ed = window._sankeyEditor;
                ed.pan = {x: 0, y: 0};
                ed.zoom = 1;
                ed.render();
                let key = null;
                Object.entries(ed.catalog).forEach(([k, info]) => {
                    if (info.title === 'Salary') key = k;
                });
                ed._place(key);
                ed.render();

                const panBefore = {...ed.pan};
                ed._startConnect(key, 'output', {clientX: 400, clientY: 400});
                const w = ed.svg.clientWidth;
                const h = ed.svg.clientHeight;
                ed._lastMouseScreenPos = {x: w - 5, y: h / 2};

                for (let i = 0; i < 20; i++) ed._autoPanTick();

                const panAfter = {...ed.pan};
                const tempLineD = ed._tempLine.getAttribute('d');
                const rafScheduledWhileConnecting = ed._autoPanRAF !== null;

                ed._endConnect();

                return {
                    panBefore, panAfter, tempLineD,
                    rafScheduledWhileConnecting,
                    rafStoppedAfterEnd: ed._autoPanRAF === null,
                    tempLineRemoved: !ed._tempLine,
                };
                """
            )
            assert result["panBefore"] == {"x": 0, "y": 0}
            # Cursor near the right edge pans the view rightward (pan.x
            # decreases) to reveal what's further right; vertically
            # centered, so pan.y is untouched.
            assert result["panAfter"]["x"] < 0
            assert result["panAfter"]["y"] == 0
            assert result["tempLineD"]
            assert result["rafScheduledWhileConnecting"] is True
            assert result["rafStoppedAfterEnd"] is True
            assert result["tempLineRemoved"] is True
        finally:
            cleanup_user(ctx["email"])

    def test_cursor_away_from_edges_does_not_auto_pan(self, driver, w):
        ctx = setup_user(driver, w)
        try:
            driver.get(SANKEY_URL)
            time.sleep(1)
            result = driver.execute_script(
                """
                const ed = window._sankeyEditor;
                ed.pan = {x: 0, y: 0};
                ed.zoom = 1;
                ed.render();
                let key = null;
                Object.entries(ed.catalog).forEach(([k, info]) => {
                    if (info.title === 'Salary') key = k;
                });
                ed._place(key);
                ed.render();

                ed._startConnect(key, 'output', {clientX: 400, clientY: 400});
                ed._lastMouseScreenPos = {x: ed.svg.clientWidth / 2, y: ed.svg.clientHeight / 2};
                for (let i = 0; i < 20; i++) ed._autoPanTick();
                const pan = {...ed.pan};
                ed._endConnect();
                return pan;
                """
            )
            assert result == {"x": 0, "y": 0}
        finally:
            cleanup_user(ctx["email"])
