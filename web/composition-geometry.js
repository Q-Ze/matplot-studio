/* Physical dimensions shared by the editable canvas and automatic height fitting. */
((root) => {
  "use strict";
  function rowWidths(layout, row) {
    const columns = Math.max(1, Math.min(6, Math.trunc(layout.columns) || 1));
    const configured = layout.row_width_ratios?.[row - 1];
    const ratios = configured?.length === columns ? configured : Array(columns).fill(1);
    const total = ratios.reduce((sum, value) => sum + value, 0);
    const available = layout.width_mm - 2 * layout.margin_mm - (columns - 1) * layout.gap_mm;
    return ratios.map((value) => available * value / total);
  }
  function parseWidthRatios(text, columns) {
    const ratios = text.trim().split(/[:：,，\s]+/).map(Number);
    if (ratios.length !== columns || ratios.some((value) => !Number.isFinite(value) || value <= 0 || value > 1000)) {
      throw new Error(`请填写 ${columns} 个大于 0、不超过 1000 的比例值，例如 ${Array(columns).fill(1).join(":")}`);
    }
    return ratios;
  }
  function panelBox(layout, panel) {
    const widths = rowWidths(layout, panel.row);
    const cellHeight = (layout.height_mm - 2 * layout.margin_mm - (layout.rows - 1) * layout.gap_mm) / layout.rows;
    return {
      x: layout.margin_mm + widths.slice(0, panel.column - 1).reduce((sum, value) => sum + value, 0) + (panel.column - 1) * layout.gap_mm,
      y: layout.margin_mm + (panel.row - 1) * (cellHeight + layout.gap_mm),
      width: widths.slice(panel.column - 1, panel.column - 1 + panel.colspan).reduce((sum, value) => sum + value, 0) + layout.gap_mm * (panel.colspan - 1),
      height: cellHeight * panel.rowspan + layout.gap_mm * (panel.rowspan - 1),
    };
  }
  function validateWidths(layout) {
    for (let row = 1; row <= layout.rows; row++) {
      if (rowWidths(layout, row).some((width) => width < 8)) throw new Error("宽度比例使部分区域小于 8 mm，请调整比例或增加画布宽度");
    }
    for (const panel of layout.panels) {
      const box = panelBox(layout, panel);
      for (let row = panel.row + 1; row < panel.row + panel.rowspan; row++) {
        const other = panelBox(layout, { ...panel, row });
        if (Math.abs(box.x - other.x) > 1e-6 || Math.abs(box.width - other.width) > 1e-6) {
          throw new Error("跨行子图的左右边界需对齐，请调整相关行的宽度比例或取消跨行");
        }
      }
    }
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
  const geometry = { panelBox, fittedHeight, imageBox, rowWidths, parseWidthRatios, validateWidths };
  if (typeof module !== "undefined" && module.exports) module.exports = geometry;
  else root.CompositionGeometry = geometry;
})(typeof window !== "undefined" ? window : globalThis);
