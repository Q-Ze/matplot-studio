/* Clipboard images only: pasted text and HTML are never fetched or executed. */
((root) => {
  "use strict";
  const imageTypes = ["image/png", "image/jpeg", "image/webp", "image/tiff"];
  function pastedImage(data) {
    if (!data) return null;
    for (const item of Array.from(data.items || [])) {
      if (item.kind === "file" && imageTypes.includes(item.type)) {
        const image = item.getAsFile();
        if (image) return image;
      }
    }
    return Array.from(data.files || []).find((file) => imageTypes.includes(file.type)) || null;
  }
  function writeSupportMessage(clipboard = root.navigator?.clipboard, Item = root.ClipboardItem) {
    return !clipboard?.write || typeof Item !== "function"
      ? "当前浏览器不支持复制图片，请使用 PNG 按钮下载；或通过 localhost / HTTPS 打开后重试。" : "";
  }
  async function readImage(clipboard = root.navigator?.clipboard) {
    if (!clipboard?.read) throw new Error("当前浏览器不支持按钮读取剪贴板，请点击拼图画布后按 Ctrl/⌘ + V 粘贴图片。");
    let items;
    try {
      items = await clipboard.read();
      for (const item of items) {
        const type = imageTypes.find((type) => item.types.includes(type));
        if (type) return await item.getType(type);
      }
    } catch (error) {
      if (error.name === "NotAllowedError" || error.name === "SecurityError") {
        throw new Error("浏览器未允许读取剪贴板。请允许访问，或点击拼图画布后按 Ctrl/⌘ + V 粘贴图片。");
      }
      throw error;
    }
    throw new Error("剪贴板里没有可导入的图片。请先复制图片或截图，再粘贴子图。");
  }
  function dataUrl(blob) {
    return new Promise((resolve, reject) => {
      const reader = new root.FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error || new Error("无法读取拼图图片"));
      reader.readAsDataURL(blob);
    });
  }
  async function clipboardHtml(pngPromise, { width_mm, height_mm }) {
    const src = await dataUrl(await pngPromise);
    const width = Math.max(1, Math.round(width_mm / 25.4 * 96));
    const height = Math.max(1, Math.round(height_mm / 25.4 * 96));
    const style = `width:${(width_mm / 25.4 * 72).toFixed(4)}pt;height:${(height_mm / 25.4 * 72).toFixed(4)}pt;max-width:none;max-height:none`;
    return new Blob([`<!doctype html><html><body><!--StartFragment--><img src="${src}" alt="" width="${width}" height="${height}" style="${style}"><!--EndFragment--></body></html>`], { type: "text/html" });
  }
  function writeImage(pngPromise, size, clipboard = root.navigator?.clipboard, Item = root.ClipboardItem) {
    const message = writeSupportMessage(clipboard, Item);
    if (message) throw new Error(message);
    const png = Promise.resolve(pngPromise).then((blob) => {
      if (!blob?.size || blob.type !== "image/png") throw new Error("无法复制：未生成有效的 PNG 图片");
      return blob;
    });
    const representations = { "image/png": png }, pending = [png];
    if (typeof Item.supports !== "function" || Item.supports("text/html")) {
      const html = clipboardHtml(png, size);
      representations["text/html"] = html; pending.push(html);
    }
    let writing;
    try {
      // Call write inside the original user gesture; blobs may arrive after rendering.
      writing = clipboard.write([new Item(representations)]);
    } catch (error) { writing = Promise.reject(error); }
    // A denied write must not leave background save/render promises unobserved.
    return Promise.allSettled([writing, ...pending]).then((results) => {
      const failedContent = results.slice(1).find((result) => result.status === "rejected");
      if (failedContent) throw failedContent.reason;
      if (results[0].status === "rejected") {
        const error = results[0].reason;
        if (error?.name === "NotAllowedError" || error?.name === "SecurityError") {
          throw new Error("浏览器未允许写入剪贴板，请允许访问后重试，或使用 PNG 按钮下载。");
        }
        throw new Error("复制拼图失败，请重试或使用 PNG 按钮下载。");
      }
    });
  }
  const api = { pastedImage, readImage, writeSupportMessage, writeImage, clipboardHtml };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CompositionClipboard = api;
})(typeof window !== "undefined" ? window : globalThis);
