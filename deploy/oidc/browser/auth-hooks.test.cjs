const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function harness() {
  const listeners = {}, alerts = [], requests = [];
  const originalFetch = async (...args) => { requests.push(args); return { ok: true }; };
  const originalOpen = () => {};
  const document = { cookie: '__Host-ls_csrf=first', body: { append(node) { alerts.push(node); } },
    createElement() { return { style: {}, setAttribute() {}, append() {}, remove() { alerts.pop(); } }; } };
  const window = { fetch: originalFetch, addEventListener(name, callback) { listeners[name] = callback; } };
  const context = { window, document, URL, fetch: originalFetch, location: { href: 'https://labels.test/projects/1/data', origin: 'https://labels.test' },
    XMLHttpRequest: { prototype: { open: originalOpen } } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../../label_studio/verdant_ls/static/verdant_ls/csrf.js'), 'utf8'), context);
  return { context, listeners, alerts, requests, originalFetch, originalOpen, hooks: window.LSBridgeAuth };
}

test('CSRF follows cookie rotation and never crosses origins', () => {
  const { context, hooks } = harness();
  const first = new Headers();
  hooks.prepareRequest(first, 'PATCH', '/api/annotations/1/');
  assert.equal(first.get('X-CSRFToken'), 'first');
  context.document.cookie = '__Host-ls_csrf=rotated';
  const second = new Headers();
  hooks.prepareRequest(second, 'POST', '/api/tasks/');
  assert.equal(second.get('X-CSRFToken'), 'rotated');
  const external = new Headers();
  hooks.prepareRequest(external, 'POST', 'https://other.test/api/');
  assert.equal(external.has('X-CSRFToken'), false);
});

test('expiry offers one accessible action and never replays a mutation', async () => {
  const { hooks, alerts, listeners, requests } = harness();
  assert.equal(hooks.expired(), true);
  hooks.expired();
  assert.equal(alerts.length, 1);
  assert.equal(requests.length, 0);
  await listeners.focus();
  assert.equal(alerts.length, 0);
  assert.equal(requests.length, 1);
  assert.equal(requests[0][0], '/api/current-user/whoami');
});

test('native transport globals and prototypes remain intact', () => {
  const { context, originalFetch, originalOpen } = harness();
  assert.equal(context.window.fetch, originalFetch);
  assert.equal(context.XMLHttpRequest.prototype.open, originalOpen);
});
