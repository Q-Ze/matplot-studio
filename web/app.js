(() => {
  "use strict";

  const API_ROOT = "/api";
  const AUTOSAVE_DELAY = 1200;
  const PROPERTY_DELAY = 420;
  const ZOOM_MIN = 0.08;
  const ZOOM_MAX = 8;
  const CLIPBOARD_PNG_DPI = 600;

  const $ = (selector, root = document) => root.querySelector(selector);

  const dom = {
    app: $("#app"),
    explorer: $("#explorer"),
    inspector: $("#inspector"),
    toggleExplorer: $("#toggleExplorer"),
    toggleInspector: $("#toggleInspector"),
    mobileBackdrop: $("#mobileBackdrop"),
    projectTree: $("#projectTree"),
    projectSearch: $("#projectSearch"),
    refreshProjectsButton: $("#refreshProjectsButton"),
    importProjectButton: $("#importProjectButton"),
    newProjectButton: $("#newProjectButton"),
    breadcrumbProject: $("#breadcrumbProject"),
    breadcrumbPlot: $("#breadcrumbPlot"),
    globalStatus: $("#globalStatus"),
    globalStatusText: $("#globalStatusText"),
    renderButton: $("#renderButton"),
    copyPngButton: $("#copyPngButton"),
    imageExportMenu: $("#imageExportMenu"),
    imageExportButton: $("#imageExportButton"),
    imageExportPopover: $("#imageExportPopover"),
    dataExportMenu: $("#dataExportMenu"),
    dataExportButton: $("#dataExportButton"),
    dataExportPopover: $("#dataExportPopover"),
    exportCsvOption: $("#exportCsvOption"),
    exportJsonOption: $("#exportJsonOption"),
    dataExportNote: $("#dataExportNote"),
    canvasViewport: $("#canvasViewport"),
    renderStage: $("#renderStage"),
    renderContent: $("#renderContent"),
    canvasEmpty: $("#canvasEmpty"),
    canvasLoading: $("#canvasLoading"),
    canvasError: $("#canvasError"),
    canvasErrorText: $("#canvasErrorText"),
    canvasHelp: $("#canvasHelp"),
    canvasMeta: $("#canvasMeta"),
    retryRenderButton: $("#retryRenderButton"),
    fitCanvasButton: $("#fitCanvasButton"),
    zoomOutButton: $("#zoomOutButton"),
    zoomInButton: $("#zoomInButton"),
    resetZoomButton: $("#resetZoomButton"),
    studio: $(".studio"),
    editorResizer: $("#editorResizer"),
    editorTitle: $("#editorTitle"),
    dirtyDot: $("#dirtyDot"),
    autoRenderToggle: $("#autoRenderToggle"),
    saveState: $("#saveState"),
    codeInput: $("#codeInput"),
    lineNumbers: $("#lineNumbers"),
    cursorPosition: $("#cursorPosition"),
    errorSummary: $("#errorSummary"),
    errorSummaryText: $("#errorSummaryText"),
    errorConsole: $("#errorConsole"),
    errorConsoleText: $("#errorConsoleText"),
    closeErrorConsole: $("#closeErrorConsole"),
    propertySearch: $("#propertySearch"),
    propertiesPanel: $("#propertiesPanel"),
    detectedCount: $("#detectedCount"),
    inspectorNotice: $("#inspectorNotice"),
    propertySyncState: $("#propertySyncState"),
    createProjectDialog: $("#createProjectDialog"),
    createProjectForm: $("#createProjectForm"),
    newProjectName: $("#newProjectName"),
    createProjectError: $("#createProjectError"),
    confirmCreateProject: $("#confirmCreateProject"),
    importProjectDialog: $("#importProjectDialog"),
    importProjectForm: $("#importProjectForm"),
    closeImportProjectDialog: $("#closeImportProjectDialog"),
    chooseProjectZip: $("#chooseProjectZip"),
    chooseProjectFolder: $("#chooseProjectFolder"),
    projectZipInput: $("#projectZipInput"),
    projectFolderInput: $("#projectFolderInput"),
    importProjectFeedback: $("#importProjectFeedback"),
    importProjectFeedbackText: $("#importProjectFeedbackText"),
    importProjectSpinner: $("#importProjectSpinner"),
    cancelImportProject: $("#cancelImportProject"),
    importPlotDialog: $("#importPlotDialog"),
    importPlotForm: $("#importPlotForm"),
    importPlotProjectLabel: $("#importPlotProjectLabel"),
    closeImportPlotDialog: $("#closeImportPlotDialog"),
    choosePlotFile: $("#choosePlotFile"),
    choosePlotFolder: $("#choosePlotFolder"),
    plotFileInput: $("#plotFileInput"),
    plotFolderInput: $("#plotFolderInput"),
    importPlotFeedback: $("#importPlotFeedback"),
    importPlotFeedbackText: $("#importPlotFeedbackText"),
    importPlotSpinner: $("#importPlotSpinner"),
    cancelImportPlot: $("#cancelImportPlot"),
    createPlotDialog: $("#createPlotDialog"),
    createPlotForm: $("#createPlotForm"),
    newPlotProjectLabel: $("#newPlotProjectLabel"),
    newPlotName: $("#newPlotName"),
    createPlotError: $("#createPlotError"),
    confirmCreatePlot: $("#confirmCreatePlot"),
    deleteEntityDialog: $("#deleteEntityDialog"),
    deleteEntityForm: $("#deleteEntityForm"),
    deleteEntityKindLabel: $("#deleteEntityKindLabel"),
    deleteEntityTitle: $("#deleteEntityTitle"),
    deleteEntityName: $("#deleteEntityName"),
    deleteEntityDescription: $("#deleteEntityDescription"),
    deleteEntityError: $("#deleteEntityError"),
    closeDeleteEntityDialog: $("#closeDeleteEntityDialog"),
    cancelDeleteEntity: $("#cancelDeleteEntity"),
    confirmDeleteEntity: $("#confirmDeleteEntity"),
    toastRegion: $("#toastRegion"),
    toastTemplate: $("#toastTemplate"),
  };

  const state = {
    projects: [],
    project: null,
    plot: null,
    current: null,
    revision: null,
    settings: {},
    schemaGroups: [],
    propertyMap: new Map(),
    dirty: false,
    saving: false,
    rendering: false,
    loadingPlot: false,
    pendingSettings: 0,
    exporting: null,
    copyingPng: false,
    importing: false,
    importingLabel: null,
    deleting: false,
    codeVersion: 0,
    autosaveTimer: null,
    propertyTimers: new Map(),
    patchChain: Promise.resolve(),
    loadToken: 0,
    artifactToken: 0,
    artifactAbort: null,
    selectedProjectForNewPlot: null,
    selectedProjectForImportPlot: null,
    deleteTarget: null,
    confirmationResolver: null,
    pausedAutosaveForDialog: false,
    collapsedProjects: new Set(readStorage("matplot.collapsedProjects", [])),
    collapsedGroups: new Set(readStorage("matplot.collapsedGroups", [])),
    transform: { zoom: 1, x: 0, y: 0 },
    asset: { width: 0, height: 0 },
    fitted: true,
    panning: null,
    statusError: null,
  };

  class ApiError extends Error {
    constructor(message, status = 0, payload = null) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.payload = payload;
    }
  }

  function readStorage(key, fallback) {
    try {
      const value = JSON.parse(localStorage.getItem(key));
      return value ?? fallback;
    } catch {
      return fallback;
    }
  }

  function writeStorage(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Storage is optional; the editor remains fully functional without it.
    }
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function icon(path, viewBox = "0 0 20 20") {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", viewBox);
    svg.setAttribute("aria-hidden", "true");
    const pathNode = document.createElementNS("http://www.w3.org/2000/svg", "path");
    pathNode.setAttribute("d", path);
    svg.append(pathNode);
    return svg;
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function unwrap(payload) {
    if (isObject(payload) && isObject(payload.data)) return payload.data;
    return payload;
  }

  function displayName(value, fallback = "未命名") {
    if (typeof value === "string" && value.trim()) return value.trim();
    if (isObject(value)) return value.name || value.title || value.label || value.id || fallback;
    return fallback;
  }

  function entityId(value, fallback = "") {
    if (typeof value === "string" || typeof value === "number") return String(value);
    if (isObject(value)) return String(value.id ?? value.slug ?? value.key ?? value.name ?? fallback);
    return fallback;
  }

  function encodeSegment(value) {
    return encodeURIComponent(String(value));
  }

  function plotPath(projectId = state.project?.id, plotId = state.plot?.id) {
    return `${API_ROOT}/projects/${encodeSegment(projectId)}/plots/${encodeSegment(plotId)}`;
  }

  function extractMessage(payload, fallback) {
    if (typeof payload === "string") return payload.trim() || fallback;
    if (!payload) return fallback;
    const detail = payload.detail ?? payload.error ?? payload.message;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((item) => item.msg || item.message || String(item)).join("\n");
    }
    if (isObject(detail)) return detail.message || detail.detail || JSON.stringify(detail, null, 2);
    return fallback;
  }

  function friendlyError(error) {
    if (error instanceof ApiError) {
      if (error.status === 409) return "内容已在其他位置更新，请刷新项目后重试。";
      if (error.status === 404) return "请求的项目或图表不存在。";
      return error.message;
    }
    if (error instanceof TypeError && /fetch|network|load/i.test(error.message)) {
      return "无法连接本地服务，请确认应用服务已经启动。";
    }
    return error?.message || "发生了未知错误。";
  }

  async function apiRequest(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body !== undefined && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    headers.set("Accept", "application/json, image/svg+xml, text/plain");

    let response;
    try {
      response = await fetch(path, { ...options, headers });
    } catch (error) {
      throw new ApiError(friendlyError(error), 0);
    }

    const contentType = response.headers.get("content-type") || "";
    let payload = null;
    if (response.status !== 204) {
      if (contentType.includes("json")) {
        try {
          payload = await response.json();
        } catch {
          payload = null;
        }
      } else {
        payload = await response.text();
      }
    }

    if (!response.ok) {
      throw new ApiError(
        extractMessage(payload, `请求失败（${response.status}）`),
        response.status,
        payload,
      );
    }
    return payload;
  }

  function setGlobalStatus(text, tone = "neutral") {
    dom.globalStatusText.textContent = text;
    dom.globalStatus.dataset.tone = tone;
  }

  function updateActivityStatus() {
    updateTreeActionAvailability();
    if (state.statusError) {
      setGlobalStatus(state.statusError, "error");
      return;
    }
    if (state.loadingPlot) {
      setGlobalStatus("正在载入图表", "busy");
      return;
    }
    if (state.deleting) {
      setGlobalStatus("正在删除", "busy");
      return;
    }
    if (state.importing) {
      setGlobalStatus(`正在导入${state.importingLabel || "内容"}`, "busy");
      return;
    }
    if (state.copyingPng) {
      setGlobalStatus("正在复制 PNG", "busy");
      return;
    }
    if (state.exporting) {
      setGlobalStatus(`正在导出 ${state.exporting.format.toUpperCase()}`, "busy");
      return;
    }
    if (state.saving) {
      setGlobalStatus("正在保存代码", "busy");
      return;
    }
    if (state.pendingSettings > 0) {
      setGlobalStatus("正在同步属性", "busy");
      return;
    }
    if (state.rendering) {
      setGlobalStatus("正在渲染", "busy");
      return;
    }
    if (state.dirty) {
      setGlobalStatus("有未保存更改", "neutral");
      return;
    }
    setGlobalStatus(state.current ? "已同步" : "服务已连接", "success");
  }

  function clearStatusError() {
    state.statusError = null;
    updateActivityStatus();
  }

  function reportStatusError(message) {
    state.statusError = message;
    updateActivityStatus();
  }

  function showToast(message, tone = "neutral", duration = 3600) {
    const fragment = dom.toastTemplate.content.cloneNode(true);
    const toast = $(".toast", fragment);
    $(".toast__text", toast).textContent = message;
    toast.dataset.tone = tone;
    const close = () => {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(5px)";
      window.setTimeout(() => toast.remove(), 150);
    };
    $(".toast__close", toast).addEventListener("click", close);
    dom.toastRegion.append(toast);
    if (duration) window.setTimeout(close, duration);
  }

  function dataExportPolicy() {
    const declaration = state.current?.meta?.data_export;
    if (declaration === false) {
      return { csv: false, json: false, note: "此图表未提供可导出的结构化数据。" };
    }
    if (!isObject(declaration)) return { csv: true, json: true, note: "" };
    return {
      csv: declaration.csv !== false,
      json: declaration.json !== false,
      note: typeof declaration.note === "string" ? declaration.note.trim() : "",
    };
  }

  function updateExportControls() {
    const available = Boolean(state.current && state.project && state.plot);
    const rendered = available
      && state.asset.width > 0
      && state.asset.height > 0
      && dom.canvasViewport.classList.contains("has-render")
      && dom.renderContent.childElementCount > 0
      && dom.canvasError.hidden;
    const busy = Boolean(state.exporting || state.copyingPng);
    const policy = dataExportPolicy();
    const imageOptions = dom.imageExportPopover.querySelectorAll(".export-option");

    dom.copyPngButton.disabled = !rendered || busy || state.rendering;
    dom.imageExportButton.disabled = !available || busy;
    dom.dataExportButton.disabled = !available || busy;
    imageOptions.forEach((option) => { option.disabled = !available || busy; });
    dom.exportCsvOption.disabled = !available || busy || !policy.csv;
    dom.exportJsonOption.disabled = !available || busy || !policy.json;
    dom.exportCsvOption.title = !policy.csv ? (policy.note || "此图表不支持 CSV 数据导出") : "";
    dom.exportJsonOption.title = !policy.json ? (policy.note || "此图表不支持 JSON 数据导出") : "";

    const showNote = available && Boolean(policy.note || !policy.csv || !policy.json);
    dom.dataExportNote.hidden = !showNote;
    dom.dataExportNote.textContent = policy.note || "此图表未提供可导出的结构化数据。";
    dom.dataExportButton.title = !policy.csv && !policy.json
      ? dom.dataExportNote.textContent
      : "导出数据";

    const clipboardUnavailable = !window.isSecureContext
      || !navigator.clipboard
      || typeof navigator.clipboard.write !== "function"
      || typeof window.ClipboardItem !== "function";
    dom.copyPngButton.title = !available
      ? "请先选择一个图表"
      : !rendered
        ? "请先完成图表渲染"
        : clipboardUnavailable
          ? "当前浏览器环境不支持复制图片，可使用“导出图片”下载 PNG"
          : "复制 PNG 到剪贴板";
    dom.copyPngButton.classList.toggle("is-busy", state.copyingPng);
    dom.copyPngButton.setAttribute("aria-label", state.copyingPng ? "正在复制 PNG" : "复制 PNG 到剪贴板");
    $(".copy-png-button__label", dom.copyPngButton).textContent = state.copyingPng ? "正在复制…" : "复制 PNG";

    const imageLabel = $(".export-toggle__label", dom.imageExportButton);
    const dataLabel = $(".export-toggle__label", dom.dataExportButton);
    imageLabel.textContent = state.exporting?.kind === "image"
      ? `导出 ${state.exporting.format.toUpperCase()}…`
      : "导出图片";
    dataLabel.textContent = state.exporting?.kind === "data"
      ? `导出 ${state.exporting.format.toUpperCase()}…`
      : "导出数据";
    dom.imageExportMenu.classList.toggle("is-busy", state.exporting?.kind === "image");
    dom.dataExportMenu.classList.toggle("is-busy", state.exporting?.kind === "data");
    if (!available || busy) closeExportMenus();
  }

  function closeExportMenus(except = null) {
    [dom.imageExportMenu, dom.dataExportMenu].forEach((menu) => {
      if (menu === except) return;
      const button = $(".export-toggle", menu);
      const popover = $(".export-popover", menu);
      button.setAttribute("aria-expanded", "false");
      popover.hidden = true;
    });
  }

  function toggleExportMenu(menu) {
    const button = $(".export-toggle", menu);
    const popover = $(".export-popover", menu);
    if (button.disabled) return;
    const opening = popover.hidden;
    closeExportMenus(menu);
    popover.hidden = !opening;
    button.setAttribute("aria-expanded", String(opening));
  }

  function filenameFromDisposition(header, fallback) {
    if (!header) return fallback;
    let value = "";
    const encoded = header.match(/filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i);
    const plain = header.match(/filename\s*=\s*(?:"([^"]+)"|([^;]+))/i);
    if (encoded) {
      try {
        value = decodeURIComponent(encoded[1].trim().replace(/^"|"$/g, ""));
      } catch {
        value = encoded[1].trim();
      }
    } else if (plain) {
      value = (plain[1] || plain[2] || "").trim();
    }
    const safe = value.split(/[\\/]/).at(-1).replace(/[\u0000-\u001f\u007f]/g, "");
    return safe || fallback;
  }

  function triggerDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.hidden = true;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 30000);
  }

  function clipboardSupportMessage() {
    if (!window.isSecureContext) {
      return "浏览器只允许网页在安全连接或本机地址中写入剪贴板。请通过 HTTPS 或 localhost 打开后重试。";
    }
    if (!navigator.clipboard || typeof navigator.clipboard.write !== "function" || typeof window.ClipboardItem !== "function") {
      return "当前浏览器不支持复制图片到剪贴板，请使用“导出图片”下载 PNG。";
    }
    return "";
  }

  function friendlyClipboardError(error) {
    if (error?.name === "NotAllowedError") {
      return "浏览器没有获得剪贴板权限。请允许此网站访问剪贴板后重试。";
    }
    if (error?.name === "DataError" || error?.name === "NotSupportedError") {
      return "当前浏览器无法将 PNG 图片写入剪贴板，请使用“导出图片”下载。";
    }
    return friendlyError(error);
  }

  function clipboardFigureSizeInches() {
    const configured = getPath(state.settings, "figure.size");
    if (Array.isArray(configured) && configured.length === 2) {
      const width = Number(configured[0]);
      const height = Number(configured[1]);
      if (Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0) {
        return [width, height];
      }
    }
    if (state.asset.width > 0 && state.asset.height > 0) {
      return [state.asset.width / 96, state.asset.height / 96];
    }
    return null;
  }

  function blobToDataUrl(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(reader.error || new Error("无法读取 PNG 图片。"));
      reader.readAsDataURL(blob);
    });
  }

  async function prepareClipboardHtml(pngPromise) {
    const png = await pngPromise;
    const size = clipboardFigureSizeInches();
    if (!size) throw new Error("无法确定图像的物理尺寸。");
    const [widthInches, heightInches] = size;
    const dataUrl = await blobToDataUrl(png);
    const widthPoints = (widthInches * 72).toFixed(4).replace(/\.?0+$/, "");
    const heightPoints = (heightInches * 72).toFixed(4).replace(/\.?0+$/, "");
    const widthPixels = Math.max(1, Math.round(widthInches * 96));
    const heightPixels = Math.max(1, Math.round(heightInches * 96));
    const html = `<!doctype html><html><head><meta charset="utf-8"></head><body><!--StartFragment--><img src="${dataUrl}" alt="" width="${widthPixels}" height="${heightPixels}" style="display:block;width:${widthPoints}pt;height:${heightPoints}pt;max-width:none;max-height:none;border:0"><!--EndFragment--></body></html>`;
    return new Blob([html], { type: "text/html" });
  }

  async function prepareClipboardPng(projectId, plotId) {
    if (state.propertyTimers.size) {
      await waitUntil(() => state.propertyTimers.size === 0, 3000);
    }
    await state.patchChain.catch(() => undefined);
    if (state.dirty) {
      const saved = await saveCode({ render: false });
      if (!saved) throw new ApiError("代码尚未保存，暂时无法复制 PNG。", 0);
    }
    if (projectId !== state.project?.id || plotId !== state.plot?.id) {
      throw new ApiError("当前图表已切换，请重新复制。", 0);
    }

    // Keep the clipboard image publication-quality. Logical display size is
    // provided separately because PowerPoint ignores PNG pHYs metadata.
    const url = `${plotPath(projectId, plotId)}/export/image?format=png&dpi=${CLIPBOARD_PNG_DPI}`;
    const response = await fetch(url, {
      headers: { Accept: "image/png" },
      credentials: "same-origin",
    });
    if (!response.ok) {
      const contentType = response.headers.get("content-type") || "";
      let payload;
      try {
        payload = contentType.includes("json") ? await response.json() : await response.text();
      } catch {
        payload = null;
      }
      throw new ApiError(extractMessage(payload, `复制所需的 PNG 生成失败（${response.status}）`), response.status, payload);
    }

    const exportedBlob = await response.blob();
    if (!exportedBlob.size) throw new ApiError("服务返回了空的 PNG 图片。", 500);
    return exportedBlob.type === "image/png"
      ? exportedBlob
      : new Blob([exportedBlob], { type: "image/png" });
  }

  async function copyPngToClipboard() {
    const supportMessage = clipboardSupportMessage();
    if (supportMessage) {
      showToast(supportMessage, "warning", 6000);
      return;
    }
    if (!state.current || !state.project || !state.plot || state.copyingPng || state.exporting || state.rendering) return;
    if (!state.asset.width || !state.asset.height || !dom.canvasViewport.classList.contains("has-render")) {
      showToast("请先完成图表渲染，再复制 PNG。", "warning", 3600);
      updateExportControls();
      return;
    }

    const projectId = state.project.id;
    const plotId = state.plot.id;
    state.copyingPng = true;
    state.statusError = null;
    closeExportMenus();
    updateExportControls();
    updateActivityStatus();

    try {
      // Edge/Chromium requires clipboard.write() to run during the original click.
      // ClipboardItem accepts a Blob promise, so saving and PNG generation can finish afterward.
      const pngPromise = prepareClipboardPng(projectId, plotId);
      const representations = { "image/png": pngPromise };
      if (typeof window.ClipboardItem.supports !== "function" || window.ClipboardItem.supports("text/html")) {
        representations["text/html"] = prepareClipboardHtml(pngPromise);
      }
      await navigator.clipboard.write([new window.ClipboardItem(representations)]);
      state.statusError = null;
      showToast(`${CLIPBOARD_PNG_DPI} DPI PNG 已复制到剪贴板`, "success", 3000);
    } catch (error) {
      reportStatusError("复制失败");
      showToast(friendlyClipboardError(error), "error", 6000);
    } finally {
      state.copyingPng = false;
      updateExportControls();
      updateActivityStatus();
    }
  }

  async function downloadExport(kind, format) {
    if (!state.current || state.exporting || state.copyingPng) return;
    const policy = dataExportPolicy();
    if (kind === "data" && policy[format] === false) {
      showToast(policy.note || `此图表不支持 ${format.toUpperCase()} 数据导出`, "warning", 4500);
      return;
    }

    const projectId = state.project.id;
    const plotId = state.plot.id;
    state.exporting = { kind, format };
    state.statusError = null;
    closeExportMenus();
    updateExportControls();
    updateActivityStatus();

    try {
      if (state.propertyTimers.size) {
        await waitUntil(() => state.propertyTimers.size === 0, 3000);
      }
      await state.patchChain.catch(() => undefined);
      if (state.dirty) {
        const saved = await saveCode({ render: false });
        if (!saved) return;
      }
      if (projectId !== state.project?.id || plotId !== state.plot?.id) {
        throw new ApiError("当前图表已切换，请重新执行导出。", 0);
      }

      const endpoint = kind === "image" ? "image" : "data";
      const accept = kind === "image"
        ? { png: "image/png", svg: "image/svg+xml", pdf: "application/pdf" }[format]
        : { csv: "text/csv", json: "application/json" }[format];
      const url = `${plotPath(projectId, plotId)}/export/${endpoint}?format=${encodeURIComponent(format)}`;
      const response = await fetch(url, { headers: { Accept: accept }, credentials: "same-origin" });
      if (!response.ok) {
        const contentType = response.headers.get("content-type") || "";
        let payload;
        try {
          payload = contentType.includes("json") ? await response.json() : await response.text();
        } catch {
          payload = null;
        }
        throw new ApiError(extractMessage(payload, `导出失败（${response.status}）`), response.status, payload);
      }
      const blob = await response.blob();
      if (!blob.size) throw new ApiError("服务返回了空的导出文件。", 500);
      const suffix = kind === "data" ? `-data.${format}` : `.${format}`;
      const fallbackName = `${plotId}${suffix}`;
      const filename = filenameFromDisposition(response.headers.get("content-disposition"), fallbackName);
      triggerDownload(blob, filename);
      state.statusError = null;
      showToast(`${format.toUpperCase()} 文件已开始下载`, "success", 2600);
    } catch (error) {
      const message = friendlyError(error);
      reportStatusError("导出失败");
      showToast(message, "error", 5200);
      showEditorError(errorDetails(error));
    } finally {
      state.exporting = null;
      updateExportControls();
      updateActivityStatus();
    }
  }

  function bindExportMenu(menu) {
    const button = $(".export-toggle", menu);
    const popover = $(".export-popover", menu);
    button.addEventListener("click", () => toggleExportMenu(menu));
    button.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowDown") return;
      event.preventDefault();
      if (popover.hidden) toggleExportMenu(menu);
      const first = [...popover.querySelectorAll(".export-option:not(:disabled)")][0];
      first?.focus();
    });
    popover.addEventListener("keydown", (event) => {
      const options = [...popover.querySelectorAll(".export-option:not(:disabled)")];
      if (event.key === "Escape") {
        event.preventDefault();
        closeExportMenus();
        button.focus();
        return;
      }
      if (!["ArrowDown", "ArrowUp"].includes(event.key) || !options.length) return;
      event.preventDefault();
      const current = options.indexOf(document.activeElement);
      const direction = event.key === "ArrowDown" ? 1 : -1;
      options[(current + direction + options.length) % options.length].focus();
    });
  }

  function normalizeProjects(payload) {
    const root = unwrap(payload);
    const list = Array.isArray(root) ? root : root?.projects || root?.items || [];
    return list.map((project, projectIndex) => {
      const projectId = entityId(project, `project-${projectIndex + 1}`);
      const rawPlots = typeof project === "string" ? [] : project.plots || project.items || project.children || [];
      const plots = (Array.isArray(rawPlots) ? rawPlots : []).map((plot, plotIndex) => ({
        id: entityId(plot, `plot-${plotIndex + 1}`),
        name: displayName(plot, `图表 ${plotIndex + 1}`),
        raw: plot,
      }));
      return {
        id: projectId,
        name: displayName(project, `项目 ${projectIndex + 1}`),
        plots,
        raw: project,
      };
    });
  }

  function normalizePlotPayload(payload) {
    const root = unwrap(payload) || {};
    return {
      ...root,
      code: typeof root.code === "string" ? root.code : "",
      revision: root.revision ?? root.version ?? null,
      settings: isObject(root.settings) ? structuredCloneSafe(root.settings) : {},
      schema: root.schema || root.properties || [],
      render_url: root.render_url || root.image_url || root.svg_url || null,
      svg: root.svg || root.render_svg || null,
    };
  }

  function structuredCloneSafe(value) {
    if (typeof structuredClone === "function") {
      try {
        return structuredClone(value);
      } catch {
        // JSON data from the API should be cloneable; fall through for older browsers.
      }
    }
    try {
      return JSON.parse(JSON.stringify(value));
    } catch {
      return value;
    }
  }

  function humanize(value) {
    const text = String(value || "属性")
      .split(".").pop()
      .replace(/[_-]+/g, " ")
      .replace(/\b\w/g, (letter) => letter.toUpperCase());
    return text || "属性";
  }

  function normalizeType(type) {
    const value = String(type || "string").toLowerCase().replace(/[-\s]/g, "_");
    const aliases = {
      int: "integer",
      float: "number",
      double: "number",
      bool: "boolean",
      textarea: "text",
      enum: "select",
      tuple: "number_pair",
      pair: "number_pair",
      array: "string_list",
      list: "string_list",
      colors: "color_list",
    };
    const normalized = aliases[value] || value;
    const supported = new Set([
      "number", "integer", "string", "text", "boolean", "color",
      "select", "number_pair", "string_list", "color_list",
    ]);
    return supported.has(normalized) ? normalized : "string";
  }

  function normalizeProperty(raw, fallbackPath, fallbackGroup) {
    const source = isObject(raw) ? raw : { default: raw };
    const path = String(source.path || source.key || source.name || fallbackPath || "property");
    const options = source.options || source.choices || source.enum || [];
    return {
      ...source,
      path,
      label: source.label || source.title || humanize(path),
      group: source.group || fallbackGroup || "常规",
      type: normalizeType(source.type || source.kind),
      optional: source.optional !== undefined ? Boolean(source.optional) : source.required !== true,
      default: source.default ?? source.default_value,
      description: source.description || source.help || source.hint || "",
      unit: source.unit || source.suffix || "",
      min: source.min ?? source.minimum,
      max: source.max ?? source.maximum,
      step: source.step,
      placeholder: source.placeholder || "",
      options: Array.isArray(options) ? options : Object.entries(options).map(([value, label]) => ({ value, label })),
    };
  }

  function normalizeSchema(schema) {
    if (!schema) return [];
    const groups = [];
    const pushGroup = (groupName, properties, groupId = groupName) => {
      const list = Array.isArray(properties)
        ? properties.map((property, index) => normalizeProperty(property, property?.path || `property_${index + 1}`, groupName))
        : Object.entries(properties || {}).map(([key, property]) => normalizeProperty(property, key, groupName));
      if (list.length) groups.push({ id: String(groupId || groupName), label: groupName || "常规", properties: list });
    };

    if (Array.isArray(schema)) {
      const looksGrouped = schema.some((item) => isObject(item) && (item.properties || item.fields || item.items));
      if (looksGrouped) {
        schema.forEach((group, index) => {
          const name = group.label || group.title || group.name || group.id || `分组 ${index + 1}`;
          pushGroup(name, group.properties || group.fields || group.items || [], group.id || name);
        });
      } else {
        const byGroup = new Map();
        schema.forEach((property, index) => {
          const normalized = normalizeProperty(property, property?.path || `property_${index + 1}`, property?.group || "常规");
          if (!byGroup.has(normalized.group)) byGroup.set(normalized.group, []);
          byGroup.get(normalized.group).push(normalized);
        });
        byGroup.forEach((properties, name) => groups.push({ id: name, label: name, properties }));
      }
      return groups;
    }

    if (isObject(schema.groups)) {
      Object.entries(schema.groups).forEach(([key, group]) => {
        const name = group.label || group.title || group.name || key;
        pushGroup(name, group.properties || group.fields || group.items || group, group.id || key);
      });
      return groups;
    }

    if (Array.isArray(schema.groups)) {
      schema.groups.forEach((group, index) => {
        const name = group.label || group.title || group.name || group.id || `分组 ${index + 1}`;
        pushGroup(name, group.properties || group.fields || group.items || [], group.id || name);
      });
      return groups;
    }

    const candidates = schema.properties || schema.fields;
    if (Array.isArray(candidates)) return normalizeSchema(candidates);
    if (isObject(candidates)) {
      pushGroup(schema.label || schema.title || "常规", candidates, schema.id || "general");
      return groups;
    }

    Object.entries(schema).forEach(([key, value]) => {
      if (isObject(value) && (value.properties || value.fields || value.items)) {
        pushGroup(value.label || value.title || key, value.properties || value.fields || value.items, value.id || key);
      } else {
        const normalized = normalizeProperty(value, key, value?.group || "常规");
        let group = groups.find((item) => item.label === normalized.group);
        if (!group) {
          group = { id: normalized.group, label: normalized.group, properties: [] };
          groups.push(group);
        }
        group.properties.push(normalized);
      }
    });
    return groups;
  }

  function pathParts(path) {
    if (Array.isArray(path)) return path;
    if (String(path).startsWith("/")) {
      return String(path).slice(1).split("/").filter(Boolean).map((part) => part.replace(/~1/g, "/").replace(/~0/g, "~"));
    }
    return String(path)
      .replace(/\[(\d+)\]/g, ".$1")
      .split(".")
      .filter(Boolean);
  }

  function hasPath(object, path) {
    if (!isObject(object) && !Array.isArray(object)) return false;
    if (Object.prototype.hasOwnProperty.call(object, path)) return true;
    let cursor = object;
    for (const part of pathParts(path)) {
      if (cursor === null || cursor === undefined || !Object.prototype.hasOwnProperty.call(cursor, part)) return false;
      cursor = cursor[part];
    }
    return true;
  }

  function getPath(object, path) {
    if (object && Object.prototype.hasOwnProperty.call(object, path)) return object[path];
    let cursor = object;
    for (const part of pathParts(path)) {
      if (cursor === null || cursor === undefined) return undefined;
      cursor = cursor[part];
    }
    return cursor;
  }

  function setPath(object, path, value) {
    if (Object.prototype.hasOwnProperty.call(object, path)) {
      object[path] = value;
      return;
    }
    const parts = pathParts(path);
    let cursor = object;
    parts.forEach((part, index) => {
      if (index === parts.length - 1) {
        cursor[part] = value;
      } else {
        const nextIsIndex = /^\d+$/.test(parts[index + 1]);
        if (!isObject(cursor[part]) && !Array.isArray(cursor[part])) cursor[part] = nextIsIndex ? [] : {};
        cursor = cursor[part];
      }
    });
  }

  function deletePath(object, path) {
    if (Object.prototype.hasOwnProperty.call(object, path)) {
      delete object[path];
      return;
    }
    const parts = pathParts(path);
    let cursor = object;
    for (let index = 0; index < parts.length - 1; index += 1) {
      cursor = cursor?.[parts[index]];
      if (cursor === undefined || cursor === null) return;
    }
    if (cursor) delete cursor[parts.at(-1)];
  }

  function defaultForProperty(property) {
    if (property.default !== undefined && property.default !== null) return structuredCloneSafe(property.default);
    switch (property.type) {
      case "number": return 0;
      case "integer": return 0;
      case "boolean": return false;
      case "color": return "#176b5d";
      case "number_pair": return [6.4, 4.8];
      case "string_list": return [""];
      case "color_list": return ["#176b5d"];
      case "select": {
        const first = property.options[0];
        return isObject(first) ? first.value : first ?? "";
      }
      default: return "";
    }
  }

  async function fetchProjects({ keepSelection = true, selectProjectId = null, selectPlotId = null } = {}) {
    const requestedProject = selectProjectId === null ? null : String(selectProjectId);
    const requestedPlot = selectPlotId === null ? null : String(selectPlotId);
    const previousProject = keepSelection && !requestedProject ? state.project?.id : null;
    const previousPlot = keepSelection && !requestedProject ? state.plot?.id : null;
    dom.projectTree.innerHTML = `<div class="tree-skeleton" aria-label="正在载入项目"><span></span><span></span><span></span><span></span><span></span></div>`;
    state.statusError = null;
    setGlobalStatus("正在载入项目", "busy");
    try {
      const payload = await apiRequest(`${API_ROOT}/projects`);
      state.projects = normalizeProjects(payload);
      renderProjectTree();
      clearStatusError();

      let targetProject = requestedProject
        ? state.projects.find((project) => project.id === requestedProject)
        : state.projects.find((project) => project.id === previousProject);
      let targetPlot = requestedProject
        ? targetProject?.plots.find((plot) => plot.id === requestedPlot) || targetProject?.plots[0]
        : targetProject?.plots.find((plot) => plot.id === previousPlot);
      if (!targetPlot && !requestedProject) {
        const remembered = readStorage("matplot.lastSelection", null);
        targetProject = state.projects.find((project) => project.id === remembered?.projectId) || state.projects[0];
        targetPlot = targetProject?.plots.find((plot) => plot.id === remembered?.plotId) || targetProject?.plots[0];
      }
      if (!targetPlot && !requestedProject) {
        targetProject = state.projects.find((project) => project.plots.length) || null;
        targetPlot = targetProject?.plots[0] || null;
      }
      if (targetProject && targetPlot && (!state.current || targetProject.id !== state.project?.id || targetPlot.id !== state.plot?.id)) {
        await selectPlot(targetProject, targetPlot, { skipSave: true });
      } else if (!targetPlot) {
        resetEditor();
        updateActivityStatus();
      }
    } catch (error) {
      const message = friendlyError(error);
      reportStatusError("连接失败");
      renderTreeError(message);
      resetEditor();
    }
  }

  function renderTreeError(message) {
    dom.projectTree.replaceChildren();
    const wrapper = element("div", "tree-error");
    wrapper.append(element("strong", "", "无法载入项目"), element("span", "", message));
    const retry = element("button", "button button--quiet", "重新连接");
    retry.type = "button";
    retry.addEventListener("click", () => fetchProjects());
    wrapper.append(retry);
    dom.projectTree.append(wrapper);
  }

  function workspaceMutationBusy({ includeScheduledProperties = true } = {}) {
    return state.importing
      || state.deleting
      || state.loadingPlot
      || state.saving
      || state.rendering
      || Boolean(state.exporting)
      || state.copyingPng
      || state.pendingSettings > 0
      || (includeScheduledProperties && state.propertyTimers.size > 0);
  }

  function updateTreeActionAvailability() {
    const disabled = workspaceMutationBusy();
    if (dom.importProjectButton) dom.importProjectButton.disabled = disabled;
    if (dom.newProjectButton) dom.newProjectButton.disabled = disabled;
    dom.projectTree?.querySelectorAll("[data-tree-mutation]").forEach((button) => {
      button.disabled = disabled;
    });
  }

  function rejectBusyAction(action) {
    if (!workspaceMutationBusy()) return false;
    showToast(`当前操作尚未完成，暂时无法${action}。`, "warning", 3600);
    return true;
  }

  function renderProjectTree() {
    const query = dom.projectSearch.value.trim().toLocaleLowerCase();
    dom.projectTree.replaceChildren();
    let visibleCount = 0;

    for (const project of state.projects) {
      const matchingPlots = query
        ? project.plots.filter((plot) => plot.name.toLocaleLowerCase().includes(query))
        : project.plots;
      const projectMatches = !query || project.name.toLocaleLowerCase().includes(query);
      if (!projectMatches && !matchingPlots.length) continue;
      visibleCount += 1;

      const wrapper = element("div", "tree-project");
      wrapper.dataset.projectId = project.id;
      const isCollapsed = query ? false : state.collapsedProjects.has(project.id);
      if (isCollapsed) wrapper.classList.add("is-collapsed");

      const row = element("div", "tree-project__row");
      const toggle = element("button", "tree-project__toggle");
      toggle.type = "button";
      toggle.setAttribute("aria-expanded", String(!isCollapsed));
      toggle.title = project.name;
      toggle.append(
        icon("m5.5 7.5 4.5 4.5 4.5-4.5", "0 0 20 20"),
        icon("M3.5 6.5h5l1.3 1.5h6.7v7.5h-13v-9Z", "0 0 20 20"),
      );
      toggle.lastElementChild.classList.add("folder-icon");
      toggle.append(element("span", "tree-project__name", project.name));
      toggle.append(element("span", "tree-project__count", project.plots.length));
      toggle.addEventListener("click", () => {
        if (state.collapsedProjects.has(project.id)) state.collapsedProjects.delete(project.id);
        else state.collapsedProjects.add(project.id);
        writeStorage("matplot.collapsedProjects", [...state.collapsedProjects]);
        wrapper.classList.toggle("is-collapsed");
        toggle.setAttribute("aria-expanded", String(!wrapper.classList.contains("is-collapsed")));
      });

      const addPlot = element("button", "tree-project__add");
      addPlot.type = "button";
      addPlot.dataset.treeMutation = "true";
      addPlot.title = `在“${project.name}”中新建图表`;
      addPlot.setAttribute("aria-label", `在“${project.name}”中新建图表`);
      addPlot.append(icon("M10 4v12M4 10h12"));
      addPlot.addEventListener("click", () => openCreatePlotDialog(project));

      const importPlots = element("button", "tree-project__import");
      importPlots.type = "button";
      importPlots.dataset.treeMutation = "true";
      importPlots.title = `向“${project.name}”导入图表`;
      importPlots.setAttribute("aria-label", `向“${project.name}”导入图表`);
      importPlots.append(icon("M10 3v8M6.5 7.5 10 11l3.5-3.5M4 14v2h12v-2"));
      importPlots.addEventListener("click", () => openImportPlotDialog(project));

      const deleteProject = element("button", "tree-project__delete");
      deleteProject.type = "button";
      deleteProject.dataset.treeMutation = "true";
      deleteProject.title = `删除项目“${project.name}”`;
      deleteProject.setAttribute("aria-label", `删除项目“${project.name}”`);
      deleteProject.append(icon("M6 6h8M8 6V4h4v2M7 8v7M10 8v7M13 8v7M5 6l1 11h8l1-11"));
      deleteProject.addEventListener("click", () => openDeleteDialog({ type: "project", project }));

      const projectActions = element("div", "tree-project__actions");
      projectActions.append(importPlots, addPlot, deleteProject);
      row.append(toggle, projectActions);
      wrapper.append(row);

      const plots = element("div", "tree-plots");
      const list = projectMatches && query ? project.plots : matchingPlots;
      list.forEach((plot) => {
        const plotRow = element("div", "tree-plot__row");
        const button = element("button", "tree-plot");
        button.type = "button";
        button.title = plot.name;
        button.dataset.projectId = project.id;
        button.dataset.plotId = plot.id;
        if (state.project?.id === project.id && state.plot?.id === plot.id) button.classList.add("is-active");
        button.append(icon("M3.5 15.5V4.5M3.5 15.5h13M6.5 12l3-4 2.4 2 3.6-5", "0 0 20 20"));
        button.append(element("span", "tree-plot__name", plot.name));
        button.addEventListener("click", () => selectPlot(project, plot));

        const deletePlot = element("button", "tree-plot__delete");
        deletePlot.type = "button";
        deletePlot.dataset.treeMutation = "true";
        deletePlot.title = `删除图表“${plot.name}”`;
        deletePlot.setAttribute("aria-label", `删除图表“${plot.name}”`);
        deletePlot.append(icon("M6 6h8M8 6V4h4v2M7 8v7M10 8v7M13 8v7M5 6l1 11h8l1-11"));
        deletePlot.addEventListener("click", () => openDeleteDialog({ type: "plot", project, plot }));
        plotRow.append(button, deletePlot);
        plots.append(plotRow);
      });
      wrapper.append(plots);
      dom.projectTree.append(wrapper);
    }

    if (!visibleCount) {
      const empty = element("div", "tree-empty");
      empty.append(
        element("strong", "", query ? "没有匹配结果" : "还没有项目"),
        element("span", "", query ? "换一个关键词试试" : "创建项目后即可添加图表"),
      );
      if (!query) {
        const create = element("button", "button button--quiet", "新建项目");
        create.type = "button";
        create.addEventListener("click", openCreateProjectDialog);
        empty.append(create);
      }
      dom.projectTree.append(empty);
    }
    updateTreeActionAvailability();
  }

  async function selectPlot(project, plot, { skipSave = false } = {}) {
    if (state.loadingPlot) return;
    if (state.project?.id === project.id && state.plot?.id === plot.id && state.current) {
      closeMobilePanels();
      return;
    }

    if (!skipSave && state.dirty) {
      const saved = await saveCode({ render: false });
      if (!saved && !(await confirmDiscardChanges())) return;
    }

    clearTimeout(state.autosaveTimer);
    state.propertyTimers.forEach((timer) => clearTimeout(timer));
    state.propertyTimers.clear();
    const token = ++state.loadToken;
    state.project = project;
    state.plot = plot;
    state.current = null;
    state.loadingPlot = true;
    state.statusError = null;
    state.dirty = false;
    state.codeVersion += 1;
    updateActivityStatus();
    updateSelectionUI();
    setEditorLoading();
    closeMobilePanels();

    try {
      const payload = await apiRequest(plotPath(project.id, plot.id));
      if (token !== state.loadToken) return;
      const current = normalizePlotPayload(payload);
      state.current = current;
      state.revision = current.revision;
      state.settings = current.settings;
      state.schemaGroups = normalizeSchema(current.schema);
      rebuildPropertyMap();
      state.loadingPlot = false;
      state.dirty = false;
      dom.codeInput.value = current.code;
      dom.codeInput.disabled = false;
      dom.renderButton.disabled = false;
      updateExportControls();
      dom.editorTitle.textContent = "plot.py";
      dom.breadcrumbProject.textContent = project.name;
      dom.breadcrumbPlot.textContent = plot.name;
      writeStorage("matplot.lastSelection", { projectId: project.id, plotId: plot.id });
      updateLineNumbers();
      updateCursorPosition();
      updateDirtyUI();
      clearEditorError();
      renderProperties();
      renderProjectTree();
      clearStatusError();

      if (current.svg) {
        mountSvg(current.svg);
      } else if (current.render_url) {
        await loadRenderArtifact(current.render_url);
      } else {
        await renderPlot({ quiet: true });
      }
    } catch (error) {
      if (token !== state.loadToken) return;
      state.loadingPlot = false;
      const message = friendlyError(error);
      reportStatusError("载入失败");
      showEditorError(message);
      showCanvasError(message);
      dom.saveState.textContent = "载入失败";
      dom.saveState.dataset.tone = "error";
    }
  }

  function updateSelectionUI() {
    dom.breadcrumbProject.textContent = state.project?.name || "工作区";
    dom.breadcrumbPlot.textContent = state.plot?.name || "选择一个图表";
    renderProjectTree();
  }

  function resetEditor() {
    state.project = null;
    state.plot = null;
    state.current = null;
    state.revision = null;
    state.settings = {};
    state.schemaGroups = [];
    state.propertyMap.clear();
    state.asset = { width: 0, height: 0 };
    state.fitted = true;
    state.dirty = false;
    dom.codeInput.value = "";
    dom.codeInput.disabled = true;
    dom.renderButton.disabled = true;
    updateExportControls();
    dom.editorTitle.textContent = "plot.py";
    dom.breadcrumbProject.textContent = "工作区";
    dom.breadcrumbPlot.textContent = "选择一个图表";
    dom.saveState.textContent = "未载入";
    dom.saveState.dataset.tone = "neutral";
    dom.renderContent.replaceChildren();
    dom.canvasViewport.classList.remove("has-render");
    dom.canvasEmpty.hidden = false;
    dom.canvasHelp.hidden = true;
    setCanvasToolsEnabled(false);
    updateLineNumbers();
    updateDirtyUI();
    renderProperties();
  }

  function setEditorLoading() {
    state.asset = { width: 0, height: 0 };
    state.fitted = true;
    dom.codeInput.value = "# 正在载入图表…";
    dom.codeInput.disabled = true;
    dom.renderButton.disabled = true;
    updateExportControls();
    dom.editorTitle.textContent = "plot.py";
    dom.saveState.textContent = "正在载入";
    dom.saveState.dataset.tone = "busy";
    dom.renderContent.replaceChildren();
    dom.canvasEmpty.hidden = true;
    dom.canvasLoading.hidden = false;
    dom.canvasError.hidden = true;
    dom.canvasHelp.hidden = true;
    setCanvasToolsEnabled(false);
    renderProperties(true);
    updateLineNumbers();
  }

  function updateDirtyUI() {
    dom.dirtyDot.hidden = !state.dirty;
    if (state.saving) {
      dom.saveState.textContent = "正在保存…";
      dom.saveState.dataset.tone = "busy";
    } else if (state.dirty) {
      dom.saveState.textContent = dom.autoRenderToggle.checked ? "等待自动保存" : "未保存";
      dom.saveState.dataset.tone = "neutral";
    } else if (state.current) {
      dom.saveState.textContent = "已保存";
      dom.saveState.dataset.tone = "success";
    }
    dom.propertiesPanel.classList.toggle("is-disabled", state.dirty || state.saving);
    if (state.dirty || state.saving) {
      dom.inspectorNotice.dataset.tone = "pending";
      $("span", dom.inspectorNotice).textContent = state.saving
        ? "正在重新分析代码，属性稍后恢复编辑。"
        : "保存代码后将重新识别可编辑属性。";
    } else {
      dom.inspectorNotice.dataset.tone = "normal";
      $("span", dom.inspectorNotice).innerHTML = "属性由当前代码自动识别，修改会同步回 <code>plot.py</code>。";
    }
    updateActivityStatus();
  }

  function updateLineNumbers() {
    const count = Math.max(1, dom.codeInput.value.split("\n").length);
    dom.lineNumbers.textContent = Array.from({ length: count }, (_, index) => index + 1).join("\n");
    dom.lineNumbers.scrollTop = dom.codeInput.scrollTop;
  }

  function updateCursorPosition() {
    const position = dom.codeInput.selectionStart || 0;
    const before = dom.codeInput.value.slice(0, position);
    const lines = before.split("\n");
    dom.cursorPosition.textContent = `Ln ${lines.length}, Col ${lines.at(-1).length + 1}`;
  }

  function handleCodeInput() {
    if (!state.current) return;
    state.codeVersion += 1;
    state.dirty = true;
    state.statusError = null;
    updateLineNumbers();
    updateCursorPosition();
    updateDirtyUI();
    clearTimeout(state.autosaveTimer);
    if (dom.autoRenderToggle.checked) {
      state.autosaveTimer = window.setTimeout(() => runAndRender({ source: "auto" }), AUTOSAVE_DELAY);
    }
  }

  async function saveCode({ render = false } = {}) {
    if (!state.current || !state.project || !state.plot) return false;
    if (state.saving) {
      await waitUntil(() => !state.saving, 8000);
      if (render && !state.dirty) await renderPlot();
      return !state.dirty;
    }
    if (!state.dirty) {
      if (render) await renderPlot();
      return true;
    }

    clearTimeout(state.autosaveTimer);
    const code = dom.codeInput.value;
    const version = state.codeVersion;
    const projectId = state.project.id;
    const plotId = state.plot.id;
    let embeddedRender = null;
    state.saving = true;
    state.statusError = null;
    clearEditorError();
    updateDirtyUI();

    try {
      const payload = await apiRequest(`${plotPath(projectId, plotId)}/code`, {
        method: "PUT",
        body: JSON.stringify({ code, revision: state.revision }),
      });
      if (projectId !== state.project?.id || plotId !== state.plot?.id) return true;
      const result = isObject(unwrap(payload)) ? unwrap(payload) : {};
      embeddedRender = isObject(result.render) ? result.render : null;
      state.revision = result.revision ?? result.version ?? state.revision;
      state.current = { ...state.current, ...result, revision: state.revision };
      updateExportControls();

      if (version === state.codeVersion && code === dom.codeInput.value) {
        state.dirty = false;
        if (typeof result.code === "string" && result.code !== code) dom.codeInput.value = result.code;
        if (isObject(result.settings)) state.settings = structuredCloneSafe(result.settings);
        if (result.schema || result.properties) state.schemaGroups = normalizeSchema(result.schema || result.properties);
        rebuildPropertyMap();
        renderProperties();
        updateLineNumbers();
      } else if (dom.autoRenderToggle.checked) {
        state.autosaveTimer = window.setTimeout(() => runAndRender({ source: "auto" }), AUTOSAVE_DELAY);
      }
      state.statusError = null;
      return true;
    } catch (error) {
      const message = friendlyError(error);
      reportStatusError(error.status === 409 ? "版本冲突" : "保存失败");
      showEditorError(errorDetails(error));
      showToast(message, "error", 5000);
      return false;
    } finally {
      state.saving = false;
      updateDirtyUI();
      if (render && !state.dirty) {
        const handled = await presentEmbeddedRender(embeddedRender, { quiet: true });
        if (!handled) await renderPlot();
      }
    }
  }

  async function waitUntil(predicate, timeout) {
    const started = Date.now();
    while (!predicate()) {
      if (Date.now() - started > timeout) return false;
      await new Promise((resolve) => window.setTimeout(resolve, 50));
    }
    return true;
  }

  async function runAndRender({ source = "manual" } = {}) {
    if (!state.current) return;
    if (state.pendingSettings > 0) await waitUntil(() => state.pendingSettings === 0, 20000);
    if (state.saving) await waitUntil(() => !state.saving, 8000);
    if (state.rendering) await waitUntil(() => !state.rendering, 20000);
    if (!state.current || state.saving || state.rendering) return;
    if (state.dirty) {
      await saveCode({ render: true });
      return;
    }
    await renderPlot({ quiet: source === "auto" });
  }

  function errorDetails(error) {
    const payload = error?.payload;
    if (isObject(payload)) {
      const detail = payload.detail || payload.error;
      if (isObject(detail)) return detail.traceback || detail.message || JSON.stringify(detail, null, 2);
      return payload.traceback || (typeof detail === "string" ? detail : error.message);
    }
    return error?.message || "运行失败";
  }

  async function renderPlot({ quiet = false } = {}) {
    if (!state.current || state.rendering) return false;
    const projectId = state.project.id;
    const plotId = state.plot.id;
    const startedAt = performance.now();
    state.rendering = true;
    state.statusError = null;
    dom.canvasLoading.hidden = false;
    dom.canvasError.hidden = true;
    dom.canvasEmpty.hidden = true;
    dom.canvasMeta.textContent = "正在渲染…";
    updateExportControls();
    updateActivityStatus();

    try {
      const payload = await apiRequest(`${plotPath(projectId, plotId)}/render`, {
        method: "POST",
        body: JSON.stringify({ revision: state.revision }),
      });
      if (projectId !== state.project?.id || plotId !== state.plot?.id) return false;
      const result = typeof payload === "string" ? { svg: payload } : (unwrap(payload) || {});
      state.revision = result.revision ?? result.version ?? state.revision;
      if (state.current) state.current.revision = state.revision;
      if (result.error && !result.svg && !result.render_url && !result.image_url) {
        throw new ApiError(extractMessage(result.error, "渲染失败"), 422, result);
      }
      if (result.svg || result.render_svg) {
        mountSvg(result.svg || result.render_svg);
      } else {
        const renderUrl = result.render_url || result.image_url || result.svg_url || state.current.render_url;
        if (!renderUrl) throw new ApiError("服务没有返回可显示的渲染结果。", 500, result);
        state.current.render_url = renderUrl;
        await loadRenderArtifact(renderUrl);
      }
      const elapsed = result.duration_ms ?? Math.round(performance.now() - startedAt);
      dom.canvasMeta.textContent = `${formatDimensions()} · ${formatDuration(elapsed)}`;
      clearEditorError();
      state.statusError = null;
      if (!quiet) showToast("图表已渲染", "success", 1800);
      return true;
    } catch (error) {
      const message = friendlyError(error);
      showCanvasError(message);
      showEditorError(errorDetails(error));
      reportStatusError("渲染失败");
      if (!quiet) showToast(message, "error", 5000);
      return false;
    } finally {
      state.rendering = false;
      dom.canvasLoading.hidden = true;
      updateExportControls();
      updateActivityStatus();
    }
  }

  async function presentEmbeddedRender(result, { quiet = true } = {}) {
    if (!isObject(result)) return false;
    state.revision = result.revision ?? state.revision;
    if (state.current) state.current.revision = state.revision;
    if (result.ok === false) {
      const message = result.message || result.error || "渲染失败";
      const details = result.traceback || result.stderr || message;
      showCanvasError(message);
      showEditorError(details);
      reportStatusError("渲染失败");
      if (!quiet) showToast(message, "error", 5000);
      return true;
    }
    const svg = result.svg || result.render_svg;
    const url = result.svg_url || result.render_url || result.image_url;
    if (!svg && !url) return false;

    state.rendering = true;
    dom.canvasLoading.hidden = false;
    dom.canvasError.hidden = true;
    dom.canvasEmpty.hidden = true;
    updateExportControls();
    updateActivityStatus();
    try {
      if (svg) mountSvg(svg);
      else await loadRenderArtifact(url);
      dom.canvasMeta.textContent = `${formatDimensions()} · ${formatDuration(result.duration_ms)}`;
      clearEditorError();
      state.statusError = null;
      if (!quiet) showToast("图表已渲染", "success", 1800);
    } catch (error) {
      const message = friendlyError(error);
      showCanvasError(message);
      showEditorError(errorDetails(error));
      reportStatusError("渲染失败");
      if (!quiet) showToast(message, "error", 5000);
    } finally {
      state.rendering = false;
      dom.canvasLoading.hidden = true;
      updateExportControls();
      updateActivityStatus();
    }
    return true;
  }

  function formatDuration(milliseconds) {
    const value = Number(milliseconds);
    if (!Number.isFinite(value)) return "已渲染";
    return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
  }

  function formatDimensions() {
    const width = Math.round(state.asset.width);
    const height = Math.round(state.asset.height);
    return width && height ? `${width} × ${height}` : "SVG";
  }

  function cacheBustedUrl(url) {
    try {
      const parsed = new URL(url, window.location.href);
      parsed.searchParams.set("_render", String(Date.now()));
      return parsed.href;
    } catch {
      const divider = String(url).includes("?") ? "&" : "?";
      return `${url}${divider}_render=${Date.now()}`;
    }
  }

  async function loadRenderArtifact(url) {
    const token = ++state.artifactToken;
    if (state.artifactAbort) state.artifactAbort.abort();
    state.artifactAbort = new AbortController();
    const response = await fetch(cacheBustedUrl(url), {
      headers: { Accept: "image/svg+xml,image/*" },
      signal: state.artifactAbort.signal,
    });
    if (!response.ok) throw new ApiError(`无法读取渲染结果（${response.status}）。`, response.status);
    if (token !== state.artifactToken) return;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("svg") || contentType.includes("text")) {
      const text = await response.text();
      if (/<svg[\s>]/i.test(text)) {
        mountSvg(text);
        return;
      }
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    await mountImage(objectUrl, true);
  }

  function parseSvgLength(value) {
    const match = String(value || "").trim().match(/^([\d.]+)\s*(px|pt|in|cm|mm)?$/i);
    if (!match) return 0;
    const number = Number(match[1]);
    const factors = { px: 1, pt: 96 / 72, in: 96, cm: 96 / 2.54, mm: 96 / 25.4 };
    return number * (factors[(match[2] || "px").toLowerCase()] || 1);
  }

  function sanitizeSvg(svg) {
    svg.querySelectorAll("script, iframe, object, embed").forEach((node) => node.remove());
    svg.querySelectorAll("*").forEach((node) => {
      [...node.attributes].forEach((attribute) => {
        const name = attribute.name.toLowerCase();
        const value = attribute.value.trim().toLowerCase();
        if (name.startsWith("on") || ((name === "href" || name.endsWith(":href")) && value.startsWith("javascript:"))) {
          node.removeAttribute(attribute.name);
        }
      });
    });
    return svg;
  }

  function mountSvg(source) {
    const parser = new DOMParser();
    const documentNode = parser.parseFromString(String(source), "image/svg+xml");
    if (documentNode.querySelector("parsererror") || !documentNode.documentElement.matches("svg")) {
      throw new ApiError("返回的 SVG 内容无法解析。", 500);
    }
    const svg = sanitizeSvg(documentNode.documentElement);
    const viewBox = svg.viewBox?.baseVal;
    const width = parseSvgLength(svg.getAttribute("width")) || viewBox?.width || 800;
    const height = parseSvgLength(svg.getAttribute("height")) || viewBox?.height || 600;
    svg.setAttribute("width", String(width));
    svg.setAttribute("height", String(height));
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `${state.plot?.name || "Matplotlib"} 渲染结果`);
    dom.renderContent.replaceChildren(document.importNode(svg, true));
    finishMount(width, height);
  }

  function mountImage(source, revoke = false) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.alt = `${state.plot?.name || "Matplotlib"} 渲染结果`;
      image.draggable = false;
      image.onload = () => {
        const width = image.naturalWidth || 800;
        const height = image.naturalHeight || 600;
        image.width = width;
        image.height = height;
        dom.renderContent.replaceChildren(image);
        finishMount(width, height);
        if (revoke) URL.revokeObjectURL(source);
        resolve();
      };
      image.onerror = () => {
        if (revoke) URL.revokeObjectURL(source);
        reject(new ApiError("渲染图片无法显示。", 500));
      };
      image.src = source;
    });
  }

  function finishMount(width, height) {
    const shouldFit = !state.asset.width || state.fitted;
    state.asset = { width, height };
    dom.renderContent.style.width = `${width}px`;
    dom.renderContent.style.height = `${height}px`;
    dom.canvasEmpty.hidden = true;
    dom.canvasLoading.hidden = true;
    dom.canvasError.hidden = true;
    dom.canvasViewport.classList.add("has-render");
    dom.canvasHelp.hidden = false;
    setCanvasToolsEnabled(true);
    updateExportControls();
    dom.canvasMeta.textContent = formatDimensions();
    requestAnimationFrame(shouldFit ? fitCanvas : applyCanvasTransform);
  }

  function showCanvasError(message) {
    dom.canvasLoading.hidden = true;
    dom.canvasEmpty.hidden = true;
    dom.canvasError.hidden = false;
    dom.canvasErrorText.textContent = String(message).split("\n")[0];
    dom.canvasMeta.textContent = "渲染失败";
    updateExportControls();
  }

  function setCanvasToolsEnabled(enabled) {
    [dom.fitCanvasButton, dom.zoomOutButton, dom.zoomInButton, dom.resetZoomButton].forEach((button) => {
      button.disabled = !enabled;
    });
  }

  function applyCanvasTransform() {
    const { zoom, x, y } = state.transform;
    dom.renderStage.style.transform = `translate(${x}px, ${y}px) scale(${zoom})`;
    dom.resetZoomButton.textContent = `${Math.round(zoom * 100)}%`;
    dom.zoomOutButton.disabled = !state.asset.width || zoom <= ZOOM_MIN + 0.001;
    dom.zoomInButton.disabled = !state.asset.width || zoom >= ZOOM_MAX - 0.001;
  }

  function fitCanvas() {
    if (!state.asset.width || !state.asset.height) return;
    const bounds = dom.canvasViewport.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    const padding = bounds.width < 600 ? 32 : 64;
    const zoom = clamp(
      Math.min((bounds.width - padding) / state.asset.width, (bounds.height - padding) / state.asset.height),
      ZOOM_MIN,
      Math.min(ZOOM_MAX, 1.6),
    );
    state.transform.zoom = zoom;
    state.transform.x = (bounds.width - state.asset.width * zoom) / 2;
    state.transform.y = (bounds.height - state.asset.height * zoom) / 2;
    state.fitted = true;
    applyCanvasTransform();
  }

  function resetZoom() {
    if (!state.asset.width) return;
    const bounds = dom.canvasViewport.getBoundingClientRect();
    state.transform.zoom = 1;
    state.transform.x = (bounds.width - state.asset.width) / 2;
    state.transform.y = (bounds.height - state.asset.height) / 2;
    state.fitted = false;
    applyCanvasTransform();
  }

  function setZoom(nextZoom, anchorX, anchorY) {
    if (!state.asset.width) return;
    const oldZoom = state.transform.zoom;
    const zoom = clamp(nextZoom, ZOOM_MIN, ZOOM_MAX);
    if (Math.abs(zoom - oldZoom) < 0.0001) return;
    const bounds = dom.canvasViewport.getBoundingClientRect();
    const x = anchorX ?? bounds.width / 2;
    const y = anchorY ?? bounds.height / 2;
    const ratio = zoom / oldZoom;
    state.transform.x = x - (x - state.transform.x) * ratio;
    state.transform.y = y - (y - state.transform.y) * ratio;
    state.transform.zoom = zoom;
    state.fitted = false;
    applyCanvasTransform();
  }

  function showEditorError(details) {
    const text = String(details || "运行失败");
    dom.errorSummary.hidden = false;
    dom.errorSummaryText.textContent = /traceback/i.test(text) ? "运行错误" : "1 个错误";
    dom.errorConsoleText.textContent = text;
  }

  function clearEditorError() {
    dom.errorSummary.hidden = true;
    dom.errorSummary.setAttribute("aria-expanded", "false");
    dom.errorConsole.hidden = true;
    dom.errorConsoleText.textContent = "";
  }

  function rebuildPropertyMap() {
    state.propertyMap.clear();
    state.schemaGroups.forEach((group) => group.properties.forEach((property) => state.propertyMap.set(property.path, property)));
  }

  function renderProperties(loading = false) {
    dom.propertiesPanel.replaceChildren();
    if (loading) {
      const skeleton = element("div", "tree-skeleton");
      for (let index = 0; index < 6; index += 1) skeleton.append(element("span"));
      dom.propertiesPanel.append(skeleton);
      dom.detectedCount.textContent = "…";
      return;
    }

    const query = dom.propertySearch.value.trim().toLocaleLowerCase();
    const total = state.schemaGroups.reduce((sum, group) => sum + group.properties.length, 0);
    dom.detectedCount.textContent = `${total} 项`;
    if (!total) {
      const empty = element("div", "properties-empty");
      empty.append(icon("M7 11h13M26 11h3M7 25h3M16 25h13", "0 0 36 36"));
      const svg = empty.firstElementChild;
      const circle1 = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle1.setAttribute("cx", "23"); circle1.setAttribute("cy", "11"); circle1.setAttribute("r", "3");
      const circle2 = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle2.setAttribute("cx", "13"); circle2.setAttribute("cy", "25"); circle2.setAttribute("r", "3");
      svg.append(circle1, circle2);
      empty.append(element("strong", "", "暂无可编辑属性"), element("span", "", state.current ? "当前代码未识别到规范化属性" : "载入图表后会自动分析代码"));
      dom.propertiesPanel.append(empty);
      return;
    }

    let matched = 0;
    state.schemaGroups.forEach((group) => {
      const properties = group.properties.filter((property) => {
        if (!query) return true;
        return [property.label, property.path, property.description, group.label]
          .some((value) => String(value || "").toLocaleLowerCase().includes(query));
      });
      if (!properties.length) return;
      matched += properties.length;
      dom.propertiesPanel.append(createPropertyGroup(group, properties, Boolean(query)));
    });

    if (!matched) dom.propertiesPanel.append(element("div", "properties-search-empty", `没有与“${dom.propertySearch.value.trim()}”匹配的属性`));
    dom.propertiesPanel.classList.toggle("is-disabled", state.dirty || state.saving);
  }

  function createPropertyGroup(group, properties, forceOpen) {
    const wrapper = element("section", "property-group");
    wrapper.dataset.groupId = group.id;
    const collapsed = !forceOpen && state.collapsedGroups.has(group.id);
    if (collapsed) wrapper.classList.add("is-collapsed");
    const toggle = element("button", "property-group__toggle");
    toggle.type = "button";
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.append(icon("m5.5 7.5 4.5 4.5 4.5-4.5"));
    toggle.append(element("span", "property-group__name", group.label));
    toggle.append(element("span", "property-group__count", properties.length));
    toggle.addEventListener("click", () => {
      if (state.collapsedGroups.has(group.id)) state.collapsedGroups.delete(group.id);
      else state.collapsedGroups.add(group.id);
      writeStorage("matplot.collapsedGroups", [...state.collapsedGroups]);
      wrapper.classList.toggle("is-collapsed");
      toggle.setAttribute("aria-expanded", String(!wrapper.classList.contains("is-collapsed")));
    });
    const body = element("div", "property-group__body");
    properties.forEach((property) => body.append(createPropertyField(property)));
    wrapper.append(toggle, body);
    return wrapper;
  }

  function createPropertyField(property) {
    const field = element("div", "property-field");
    field.dataset.path = property.path;
    const present = hasPath(state.settings, property.path);
    const value = present ? getPath(state.settings, property.path) : property.default;
    const labelRow = element("div", "property-label-row");
    const label = element("div", "property-label");
    label.title = property.path;
    label.append(element("span", "property-label__text", property.label));
    if (property.unit) label.append(element("span", "property-label__unit", property.unit));
    if (property.optional) label.append(element("span", "optional-badge", "可选"));
    labelRow.append(label);

    if (property.optional && present) {
      const remove = element("button", "property-remove");
      remove.type = "button";
      remove.title = `删除 ${property.label}`;
      remove.setAttribute("aria-label", `删除 ${property.label}`);
      remove.dataset.action = "remove-property";
      remove.append(icon("M5 10h10"));
      labelRow.append(remove);
    }
    field.append(labelRow);

    if (property.optional && !present) {
      const add = element("button", "property-add");
      add.type = "button";
      add.dataset.action = "add-property";
      add.append(icon("M10 4v12M4 10h12"), element("span", "", `添加 ${property.label}`));
      field.append(add);
    } else {
      field.append(createPropertyControl(property, value));
      if (property.description) field.append(element("p", "property-description", property.description));
    }
    return field;
  }

  function applyNumericAttributes(input, property, integer = false) {
    input.type = "number";
    if (property.min !== undefined && property.min !== null) input.min = property.min;
    if (property.max !== undefined && property.max !== null) input.max = property.max;
    input.step = property.step ?? (integer ? "1" : "any");
    input.inputMode = "decimal";
  }

  function markSettingInput(input, kind = "scalar", index = null) {
    input.dataset.settingInput = "true";
    input.dataset.kind = kind;
    if (index !== null) input.dataset.index = String(index);
    return input;
  }

  function createPropertyControl(property, rawValue) {
    const control = element("div", `property-control property-control--${property.type}`);
    const value = rawValue ?? defaultForProperty(property);
    let input;

    if (property.type === "number" || property.type === "integer") {
      const wrapper = element("div", `number-input-wrap${property.unit ? " has-unit" : ""}`);
      input = markSettingInput(element("input"));
      applyNumericAttributes(input, property, property.type === "integer");
      input.value = value ?? "";
      input.setAttribute("aria-label", property.label);
      wrapper.append(input);
      if (property.unit) wrapper.append(element("span", "", property.unit));
      control.append(wrapper);
    } else if (property.type === "text") {
      input = markSettingInput(element("textarea"));
      input.value = value ?? "";
      input.placeholder = property.placeholder;
      input.setAttribute("aria-label", property.label);
      control.append(input);
    } else if (property.type === "boolean") {
      const label = element("label", "boolean-control");
      label.append(element("span", "", value ? "已启用" : "已关闭"));
      input = markSettingInput(element("input"));
      input.type = "checkbox";
      input.checked = Boolean(value);
      input.setAttribute("aria-label", property.label);
      label.append(input, element("span", "switch"));
      control.append(label);
    } else if (property.type === "color") {
      const wrapper = element("div", "color-control");
      const well = element("label", "color-well");
      const color = markSettingInput(element("input"), "color-well");
      color.type = "color";
      color.value = normalizeColor(value);
      color.setAttribute("aria-label", `${property.label} 颜色选择器`);
      const text = markSettingInput(element("input", "color-text-input"), "color-text");
      text.type = "text";
      text.value = value ?? "";
      text.pattern = "^(#[0-9a-fA-F]{3,8}|[a-zA-Z]+|rgba?\\(.+\\)|hsla?\\(.+\\))$";
      text.setAttribute("aria-label", property.label);
      well.append(color);
      wrapper.append(well, text);
      control.append(wrapper);
    } else if (property.type === "select") {
      input = markSettingInput(element("select"));
      input.setAttribute("aria-label", property.label);
      property.options.forEach((option) => {
        const source = isObject(option) ? option : { value: option, label: option };
        const optionNode = element("option", "", source.label ?? source.name ?? source.value);
        optionNode.value = String(source.value ?? source.id ?? source.label ?? "");
        optionNode.selected = String(value) === optionNode.value;
        input.append(optionNode);
      });
      control.append(input);
    } else if (property.type === "number_pair") {
      const wrapper = element("div", "pair-control");
      const values = Array.isArray(value) ? value : [0, 0];
      ["W", "H"].forEach((axis, index) => {
        const pair = element("div", "pair-input");
        const number = markSettingInput(element("input"), "pair", index);
        applyNumericAttributes(number, property, false);
        number.value = values[index] ?? 0;
        number.setAttribute("aria-label", `${property.label} ${axis === "W" ? "宽度" : "高度"}`);
        pair.append(number, element("span", "", axis));
        wrapper.append(pair);
      });
      control.append(wrapper);
    } else if (property.type === "string_list" || property.type === "color_list") {
      control.append(createListControl(property, Array.isArray(value) ? value : []));
    } else {
      input = markSettingInput(element("input"));
      input.type = "text";
      input.value = value ?? "";
      input.placeholder = property.placeholder;
      input.setAttribute("aria-label", property.label);
      control.append(input);
    }
    return control;
  }

  function createListControl(property, values) {
    const wrapper = element("div", "list-control");
    values.forEach((value, index) => {
      const row = element("div", property.type === "color_list" ? "list-row color-list-row" : "list-row");
      row.append(element("span", "list-index", index + 1));
      if (property.type === "color_list") {
        const well = element("label", "color-well");
        const color = markSettingInput(element("input"), "list-color-well", index);
        color.type = "color";
        color.value = normalizeColor(value);
        color.setAttribute("aria-label", `${property.label} 第 ${index + 1} 项颜色选择器`);
        well.append(color);
        const text = markSettingInput(element("input", "color-text-input"), "list", index);
        text.type = "text";
        text.value = value;
        text.setAttribute("aria-label", `${property.label} 第 ${index + 1} 项`);
        row.append(well, text);
      } else {
        const text = markSettingInput(element("input", "list-value-input"), "list", index);
        text.type = "text";
        text.value = value;
        text.setAttribute("aria-label", `${property.label} 第 ${index + 1} 项`);
        row.append(text);
      }
      const remove = element("button", "list-remove");
      remove.type = "button";
      remove.dataset.action = "remove-list-item";
      remove.dataset.index = String(index);
      remove.setAttribute("aria-label", `删除第 ${index + 1} 项`);
      remove.append(icon("M5 10h10"));
      row.append(remove);
      wrapper.append(row);
    });
    const add = element("button", "list-add");
    add.type = "button";
    add.dataset.action = "add-list-item";
    add.append(icon("M10 4v12M4 10h12"), element("span", "", "添加一项"));
    wrapper.append(add);
    return wrapper;
  }

  function normalizeColor(value) {
    const text = String(value || "");
    if (/^#[0-9a-f]{6}$/i.test(text)) return text;
    if (/^#[0-9a-f]{3}$/i.test(text)) return `#${text.slice(1).split("").map((char) => char + char).join("")}`;
    const temporary = document.createElement("canvas").getContext("2d");
    if (temporary) {
      temporary.fillStyle = "#000000";
      temporary.fillStyle = text;
      if (/^#[0-9a-f]{6}$/i.test(temporary.fillStyle)) return temporary.fillStyle;
    }
    return "#176b5d";
  }

  function readFieldValue(field, property, sourceInput = null) {
    if (property.type === "number" || property.type === "integer") {
      const input = $("[data-setting-input]", field);
      if (!input || input.value === "" || !input.checkValidity()) return { valid: false };
      const value = Number(input.value);
      return { valid: Number.isFinite(value), value: property.type === "integer" ? Math.round(value) : value };
    }
    if (property.type === "boolean") return { valid: true, value: $("input[type='checkbox']", field).checked };
    if (property.type === "select") {
      const input = $("select[data-setting-input]", field);
      if (!input) return { valid: false };
      const matchingOption = property.options.find((option) => {
        const source = isObject(option) ? option : { value: option };
        return String(source.value ?? source.id ?? source.label ?? "") === input.value;
      });
      const source = isObject(matchingOption) ? matchingOption : { value: matchingOption };
      return { valid: true, value: source.value ?? source.id ?? source.label ?? input.value };
    }
    if (property.type === "number_pair") {
      const inputs = [...field.querySelectorAll("input[data-kind='pair']")];
      if (inputs.some((input) => input.value === "" || !input.checkValidity())) return { valid: false };
      const value = inputs.map((input) => Number(input.value));
      return { valid: value.every(Number.isFinite), value };
    }
    if (property.type === "string_list" || property.type === "color_list") {
      const inputs = [...field.querySelectorAll("input[data-kind='list']")];
      return { valid: true, value: inputs.map((input) => input.value) };
    }
    if (property.type === "color") {
      const text = $("input[data-kind='color-text']", field);
      return { valid: Boolean(text?.checkValidity()), value: text?.value || "" };
    }
    const input = sourceInput || $("[data-setting-input]", field);
    return { valid: Boolean(input), value: input?.value ?? "" };
  }

  function handlePropertyInput(event, immediate = false) {
    const input = event.target.closest("[data-setting-input]");
    if (!input) return;
    const field = input.closest(".property-field");
    const property = state.propertyMap.get(field?.dataset.path);
    if (!field || !property) return;

    if (input.dataset.kind === "color-well") {
      const text = $("input[data-kind='color-text']", field);
      if (text) text.value = input.value;
    } else if (input.dataset.kind === "color-text" && input.checkValidity()) {
      const well = $("input[data-kind='color-well']", field);
      if (well) well.value = normalizeColor(input.value);
    } else if (input.dataset.kind === "list-color-well") {
      const index = input.dataset.index;
      const text = field.querySelector(`input[data-kind="list"][data-index="${index}"]`);
      if (text) text.value = input.value;
    }

    const result = readFieldValue(field, property, input);
    if (!result.valid) return;
    if (property.type === "boolean") {
      const label = $(".boolean-control > span:first-child", field);
      if (label) label.textContent = result.value ? "已启用" : "已关闭";
    }
    setPath(state.settings, property.path, result.value);
    schedulePropertyPatch(property.path, result.value, "set", immediate);
  }

  function schedulePropertyPatch(path, value, operation = "set", immediate = false) {
    const existing = state.propertyTimers.get(path);
    if (existing) clearTimeout(existing);
    const run = () => {
      state.propertyTimers.delete(path);
      updateTreeActionAvailability();
      enqueuePropertyPatch(path, structuredCloneSafe(value), operation);
    };
    if (immediate) run();
    else {
      state.propertyTimers.set(path, window.setTimeout(run, PROPERTY_DELAY));
      updateTreeActionAvailability();
    }
  }

  function enqueuePropertyPatch(path, value, operation) {
    const projectId = state.project?.id;
    const plotId = state.plot?.id;
    if (!projectId || !plotId) return;
    state.patchChain = state.patchChain.catch(() => undefined).then(async () => {
      if (projectId !== state.project?.id || plotId !== state.plot?.id) return;
      if (state.dirty) {
        const saved = await saveCode({ render: false });
        if (!saved) throw new Error("代码未保存，属性修改已暂停。");
      }
      state.pendingSettings += 1;
      state.statusError = null;
      markFieldSyncing(path, true);
      updateActivityStatus();
      try {
        const codeVersionAtStart = state.codeVersion;
        const payload = await apiRequest(`${plotPath(projectId, plotId)}/settings`, {
          method: "PATCH",
          body: JSON.stringify({
            path,
            value,
            op: operation === "remove" ? "unset" : "set",
            revision: state.revision,
          }),
        });
        if (projectId !== state.project?.id || plotId !== state.plot?.id) return;
        const result = unwrap(payload) || {};
        state.revision = result.revision ?? result.version ?? state.revision;
        if (state.current) state.current = { ...state.current, ...result, revision: state.revision };
        updateExportControls();
        if (typeof result.code === "string" && codeVersionAtStart === state.codeVersion && !state.dirty) {
          dom.codeInput.value = result.code;
          if (state.current) state.current.code = result.code;
          updateLineNumbers();
          updateCursorPosition();
        }
        if (isObject(result.settings)) state.settings = structuredCloneSafe(result.settings);
        if (result.schema || result.properties) {
          state.schemaGroups = normalizeSchema(result.schema || result.properties);
          rebuildPropertyMap();
        }
        state.statusError = null;
        if (!state.dirty) {
          const handled = await presentEmbeddedRender(result.render, { quiet: true });
          if (!handled) await renderPlot({ quiet: true });
        }
      } catch (error) {
        const message = friendlyError(error);
        reportStatusError("属性同步失败");
        showToast(message, "error", 5000);
        showEditorError(errorDetails(error));
      } finally {
        state.pendingSettings = Math.max(0, state.pendingSettings - 1);
        markFieldSyncing(path, false);
        updateActivityStatus();
      }
    });
  }

  function markFieldSyncing(path, syncing) {
    const field = [...dom.propertiesPanel.querySelectorAll(".property-field")]
      .find((node) => node.dataset.path === path);
    field?.classList.toggle("is-syncing", syncing);
  }

  function handlePropertyAction(event) {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const field = button.closest(".property-field");
    const property = state.propertyMap.get(field?.dataset.path);
    if (!field || !property) return;
    const action = button.dataset.action;
    if (action === "add-property") {
      const value = defaultForProperty(property);
      setPath(state.settings, property.path, value);
      renderProperties();
      schedulePropertyPatch(property.path, value, "add", true);
    } else if (action === "remove-property") {
      deletePath(state.settings, property.path);
      renderProperties();
      schedulePropertyPatch(property.path, null, "remove", true);
    } else if (action === "add-list-item" || action === "remove-list-item") {
      const list = [...(getPath(state.settings, property.path) || [])];
      if (action === "add-list-item") list.push(property.type === "color_list" ? "#176b5d" : "");
      else list.splice(Number(button.dataset.index), 1);
      setPath(state.settings, property.path, list);
      renderProperties();
      schedulePropertyPatch(property.path, list, "set", true);
    }
  }

  function resumeAutosaveIfNeeded() {
    if (!state.dirty || !state.current || !dom.autoRenderToggle.checked || state.importing || state.deleting) return;
    clearTimeout(state.autosaveTimer);
    state.autosaveTimer = window.setTimeout(() => runAndRender({ source: "auto" }), AUTOSAVE_DELAY);
  }

  async function settleCurrentEditsForImport(report, actionName) {
    clearTimeout(state.autosaveTimer);
    if (state.rendering) {
      report("正在等待当前渲染完成…", "neutral", true);
      const finished = await waitUntil(() => !state.rendering, 20000);
      if (!finished) throw new ApiError(`当前渲染尚未完成，${actionName}已取消。`, 0);
    }
    if (state.saving) {
      report("正在等待当前保存完成…", "neutral", true);
      const finished = await waitUntil(() => !state.saving, 8000);
      if (!finished) throw new ApiError(`当前保存尚未完成，${actionName}已取消。`, 0);
    }
    if (state.propertyTimers.size) {
      report("正在完成当前属性修改…", "neutral", true);
      const finished = await waitUntil(() => state.propertyTimers.size === 0, 3000);
      if (!finished) throw new ApiError(`属性修改尚未完成，${actionName}已取消。`, 0);
    }
    await state.patchChain.catch(() => undefined);
    if (state.pendingSettings > 0) {
      report("正在同步当前属性修改…", "neutral", true);
      const finished = await waitUntil(() => state.pendingSettings === 0, 10000);
      if (!finished) throw new ApiError(`属性同步尚未完成，${actionName}已取消。`, 0);
    }
    if (state.dirty) {
      report("正在保存当前图表…", "neutral", true);
      const saved = await saveCode({ render: false });
      if (!saved) throw new ApiError(`当前图表未能保存，${actionName}已取消。`, 0);
    }
  }

  function setImportFeedback(message = "", tone = "neutral", busy = false) {
    dom.importProjectFeedback.hidden = !message;
    dom.importProjectFeedback.dataset.tone = tone;
    dom.importProjectFeedbackText.textContent = message;
    dom.importProjectSpinner.hidden = !busy;
  }

  function setImportBusy(busy) {
    state.importing = busy;
    state.importingLabel = busy ? "项目" : null;
    dom.chooseProjectZip.disabled = busy;
    dom.chooseProjectFolder.disabled = busy;
    dom.closeImportProjectDialog.disabled = busy;
    dom.cancelImportProject.disabled = busy;
    updateActivityStatus();
  }

  function resetImportDialog() {
    if (state.importing) return;
    dom.projectZipInput.value = "";
    dom.projectFolderInput.value = "";
    setImportFeedback();
  }

  function openImportProjectDialog() {
    if (rejectBusyAction("导入项目")) return;
    resetImportDialog();
    dom.importProjectDialog.showModal();
    requestAnimationFrame(() => dom.chooseProjectZip.focus());
  }

  async function importProjectSelection(kind, selectedFiles) {
    if (state.importing || !selectedFiles.length) return;
    let importedProject = null;
    let importSucceeded = false;
    state.statusError = null;
    setImportBusy(true);

    try {
      await settleCurrentEditsForImport(setImportFeedback, "项目导入");

      let payload;
      if (kind === "zip") {
        const [file] = selectedFiles;
        setImportFeedback(`正在上传并校验 ${file.name}…`, "neutral", true);
        payload = await apiRequest(`${API_ROOT}/projects/import`, {
          method: "POST",
          headers: { "Content-Type": "application/zip" },
          body: file,
        });
      } else {
        const projectFiles = selectedFiles.filter((file) => {
          const path = file.webkitRelativePath || file.name;
          const parts = path.split("/");
          const name = parts.at(-1);
          return !parts.includes("__MACOSX")
            && !parts.includes("__pycache__")
            && name !== ".DS_Store"
            && name !== "Thumbs.db"
            && !name.startsWith("._")
            && !/\.py[co]$/i.test(name);
        });
        if (!projectFiles.length) {
          throw new ApiError("所选文件夹中没有可导入的项目文件。", 422);
        }
        if (projectFiles.length > 256) {
          throw new ApiError("项目文件不能超过 256 个。", 413);
        }
        const totalSize = projectFiles.reduce((sum, file) => sum + file.size, 0);
        if (totalSize > 16 * 1024 * 1024) {
          throw new ApiError("项目文件总大小不能超过 16 MiB。", 413);
        }
        const files = [];
        const decoder = new TextDecoder("utf-8", { fatal: true });
        for (let index = 0; index < projectFiles.length; index += 1) {
          const file = projectFiles[index];
          if (file.size > 2 * 1024 * 1024) {
            throw new ApiError(`文件“${file.name}”不能超过 2 MiB。`, 413);
          }
          setImportFeedback(`正在读取项目文件（${index + 1}/${projectFiles.length}）…`, "neutral", true);
          let content;
          try {
            content = decoder.decode(await file.arrayBuffer());
          } catch {
            throw new ApiError(`文件“${file.name}”不是 UTF-8 文本；含二进制文件的项目请使用 ZIP 导入。`, 422);
          }
          files.push({
            path: file.webkitRelativePath || file.name,
            content,
          });
        }
        setImportFeedback("正在上传并校验项目…", "neutral", true);
        payload = await apiRequest(`${API_ROOT}/projects/import`, {
          method: "POST",
          body: JSON.stringify({ files }),
        });
      }

      const result = unwrap(payload) || {};
      importedProject = isObject(result.project) ? result.project : result;
      const projectId = entityId(importedProject);
      if (!projectId) throw new ApiError("服务未返回导入后的项目编号。", 500, payload);
      const projectName = displayName(importedProject, projectId);
      const importedPlots = Array.isArray(importedProject.plots) ? importedProject.plots : [];
      const firstPlotId = importedPlots.length ? entityId(importedPlots[0]) : null;

      state.collapsedProjects.delete(projectId);
      writeStorage("matplot.collapsedProjects", [...state.collapsedProjects]);
      dom.projectSearch.value = "";
      setImportFeedback(`项目“${projectName}”已导入，正在打开…`, "success", true);
      await fetchProjects({ keepSelection: false, selectProjectId: projectId, selectPlotId: firstPlotId });
      clearStatusError();
      showToast(`已导入项目“${projectName}”`, "success", 3600);
      importSucceeded = true;
    } catch (error) {
      const message = friendlyError(error);
      reportStatusError("导入失败");
      setImportFeedback(message, "error", false);
      showToast(message, "error", 6000);
    } finally {
      setImportBusy(false);
      resumeAutosaveIfNeeded();
      dom.projectZipInput.value = "";
      dom.projectFolderInput.value = "";
      if (importSucceeded) dom.importProjectDialog.close();
    }
  }

  function setPlotImportFeedback(message = "", tone = "neutral", busy = false) {
    dom.importPlotFeedback.hidden = !message;
    dom.importPlotFeedback.dataset.tone = tone;
    dom.importPlotFeedbackText.textContent = message;
    dom.importPlotSpinner.hidden = !busy;
  }

  function setPlotImportBusy(busy) {
    state.importing = busy;
    state.importingLabel = busy ? "图表" : null;
    dom.choosePlotFile.disabled = busy;
    dom.choosePlotFolder.disabled = busy;
    dom.closeImportPlotDialog.disabled = busy;
    dom.cancelImportPlot.disabled = busy;
    dom.importPlotForm.setAttribute("aria-busy", String(busy));
    updateActivityStatus();
  }

  function resetPlotImportDialog() {
    if (state.importing) return;
    state.selectedProjectForImportPlot = null;
    dom.plotFileInput.value = "";
    dom.plotFolderInput.value = "";
    setPlotImportFeedback();
  }

  function openImportPlotDialog(project) {
    if (rejectBusyAction("导入图表")) return;
    resetPlotImportDialog();
    state.selectedProjectForImportPlot = project;
    dom.importPlotProjectLabel.textContent = `目标项目 · ${project.name}`;
    dom.importPlotDialog.showModal();
    requestAnimationFrame(() => dom.choosePlotFile.focus());
  }

  function plotImportPath(file) {
    return String(file.webkitRelativePath || file.name || "").replaceAll("\\", "/");
  }

  function isIgnoredPlotPath(path) {
    const ignoredDirectories = new Set([
      "__pycache__", "__macosx", ".git", ".hg", ".svn", ".mypy_cache",
      ".pytest_cache", ".ruff_cache", ".tox", ".nox", "node_modules",
    ]);
    const parts = path.split("/").filter(Boolean);
    return parts.slice(0, -1).some((part) => ignoredDirectories.has(part.toLocaleLowerCase()));
  }

  async function readPlotImportFiles(kind, selectedFiles) {
    let candidates;
    if (kind === "file") {
      const [file] = selectedFiles;
      if (!file || file.name !== "plot.py") {
        throw new ApiError("请选择名为 plot.py 的文件。", 422);
      }
      candidates = [file];
    } else {
      candidates = selectedFiles.filter((file) => {
        const path = plotImportPath(file);
        const name = path.split("/").at(-1);
        return name === "plot.py" && !isIgnoredPlotPath(path);
      });
      if (!candidates.length) {
        throw new ApiError("所选文件夹中没有找到可导入的 plot.py。", 422);
      }
    }

    if (candidates.length > 256) throw new ApiError("一次最多导入 256 个 plot.py。", 413);
    const totalSize = candidates.reduce((sum, file) => sum + file.size, 0);
    if (totalSize > 16 * 1024 * 1024) throw new ApiError("导入文件总大小不能超过 16 MiB。", 413);

    const decoder = new TextDecoder("utf-8", { fatal: true });
    const files = [];
    for (let index = 0; index < candidates.length; index += 1) {
      const file = candidates[index];
      const path = kind === "file" ? file.name : plotImportPath(file);
      if (file.size > 2 * 1024 * 1024) {
        throw new ApiError(`文件“${path}”不能超过 2 MiB。`, 413);
      }
      setPlotImportFeedback(`正在读取 plot.py（${index + 1}/${candidates.length}）…`, "neutral", true);
      let content;
      try {
        content = decoder.decode(await file.arrayBuffer());
      } catch {
        throw new ApiError(`文件“${path}”不是有效的 UTF-8 文本。`, 422);
      }
      files.push({ path, content });
    }
    return files;
  }

  async function importPlotSelection(kind, selectedFiles) {
    const project = state.selectedProjectForImportPlot;
    if (state.importing || !project || !selectedFiles.length) return;
    let importSucceeded = false;
    state.statusError = null;
    setPlotImportBusy(true);

    try {
      await settleCurrentEditsForImport(setPlotImportFeedback, "图表导入");
      const files = await readPlotImportFiles(kind, selectedFiles);
      setPlotImportFeedback(`正在向“${project.name}”导入 ${files.length} 个图表…`, "neutral", true);
      const payload = await apiRequest(`${API_ROOT}/projects/${encodeSegment(project.id)}/plots/import`, {
        method: "POST",
        body: JSON.stringify({ files }),
      });
      const result = unwrap(payload) || {};
      const importedPlots = Array.isArray(result.plots) ? result.plots : [];
      const firstPlotId = importedPlots.length ? entityId(importedPlots[0]) : "";
      if (!firstPlotId) throw new ApiError("服务未返回导入后的图表编号。", 500, payload);

      state.collapsedProjects.delete(project.id);
      writeStorage("matplot.collapsedProjects", [...state.collapsedProjects]);
      dom.projectSearch.value = "";
      setPlotImportFeedback(`已导入 ${importedPlots.length} 个图表，正在打开…`, "success", true);
      await fetchProjects({ keepSelection: false, selectProjectId: project.id, selectPlotId: firstPlotId });
      clearStatusError();
      showToast(`已向“${project.name}”导入 ${importedPlots.length} 个图表`, "success", 4200);
      importSucceeded = true;
    } catch (error) {
      const message = friendlyError(error);
      reportStatusError("导入失败");
      setPlotImportFeedback(message, "error", false);
      showToast(message, "error", 6000);
    } finally {
      setPlotImportBusy(false);
      resumeAutosaveIfNeeded();
      dom.plotFileInput.value = "";
      dom.plotFolderInput.value = "";
      if (importSucceeded) dom.importPlotDialog.close();
    }
  }

  function deleteAffectsCurrent(target) {
    if (!target || !state.project) return false;
    if (target.type === "project") return state.project.id === target.project.id;
    return state.project.id === target.project.id && state.plot?.id === target.plot.id;
  }

  function fallbackAfterDelete(target) {
    const flattened = state.projects.flatMap((project) => project.plots.map((plot) => ({
      projectId: project.id,
      plotId: plot.id,
    })));
    const removedIndexes = [];
    flattened.forEach((item, index) => {
      const removed = target.type === "project"
        ? item.projectId === target.project.id
        : item.projectId === target.project.id && item.plotId === target.plot.id;
      if (removed) removedIndexes.push(index);
    });
    if (!removedIndexes.length) return flattened[0] || null;
    const first = removedIndexes[0];
    const last = removedIndexes.at(-1);
    const isRemoved = (item) => target.type === "project"
      ? item.projectId === target.project.id
      : item.projectId === target.project.id && item.plotId === target.plot.id;
    return flattened.slice(last + 1).find((item) => !isRemoved(item))
      || flattened.slice(0, first).reverse().find((item) => !isRemoved(item))
      || null;
  }

  function configureConfirmation({ eyebrow, title, name, description, confirmLabel, danger = true }) {
    dom.deleteEntityKindLabel.textContent = eyebrow;
    dom.deleteEntityTitle.textContent = title;
    dom.deleteEntityName.textContent = name;
    dom.deleteEntityDescription.textContent = description;
    dom.confirmDeleteEntity.textContent = confirmLabel;
    dom.confirmDeleteEntity.classList.toggle("button--danger", danger);
    dom.confirmDeleteEntity.classList.toggle("button--primary", !danger);
    dom.deleteEntityError.hidden = true;
    dom.deleteEntityError.textContent = "";
  }

  function openDeleteDialog(target) {
    if (rejectBusyAction(target.type === "project" ? "删除项目" : "删除图表")) return;
    state.deleteTarget = target;
    const isProject = target.type === "project";
    const name = isProject ? target.project.name : target.plot.name;
    const count = target.project.plots.length;
    const unsaved = state.dirty && deleteAffectsCurrent(target) ? " 当前未保存的代码修改也会丢失。" : "";
    configureConfirmation({
      eyebrow: isProject ? "删除项目" : `项目 · ${target.project.name}`,
      title: isProject ? "确认删除项目" : "确认删除图表",
      name: `“${name}”`,
      description: isProject
        ? `此操作会永久删除该项目及其中 ${count} 个图表，且无法撤销。${unsaved}`
        : `此操作会永久删除该图表的代码与配置，且无法撤销。${unsaved}`,
      confirmLabel: isProject ? "永久删除项目" : "永久删除图表",
    });
    if (state.dirty) {
      clearTimeout(state.autosaveTimer);
      state.pausedAutosaveForDialog = true;
    }
    dom.deleteEntityDialog.returnValue = "";
    dom.deleteEntityDialog.showModal();
    requestAnimationFrame(() => dom.cancelDeleteEntity.focus());
  }

  function confirmDiscardChanges() {
    if (dom.deleteEntityDialog.open) return Promise.resolve(false);
    state.deleteTarget = null;
    configureConfirmation({
      eyebrow: "未保存的更改",
      title: "放弃修改并切换？",
      name: `“${state.plot?.name || "当前图表"}”`,
      description: "当前代码无法保存。继续切换会放弃这些尚未保存的修改。",
      confirmLabel: "放弃并切换",
      danger: false,
    });
    return new Promise((resolve) => {
      state.confirmationResolver = resolve;
      dom.deleteEntityDialog.returnValue = "";
      dom.deleteEntityDialog.showModal();
      requestAnimationFrame(() => dom.cancelDeleteEntity.focus());
    });
  }

  function setDeleteBusy(busy) {
    state.deleting = busy;
    dom.confirmDeleteEntity.disabled = busy;
    dom.cancelDeleteEntity.disabled = busy;
    dom.closeDeleteEntityDialog.disabled = busy;
    dom.deleteEntityForm.setAttribute("aria-busy", String(busy));
    updateActivityStatus();
  }

  function invalidateDeletedSelection() {
    clearTimeout(state.autosaveTimer);
    state.propertyTimers.forEach((timer) => clearTimeout(timer));
    state.propertyTimers.clear();
    state.loadToken += 1;
    state.artifactToken += 1;
    state.artifactAbort?.abort();
    state.artifactAbort = null;
    try {
      localStorage.removeItem("matplot.lastSelection");
    } catch {
      // Local storage is optional.
    }
    resetEditor();
  }

  async function submitDeleteEntity(event) {
    event.preventDefault();
    if (event.submitter?.value === "cancel") {
      if (!state.deleting) dom.deleteEntityDialog.close("cancel");
      return;
    }
    if (state.confirmationResolver && !state.deleteTarget) {
      dom.deleteEntityDialog.close("confirm");
      return;
    }

    const target = state.deleteTarget;
    if (!target || state.deleting) return;
    if (workspaceMutationBusy()) {
      dom.deleteEntityError.textContent = "当前操作尚未完成，请稍后再试。";
      dom.deleteEntityError.hidden = false;
      return;
    }

    const affectsCurrent = deleteAffectsCurrent(target);
    const fallback = affectsCurrent ? fallbackAfterDelete(target) : null;
    const name = target.type === "project" ? target.project.name : target.plot.name;
    const endpoint = target.type === "project"
      ? `${API_ROOT}/projects/${encodeSegment(target.project.id)}`
      : plotPath(target.project.id, target.plot.id);
    let succeeded = false;
    state.statusError = null;
    setDeleteBusy(true);
    dom.deleteEntityError.hidden = true;

    try {
      await apiRequest(endpoint, { method: "DELETE" });
      if (affectsCurrent) invalidateDeletedSelection();
      await fetchProjects({
        keepSelection: !affectsCurrent,
        selectProjectId: fallback?.projectId ?? null,
        selectPlotId: fallback?.plotId ?? null,
      });
      clearStatusError();
      showToast(`已删除${target.type === "project" ? "项目" : "图表"}“${name}”`, "success", 3600);
      succeeded = true;
    } catch (error) {
      const message = friendlyError(error);
      reportStatusError("删除失败");
      dom.deleteEntityError.textContent = message;
      dom.deleteEntityError.hidden = false;
      showToast(message, "error", 6000);
    } finally {
      setDeleteBusy(false);
      if (succeeded) dom.deleteEntityDialog.close("deleted");
    }
  }

  function handleDeleteDialogClose() {
    const resolver = state.confirmationResolver;
    const confirmed = dom.deleteEntityDialog.returnValue === "confirm";
    state.confirmationResolver = null;
    state.deleteTarget = null;
    dom.deleteEntityError.hidden = true;
    if (state.pausedAutosaveForDialog) {
      state.pausedAutosaveForDialog = false;
      resumeAutosaveIfNeeded();
    }
    if (resolver) resolver(confirmed);
  }

  function openCreateProjectDialog() {
    if (rejectBusyAction("新建项目")) return;
    dom.newProjectName.value = "";
    dom.createProjectError.hidden = true;
    dom.createProjectDialog.showModal();
    requestAnimationFrame(() => dom.newProjectName.focus());
  }

  function openCreatePlotDialog(project) {
    if (rejectBusyAction("新建图表")) return;
    state.selectedProjectForNewPlot = project;
    dom.newPlotProjectLabel.textContent = project.name;
    dom.newPlotName.value = "";
    dom.createPlotError.hidden = true;
    dom.createPlotDialog.showModal();
    requestAnimationFrame(() => dom.newPlotName.focus());
  }

  async function submitCreateProject(event) {
    event.preventDefault();
    if (event.submitter?.value === "cancel") {
      dom.createProjectDialog.close();
      return;
    }
    if (!dom.createProjectForm.reportValidity()) return;
    const name = dom.newProjectName.value.trim();
    dom.confirmCreateProject.disabled = true;
    dom.createProjectError.hidden = true;
    try {
      await apiRequest(`${API_ROOT}/projects`, { method: "POST", body: JSON.stringify({ name }) });
      dom.createProjectDialog.close();
      showToast(`已创建项目“${name}”`, "success");
      await fetchProjects({ keepSelection: false });
    } catch (error) {
      dom.createProjectError.textContent = friendlyError(error);
      dom.createProjectError.hidden = false;
    } finally {
      dom.confirmCreateProject.disabled = false;
    }
  }

  async function submitCreatePlot(event) {
    event.preventDefault();
    if (event.submitter?.value === "cancel") {
      dom.createPlotDialog.close();
      return;
    }
    if (!dom.createPlotForm.reportValidity() || !state.selectedProjectForNewPlot) return;
    const name = dom.newPlotName.value.trim();
    const project = state.selectedProjectForNewPlot;
    dom.confirmCreatePlot.disabled = true;
    dom.createPlotError.hidden = true;
    try {
      await apiRequest(`${API_ROOT}/projects/${encodeSegment(project.id)}/plots`, {
        method: "POST",
        body: JSON.stringify({ name }),
      });
      dom.createPlotDialog.close();
      showToast(`已创建图表“${name}”`, "success");
      await fetchProjects();
    } catch (error) {
      dom.createPlotError.textContent = friendlyError(error);
      dom.createPlotError.hidden = false;
    } finally {
      dom.confirmCreatePlot.disabled = false;
    }
  }

  function closeMobilePanels() {
    dom.explorer.classList.remove("is-open");
    dom.inspector.classList.remove("is-open");
    dom.mobileBackdrop.hidden = true;
  }

  function toggleMobilePanel(panel) {
    const open = !panel.classList.contains("is-open");
    closeMobilePanels();
    if (open) {
      panel.classList.add("is-open");
      dom.mobileBackdrop.hidden = false;
    }
  }

  function bindCanvasEvents() {
    dom.fitCanvasButton.addEventListener("click", fitCanvas);
    dom.resetZoomButton.addEventListener("click", resetZoom);
    dom.zoomInButton.addEventListener("click", () => setZoom(state.transform.zoom * 1.2));
    dom.zoomOutButton.addEventListener("click", () => setZoom(state.transform.zoom / 1.2));
    dom.retryRenderButton.addEventListener("click", () => runAndRender());
    dom.canvasViewport.addEventListener("dblclick", fitCanvas);
    dom.canvasViewport.addEventListener("wheel", (event) => {
      if (!state.asset.width) return;
      event.preventDefault();
      if (event.ctrlKey || event.metaKey) {
        const bounds = dom.canvasViewport.getBoundingClientRect();
        const factor = Math.exp(-event.deltaY * 0.0025);
        setZoom(state.transform.zoom * factor, event.clientX - bounds.left, event.clientY - bounds.top);
      } else {
        state.transform.x -= event.deltaX;
        state.transform.y -= event.deltaY;
        state.fitted = false;
        applyCanvasTransform();
      }
    }, { passive: false });

    dom.canvasViewport.addEventListener("pointerdown", (event) => {
      if (!state.asset.width || event.button !== 0) return;
      state.panning = {
        pointerId: event.pointerId,
        clientX: event.clientX,
        clientY: event.clientY,
        x: state.transform.x,
        y: state.transform.y,
      };
      dom.canvasViewport.setPointerCapture(event.pointerId);
      dom.canvasViewport.classList.add("is-panning");
    });
    dom.canvasViewport.addEventListener("pointermove", (event) => {
      if (!state.panning || state.panning.pointerId !== event.pointerId) return;
      state.transform.x = state.panning.x + event.clientX - state.panning.clientX;
      state.transform.y = state.panning.y + event.clientY - state.panning.clientY;
      state.fitted = false;
      applyCanvasTransform();
    });
    const stopPanning = (event) => {
      if (!state.panning || (event.pointerId !== undefined && state.panning.pointerId !== event.pointerId)) return;
      state.panning = null;
      dom.canvasViewport.classList.remove("is-panning");
    };
    dom.canvasViewport.addEventListener("pointerup", stopPanning);
    dom.canvasViewport.addEventListener("pointercancel", stopPanning);
    dom.canvasViewport.addEventListener("keydown", (event) => {
      if (["+", "="].includes(event.key)) {
        event.preventDefault(); setZoom(state.transform.zoom * 1.2);
      } else if (event.key === "-") {
        event.preventDefault(); setZoom(state.transform.zoom / 1.2);
      } else if (event.key === "0") {
        event.preventDefault(); resetZoom();
      } else if (event.key.toLowerCase() === "f") {
        event.preventDefault(); fitCanvas();
      }
    });

    const resizeObserver = new ResizeObserver(() => {
      if (state.fitted) requestAnimationFrame(fitCanvas);
    });
    resizeObserver.observe(dom.canvasViewport);
  }

  function bindEditorResizer() {
    let drag = null;
    dom.editorResizer.addEventListener("pointerdown", (event) => {
      drag = { pointerId: event.pointerId };
      dom.editorResizer.setPointerCapture(event.pointerId);
      dom.studio.classList.add("is-resizing");
      document.body.style.cursor = "row-resize";
    });
    dom.editorResizer.addEventListener("pointermove", (event) => {
      if (!drag || drag.pointerId !== event.pointerId) return;
      const bounds = dom.studio.getBoundingClientRect();
      const available = bounds.height - 7;
      const editorPixels = bounds.bottom - event.clientY;
      const percent = clamp((editorPixels / available) * 100, 24, 68);
      dom.studio.style.setProperty("--editor-height", `${percent}%`);
      writeStorage("matplot.editorHeight", percent);
    });
    const end = (event) => {
      if (!drag || drag.pointerId !== event.pointerId) return;
      drag = null;
      dom.studio.classList.remove("is-resizing");
      document.body.style.cursor = "";
    };
    dom.editorResizer.addEventListener("pointerup", end);
    dom.editorResizer.addEventListener("pointercancel", end);
    dom.editorResizer.addEventListener("keydown", (event) => {
      if (!["ArrowUp", "ArrowDown"].includes(event.key)) return;
      event.preventDefault();
      const current = parseFloat(getComputedStyle(dom.studio).getPropertyValue("--editor-height")) || 38;
      const next = clamp(current + (event.key === "ArrowUp" ? 3 : -3), 24, 68);
      dom.studio.style.setProperty("--editor-height", `${next}%`);
      writeStorage("matplot.editorHeight", next);
    });
    const savedHeight = Number(readStorage("matplot.editorHeight", 38));
    if (Number.isFinite(savedHeight)) dom.studio.style.setProperty("--editor-height", `${clamp(savedHeight, 24, 68)}%`);
  }

  function handleEditorKeydown(event) {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      runAndRender();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      saveCode({ render: false });
      return;
    }
    if (event.key !== "Tab") return;
    event.preventDefault();
    const input = dom.codeInput;
    const start = input.selectionStart;
    const end = input.selectionEnd;
    if (start === end) {
      const spaces = " ".repeat(4 - (start - input.value.lastIndexOf("\n", start - 1) - 1) % 4);
      input.setRangeText(spaces, start, end, "end");
    } else {
      const lineStart = input.value.lastIndexOf("\n", start - 1) + 1;
      const selected = input.value.slice(lineStart, end);
      const replacement = event.shiftKey
        ? selected.replace(/^ {1,4}/gm, "")
        : selected.replace(/^/gm, "    ");
      input.setRangeText(replacement, lineStart, end, "select");
    }
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function bindEvents() {
    bindExportMenu(dom.imageExportMenu);
    bindExportMenu(dom.dataExportMenu);
    dom.copyPngButton.addEventListener("click", copyPngToClipboard);
    document.querySelectorAll(".export-option").forEach((option) => {
      option.addEventListener("click", () => downloadExport(option.dataset.exportKind, option.dataset.format));
    });
    document.addEventListener("click", (event) => {
      if (!event.target.closest(".export-menu")) closeExportMenus();
    });
    dom.projectSearch.addEventListener("input", renderProjectTree);
    dom.propertySearch.addEventListener("input", () => renderProperties());
    dom.refreshProjectsButton.addEventListener("click", () => fetchProjects());
    dom.importProjectButton.addEventListener("click", openImportProjectDialog);
    dom.newProjectButton.addEventListener("click", openCreateProjectDialog);
    dom.chooseProjectZip.addEventListener("click", () => dom.projectZipInput.click());
    dom.chooseProjectFolder.addEventListener("click", () => dom.projectFolderInput.click());
    dom.projectZipInput.addEventListener("change", () => {
      const files = Array.from(dom.projectZipInput.files || []);
      if (files.length) importProjectSelection("zip", files);
    });
    dom.projectFolderInput.addEventListener("change", () => {
      const files = Array.from(dom.projectFolderInput.files || []);
      if (files.length) importProjectSelection("folder", files);
    });
    dom.importProjectForm.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!state.importing) dom.importProjectDialog.close();
    });
    dom.importProjectDialog.addEventListener("cancel", (event) => {
      if (state.importing) event.preventDefault();
    });
    dom.importProjectDialog.addEventListener("close", resetImportDialog);
    dom.choosePlotFile.addEventListener("click", () => dom.plotFileInput.click());
    dom.choosePlotFolder.addEventListener("click", () => dom.plotFolderInput.click());
    dom.plotFileInput.addEventListener("change", () => {
      const files = Array.from(dom.plotFileInput.files || []);
      if (files.length) importPlotSelection("file", files);
    });
    dom.plotFolderInput.addEventListener("change", () => {
      const files = Array.from(dom.plotFolderInput.files || []);
      if (files.length) importPlotSelection("folder", files);
    });
    dom.importPlotForm.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!state.importing) dom.importPlotDialog.close();
    });
    dom.importPlotDialog.addEventListener("cancel", (event) => {
      if (state.importing) event.preventDefault();
    });
    dom.importPlotDialog.addEventListener("close", resetPlotImportDialog);
    dom.deleteEntityForm.addEventListener("submit", submitDeleteEntity);
    dom.deleteEntityDialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      if (!state.deleting) dom.deleteEntityDialog.close("cancel");
    });
    dom.deleteEntityDialog.addEventListener("close", handleDeleteDialogClose);
    dom.renderButton.addEventListener("click", () => runAndRender());
    dom.autoRenderToggle.addEventListener("change", () => {
      if (dom.autoRenderToggle.checked && state.dirty) {
        clearTimeout(state.autosaveTimer);
        state.autosaveTimer = window.setTimeout(() => runAndRender({ source: "auto" }), AUTOSAVE_DELAY);
      } else {
        clearTimeout(state.autosaveTimer);
      }
      updateDirtyUI();
    });

    dom.codeInput.addEventListener("input", handleCodeInput);
    dom.codeInput.addEventListener("keydown", handleEditorKeydown);
    dom.codeInput.addEventListener("scroll", () => { dom.lineNumbers.scrollTop = dom.codeInput.scrollTop; });
    ["click", "keyup", "select"].forEach((eventName) => dom.codeInput.addEventListener(eventName, updateCursorPosition));

    dom.errorSummary.addEventListener("click", () => {
      const open = dom.errorConsole.hidden;
      dom.errorConsole.hidden = !open;
      dom.errorSummary.setAttribute("aria-expanded", String(open));
    });
    dom.closeErrorConsole.addEventListener("click", () => {
      dom.errorConsole.hidden = true;
      dom.errorSummary.setAttribute("aria-expanded", "false");
    });

    dom.propertiesPanel.addEventListener("input", (event) => handlePropertyInput(event, false));
    dom.propertiesPanel.addEventListener("change", (event) => handlePropertyInput(event, true));
    dom.propertiesPanel.addEventListener("click", handlePropertyAction);

    dom.createProjectForm.addEventListener("submit", submitCreateProject);
    dom.createPlotForm.addEventListener("submit", submitCreatePlot);
    dom.toggleExplorer.addEventListener("click", () => toggleMobilePanel(dom.explorer));
    dom.toggleInspector.addEventListener("click", () => toggleMobilePanel(dom.inspector));
    dom.mobileBackdrop.addEventListener("click", closeMobilePanels);

    document.addEventListener("keydown", (event) => {
      const isTyping = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName);
      if (event.key === "/" && !isTyping && !event.ctrlKey && !event.metaKey) {
        event.preventDefault();
        if (window.matchMedia("(max-width: 960px)").matches) toggleMobilePanel(dom.explorer);
        dom.projectSearch.focus();
      } else if (event.key === "Escape") {
        closeExportMenus();
        closeMobilePanels();
      }
    });

    window.addEventListener("beforeunload", (event) => {
      if (!state.dirty) return;
      event.preventDefault();
      event.returnValue = "";
    });
    window.addEventListener("online", () => {
      state.statusError = null;
      updateActivityStatus();
      showToast("网络连接已恢复", "success", 2200);
    });
    window.addEventListener("offline", () => {
      reportStatusError("网络已断开");
      showToast("网络连接已断开", "warning", 0);
    });
    window.matchMedia("(max-width: 960px)").addEventListener("change", (event) => {
      if (!event.matches) closeMobilePanels();
    });
  }

  function initialize() {
    bindEvents();
    bindCanvasEvents();
    bindEditorResizer();
    updateLineNumbers();
    updateExportControls();
    fetchProjects();
  }

  initialize();
})();
