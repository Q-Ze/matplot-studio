/* Keep display sorting independent of project manifests and panel references. */
((root) => {
  "use strict";
  const modes = ["original", "name-asc", "name-desc", "modified-desc", "modified-asc"];
  const collator = new Intl.Collator("zh-CN", { numeric: true, sensitivity: "base" });
  function sortPlots(plots, mode) {
    const result = [...plots];
    if (mode === "name-asc" || mode === "name-desc") {
      result.sort((a, b) => collator.compare(a.name, b.name) * (mode === "name-asc" ? 1 : -1));
    } else if (mode === "modified-asc" || mode === "modified-desc") {
      result.sort((a, b) => {
        const first = a.raw?.modified_at, second = b.raw?.modified_at;
        if (!Number.isFinite(first)) return Number.isFinite(second) ? 1 : 0;
        if (!Number.isFinite(second)) return -1;
        return (first - second) * (mode === "modified-asc" ? 1 : -1);
      });
    }
    return result;
  }
  const sorting = { modes, sortPlots };
  if (typeof module !== "undefined" && module.exports) module.exports = sorting;
  else root.ProjectSorting = sorting;
})(typeof window !== "undefined" ? window : globalThis);
