/* Project illustration library, with live reference checks before deletion. */
(() => {
  "use strict";
  const node = (tag, text = "", className = "") => {
    const element = document.createElement(tag); element.textContent = text; element.className = className; return element;
  };
  window.CompositionAssets = {
    create() {
      const dialog = node("dialog", "", "asset-library");
      dialog.setAttribute("aria-label", "管理示意图");
      const heading = node("header", "", "composition-header");
      const title = node("h2", "管理示意图"), close = node("button", "关闭", "button button--quiet");
      close.type = "button"; close.setAttribute("aria-label", "关闭示意图管理"); heading.append(title, close);
      const body = node("div", "", "asset-library__body");
      const controls = node("div", "", "asset-library__controls");
      const search = node("input"); search.type = "search"; search.placeholder = "按文件名搜索示意图";
      search.setAttribute("aria-label", "搜索示意图");
      const refresh = node("button", "刷新", "button button--quiet"); refresh.type = "button";
      const status = node("p", "", "composition-hint"); status.setAttribute("role", "status");
      const hint = node("p", "点击缩略图可放大查看。正在被已保存拼图或当前排版使用的素材，需先移除对应子图并保存后才能删除。", "composition-hint");
      const grid = node("div", "", "asset-library__grid");
      controls.append(search, refresh); body.append(controls, hint, status, grid); dialog.append(heading, body);
      const preview = node("dialog", "", "asset-preview"); preview.setAttribute("aria-label", "示意图大图预览");
      const previewTitle = node("h2"), previewClose = node("button", "关闭预览", "button button--quiet"); previewClose.type = "button";
      const previewHeading = node("header", "", "composition-header"); previewHeading.append(previewTitle, previewClose);
      const largeImage = node("img"); preview.append(previewHeading, largeImage);
      const confirmation = node("dialog", "", "modal"); confirmation.setAttribute("aria-label", "确认删除示意图");
      const confirmationTitle = node("h2", "确认删除示意图"), confirmationText = node("p", "", "composition-hint");
      const confirmationActions = node("div", "", "modal__actions");
      const cancelDelete = node("button", "取消", "button button--quiet"), confirmDelete = node("button", "确认删除", "button button--danger");
      cancelDelete.type = confirmDelete.type = "button";
      confirmationActions.append(cancelDelete, confirmDelete); confirmation.append(confirmationTitle, confirmationText, confirmationActions);
      document.body.append(dialog, preview, confirmation);
      let resolveConfirmation = null;
      cancelDelete.addEventListener("click", () => confirmation.close("cancel"));
      confirmDelete.addEventListener("click", () => confirmation.close("delete"));
      confirmation.addEventListener("close", () => {
        resolveConfirmation?.(confirmation.returnValue === "delete"); resolveConfirmation = null;
      });
      function askDelete(image) {
        confirmationText.textContent = `确定删除“${image.name}”吗？此操作无法撤销。`;
        confirmation.returnValue = "";
        return new Promise(resolve => { resolveConfirmation = resolve; confirmation.showModal(); cancelDelete.focus(); });
      }
      let context, images = [], busy = false;
      const url = () => `/api/projects/${encodeURIComponent(context.project.id)}/composition-images`;
      function setBusy(value) {
        busy = value; close.disabled = refresh.disabled = search.disabled = value;
        dialog.setAttribute("aria-busy", String(value));
        grid.querySelectorAll("button").forEach(button => { button.disabled = value || button.dataset.blocked === "true"; });
      }
      function message(text, error = false) { status.textContent = text; status.classList.toggle("is-error", error); }
      function render() {
        grid.replaceChildren();
        const visible = images.filter(image => image.name.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase()));
        message(`共 ${images.length} 张示意图${visible.length !== images.length ? `，显示 ${visible.length} 张` : ""}`);
        if (!visible.length) grid.append(node("p", images.length ? "没有匹配的示意图" : "尚未导入示意图，可返回拼图编辑器点击“导入示意图”或“粘贴子图”。", "composition-hint"));
        for (const image of visible) {
          const card = node("article", "", "asset-card");
          const view = node("button", "", "asset-card__view"); view.type = "button"; view.setAttribute("aria-label", `查看示意图“${image.name}”`);
          const thumbnail = node("img"); thumbnail.src = `${url()}/${encodeURIComponent(image.id)}`; thumbnail.alt = image.name; thumbnail.loading = "lazy";
          view.append(thumbnail);
          view.addEventListener("click", () => {
            previewTitle.textContent = image.name; largeImage.src = thumbnail.src; largeImage.alt = image.name; preview.showModal();
          });
          const name = node("strong", image.name);
          const format = (image.format || "png").toUpperCase();
          const details = node("p", ["svg", "pdf"].includes(image.format)
            ? `${format} · 宽高比 ${(image.width / image.height).toFixed(2)}:1`
            : `${format} · ${image.width} × ${image.height} 像素`, "composition-hint");
          const inDraft = context.isInDraft(image.id), usages = image.used_by || [];
          const usage = node("p", [usages.length ? `用于：${usages.map(item => item.name).join("、")}` : "未被已保存的拼图使用",
            inDraft ? "当前排版正在使用" : ""].filter(Boolean).join("；"), "asset-card__usage");
          const remove = node("button", "删除", "button button--quiet asset-card__delete"); remove.type = "button";
          remove.setAttribute("aria-label", `删除示意图“${image.name}”`);
          remove.dataset.blocked = String(inDraft || usages.length > 0); remove.disabled = remove.dataset.blocked === "true";
          remove.title = remove.disabled ? "请先移除使用此素材的子图并保存拼图" : "删除此项目中的示意图素材";
          remove.addEventListener("click", async () => {
            if (busy || !(await askDelete(image))) return;
            if (context.isInDraft(image.id)) { message("当前排版正在使用这张示意图，请先移除对应子图。", true); return; }
            setBusy(true);
            try {
              await context.request(`${url()}/${encodeURIComponent(image.id)}`, { method: "DELETE" });
              images = images.filter(item => item.id !== image.id); context.afterDelete(image.id); render(); message(`已删除 ${image.name}`);
            } catch (error) {
              const reason = error.message || "删除失败";
              try { images = (await context.request(`${url()}/library`)).images; render(); } catch { /* Retain the last available list. */ }
              message(reason, true);
            } finally { setBusy(false); }
          });
          card.append(view, name, details, usage, remove); grid.append(card);
        }
      }
      async function reload() {
        if (busy) return; setBusy(true); message("正在载入示意图…");
        try { images = (await context.request(`${url()}/library`)).images; render(); }
        catch (error) { message(error.message || "载入失败，请刷新重试", true); }
        finally { setBusy(false); }
      }
      close.addEventListener("click", () => { if (!busy) dialog.close(); });
      dialog.addEventListener("cancel", event => { if (busy) event.preventDefault(); });
      previewClose.addEventListener("click", () => preview.close());
      preview.addEventListener("close", () => largeImage.removeAttribute("src"));
      dialog.addEventListener("close", () => { preview.close(); confirmation.close("cancel"); grid.replaceChildren(); images = []; });
      search.addEventListener("input", render); refresh.addEventListener("click", reload);
      return { async open(options) { context = options; search.value = ""; dialog.showModal(); await reload(); } };
    },
  };
})();
