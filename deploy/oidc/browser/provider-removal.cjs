/* Test realm only: measure actual provider removal over the configured lease. */
const { chromium } = require('@playwright/test');
const assert = require('node:assert/strict');
const https = require('node:https');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../../..');
const origin = 'https://labels.localhost:8443';
const keycloak = 'https://keycloak.localhost:8443';
const credentials = JSON.parse(fs.readFileSync(path.join(root, 'deploy/oidc/.local/credentials.json')));
const ca = fs.readFileSync(path.join(root, 'deploy/oidc/.local/root.crt'));
let phase = 'login';
let lastAllowed = 0, deniedAt, lastStatus, maximumSampleGap = 0;
const adminPassword = fs.readFileSync(path.join(root, 'deploy/oidc/.local/keycloak.env'), 'utf8')
  .split('\n').find(line => line.startsWith('KC_BOOTSTRAP_ADMIN_PASSWORD=')).slice('KC_BOOTSTRAP_ADMIN_PASSWORD='.length);
function request(url, method = 'GET', body, token) {
  return new Promise((resolve, reject) => {
    const req = https.request(url, { method, ca, lookup(_host, options, callback) {
      callback(null, options.all ? [{ address: '127.0.0.1', family: 4 }] : '127.0.0.1', ...(options.all ? [] : [4]));
    }, headers: { ...(token ? { Authorization: 'Bearer ' + token } : {}), ...(body ? { 'Content-Type': 'application/x-www-form-urlencoded' } : {}) } }, res => {
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => {
        const text = Buffer.concat(chunks).toString();
        try { resolve({ status: res.statusCode, body: text ? JSON.parse(text) : null }); }
        catch (error) { reject(error); }
      });
    });
    req.on('error', reject);
    req.setTimeout(10000, () => req.destroy(new Error('Provider request timeout')));
    req.end(body);
  });
}
async function administrator() {
  const response = await request(keycloak + '/realms/master/protocol/openid-connect/token', 'POST', new URLSearchParams({
    client_id: 'admin-cli', grant_type: 'password', username: 'operator', password: adminPassword,
  }).toString());
  assert.equal(response.status, 200);
  return response.body.access_token;
}
(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.LS_BROWSER_CHANNEL ? { channel: process.env.LS_BROWSER_CHANNEL } : {}) });
  let user, group;
  try {
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    const page = await context.newPage();
    await page.goto(origin + '/oidc/login/');
    await page.getByLabel('Username or email').fill('bob');
    await page.getByLabel('Password', { exact: true }).fill(credentials.bob);
    await page.getByRole('button', { name: 'Sign In', exact: true }).click();
    await page.waitForURL(origin + '/');
    const native = await (await context.request.get(origin + '/api/current-user/whoami')).json();
    phase = 'remove test admission group';
    const token = await administrator();
    user = (await request(keycloak + '/admin/realms/labeling/users?username=bob&exact=true', 'GET', undefined, token)).body[0];
    group = (await request(keycloak + `/admin/realms/labeling/users/${user.id}/groups`, 'GET', undefined, token)).body.find(g => g.path === '/verdant/labeling/shared');
    assert(group);
    const removed = await request(keycloak + `/admin/realms/labeling/users/${user.id}/groups/${group.id}`, 'DELETE', undefined, token);
    assert.equal(removed.status, 204);
    const start = performance.now();
    let previousSample = 0;
    phase = 'poll authentication lease';
    while (true) {
      // Probe before checking the deadline: a suspended process must still
      // observe access after resuming instead of reporting a missing sample.
      const response = await context.request.get(origin + '/api/current-user/whoami');
      lastStatus = response.status();
      const elapsed = (performance.now() - start) / 1000;
      maximumSampleGap = Math.max(maximumSampleGap, elapsed - previousSample);
      previousSample = elapsed;
      if (response.status() === 401) { deniedAt = elapsed; break; }
      assert.equal(response.status(), 200);
      lastAllowed = elapsed;
      assert(elapsed < 320, 'Protected work remained allowed after the measurement deadline');
      await new Promise(resolve => setTimeout(resolve, 5000));
    }
    assert(deniedAt !== undefined);
    phase = 'renew with removed group';
    await page.goto(origin + '/oidc/login/');
    await page.waitForURL(origin + '/oidc/callback/**');
    assert.match(await page.locator('body').innerText(), /Sign-in could not be completed/);
    const evidence = { native_user_id: native.id, configured_lease_seconds: 300, polling_interval_seconds: 5,
      timing_clock: 'monotonic performance.now', maximum_observed_sample_gap_seconds: maximumSampleGap,
      last_protected_200_seconds_after_group_removal: lastAllowed,
      first_protected_401_seconds_after_group_removal: deniedAt,
      renewal_group_denial: true, provider_pushed_logout: false };
    fs.writeFileSync(path.join(root, 'deploy/oidc/evidence/provider-removal.json'), JSON.stringify(evidence, null, 2) + '\n');
    console.log(JSON.stringify(evidence));
  } finally {
    if (user && group) {
      const restored = await request(keycloak + `/admin/realms/labeling/users/${user.id}/groups/${group.id}`, 'PUT', undefined, await administrator());
      assert.equal(restored.status, 204);
    }
    await browser.close();
  }
})().catch(error => {
  console.error('Provider-removal qualification failed during ' + phase + ': ' + error.name);
  console.error(JSON.stringify({ last_protected_200_seconds: lastAllowed, first_401_seconds: deniedAt, last_status: lastStatus, maximum_observed_sample_gap_seconds: maximumSampleGap }));
  if (typeof error.actual === 'number' && typeof error.expected === 'number') console.error(`Expected status ${error.expected}; got ${error.actual}`);
  process.exit(1);
});
