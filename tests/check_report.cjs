// Pure JavaScript logic validation. No browser, network, or UI automation.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert').strict;
const html = fs.readFileSync(process.argv[2], 'utf8');
const payload = html.match(/<script id="data" type="application\/json">([\s\S]*?)<\/script>/)[1];
const source = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
const elements = new Map();
let drawCalls = 0, downloads = 0;
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    textContent: id === 'data' ? payload : '', value: id === 'signal' ? 'corrected' : '',
    hidden: false, disabled: false, events: {},
    addEventListener(name, callback) { this.events[name] = callback; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 620, height: 600 }; },
    getContext() { return new Proxy({}, { get(target, key) {
      if (key in target) return target[key];
      return (...args) => { for (const arg of args) if (typeof arg === 'number') assert(Number.isFinite(arg)); drawCalls++; };
    }}); }
  });
  return elements.get(id);
}
const sandbox = {
  document: { getElementById: element, createElement() { return { click() { downloads++; } }; } },
  Blob: class Blob { constructor(parts, options) { this.parts = parts; this.options = options; } },
  URL: { createObjectURL() { return 'blob:test'; }, revokeObjectURL() {} },
  setTimeout(callback) { callback(); }
};
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { timeout: 10000 });
const data = JSON.parse(payload);
assert.equal(element('count').textContent, data.summary.saved_points.toLocaleString());
assert.equal(element('notice').hidden, data.summary.mode !== 'simulation' && data.summary.mode !== 'imported');
assert(drawCalls > 0);
if (data.points.length) {
  assert.match(element('detail').textContent, /Point/);
  assert.equal(element('download').disabled, false);
  element('signal').value = 'raw';
  element('signal').events.change();
  element('download').events.click();
  assert.equal(downloads, 1);
  element('map').events.click({ clientX: 310, clientY: 300 });
}
console.log(JSON.stringify({ report: process.argv[2], recorded_points: data.points.length, previews: data.summary.preview_spectra, draw_calls: drawCalls, downloads, result: 'passed' }));
