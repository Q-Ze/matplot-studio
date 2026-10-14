const { test } = require("node:test");
const assert = require("node:assert/strict");
const { panelBox, fittedHeight } = require("../web/composition-geometry.js");

const base = { width_mm: 180, height_mm: 140, rows: 2, columns: 2,
  margin_mm: 4, gap_mm: 3, labels: "lower", label_size: 10,
  panels: [{ row: 1, column: 1, rowspan: 1, colspan: 1 }, { row: 2, column: 2, rowspan: 1, colspan: 1 }] };

test("physical boxes retain margins, gaps and spanning dimensions", () => {
  const first = panelBox(base, base.panels[0]), last = panelBox(base, base.panels[1]);
  assert.equal(first.x, 4); assert.equal(first.y, 4);
  assert.equal(first.width, 84.5); assert.equal(first.height, 64.5);
  assert.equal(last.x - first.x - first.width, 3);
  assert.equal(last.y - first.y - first.height, 3);
  assert.equal(last.x + last.width, 176); assert.equal(last.y + last.height, 136);
  const span = panelBox(base, { row: 1, column: 1, rowspan: 2, colspan: 2 });
  assert.equal(span.width, 172); assert.equal(span.height, 132);
});

test("height fitting accommodates the tallest original without distorting any panel", () => {
  const ratios = [2, 0.8], fitted = { ...base, height_mm: fittedHeight(base, ratios) };
  assert.equal(fitted.width_mm, base.width_mm);
  base.panels.forEach((panel, index) => {
    const box = panelBox(fitted, panel);
    assert.ok(box.height - box.labelHeight >= box.width / ratios[index]);
  });
  const limiting = panelBox(fitted, base.panels[1]);
  assert.ok(limiting.height - limiting.labelHeight - limiting.width / 0.8 < 0.1);
});

test("spanning panels account for the internal gap and a single label", () => {
  const layout = { ...base, panels: [{ row: 1, column: 1, rowspan: 2, colspan: 1 }] };
  layout.height_mm = fittedHeight(layout, [0.5]);
  const box = panelBox(layout, layout.panels[0]);
  assert.ok(box.height - box.labelHeight >= box.width / 0.5);
  assert.ok(box.height - box.labelHeight - box.width / 0.5 < 0.1);
});

test("hiding labels removes the reserved label band", () => {
  const layout = { ...base, labels: "none" };
  assert.equal(panelBox(layout, base.panels[0]).labelHeight, 0);
  assert.ok(fittedHeight(layout, [1, 1]) < fittedHeight(base, [1, 1]));
});

test("fitting reports missing sources and oversized results without changing the layout", () => {
  const before = JSON.stringify(base);
  assert.throws(() => fittedHeight(base, [NaN, 1]), /尚未载入/);
  assert.throws(() => fittedHeight(base, [0.01, 1]), /400 mm/);
  assert.throws(() => fittedHeight({ ...base, panels: [] }, []), /添加子图/);
  assert.equal(JSON.stringify(base), before);
});
