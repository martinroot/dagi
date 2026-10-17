import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

function fakeElement() {
  return {
    children: [], textContent: "", disabled: false, value: "", hidden: false,
    scrollTop: 0, scrollHeight: 0, className: "",
    classList: {toggle() {}},
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    querySelector() { return {disabled: false}; },
  };
}

test("adjacent streamed text chunks render as one assistant message", () => {
  const elements = new Map();
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, fakeElement());
      return elements.get(id);
    },
    createElement() { return fakeElement(); },
  };
  const context = {
    document,
    fetch: async () => ({status: 401, ok: false, text: async () => '{"error":"authentication required"}'}),
    EventSource: class { close() {} },
  };
  vm.runInNewContext(fs.readFileSync(new URL("../dagi_core/static/app.js", import.meta.url), "utf8"), context);

  context.addEvent({kind: "text", text: "пон"});
  context.addEvent({kind: "text", text: "г"});

  const chat = elements.get("chat");
  assert.equal(chat.children.length, 1, "one provider text turn should create one assistant bubble");
  assert.equal(chat.children[0].children[1].textContent, "понг");
});
