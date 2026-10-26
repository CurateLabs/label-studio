/* Disposable local realm only: stop/restart provider and preserve native identity. */
const { chromium } = require('@playwright/test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const root = path.resolve(__dirname, '../../..');
const origin = 'https://labels.localhost:8443';
const compose = ['compose', '-f', 'deploy/oidc/compose.yml'];
const credentials = JSON.parse(fs.readFileSync(path.join(root, 'deploy/oidc/.local/credentials.json')));
const run = args => execFileSync('docker', [...compose, ...args], { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
let phase = 'login';
(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.LS_BROWSER_CHANNEL ? { channel: process.env.LS_BROWSER_CHANNEL } : {}) });
  let stopped = false;
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
    phase = 'live provider outage';
    run(['stop', 'keycloak']); stopped = true;
    assert.equal((await who()).status(), 200);
    run(['exec', '-T', 'web', 'python', '/label-studio/label_studio/manage.py', 'shell', '-c',
      `import time\nfrom django.contrib.sessions.models import Session\nfor session in Session.objects.all():\n data=session.get_decoded()\n if data.get('bridge',{}).get('user')==${user.id}:\n  data['bridge']['lease']=time.time()-1\n  session.session_data=Session.get_session_store_class()().encode(data)\n  session.save(update_fields=['session_data'])`]);
    assert.equal((await who()).status(), 401);
    const start = await context.request.get(origin + '/oidc/login/', { maxRedirects: 0 });
    assert([302, 503].includes(start.status()));
    assert.equal((await who()).status(), 401);
    phase = 'persistent provider restart';
    run(['start', 'keycloak']); stopped = false;
    let ready = false;
    for (let attempt = 0; attempt < 30; attempt++) {
      const response = await context.request.get('https://keycloak.localhost:8443/realms/labeling/.well-known/openid-configuration');
      if (response.status() === 200) { ready = true; break; }
      await delay(1000);
    }
    assert(ready);
    await page.goto(origin + '/oidc/login/');
    await page.waitForURL(origin + '/');
    assert.equal((await (await who()).json()).id, user.id);
    const evidence = { passed: true, runtime: process.env.LS_QUALIFICATION_RUNTIME || 'compose', native_user_id: user.id,
      valid_lease_works_without_provider: true, expired_lease_401_during_outage: true,
      renewal_did_not_extend_access_during_outage: true, provider_restart_retained_sso: true, native_id_preserved: true };
    fs.writeFileSync(path.join(root, 'deploy/oidc/evidence/provider-outage.json'), JSON.stringify(evidence, null, 2) + '\n');
    console.log(JSON.stringify(evidence));
  } finally {
    if (stopped) run(['start', 'keycloak']);
    await browser.close();
  }
})().catch(error => { console.error(`Provider outage qualification failed during ${phase}: ${error.name}`); process.exit(1); });
