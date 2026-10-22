/* Download selected editable plots as a re-importable project ZIP. */
(() => {
  "use strict";
  window.ProjectExporter = {
    create({ beforeExport, setBusy, download }) {
      const dialog = document.createElement("dialog");
      dialog.className = "modal modal--project-export";
      dialog.setAttribute("aria-labelledby", "projectExportTitle");
      dialog.innerHTML = `
        <div class="modal__heading"><h2 id="projectExportTitle">导出项目</h2>
          <button type="button" class="icon-button" data-action="close" aria-label="关闭项目导出">×</button></div>
        <label class="form-field"><span>选择项目</span><select id="exportProjectSelect"></select></label>
        <p class="import-intro">选择要打包的图表。ZIP 包含所选图表的代码、参数、附属文件和项目公共文件，可通过“导入项目”继续编辑。不包含未选图表、拼图布局及示意图素材库。</p>
        <div class="project-export-actions"><button type="button" class="button button--quiet" data-action="all">全选</button>
          <button type="button" class="button button--quiet" data-action="none">清空选择</button><span id="exportProjectCount"></span></div>
        <div class="project-export-plots" id="exportProjectPlots" role="group" aria-label="选择要导出的图表"></div>
        <p class="import-feedback" id="exportProjectStatus" role="status" aria-live="polite" hidden></p>
        <div class="modal__actions"><button type="button" class="button button--quiet" data-action="close">取消</button>
          <button type="button" class="button button--primary" data-action="export">导出 ZIP</button></div>`;
      document.body.append(dialog);
      const $ = selector => dialog.querySelector(selector);
      let projects = [], project, busy = false;
      const selected = () => [...dialog.querySelectorAll('[data-plot-id]:checked')].map(input => input.dataset.plotId);
      const report = (message, tone = "neutral") => {
        $("#exportProjectStatus").textContent = message;
        $("#exportProjectStatus").dataset.tone = tone;
        $("#exportProjectStatus").hidden = !message;
      };
      function update() {
        const count = selected().length;
        $("#exportProjectCount").textContent = `已选择 ${count} / ${project?.plots.length || 0} 张`;
        $('[data-action="export"]').disabled = busy || !count;
      }
      function render() {
        project = projects.find(item => item.id === $("#exportProjectSelect").value);
        const list = $("#exportProjectPlots"); list.replaceChildren();
        for (const plot of project?.plots || []) {
          const label = document.createElement("label");
          const input = document.createElement("input"); input.type = "checkbox";
          input.dataset.plotId = plot.id; input.checked = true;
          const name = document.createElement("span"); name.textContent = plot.name;
          label.append(input, name); list.append(label);
        }
        if (!project?.plots.length) list.textContent = "此项目暂无图表。";
        report(""); update();
      }
      $("#exportProjectSelect").addEventListener("change", render);
      $("#exportProjectPlots").addEventListener("change", () => { report(""); update(); });
      dialog.addEventListener("cancel", event => { if (busy) event.preventDefault(); });
      dialog.addEventListener("click", async event => {
        const action = event.target.closest("[data-action]")?.dataset.action;
        if (!action || busy) return;
        if (action === "close") { dialog.close(); return; }
        if (action === "all" || action === "none") {
          dialog.querySelectorAll("[data-plot-id]").forEach(input => { input.checked = action === "all"; });
          report(""); update(); return;
        }
        if (action !== "export" || !selected().length) return;
        const ids = selected(), exportingProject = project;
        busy = true; setBusy(true);
        dialog.querySelectorAll("button, input, select").forEach(control => { control.disabled = true; });
        dialog.setAttribute("aria-busy", "true");
        try {
          await beforeExport(exportingProject, ids, report);
          report("正在打包所选图表…");
          const response = await fetch(`/api/projects/${encodeURIComponent(exportingProject.id)}/export`, {
            method: "POST", headers: {"Content-Type":"application/json"},
            body: JSON.stringify({plots:ids}), credentials: "same-origin",
          });
          if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.error?.message || error.detail?.map?.(item => item.msg).join("；") || `导出失败（${response.status}）`);
          }
          const filename = `${exportingProject.name}-所选${ids.length}图.zip`.replace(/[\\/:*?"<>|\u0000-\u001f\u007f]/g, "_");
          download(await response.blob(), filename);
          report(`已生成 ZIP，包含 ${ids.length} 张图表。可在另一台机器通过“导入项目”打开。`, "success");
        } catch (error) {
          report(error.message || "导出失败，请重试", "error");
        } finally {
          busy = false; setBusy(false); dialog.removeAttribute("aria-busy");
          dialog.querySelectorAll("button, input, select").forEach(control => { control.disabled = false; });
          update();
        }
      });
      return {
        open(items, preferredId) {
          projects = items;
          const select = $("#exportProjectSelect"); select.replaceChildren();
          for (const item of projects) {
            const option = document.createElement("option"); option.value = item.id; option.textContent = item.name;
            select.append(option);
          }
          select.value = projects.some(item => item.id === preferredId) ? preferredId : projects[0]?.id || "";
          render(); dialog.showModal();
        },
      };
    },
  };
})();
