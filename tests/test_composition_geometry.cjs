const { test } = require("node:test");
const assert = require("node:assert/strict");
const { panelBox, fittedHeight, imageBox, rowWidths, rowHeights, parseWidthRatios, validateWidths, validateHeights } = require("../web/composition-geometry.js");

const base = { width_mm: 180, height_mm: 140, rows: 2, columns: 2,
  margin_mm: 4, gap_mm: 3, labels: "lower", label_size: 10,
  panels: [{ row: 1, column: 1, rowspan: 1, colspan: 1 }, { row: 2, column: 2, rowspan: 1, colspan: 1 }] };

test("5:4:3 splits 120 mm into 50, 40, 30 mm with equal-height regions", () => {
  const layout = { ...base, width_mm: 120, height_mm: 30, rows: 1, columns: 3, margin_mm: 0, gap_mm: 0,
    row_width_ratios: [[5, 4, 3]], panels: [1, 2, 3].map(column => ({row:1,column,rowspan:1,colspan:1})) };
  assert.deepEqual(layout.panels.map(panel => panelBox(layout, panel)), [
    {x:0,y:0,width:50,height:30}, {x:50,y:0,width:40,height:30}, {x:90,y:0,width:30,height:30},
  ]);
  assert.equal(fittedHeight(layout, [5 / 3, 4 / 3, 1]), 30);
  const inset = { ...layout, width_mm: 134, margin_mm: 4, gap_mm: 3 };
  assert.deepEqual(rowWidths(inset, 1), [50, 40, 30]);
  assert.equal(panelBox(inset, inset.panels[2]).x, 100);
  assert.deepEqual(imageBox({width:50,height:30},1), {x:10,y:0,width:30,height:30});
});

test("2:1 row heights compose with independent widths, margins and spanning", () => {
  const layout = { ...base, width_mm:134, height_mm:101, rows:2, columns:3,
    row_height_ratios:[2,1], row_width_ratios:[[5,4,3],[1,1,1]] };
  assert.deepEqual(rowHeights(layout),[60,30]);
  assert.deepEqual(panelBox(layout,{row:1,column:2,rowspan:1,colspan:1}),{x:57,y:4,width:40,height:60});
  assert.deepEqual(panelBox(layout,{row:2,column:2,rowspan:1,colspan:1}),{x:47,y:67,width:40,height:30});
  assert.deepEqual(panelBox(layout,{row:1,column:1,rowspan:2,colspan:3}),{x:4,y:4,width:126,height:93});
});

test("automatic height fitting preserves row ratios and contains every source", () => {
  const layout = {...base, width_mm:100, rows:3, columns:1, row_height_ratios:[2,1,3],
    panels:[{row:1,column:1,rowspan:2,colspan:1},{row:3,column:1,rowspan:1,colspan:1}]};
  const before = JSON.stringify(layout);
  const fitted = {...layout,height_mm:fittedHeight(layout,[2,1])};
  const heights = rowHeights(fitted);
  assert.ok(Math.abs(heights[0]/heights[1]-2)<1e-9);
  assert.ok(Math.abs(heights[2]/heights[1]-3)<1e-9);
  layout.panels.forEach((panel,index)=>assert.ok(panelBox(fitted,panel).height >= panelBox(fitted,panel).width / [2,1][index]));
  assert.equal(JSON.stringify(layout), before);
  assert.throws(()=>validateHeights({...base,row_height_ratios:[100,1]}),/8 mm/);
  assert.throws(()=>parseWidthRatios('2:1',0),/行列数/);
});

test("rows have independent ratios and spanning panels require aligned boundaries", () => {
  const layout = { ...base, width_mm:120, margin_mm:0, gap_mm:0, columns:3,
    row_width_ratios:[[5,4,3],[6,3,3]], panels:[{row:1,column:1,rowspan:2,colspan:2}] };
  assert.deepEqual(rowWidths(layout,2), [60,30,30]);
  validateWidths(layout);
  assert.equal(panelBox(layout,layout.panels[0]).width,90);
  assert.throws(() => validateWidths({...layout,panels:[{row:1,column:1,rowspan:2,colspan:1}]}), /左右边界/);
  assert.throws(() => validateWidths({...layout,row_width_ratios:[[100,1,1],[6,3,3]]}), /8 mm/);
});

test("ratio entry accepts decimals and Chinese separators but rejects invalid or incomplete values", () => {
  for (const value of ["5:4:3", "5：4：3", "5, 4, 3", "5 4 3"]) assert.deepEqual(parseWidthRatios(value,3),[5,4,3]);
  assert.deepEqual(parseWidthRatios("2.5:2:1.5",3),[2.5,2,1.5]);
  for (const value of ["", "5:4", "5:4:", "5:0:3", "5:-1:3", "NaN:4:3", "Infinity:4:3", "1001:4:3"]) {
    assert.throws(() => parseWidthRatios(value,3));
  }
});

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
    assert.ok(box.height >= box.width / ratios[index]);
  });
  const limiting = panelBox(fitted, base.panels[1]);
  assert.ok(limiting.height - limiting.width / 0.8 < 0.1);
});

test("spanning panels account for the internal gap without reserving a label band", () => {
  const layout = { ...base, panels: [{ row: 1, column: 1, rowspan: 2, colspan: 1 }] };
  layout.height_mm = fittedHeight(layout, [0.5]);
  const box = panelBox(layout, layout.panels[0]);
  assert.ok(box.height >= box.width / 0.5);
  assert.ok(box.height - box.width / 0.5 < 0.1);
});

test("label visibility and font size do not change fitted height or image placement", () => {
  const unlabelled = { ...base, labels: "none" };
  for (const labels of ["lower", "upper", "parentheses", "custom"]) {
    const layout = { ...base, labels, label_size: 24 };
    assert.deepEqual(panelBox(layout, base.panels[0]), panelBox(unlabelled, base.panels[0]));
    assert.equal(fittedHeight(layout, [1, 1]), fittedHeight(unlabelled, [1, 1]));
  }
});

test("overlay anchors follow the visible image even with horizontal or vertical letterboxing", () => {
  assert.deepEqual(imageBox({ width: 100, height: 100 }, 2), { x: 0, y: 25, width: 100, height: 50 });
  assert.deepEqual(imageBox({ width: 100, height: 100 }, 0.5), { x: 25, y: 0, width: 50, height: 100 });
});

test("fitting reports missing sources and oversized results without changing the layout", () => {
  const before = JSON.stringify(base);
  assert.throws(() => fittedHeight(base, [NaN, 1]), /尚未载入/);
  assert.throws(() => fittedHeight(base, [0.01, 1]), /400 mm/);
  assert.throws(() => fittedHeight({ ...base, panels: [] }, []), /添加子图/);
  assert.equal(JSON.stringify(base), before);
});
