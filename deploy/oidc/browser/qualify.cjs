/* Real Keycloak, stock UI, native APIs. No traces or state files containing credentials. */
const { chromium } = require('@playwright/test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const root = path.resolve(__dirname, '../../..');
const credentials = JSON.parse(fs.readFileSync(path.join(root, 'deploy/oidc/.local/credentials.json')));
const origin = 'https://labels.localhost:8443';
const fixture = name => fs.readFileSync(path.join(root, 'fixtures/oidc', name), 'utf8');
let phase = 'initialization';
function operator(code) {
  return execFileSync('docker', ['compose', '-f', 'deploy/oidc/compose.yml', 'exec', '-T', 'web',
    'python', '/label-studio/label_studio/manage.py', 'shell', '-c', code], { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
}
function privateJSON(code) {
  return JSON.parse(operator(code).trim().split('\n').at(-1));
}

async function api(page, url, method = 'GET', body) {
  return page.evaluate(async ({ url, method, body }) => {
    const csrf = document.cookie.split('; ').find(value => value.startsWith('__Host-ls_csrf='))?.split('=')[1];
    const response = await fetch(url, { method, headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRFToken': csrf } : {}) }, body: body === undefined ? undefined : JSON.stringify(body) });
    const text = await response.text();
    try { return { status: response.status, body: JSON.parse(text) }; }
    catch { return { status: response.status, html: true }; }
  }, { url, method, body });
}

async function login(browser, name) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true }); // Local test CA only; provider I/O verifies TLS.
  const page = await context.newPage();
  await page.goto(origin + '/oidc/login/');
  await page.getByLabel('Username or email').fill(name);
  await page.getByLabel('Password', { exact: true }).fill(credentials[name]);
  await page.getByRole('button', { name: 'Sign In', exact: true }).click();
  await page.waitForURL(origin + '/**');
  return { context, page };
}

(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.LS_BROWSER_CHANNEL ? { channel: process.env.LS_BROWSER_CHANNEL } : {}) });
  try {
    phase = 'real Keycloak login';
    const alice = await login(browser, 'alice');
    const bob = await login(browser, 'bob');
    const denied = await login(browser, 'denied');
    assert.match(await denied.page.locator('body').innerText(), /Sign-in could not be completed/);
    assert.equal((await api(denied.page, '/api/projects/')).status, 401);
    const a = (await api(alice.page, '/api/current-user/whoami')).body;
    const b = (await api(bob.page, '/api/current-user/whoami')).body;
    assert.notEqual(a.id, b.id);
    const sessionCookie = (await alice.context.cookies(origin)).find(cookie => cookie.name === '__Host-ls_session');
    assert(sessionCookie.secure && sessionCookie.httpOnly);
    assert.equal(sessionCookie.sameSite, 'Lax');
    assert.equal(sessionCookie.domain, 'labels.localhost');
    assert.equal(sessionCookie.path, '/');
    const cookieRules = { secure: true, http_only: true, same_site: 'Lax', host_only: true, path: '/',
      observed_cookie_lifetime_seconds: Math.round(sessionCookie.expires - Date.now()/1000) };
    // Existing provider session completes a fresh code flow without password entry.
    await alice.page.goto(origin + '/oidc/login/');
    await alice.page.waitForURL(origin + '/');
    assert.equal((await api(alice.page, '/api/current-user/whoami')).body.id, a.id);
    phase = 'native annotation and export';
    const created = await api(alice.page, '/api/projects/', 'POST', { title: 'OIDC synthetic qualification', label_config: fixture('config.xml') });
    assert.equal(created.status, 201, JSON.stringify(created));
    const project = created.body.id;
    const tasks = [];
    for (const task of JSON.parse(fixture('tasks.json'))) {
      const response = await api(alice.page, '/api/tasks/', 'POST', { project, ...task });
      assert.equal(response.status, 201, JSON.stringify(response));
      tasks.push(response.body);
    }
    const result = JSON.parse(fixture('result.json'));
    const annotationIds = [];
    for (const [person, user] of [[alice, a], [bob, b]]) {
      for (const task of tasks) {
        const response = await api(person.page, `/api/tasks/${task.id}/annotations/`, 'POST', { result });
        assert.equal(response.status, 201, JSON.stringify(response));
        assert.equal(response.body.completed_by, user.id);
        annotationIds.push(response.body.id);
      }
    }
    const update = await api(bob.page, `/api/annotations/${annotationIds[0]}/`, 'PATCH', { result });
    assert.equal(update.status, 200);
    assert.equal(update.body.completed_by, a.id);
    assert.equal(update.body.updated_by, b.id);
    const exported = await api(alice.page, `/api/projects/${project}/export?exportType=JSON`);
    assert.equal(exported.status, 200, JSON.stringify(exported));
    assert.equal(exported.body.length, 2);
    assert.deepEqual(exported.body[0].annotations.map(x => x.completed_by).sort(), [a.id, b.id].sort());
    assert.deepEqual(exported.body[0].annotations[0].result, result);
    fs.writeFileSync(path.join(root, 'deploy/oidc/evidence/native-export.json'), JSON.stringify(exported.body, null, 2) + '\n');
    for (const [person, name, annotation] of [[alice, 'Alice Labeler', annotationIds[0]], [bob, 'Bob Labeler', annotationIds[2]]]) {
      phase = 'native editor update: ' + name;
      await person.page.goto(`${origin}/projects/${project}/data?task=${tasks[0].id}`);
      await person.page.waitForLoadState('networkidle');
      await person.page.getByText(name, { exact: true }).click();
      await person.page.waitForFunction(id => String(window.Htx?.annotationStore?.selected?.pk) === String(id) && window.Htx.annotationStore.selected.regionStore.regions.length >= 2, annotation);
      // Select a region through the stock editor's public action; type and submit through native controls.
      await person.page.evaluate(() => window.Htx.annotationStore.selected.selectArea(window.Htx.annotationStore.selected.regionStore.regions[0]));
      const input = person.page.locator('input[name="transcription"], input[data-testid="textarea-region-input"]').first();
      await input.fill(`UI correction — Café Ω (${name})`);
      await input.press('Enter');
      const [accepted] = await Promise.all([
        person.page.waitForResponse(r => new URL(r.url()).pathname.includes(`/annotations/${annotation}`) && r.request().method() === 'PATCH'),
        person.page.getByTestId('bottombar-update-button').click(),
      ]);
      assert.equal(accepted.status(), 200);
    }
    phase = 'native editor export round trip';
    const edited = await api(alice.page, `/api/projects/${project}/export?exportType=JSON`);
    assert.equal(edited.status, 200);
    const editedPage = edited.body.find(task => task.id === tasks[0].id);
    for (const annotation of editedPage.annotations) {
      assert(annotation.result.some(r => r.type === 'relation' && r.labels.includes('precedes')));
      assert(annotation.result.some(r => r.type === 'textarea' && r.value.text.some(text => text.includes('UI correction — Café Ω'))));
      for (const box of annotation.result.filter(r => r.type === 'rectanglelabels')) {
        assert.equal(box.original_width, 1200);
        assert.equal(box.original_height, 1600);
        assert(Math.abs(box.value.width - 40) < 0.0001);
      }
    }
    fs.writeFileSync(path.join(root, 'deploy/oidc/evidence/editor-export.json'), JSON.stringify(edited.body, null, 2) + '\n');
    // Fail an actual native draft save after server-side lease expiry. No synthetic API response.
    phase = 'draft expiry preparation';
    await alice.page.evaluate(() => window.Htx.annotationStore.selected.pauseAutosave());
    operator(`import time\nfrom django.contrib.sessions.models import Session\nfor session in Session.objects.all():\n data=session.get_decoded()\n if data.get('bridge',{}).get('user')==${a.id}:\n  data['bridge']['lease']=time.time()-1\n  session.session_data=Session.get_session_store_class()().encode(data)\n  session.save(update_fields=['session_data'])`);
    phase = 'draft edit after lease expiry';
    await alice.page.evaluate(() => window.Htx.annotationStore.selected.selectArea(window.Htx.annotationStore.selected.regionStore.regions[0]));
    const live = alice.page.locator('input[name="transcription"], input[data-testid="textarea-region-input"]').first();
    await live.fill('Retained draft after expiry — Ω');
    await live.press('Enter');
    phase = 'native draft rejection';
    await Promise.all([
      alice.page.waitForResponse(r => new URL(r.url()).pathname.includes('draft') && r.status() === 401),
      alice.page.evaluate(() => window.Htx.annotationStore.selected.saveDraftImmediatelyWithResults()).catch(() => null),
    ]);
    assert.match(await alice.page.locator('body').innerText(), /Sign-in expired/);
    const beforeRenewal = await alice.page.evaluate(() => window.Htx.annotationStore.selected.serializeAnnotation());
    phase = 'silent renewal in second tab';
    const renewal = await alice.context.newPage();
    await renewal.goto(origin + '/oidc/login/');
    await renewal.waitForURL(origin + '/');
    await alice.page.bringToFront();
    assert.deepEqual(await alice.page.evaluate(() => window.Htx.annotationStore.selected.serializeAnnotation()), beforeRenewal);
    phase = 'explicit native draft retry';
    await Promise.all([
      alice.page.waitForResponse(r => new URL(r.url()).pathname.includes('draft') && [200, 201].includes(r.status())),
      alice.page.evaluate(() => window.Htx.annotationStore.selected.saveDraftImmediatelyWithResults()),
    ]);
    await alice.page.screenshot({ path: path.join(root, 'deploy/oidc/evidence/editor.png'), fullPage: true });
    await renewal.close();

    phase = 'service access and import';
    operator("from django.core.management import call_command\nfrom verdant_ls.models import ServiceAccount\nif not ServiceAccount.objects.filter(user__email='adapter@example.test').exists(): call_command('bridge_operator','create-service',email='adapter@example.test',reason='browser-qualification')");
    const service = privateJSON("import json\nfrom verdant_ls.models import ServiceAccount\ns=ServiceAccount.objects.get(user__email='adapter@example.test')\nprint(json.dumps({'id':s.user_id,'token':s.user.get_token().key}))");
    const machine = await browser.newContext({ ignoreHTTPSErrors: true });
    const serviceHeaders = { Authorization: 'Token ' + service.token };
    assert.equal((await machine.request.get('https://machine.localhost:8443/api/projects/', { headers: serviceHeaders })).status(), 200);
    assert.equal((await machine.request.get('https://machine.localhost:8443/api/projects/')).status(), 401);
    assert.equal((await machine.request.get('https://machine.localhost:8443/')).status(), 403);
    assert.equal((await machine.request.get(origin + '/oidc/login/', { headers: serviceHeaders })).status(), 401);
    assert.equal((await alice.context.request.get(origin + '/api/current-user/whoami', { headers: serviceHeaders })).status(), 401);
    const imported = await machine.request.post(`https://machine.localhost:8443/api/projects/${project}/import?return_task_ids=true`, {
      headers: serviceHeaders, data: [{ ...JSON.parse(fixture('tasks.json'))[0], annotations: [{ result }] }],
    });
    assert.equal(imported.status(), 201);
    const importedId = (await imported.json()).task_ids[0];
    const importedTask = await machine.request.get(`https://machine.localhost:8443/api/tasks/${importedId}/`, { headers: serviceHeaders });
    const importedBody = await importedTask.json();
    const importedAuthor = importedBody.annotations[0].completed_by;
    assert.equal(typeof importedAuthor === 'object' ? importedAuthor.id : importedAuthor, service.id);
    fs.writeFileSync(path.join(root, 'deploy/oidc/evidence/service-import.json'), JSON.stringify({ authenticated_service_user: service.id, task: importedBody }, null, 2) + '\n');
    const uploaded = await machine.request.post(`https://machine.localhost:8443/api/projects/${project}/import?return_task_ids=true`, {
      headers: serviceHeaders, multipart: { file: { name: 'synthetic-page.png', mimeType: 'image/png', buffer: fs.readFileSync(path.join(root, 'fixtures/oidc/page-1.png')) } },
    });
    assert.equal(uploaded.status(), 201);
    await machine.close();
    phase = 'account and logout';
    const accountErrors = [];
    alice.page.on('pageerror', error => accountErrors.push(error.name));
    await alice.page.goto(origin + '/user/account/');
    await alice.page.getByLabel('Phone', { exact: true }).waitFor();
    assert.equal(await alice.page.locator('#access_token').count(), 0);
    assert.equal(await alice.page.locator('#personal-access-token').count(), 0);
    assert.equal(await alice.page.getByRole('link', { name: /^(Personal Access Token|Legacy Token|Access Token)$/ }).count(), 0);
    assert.deepEqual(accountErrors, []);
    await alice.page.getByLabel('Phone', { exact: true }).fill('5550100');
    const savedProfile = alice.page.waitForResponse(response => new URL(response.url()).pathname === `/api/users/${a.id}/` && response.request().method() === 'PATCH');
    await alice.page.getByRole('button', { name: 'Save', exact: true }).click();
    assert.equal((await savedProfile).status(), 200);
    assert.equal((await api(alice.page, '/api/current-user/whoami')).body.phone, '5550100');
    const avatarPath = `/api/users/${a.id}/avatar/`;
    const uploadedAvatar = alice.page.waitForResponse(response => new URL(response.url()).pathname === avatarPath && response.request().method() === 'POST');
    await alice.page.locator('input[name=avatar]').setInputFiles(path.join(root, 'fixtures/oidc/page-1.png'));
    assert.equal((await uploadedAvatar).status(), 200);
    const deletedAvatar = alice.page.waitForResponse(response => new URL(response.url()).pathname === avatarPath && response.request().method() === 'DELETE');
    await alice.page.getByRole('button', { name: 'Delete', exact: true }).click();
    assert.equal((await deletedAvatar).status(), 204);
    await alice.page.getByRole('button', { name: 'Delete', exact: true }).waitFor({ state: 'detached' });
    assert.deepEqual(accountErrors, []);
    const beforeLogout = (await alice.context.cookies()).find(x => x.name === '__Host-ls_session').value;
    await alice.page.goto(origin + '/logout');
    assert.equal((await api(alice.page, '/api/current-user/whoami')).status, 200);
    await alice.page.getByRole('button', { name: 'Sign out', exact: true }).click();
    assert.match(await alice.page.locator('body').innerText(), /You are signed out/);
    assert.equal((await api(alice.page, '/api/current-user/whoami')).status, 401);
    const cookies = await alice.context.cookies();
    assert(!cookies.some(x => x.name === '__Host-ls_session' && x.value === beforeLogout));
    const evidence = { passed: true, browser_version: browser.version(), runtime: process.env.LS_QUALIFICATION_RUNTIME || 'compose',
      users: { alice: a.id, bob: b.id }, project, tasks: tasks.map(t => t.id), annotations: annotationIds, cookie_rules: cookieRules,
      proof: ['real Keycloak login', 'existing SSO session', 'denied admission', 'distinct native authors', 'Unicode/boxes/classes/relations export', 'update actor', 'native editor edits by two users', '401 draft retained and manually retried after renewal', 'service-only API and import actor', 'persistent media upload', 'account token hidden', 'native profile and avatar changes with CSRF', 'local logout'] };
    fs.writeFileSync(path.join(root, `deploy/oidc/evidence/browser-${evidence.runtime}.json`), JSON.stringify(evidence, null, 2) + '\n');
    console.log(JSON.stringify(evidence));
  } finally { await browser.close(); }
})().catch(error => {
  // Browser exception messages may include callback URLs or input values.
  console.error(`Qualification failed during ${phase}: ${error.name}`);
  if (typeof error.actual === 'number' && typeof error.expected === 'number') console.error(`Expected status ${error.expected}; got ${error.actual}`);
  process.exit(1);
});
