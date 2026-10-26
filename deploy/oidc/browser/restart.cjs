/* Disposable local qualification only. Compare state without exporting secrets. */
const { chromium } = require('@playwright/test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const root = path.resolve(__dirname, '../../..');
const runtime = process.env.LS_QUALIFICATION_RUNTIME || 'compose';
const rollbackImage = process.env.LS_QUALIFICATION_ROLLBACK_IMAGE;
assert(['compose', 'kubernetes'].includes(runtime));
assert(!rollbackImage || runtime === 'kubernetes');
const origin = 'https://labels.localhost:8443';
const credentials = JSON.parse(fs.readFileSync(path.join(root, 'deploy/oidc/.local/credentials.json')));
const compose = ['docker', 'compose', '-f', 'deploy/oidc/compose.yml'];
const kube = ['kubectl', '--kubeconfig', 'deploy/oidc/.local/kubeconfig'];
const run = args => execFileSync(args[0], args.slice(1), { cwd: root, encoding: 'utf8', timeout: 180000, stdio: ['ignore', 'pipe', 'pipe'] }).trim();
const management = runtime === 'compose' ? [...compose, 'exec', '-T', 'web'] : [...kube, 'exec', '-n', 'labeling', 'deployment/label-studio', '--'];
const snapshotCode = `import hashlib,json
from pathlib import Path
from django.conf import settings
from verdant_ls.models import ExternalIdentity
from tasks.models import Annotation,Task
from organizations.models import OrganizationMember
data={'bindings':list(ExternalIdentity.objects.order_by('pk').values('issuer','subject','user_id','session_generation')),
'annotations':list(Annotation.objects.order_by('pk').values('id','task_id','completed_by_id','updated_by_id','result')),
'tasks':list(Task.objects.order_by('pk').values('id','project_id','data')),
'memberships':list(OrganizationMember.objects.order_by('pk').values('id','user_id','organization_id','deleted_at')),
'media':{str(p.relative_to(settings.BASE_DATA_DIR)):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(settings.BASE_DATA_DIR).rglob('*') if p.is_file() and p.name!='.env'},
'secret_key_digest':hashlib.sha256(settings.SECRET_KEY.encode()).hexdigest()}
print(json.dumps({'state_sha256':hashlib.sha256(json.dumps(data,sort_keys=True,default=str).encode()).hexdigest(),'native_user_ids':[b['user_id'] for b in data['bindings']],'annotations':len(data['annotations']),'tasks':len(data['tasks']),'media_files':len(data['media'])}))`;
const snapshot = () => JSON.parse(run([...management, 'python', '/label-studio/label_studio/manage.py', 'shell', '-c', snapshotCode]).split('\n').at(-1));
let phase = 'login';
(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.LS_BROWSER_CHANNEL ? { channel: process.env.LS_BROWSER_CHANNEL } : {}) });
  let originalImage;
  try {
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    const page = await context.newPage();
    await page.goto(origin + '/oidc/login/');
    await page.getByLabel('Username or email').fill('alice');
    await page.getByLabel('Password', { exact: true }).fill(credentials.alice);
    await page.getByRole('button', { name: 'Sign In', exact: true }).click();
    await page.waitForURL(origin + '/');
    const who = () => context.request.get(origin + '/api/current-user/whoami');
    const waitForWho = async () => {
      let response;
      for (let attempt = 0; attempt < 60; attempt++) {
        response = await who();
        if (response.status() === 200) return response;
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
      console.log('Restart: ' + phase + ' HTTP ' + response.status());
      assert.equal(response.status(), 200);
    };
    const user = await (await who()).json();
    const cookie = (await context.cookies(origin)).find(c => c.name === '__Host-ls_session').value;
    const before = snapshot();
    let oldPod;
    phase = 'persistent restart';
    if (runtime === 'kubernetes') {
      oldPod = JSON.parse(run([...kube, 'get', 'pods', '-n', 'labeling', '-l', 'app=label-studio', '-o', 'json'])).items[0].metadata.uid;
      if (rollbackImage) {
        originalImage = JSON.parse(run([...kube, 'get', 'deployment', 'label-studio', '-n', 'labeling', '-o', 'json'])).spec.template.spec.containers[0].image;
        run([...kube, 'set', 'image', 'deployment/label-studio', 'web=' + rollbackImage, '-n', 'labeling']);
      } else run([...kube, 'rollout', 'restart', 'deployment/label-studio', '-n', 'labeling']);
      run([...kube, 'rollout', 'status', 'deployment/label-studio', '-n', 'labeling', '--timeout=120s']);
      assert.notEqual(JSON.parse(run([...kube, 'get', 'pods', '-n', 'labeling', '-l', 'app=label-studio', '-o', 'json'])).items[0].metadata.uid, oldPod);
    } else {
      run([...compose, 'restart', 'database', 'web']);
    }
    const response = await waitForWho();
    assert.equal((await response.json()).id, user.id);
    assert.equal((await context.cookies(origin)).find(c => c.name === '__Host-ls_session').value, cookie);
    const after = snapshot();
    assert.deepEqual(after, before);
    if (rollbackImage) {
      phase = 'return from compatible rollback image';
      run([...kube, 'set', 'image', 'deployment/label-studio', 'web=' + originalImage, '-n', 'labeling']);
      run([...kube, 'rollout', 'status', 'deployment/label-studio', '-n', 'labeling', '--timeout=120s']);
      assert.equal((await (await waitForWho()).json()).id, user.id);
      assert.deepEqual(snapshot(), before);
      assert.equal((await context.cookies(origin)).find(c => c.name === '__Host-ls_session').value, cookie);
    }
    const evidence = { passed: true, runtime, ...after, active_session_and_cookie_preserved: true,
      native_identity_annotation_membership_media_and_secret_key_preserved: true,
      ...(rollbackImage ? { compatible_image_rollback_and_return: true, rollback_image: rollbackImage } : {}),
      ...(oldPod ? { pod_replaced: true } : { database_and_web_restarted: true }) };
    fs.writeFileSync(path.join(root, `deploy/oidc/evidence/${rollbackImage ? 'rollback' : 'restart'}-${runtime}.json`), JSON.stringify(evidence, null, 2) + '\n');
    console.log(JSON.stringify(evidence));
  } finally {
    if (originalImage) run([...kube, 'set', 'image', 'deployment/label-studio', 'web=' + originalImage, '-n', 'labeling']);
    await browser.close();
  }
})().catch(error => { console.error(`Restart qualification failed during ${phase}: ${error.name}`); process.exit(1); });
