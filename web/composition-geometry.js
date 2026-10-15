/* Physical dimensions shared by the editable canvas and automatic height fitting. */
((root) => {
  "use strict";
  function panelBox(layout, panel) {
    const cellWidth = (layout.width_mm - 2 * layout.margin_mm - (layout.columns - 1) * layout.gap_mm) / layout.columns;
    const cellHeight = (layout.height_mm - 2 * layout.margin_mm - (layout.rows - 1) * layout.gap_mm) / layout.rows;
    return {
      x: layout.margin_mm + (panel.column - 1) * (cellWidth + layout.gap_mm),
      y: layout.margin_mm + (panel.row - 1) * (cellHeight + layout.gap_mm),
      width: cellWidth * panel.colspan + layout.gap_mm * (panel.colspan - 1),
      height: cellHeight * panel.rowspan + layout.gap_mm * (panel.rowspan - 1),
    };
  }
  function fittedHeight(layout, ratios) {
    if (!layout.panels.length) throw new Error("请先添加子图");
    let rowHeight = 8;
    layout.panels.forEach((panel, index) => {
      const ratio = ratios[index];
      if (!Number.isFinite(ratio) || ratio <= 0) throw new Error("原图尚未载入，无法适配尺寸");
      const box = panelBox(layout, panel);
      if (box.width < 8) throw new Error("画布过窄，请增加宽度或减小边距");
      rowHeight = Math.max(rowHeight, (box.width / ratio - (panel.rowspan - 1) * layout.gap_mm) / panel.rowspan);
    });
    const height = Math.ceil((2 * layout.margin_mm + layout.rows * rowHeight + (layout.rows - 1) * layout.gap_mm) * 10) / 10;
    if (height > 400) throw new Error("适配后高度超过 400 mm，请减小宽度、增加列数或调整跨格");
    return Math.max(30, height);
  }
  function imageBox(box, ratio) {
    const width = Math.min(box.width, box.height * ratio);
    const height = width / ratio;
    return { x: (box.width - width) / 2, y: (box.height - height) / 2, width, height };
  }
  const geometry = { panelBox, fittedHeight, imageBox };
  if (typeof module !== "undefined" && module.exports) module.exports = geometry;
  else root.CompositionGeometry = geometry;
})(typeof window !== "undefined" ? window : globalThis);
