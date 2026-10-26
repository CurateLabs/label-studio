/* Rotate signing keys in the disposable test realm, then remove the test key. */
const { chromium } = require('@playwright/test');
const assert = require('node:assert/strict');
const https = require('node:https');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../../..');
const origin = 'https://labels.localhost:8443';
const issuerOrigin = 'https://keycloak.localhost:8443';
const credentials = JSON.parse(fs.readFileSync(path.join(root, 'deploy/oidc/.local/credentials.json')));
const adminPassword = fs.readFileSync(path.join(root, 'deploy/oidc/.local/keycloak.env'), 'utf8')
  .split('\n').find(line => line.startsWith('KC_BOOTSTRAP_ADMIN_PASSWORD=')).slice('KC_BOOTSTRAP_ADMIN_PASSWORD='.length);
function request(route, method = 'GET', body, token, form = false) {
  return new Promise((resolve, reject) => {
    const req = https.request(issuerOrigin + route, { method, ca: fs.readFileSync(path.join(root, 'deploy/oidc/.local/root.crt')),
      lookup(_host, options, callback) { callback(null, options.all ? [{ address: '127.0.0.1', family: 4 }] : '127.0.0.1', ...(options.all ? [] : [4])); },
      headers: { ...(token ? { Authorization: 'Bearer ' + token } : {}), ...(body ? { 'Content-Type': form ? 'application/x-www-form-urlencoded' : 'application/json' } : {}) } }, res => {
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => {
        try { resolve({ status: res.statusCode, location: res.headers.location, body: chunks.length ? JSON.parse(Buffer.concat(chunks).toString()) : null }); }
        catch (error) { reject(error); }
      });
    });
    req.setTimeout(10000, () => req.destroy(new Error('Provider timeout')));
    req.on('error', reject);
    req.end(body);
  });
}
async function administrator() {
  const response = await request('/realms/master/protocol/openid-connect/token', 'POST', new URLSearchParams({
    client_id: 'admin-cli', grant_type: 'password', username: 'operator', password: adminPassword,
  }).toString(), undefined, true);
  assert.equal(response.status, 200);
  return response.body.access_token;
}
let phase = 'login';
(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.LS_BROWSER_CHANNEL ? { channel: process.env.LS_BROWSER_CHANNEL } : {}) });
  let component;
  try {
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    const page = await context.newPage();
    await page.goto(origin + '/oidc/login/');
    await page.getByLabel('Username or email').fill('alice');
    await page.getByLabel('Password', { exact: true }).fill(credentials.alice);
    await page.getByRole('button', { name: 'Sign In', exact: true }).click();
    await page.waitForURL(origin + '/');
    const who = () => context.request.get(origin + '/api/current-user/whoami');
    const user = await (await who()).json();
    phase = 'test realm key rotation';
    const token = await administrator();
    const previous = await request('/admin/realms/labeling/keys', 'GET', undefined, token);
    assert.equal(previous.status, 200);
    const realm = await request('/admin/realms/labeling', 'GET', undefined, token);
    assert.equal(realm.status, 200);
    const created = await request('/admin/realms/labeling/components', 'POST', JSON.stringify({
      name: 'qualification-rsa-' + Date.now(), parentId: realm.body.id, providerId: 'rsa-generated',
      providerType: 'org.keycloak.keys.KeyProvider',
      config: { priority: ['1000'], enabled: ['true'], active: ['true'], algorithm: ['RS256'], keySize: ['2048'] },
    }), token);
    assert.equal(created.status, 201);
    component = created.location.split('/').at(-1);
    const rotated = await request('/admin/realms/labeling/keys', 'GET', undefined, token);
    assert.notEqual(rotated.body.active.RS256, previous.body.active.RS256);
    phase = 'renewal with rotated provider key';
    await page.goto(origin + '/oidc/login/');
    await page.waitForURL(origin + '/');
    assert.equal((await (await who()).json()).id, user.id);
    const evidence = { passed: true, runtime: process.env.LS_QUALIFICATION_RUNTIME || 'compose', native_user_id: user.id,
      provider_active_rs256_key_changed: true, real_signed_callback_after_rotation: true, native_id_preserved: true,
      single_forced_jwks_refresh_proved_separately_in_protocol_tests: true };
    fs.writeFileSync(path.join(root, 'deploy/oidc/evidence/key-rotation.json'), JSON.stringify(evidence, null, 2) + '\n');
    console.log(JSON.stringify(evidence));
  } finally {
    if (component) assert.equal((await request('/admin/realms/labeling/components/' + component, 'DELETE', undefined, await administrator())).status, 204);
    await browser.close();
  }
})().catch(error => { console.error(`Key-rotation qualification failed during ${phase}: ${error.name}`); process.exit(1); });
