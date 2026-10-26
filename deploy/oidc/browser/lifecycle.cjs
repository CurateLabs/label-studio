/* Local test realm only. Never prints credentials, callback URLs or response claims. */
const { chromium } = require('@playwright/test');
const assert = require('node:assert/strict');
const https = require('node:https');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const root = path.resolve(__dirname, '../../..');
const origin = 'https://labels.localhost:8443';
const credentials = JSON.parse(fs.readFileSync(path.join(root, 'deploy/oidc/.local/credentials.json')));
let phase = 'login';
function operator(code) {
  return execFileSync('docker', ['compose', '-f', 'deploy/oidc/compose.yml', 'exec', '-T', 'web', 'python',
    '/label-studio/label_studio/manage.py', 'shell', '-c', code], { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim().split('\n').at(-1);
}
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function slowUpload(context, project) {
  const boundary = 'qualification-boundary';
  const image = fs.readFileSync(path.join(root, 'fixtures/oidc/page-1.png'));
  const body = Buffer.concat([Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="slow-page.png"\r\nContent-Type: image/png\r\n\r\n`), image, Buffer.from(`\r\n--${boundary}--\r\n`)]);
  const cookies = await context.cookies(origin);
  const csrf = cookies.find(cookie => cookie.name === '__Host-ls_csrf').value;
  let completed = false;
  const result = new Promise((resolve, reject) => {
    const request = https.request({ hostname: '127.0.0.1', port: 8443, servername: 'labels.localhost', method: 'POST',
      path: `/api/projects/${project}/import?return_task_ids=true`, ca: fs.readFileSync(path.join(root, 'deploy/oidc/.local/root.crt')),
      headers: { Host: 'labels.localhost:8443', Origin: origin, Cookie: cookies.map(c => `${c.name}=${c.value}`).join('; '),
        'X-CSRFToken': csrf, 'Content-Type': `multipart/form-data; boundary=${boundary}`, 'Content-Length': body.length } }, response => {
      completed = true;
      response.resume();
      response.on('end', () => resolve(response.statusCode));
    });
    request.on('error', error => { if (!completed) reject(error); });
    (async () => {
      for (let offset = 0; offset < body.length && !completed; offset += 512) { request.write(body.subarray(offset, offset + 512)); await delay(120); }
      request.end();
    })().catch(reject);
  });
  return result;
}
(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.LS_BROWSER_CHANNEL ? { channel: process.env.LS_BROWSER_CHANNEL } : {}) });
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
    phase = 'slow upload across expiry';
    const projects = await (await context.request.get(origin + '/api/projects/')).json();
    const project = (projects.results || projects)[0].id;
    const count = operator('from data_import.models import FileUpload; print(FileUpload.objects.count())');
    operator(`import time\nfrom django.contrib.sessions.models import Session\nfor session in Session.objects.all():\n data=session.get_decoded()\n if data.get('bridge',{}).get('user')==${user.id}:\n  data['bridge']['lease']=time.time()+3\n  session.session_data=Session.get_session_store_class()().encode(data)\n  session.save(update_fields=['session_data'])`);
    const slowStatus = await slowUpload(context, project);
    assert.equal(slowStatus, 401);
    assert.equal(operator('from data_import.models import FileUpload; print(FileUpload.objects.count())'), count);
    await page.goto(origin + '/oidc/login/');
    await page.waitForURL(origin + '/');
    phase = 'human credential bypasses';
    const humanCredentials = JSON.parse(operator(`import json\nfrom users.models import User\nfrom jwt_auth.models import LSAPIToken\nfrom rest_framework_simplejwt.tokens import AccessToken\nu=User.objects.get(pk=${user.id})\nprint(json.dumps({'token':u.get_token().key,'jwt':str(AccessToken.for_user(u)),'pat':str(LSAPIToken.for_user(u))}))`));
    for (const headers of [{ Authorization: 'Token ' + humanCredentials.token }, { 'X-Api-Key': humanCredentials.token },
      { Authorization: 'Bearer ' + humanCredentials.jwt }, { Authorization: 'Bearer ' + humanCredentials.pat }]) {
      assert.equal((await context.request.get(origin + '/api/current-user/whoami', { headers })).status(), 401);
      assert.equal((await context.request.get('https://machine.localhost:8443/api/projects/', { headers })).status(), 401);
    }
    assert.equal((await context.request.post(origin + '/api/token/refresh/', { data: { refresh: humanCredentials.pat } })).status(), 403);
    assert.equal((await context.request.get(origin + '/api/current-user/whoami', { headers: { 'X-Forwarded-User': 'spoofed', 'X-Remote-User': 'spoofed' } })).status(), 200);
    phase = 'local revoke and enable';
    const stale = (await context.cookies(origin)).find(c => c.name === '__Host-ls_session').value;
    operator(`from django.core.management import call_command; call_command('bridge_operator','revoke',user_id=${user.id},reason='lifecycle-qualification')`);
    const revoked = Date.now();
    assert.equal((await who()).status(), 401);
    const revokeTo401 = Date.now() - revoked;
    operator(`from django.core.management import call_command; call_command('bridge_operator','enable',user_id=${user.id},reason='lifecycle-qualification')`);
    assert.equal((await context.request.get(origin + '/api/current-user/whoami', { headers: { Cookie: '__Host-ls_session=' + stale } })).status(), 401);
    await page.goto(origin + '/oidc/login/');
    await page.waitForURL(origin + '/');
    assert.equal((await (await who()).json()).id, user.id);
    phase = 'absolute deadline';
    operator(`import time\nfrom django.contrib.sessions.models import Session\nfor session in Session.objects.all():\n data=session.get_decoded()\n if data.get('bridge',{}).get('user')==${user.id}:\n  data['bridge']['absolute']=time.time()+2\n  session.session_data=Session.get_session_store_class()().encode(data)\n  session.save(update_fields=['session_data'])`);
    await delay(2500);
    assert.equal((await who()).status(), 401);
    await page.goto(origin + '/oidc/login/');
    await page.waitForURL(origin + '/');
    phase = 'RP-initiated logout';
    await page.goto(origin + '/logout');
    await page.getByRole('checkbox').check();
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await page.waitForURL(origin + '/oidc/logged-out/**');
    assert.match(await page.locator('body').innerText(), /You are signed out/);
    assert.equal((await who()).status(), 401);
    await page.goto(origin + '/oidc/login/');
    await page.getByLabel('Username or email').waitFor();
    const evidence = { passed: true, runtime: process.env.LS_QUALIFICATION_RUNTIME || 'compose', native_user_id: user.id,
      slow_upload_401_without_committed_file: true, revoke_command_completion_to_401_ms: revokeTo401,
      real_native_token_jwt_pat_and_refresh_denied: true, spoofed_identity_headers_ignored: true,
      reenabled_old_cookie_401: true, subject_native_id_preserved: true, accelerated_absolute_deadline_seconds: 2,
      rp_initiated_logout_cleared_provider_session: true };
    fs.writeFileSync(path.join(root, 'deploy/oidc/evidence/lifecycle.json'), JSON.stringify(evidence, null, 2) + '\n');
    console.log(JSON.stringify(evidence));
  } finally { await browser.close(); }
})().catch(error => { console.error(`Lifecycle qualification failed during ${phase}: ${error.name}`); process.exit(1); });
