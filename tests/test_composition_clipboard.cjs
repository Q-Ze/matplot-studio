const { test } = require("node:test");
const assert = require("node:assert/strict");
const { pastedImage, readImage, writeImage, writeSupportMessage } = require("../web/composition-clipboard.js");

global.FileReader = class {
  readAsDataURL(blob) {
    blob.arrayBuffer().then(buffer => {
      this.result = `data:${blob.type};base64,${Buffer.from(buffer).toString("base64")}`;
      this.onload();
    }, error => { this.error = error; this.onerror(); });
  }
};
class Item {
  constructor(representations) { this.representations = representations; }
  static supports() { return true; }
}
const png = new Blob(["test png bytes"], { type: "image/png" });
const size = { width_mm: 180, height_mm: 120 };

test("paste accepts image files and leaves text, HTML and remote URLs alone", () => {
  const file = new Blob(["image"], { type: "image/png" });
  const data = { items: [{ kind: "string", type: "text/html" }, { kind: "file", type: "image/png", getAsFile: () => file }],
    getData() { throw Error("HTML and text must not be inspected"); } };
  assert.equal(pastedImage(data), file);
  assert.equal(pastedImage({ items: [{ kind: "string", type: "text/html" }] }), null);
  assert.equal(pastedImage({ files: [new Blob(["https://example.com"], { type: "text/plain" })] }), null);
  assert.equal(pastedImage({ files: [file] }), file);
});

test("clipboard read selects an image representation without requesting HTML", async () => {
  const requested = [];
  const clipboard = { read: async () => [{ types: ["text/html", "image/png"], getType: async type => { requested.push(type); return png; } }] };
  assert.equal(await readImage(clipboard), png);
  assert.deepEqual(requested, ["image/png"]);
});

test("empty, unsupported and denied reads explain the keyboard-paste fallback", async () => {
  await assert.rejects(readImage({ read: async () => [] }), /没有可导入的图片/);
  await assert.rejects(readImage({}), /Ctrl\/⌘ \+ V/);
  await assert.rejects(readImage({ read: async () => { throw { name: "NotAllowedError" }; } }), /Ctrl\/⌘ \+ V/);
});

test("write starts during the click, before the PNG has finished rendering", async () => {
  let resolvePng, captured;
  const pending = new Promise(resolve => { resolvePng = resolve; });
  const clipboard = { write: items => { captured = items[0].representations; return Promise.resolve(); } };
  const copying = writeImage(pending, size, clipboard, Item);
  assert.ok(captured, "Must call clipboard.write synchronously to retain user activation");
  resolvePng(png);
  await copying;
  assert.equal(await captured["image/png"], png);
  const html = await (await captured["text/html"]).text();
  assert.match(html, /width:510\.2362pt;height:340\.1575pt/);
  assert.match(html, /width="680" height="454"/);
  assert.match(html, /data:image\/png;base64,/);
});

test("PNG-only clipboard implementations still work", async () => {
  class PngOnly extends Item { static supports(type) { return type === "image/png"; } }
  let captured;
  await writeImage(png, size, { write: async items => { captured = items[0].representations; } }, PngOnly);
  assert.deepEqual(Object.keys(captured), ["image/png"]);
  assert.match(writeSupportMessage({}, PngOnly), /PNG/);
});

test("permission failures wait for pending rendering and report a useful error", async () => {
  let finish;
  const pending = new Promise(resolve => { finish = resolve; });
  const copying = writeImage(pending, size, { write: () => Promise.reject({ name: "NotAllowedError" }) }, Item);
  const assertion = assert.rejects(copying, /未允许写入剪贴板/);
  finish(png);
  await assertion;
});

test("render failures are surfaced even when clipboard.write rejects first", async () => {
  const failed = Promise.reject(new Error("子图渲染失败"));
  await assert.rejects(writeImage(failed, size, { write: () => Promise.reject({ name: "NotAllowedError" }) }, Item), /子图渲染失败/);
  await assert.rejects(writeImage(new Blob([]), size, { write: async () => {} }, Item), /有效的 PNG/);
});
