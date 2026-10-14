/* Project-scoped figure assembly. Source plots remain independent and editable. */
(() => {
  "use strict";
  const dialog = document.createElement("dialog");
  dialog.className = "composition-dialog";
  dialog.setAttribute("aria-labelledby", "compositionTitle");
  dialog.innerHTML = `
    <header class="composition-header">
      <div><span class="eyebrow" id="compositionProject"></span><h2 id="compositionTitle">科研拼图</h2></div>
      <div class="composition-actions"><button type="button" class="button button--quiet" data-action="new">新建拼图</button>
      <button type="button" class="button button--primary" data-action="save">保存拼图</button>
      <button type="button" class="button button--quiet" data-action="close" aria-label="关闭拼图编辑器">关闭</button></div>
    </header>
    <div class="composition-body">
      <aside class="composition-settings">
        <label class="form-field"><span>已保存的拼图</span><select id="compositionSaved"><option value="">新拼图</option></select></label>
        <label class="form-field"><span>拼图名称</span><input data-field="name" maxlength="100" required></label>
        <div class="composition-pair">
          <label class="form-field"><span>宽度 · mm</span><input data-field="width_mm" type="number" min="30" max="400" step="0.1" required></label>
          <label class="form-field"><span>高度 · mm</span><input data-field="height_mm" type="number" min="30" max="400" step="0.1" required></label>
        </div>
        <div class="composition-presets"><button type="button" data-width="85">单栏 85 mm</button><button type="button" data-width="180">双栏 180 mm</button></div>
        <button type="button" class="button button--quiet composition-fit" data-action="fit">按原图比例适配高度</button>
        <div class="composition-pair">
          <label class="form-field"><span>行数</span><input data-field="rows" type="number" min="1" max="6" required></label>
          <label class="form-field"><span>列数</span><input data-field="columns" type="number" min="1" max="6" required></label>
          <label class="form-field"><span>外边距 · mm</span><input data-field="margin_mm" type="number" min="0" max="40" step="0.5" required></label>
          <label class="form-field"><span>格间距 · mm</span><input data-field="gap_mm" type="number" min="0" max="40" step="0.5" required></label>
        </div>
        <div class="composition-pair">
          <label class="form-field"><span>子图标注</span><select data-field="labels"><option value="lower">a, b, c</option><option value="upper">A, B, C</option><option value="parentheses">(a), (b), (c)</option><option value="custom">自定义</option><option value="none">不显示</option></select></label>
          <label class="form-field"><span>标注字号 · pt</span><input data-field="label_size" type="number" min="6" max="24" step="0.5" required></label>
        </div>
        <label class="form-field"><span>原图边界</span><select data-field="source_bounds"><option value="tight">裁去原图外部留白</option><option value="canvas">保留原图完整画布</option></select></label>
        <p class="composition-hint">编辑画布自动载入真实子图并保持比例。适配高度会保留当前宽度和网格，尽量减少上下留白。</p>
        <button type="button" class="button button--quiet composition-delete" data-action="delete">删除此拼图</button>
      </aside>
      <main class="composition-work">
        <div class="composition-toolbar"><strong>排版预览</strong><span id="compositionDimensions"></span>
          <div class="composition-modes" role="group" aria-label="画布模式">
            <button type="button" data-action="edit" aria-pressed="true">编辑布局</button>
            <button type="button" data-action="view" aria-pressed="false">实际预览</button>
          </div>
          <button type="button" class="button button--quiet" data-action="preview">生成预览</button>
          <button type="button" class="button button--quiet" data-action="refresh">刷新原图</button>
          <select id="compositionDpi" aria-label="PNG 分辨率"><option value="300">300 DPI</option><option value="600">600 DPI</option></select>
          <button type="button" class="button button--quiet" data-export="pdf">PDF</button><button type="button" class="button button--quiet" data-export="svg">SVG</button><button type="button" class="button button--quiet" data-export="png">PNG</button>
        </div>
        <p id="compositionStatus" class="composition-status" role="status" aria-live="polite"></p>
        <div class="composition-preview"><div id="compositionGrid" aria-label="拼图网格"></div><img id="compositionImage" alt="拼图实际导出效果" hidden></div>
        <section class="composition-panels">
          <div class="composition-toolbar"><strong>子图与位置</strong><span>拖动网格子图可换位；行列从 1 开始</span><button type="button" class="button button--quiet" data-action="arrange">按顺序平铺</button><button type="button" class="button button--quiet" data-action="add">＋ 添加子图</button></div>
          <div id="compositionPanels"></div>
        </section>
      </main>
    </div>`;
  document.body.append(dialog);
  const $ = (selector) => dialog.querySelector(selector);
  const fields = [...dialog.querySelectorAll("[data-field]")];
  let project, layout, saved = [], current = null, baseline = "", busy = false, previewUrl = null, dragging = null;
  let mode = "edit", thumbnailSession = 0, thumbnailQueue = Promise.resolve();
  const thumbnails = new Map();
  const { panelBox, fittedHeight } = window.CompositionGeometry;
  const defaults = () => ({ name: "Figure 1", width_mm: 180, height_mm: 140, rows: 2, columns: 2,
    margin_mm: 4, gap_mm: 3, labels: "lower", label_size: 10, source_bounds: "tight", panels: [] });
  const baseUrl = () => `/api/projects/${encodeURIComponent(project.id)}/compositions`;
  const dirty = () => JSON.stringify(layout) !== baseline;
  const node = (tag, text, className = "") => {
    const el = document.createElement(tag); el.textContent = text; el.className = className; return el;
  };
  function status(message, error = false) {
    $("#compositionStatus").textContent = message;
    $("#compositionStatus").classList.toggle("is-error", error);
  }
  async function request(url, options = {}, blob = false) {
    const response = await fetch(url, { ...options, headers: { "Content-Type": "application/json" } });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error?.message || error.detail?.map?.((item) => item.msg).join("；") || `请求失败（${response.status}）`);
    }
    return blob ? response.blob() : response.json();
  }
  function invalidate() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
    setMode("edit");
    drawGrid();
  }
  function setMode(value) {
    mode = value;
    $("#compositionImage").hidden = mode !== "preview";
    $("#compositionGrid").hidden = mode !== "edit";
    $('[data-action="edit"]').setAttribute("aria-pressed", String(mode === "edit"));
    $('[data-action="view"]').setAttribute("aria-pressed", String(mode === "preview"));
    status((mode === "edit" ? "编辑布局 · 真实子图等比例显示，可拖动换位" : "实际导出效果") + (dirty() ? " · 有未保存修改" : " · 已保存"));
  }
  function clearThumbnails() {
    thumbnailSession += 1;
    thumbnails.forEach((entry) => { entry.controller.abort(); if (entry.url) URL.revokeObjectURL(entry.url); });
    thumbnails.clear(); thumbnailQueue = Promise.resolve();
  }
  function thumbnail(plot) {
    const key = `${project.id}/${plot}/${layout.source_bounds}`;
    if (thumbnails.has(key)) return thumbnails.get(key);
    const session = thumbnailSession, bounds = layout.source_bounds, projectId = project.id;
    const entry = { state: "loading", controller: new AbortController() };
    thumbnails.set(key, entry);
    entry.promise = thumbnailQueue.then(async () => {
      if (session !== thumbnailSession) return entry;
      try {
        const blob = await request(`/api/projects/${encodeURIComponent(projectId)}/plots/${encodeURIComponent(plot)}/export/image?format=svg&bounds=${bounds}`, { signal: entry.controller.signal }, true);
        const source = new DOMParser().parseFromString(await blob.text(), "image/svg+xml");
        const svg = source.documentElement, viewBox = svg.getAttribute("viewBox")?.trim().split(/[\s,]+/).map(Number);
        const width = viewBox?.[2] || parseFloat(svg.getAttribute("width"));
        const height = viewBox?.[3] || parseFloat(svg.getAttribute("height"));
        if (svg.localName !== "svg" || !(width > 0 && height > 0)) throw new Error("无法读取原图尺寸");
        if (session !== thumbnailSession) return entry;
        Object.assign(entry, { state: "ready", ratio: width / height, url: URL.createObjectURL(blob) });
      } catch (error) {
        if (session === thumbnailSession) Object.assign(entry, { state: "error", error: error.message || "原图载入失败" });
      }
      if (session === thumbnailSession && dialog.open && mode === "edit") drawGrid();
      return entry;
    });
    thumbnailQueue = entry.promise;
    return entry;
  }
  function labelFor(index) {
    if (layout.labels === "none") return "";
    if (layout.labels === "custom") return layout.panels[index].label;
    const letter = String.fromCharCode((layout.labels === "upper" ? 65 : 97) + index);
    return layout.labels === "parentheses" ? `(${letter})` : letter;
  }
  function drawGrid() {
    const grid = $("#compositionGrid"); grid.replaceChildren();
    const rows = Math.max(1, Math.min(6, layout.rows || 1)), columns = Math.max(1, Math.min(6, layout.columns || 1));
    grid.style.aspectRatio = `${layout.width_mm || 180} / ${layout.height_mm || 140}`;
    grid.style.width = `min(100%, 680px, ${55 * (layout.width_mm || 180) / (layout.height_mm || 140)}vh)`;
    const position = (el, panel) => {
      const box = panelBox(layout, panel);
      el.style.left = `${100 * box.x / layout.width_mm}%`;
      el.style.top = `${100 * box.y / layout.height_mm}%`;
      el.style.width = `${100 * box.width / layout.width_mm}%`;
      el.style.height = `${100 * box.height / layout.height_mm}%`;
      return box;
    };
    $("#compositionDimensions").textContent = `${layout.width_mm} × ${layout.height_mm} mm`;
    for (let row = 1; row <= rows; row++) for (let column = 1; column <= columns; column++) {
      const cell = node("div", `${row}, ${column}`, "composition-cell");
      position(cell, { row, column, rowspan: 1, colspan: 1 });
      cell.addEventListener("dragover", (event) => event.preventDefault());
      cell.addEventListener("drop", (event) => {
        event.preventDefault(); if (dragging === null || busy) return;
        Object.assign(layout.panels[dragging], { row, column }); renderPanels(); invalidate();
      });
      grid.append(cell);
    }
    layout.panels.forEach((panel, index) => {
      if (panel.row < 1 || panel.column < 1 || panel.row + panel.rowspan - 1 > rows || panel.column + panel.colspan - 1 > columns) return;
      const tile = node("div", "", "composition-tile");
      const box = position(tile, panel);
      const title = project.plots.find((plot) => plot.id === panel.plot)?.name || "原图已不存在";
      tile.title = `${labelFor(index)} ${title} · 拖动换位`;
      tile.setAttribute("aria-label", tile.title);
      const label = node("b", labelFor(index));
      label.style.height = `${100 * box.labelHeight / box.height}%`;
      label.style.fontSize = `${layout.label_size * 25.4 / 72 / layout.width_mm * 100}cqw`;
      const artwork = node("div", "", "composition-artwork");
      artwork.style.top = `${100 * box.labelHeight / box.height}%`;
      const source = thumbnail(panel.plot);
      if (source.state === "ready") {
        const img = document.createElement("img"); img.src = source.url; img.alt = title; img.draggable = false;
        artwork.append(img);
      } else {
        artwork.append(node("span", source.state === "error" ? `${title}：${source.error}（可刷新原图重试）` : `${title} · 正在载入…`));
      }
      tile.append(label, artwork);
      tile.draggable = true;
      tile.addEventListener("dragstart", (event) => { dragging = index; event.dataTransfer.setData("text/plain", String(index)); });
      tile.addEventListener("dragend", () => { dragging = null; });
      tile.addEventListener("dragover", (event) => event.preventDefault());
      tile.addEventListener("drop", (event) => {
        event.preventDefault(); if (dragging === null || dragging === index || busy) return;
        const other = layout.panels[dragging];
        [other.row, panel.row] = [panel.row, other.row]; [other.column, panel.column] = [panel.column, other.column];
        renderPanels(); invalidate();
      });
      grid.append(tile);
    });
  }
  function renderPanels() {
    const container = $("#compositionPanels"); container.replaceChildren();
    if (!layout.panels.length) container.append(node("p", "先添加子图，再设置其行列位置。", "composition-hint"));
    layout.panels.forEach((panel, index) => {
      const row = node("div", "", "composition-panel-row");
      const sourceLabel = node("label", `子图 ${index + 1}`);
      const select = document.createElement("select"); select.setAttribute("aria-label", `子图 ${index + 1} 来源`);
      project.plots.forEach((plot) => { const option = node("option", plot.name); option.value = plot.id; select.append(option); });
      if (!project.plots.some((plot) => plot.id === panel.plot)) { const option = node("option", "原图已不存在，请重新选择"); option.value = panel.plot; select.append(option); }
      select.value = panel.plot; select.addEventListener("change", () => { panel.plot = select.value; invalidate(); });
      sourceLabel.append(select); row.append(sourceLabel);
      for (const [key, title] of [["row", "行"], ["column", "列"], ["rowspan", "跨行"], ["colspan", "跨列"], ["label", "自定义标注"]]) {
        const wrapper = node("label", title), input = document.createElement("input");
        input.setAttribute("aria-label", `子图 ${index + 1} ${title}`);
        input.value = panel[key]; input.type = key === "label" ? "text" : "number";
        if (key === "label") { input.maxLength = 16; input.placeholder = "如 (a)"; input.disabled = layout.labels !== "custom"; }
        else { input.min = 1; input.max = 6; input.required = true; }
        input.addEventListener("input", () => { panel[key] = key === "label" ? input.value : Number(input.value); invalidate(); });
        wrapper.append(input); row.append(wrapper);
      }
      const up = node("button", "↑"), remove = node("button", "移除");
      up.type = remove.type = "button"; up.title = "上移标注顺序"; up.setAttribute("aria-label", `上移子图 ${index + 1} 的标注顺序`); up.disabled = index === 0;
      up.addEventListener("click", () => { [layout.panels[index - 1], layout.panels[index]] = [panel, layout.panels[index - 1]]; renderPanels(); invalidate(); });
      remove.addEventListener("click", () => { layout.panels.splice(index, 1); renderPanels(); invalidate(); });
      row.append(up, remove); container.append(row);
    });
  }
  function populate() {
    fields.forEach((field) => { field.value = layout[field.dataset.field]; });
    renderPanels(); invalidate();
    $('[data-action="delete"]').hidden = !current;
  }
  function savedOptions() {
    const select = $("#compositionSaved"); select.replaceChildren();
    const fresh = node("option", "新拼图（未保存）"); fresh.value = ""; select.append(fresh);
    saved.forEach((item) => { const option = node("option", item.layout.name); option.value = item.id; select.append(option); });
    select.value = current?.id || "";
  }
  function validate() {
    for (const field of dialog.querySelectorAll("input")) if (!field.reportValidity()) throw new Error("请检查输入值");
    if (!layout.name.trim()) throw new Error("请输入拼图名称");
    if (!layout.panels.length) throw new Error("请至少添加一张子图");
    const cells = new Set();
    for (const panel of layout.panels) {
      if (panel.row + panel.rowspan - 1 > layout.rows || panel.column + panel.colspan - 1 > layout.columns) throw new Error("子图超出网格，请调整位置或行列数");
      for (let r = panel.row; r < panel.row + panel.rowspan; r++) for (let c = panel.column; c < panel.column + panel.colspan; c++) {
        const key = `${r},${c}`; if (cells.has(key)) throw new Error("子图位置重叠，请调整位置或使用“按顺序平铺”"); cells.add(key);
      }
    }
  }
  async function save() {
    validate();
    const result = await request(current ? `${baseUrl()}/${current.id}` : baseUrl(), {
      method: current ? "PUT" : "POST", body: JSON.stringify(current ? { layout, revision: current.revision } : layout),
    });
    current = result;
    // Keep the live panel objects used by the input listeners after saving.
    layout.name = result.layout.name;
    $('[data-field="name"]').value = layout.name;
    baseline = JSON.stringify(layout);
    saved = saved.filter((item) => item.id !== current.id); saved.push(current); savedOptions();
    $('[data-action="delete"]').hidden = false; status("拼图已保存");
  }
  async function run(action, validateLayout = false) {
    if (busy) return;
    try { if (validateLayout) validate(); } catch (error) { status(error.message, true); return; }
    busy = true;
    const controls = [...dialog.querySelectorAll("button, input, select")];
    const disabled = controls.map((control) => control.disabled);
    controls.forEach((control) => { control.disabled = true; });
    dialog.setAttribute("aria-busy", "true");
    try { await action(); } catch (error) { status(error.message || "操作失败", true); }
    finally { controls.forEach((control, i) => { control.disabled = disabled[i]; }); busy = false; dialog.removeAttribute("aria-busy"); }
  }
  async function preview() {
    validate(); status("正在渲染子图并生成预览…");
    const blob = await request(`${baseUrl()}/preview`, { method: "POST", body: JSON.stringify(layout) }, true);
    if (previewUrl) URL.revokeObjectURL(previewUrl); previewUrl = URL.createObjectURL(blob);
    $("#compositionImage").src = previewUrl;
    setMode("preview");
  }
  function canDiscard() { return !dirty() || window.confirm("有未保存的拼图修改，确定放弃这些修改吗？"); }
  function close() { if (busy || !canDiscard()) return; if (previewUrl) URL.revokeObjectURL(previewUrl); previewUrl = null; clearThumbnails(); dialog.close(); }
  fields.forEach((field) => field.addEventListener("input", () => {
    layout[field.dataset.field] = field.type === "number" ? Number(field.value) : field.value;
    if (field.dataset.field === "labels") renderPanels(); invalidate();
  }));
  $("#compositionSaved").addEventListener("change", () => {
    if (!canDiscard()) { $("#compositionSaved").value = current?.id || ""; return; }
    current = saved.find((item) => item.id === $("#compositionSaved").value) || null;
    layout = current ? structuredClone(current.layout) : defaults(); baseline = JSON.stringify(layout); populate();
  });
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); close(); });
  window.addEventListener("beforeunload", (event) => { if (dialog.open && dirty()) { event.preventDefault(); event.returnValue = ""; } });
  dialog.addEventListener("click", (event) => {
    const button = event.target.closest("button"); if (!button || busy) return;
    if (button.dataset.width) { layout.width_mm = Number(button.dataset.width); populate(); return; }
    if (button.dataset.export) {
      const format = button.dataset.export;
      run(async () => {
        await save(); status(`正在导出 ${format.toUpperCase()}…`);
        const blob = await request(`${baseUrl()}/${current.id}/export?format=${format}&dpi=${$("#compositionDpi").value}&revision=${current.revision}`, {}, true);
        const url = URL.createObjectURL(blob), anchor = document.createElement("a");
        anchor.href = url; anchor.download = `${layout.name.replace(/[\\/:*?"<>|]/g, "_")}.${format}`; document.body.append(anchor); anchor.click(); anchor.remove();
        setTimeout(() => URL.revokeObjectURL(url), 60000); status(`${format.toUpperCase()} 已导出，拼图已保存`);
      }, true); return;
    }
    const action = button.dataset.action;
    if (action === "close") close();
    if (action === "new" && canDiscard()) { current = null; layout = defaults(); baseline = JSON.stringify(layout); savedOptions(); populate(); }
    if (action === "save") run(save, true);
    if (action === "edit") { setMode("edit"); drawGrid(); }
    if (action === "view") { if (previewUrl) setMode("preview"); else run(preview, true); }
    if (action === "preview") run(preview, true);
    if (action === "refresh") { clearThumbnails(); invalidate(); }
    if (action === "fit") run(async () => {
      validate(); status("正在读取原图比例并适配高度…");
      const sources = await Promise.all(layout.panels.map((panel) => thumbnail(panel.plot).promise));
      const failed = sources.find((source) => source.state !== "ready");
      if (failed) throw new Error(failed.error || "原图载入失败，请刷新原图后重试");
      layout.height_mm = fittedHeight(layout, sources.map((source) => source.ratio));
      fields.find((field) => field.dataset.field === "height_mm").value = layout.height_mm;
      invalidate(); status(`已按原图比例适配为 ${layout.width_mm} × ${layout.height_mm} mm，宽度和网格保持不变`);
    }, true);
    if (action === "delete" && current && window.confirm(`确定删除拼图“${current.layout.name}”吗？原图会保留。`)) run(async () => {
      await request(`${baseUrl()}/${current.id}?revision=${current.revision}`, { method: "DELETE" });
      saved = saved.filter((item) => item.id !== current.id); current = null; layout = defaults(); baseline = JSON.stringify(layout); savedOptions(); populate(); status("拼图已删除");
    });
    if (action === "arrange") {
      if (layout.panels.length > layout.rows * layout.columns) { status("网格不足，请先增加行列数", true); return; }
      layout.panels.forEach((panel, index) => Object.assign(panel, { row: Math.floor(index / layout.columns) + 1, column: index % layout.columns + 1, rowspan: 1, colspan: 1 }));
      renderPanels(); invalidate();
    }
    if (action === "add") {
      if (!project.plots.length) { status("请先向项目添加图表", true); return; }
      if (layout.panels.length >= 16) { status("每张拼图最多支持 16 张子图", true); return; }
      let slot;
      for (let row = 1; row <= layout.rows && !slot; row++) for (let column = 1; column <= layout.columns; column++) {
        if (!layout.panels.some((panel) => row >= panel.row && row < panel.row + panel.rowspan && column >= panel.column && column < panel.column + panel.colspan)) { slot = { row, column }; break; }
      }
      if (!slot) { status("网格已满，请先增加行列数", true); return; }
      const source = project.plots.find((plot) => !layout.panels.some((panel) => panel.plot === plot.id)) || project.plots[0];
      layout.panels.push({ plot: source.id, ...slot, rowspan: 1, colspan: 1, label: "" }); renderPanels(); invalidate();
    }
  });
  window.CompositionEditor = {
    async open(selectedProject) {
      if (dialog.open) return;
      clearThumbnails();
      project = selectedProject; current = null; layout = defaults(); baseline = JSON.stringify(layout); saved = [];
      $("#compositionProject").textContent = project.name; savedOptions(); populate(); dialog.showModal();
      await run(async () => {
        status("正在载入已保存的拼图…");
        saved = (await request(baseUrl())).compositions;
        if (saved.length) { current = saved[0]; layout = structuredClone(current.layout); baseline = JSON.stringify(layout); }
        savedOptions(); populate();
      });
    },
  };
})();
