"""Run against a local frontend; all API traffic is intercepted with synthetic fixtures.

    pip install playwright==1.49.0
    playwright install chromium
    UI_BASE_URL=http://127.0.0.1:5173 python tests/browser_smoke.py

Set UI_SCREENSHOTS to a directory to include the full responsive screenshot matrix.
"""
import json, os
from fixtures import fixtures as make_fixtures
from pathlib import Path
from urllib.parse import urlsplit, unquote
from playwright.sync_api import sync_playwright, expect

fixtures=make_fixtures()
BASE=os.getenv('UI_BASE_URL','http://127.0.0.1:5173').rstrip('/')
SCREENSHOTS=os.getenv('UI_SCREENSHOTS')
if SCREENSHOTS: Path(SCREENSHOTS).mkdir(parents=True, exist_ok=True)
job=fixtures['/api/jobs'][0]['name']
entry=fixtures['/api/catalog'][0]['name']
errors=[]; writes=[]; failures=[]
with sync_playwright() as pw:
    browser=pw.chromium.launch(args=['--no-sandbox'])
    context=browser.new_context(viewport={'width':1440,'height':1000}, reduced_motion='reduce')
    page=context.new_page()
    page.on('pageerror',lambda err:errors.append(str(err)))
    role=['admin']; offline=[False]; save_fails=[False]
    def route(req):
        path=unquote(urlsplit(req.request.url).path)
        if path=='/api/auth/me':
            if role[0] is None: return req.fulfill(status=401,json={'detail':'Sign in required'})
            body=dict(fixtures[path]);body['role']=role[0];body['must_change_password']=False
        elif path=='/api/auth/login':
            role[0]='admin'; body=dict(fixtures['/api/auth/me'])
        elif req.request.method!='GET':
            writes.append((req.request.method,path,req.request.post_data))
            if save_fails[0] and req.request.method=='PUT' and path=='/api/jobs/'+job:
                return req.fulfill(status=422,json={'detail':'Example save failure'})
            if path.endswith('/validate'):body={'ok':True,'warnings':[]}
            elif req.request.method in ['POST','PUT'] and path.startswith('/api/jobs'):
                body={'ok':True}
            else:body={}
        elif offline[0] and path=='/api/jobs':
            return req.fulfill(status=503,json={'detail':'API unavailable'})
        elif path in fixtures:body=fixtures[path]
        elif path.endswith('/tokens'):body=[]
        else:body=[]
        req.fulfill(json=body)
    page.route('**/api/**',route)
    def visit(path):
        page.goto(BASE+path,wait_until='domcontentloaded')
        try:
            page.locator('h1').wait_for()
        except Exception:
            print('Page failed:', path, 'errors:', errors, 'body:', page.locator('body').inner_text()[:1000], flush=True)
            raise
        page.wait_for_timeout(350)
    for theme in (['light','dark'] if SCREENSHOTS else []):
        page.add_init_script(f"localStorage.setItem('mars.theme','{theme}')")
        for width in [1440,768,390,320]:
            page.set_viewport_size({'width':width,'height':1000})
            for path,label in [('/jobs','jobs'),('/catalog','catalog'),('/jobs/'+job,'detail'),('/jobs/'+job+'/edit','editor'),('/catalog/'+entry+'/edit','catalog-editor'),('/settings/accounts','accounts'),('/settings/ai','ai'),('/settings/registry','registry'),('/settings/backup','backup'),('/settings/secrets','secrets'),('/settings/version','version'),('/pipeline','pipeline'),('/cluster','cluster'),('/activity','activity')]:
                visit(path)
                overflow=page.evaluate('document.documentElement.scrollWidth > innerWidth + 1')
                print(theme,width,path,'overflow' if overflow else 'ok',flush=True)
                if overflow:failures.append(f'Overflow {theme} {width} {path}')
                if width in [1440,390] and label in ['jobs','editor','accounts','catalog','ai','pipeline','cluster']:
                    page.screenshot(path=f'{SCREENSHOTS}/{label}-{theme}-{width}.png',full_page=True)
    page.set_viewport_size({'width':1440,'height':1000})
    for path in ['/settings/accounts','/settings/ai','/settings/registry','/settings/backup','/settings/secrets','/activity','/cluster']:
        visit(path)
    # Versions: an administrator sees the update banner and its steps.
    visit('/jobs')
    expect(page.get_by_text('Update available:')).to_be_visible()
    page.get_by_role('button',name='How to update').click()
    expect(page.get_by_text('deploy.sh console bbbbbbb')).to_be_visible()
    expect(page.get_by_text('Jobs keep running. Only the console restarts, for a few seconds.')).to_be_visible()
    visit('/settings/version')
    expect(page.get_by_role('heading',name='Version & updates')).to_be_visible()
    # The pipeline: jobs joined through a topic, with an outside producer declared.
    visit('/pipeline')
    expect(page.get_by_role('button',name='kafka topic example-events')).to_be_visible()
    expect(page.get_by_role('button',name='external event-collector')).to_be_visible()
    page.get_by_role('button',name='kafka topic example-events').click()
    expect(page.get_by_role('heading',name='example-events')).to_be_visible()
    expect(page.get_by_text('Outside Flink, writing it')).to_be_visible()
    page.get_by_label('Name',exact=True).fill('audit-service')
    page.get_by_label('Direction').select_option('consumes')
    page.get_by_role('button',name='Add',exact=True).click()
    expect(page.get_by_text('Not used by any job:')).to_be_visible()
    # Grab and pull: the view moves, and the drag does not select what it started on.
    viewport=page.get_by_role('group',name='Pipeline graph. Drag or use the arrow keys to move around; plus and minus zoom; 0 fits.')
    drawing=viewport.locator('svg > g').first
    before=drawing.get_attribute('transform')
    box=viewport.bounding_box()
    page.mouse.move(box['x']+12,box['y']+box['height']-12); page.mouse.down()
    page.mouse.move(box['x']+120,box['y']+box['height']-60,steps=5); page.mouse.up()
    assert drawing.get_attribute('transform')!=before, 'dragging did not move the pipeline'
    page.get_by_role('button',name='Zoom in').click()
    page.get_by_role('button',name='Fit').click()
    # Focus: only the flow through one topic, upstream and downstream.
    page.get_by_role('combobox',name='Focus on').select_option(label='example-events (kafka topic)')
    expect(page.get_by_role('button',name='job enrich_events')).to_be_visible()
    expect(page.get_by_role('button',name='job readings_to_output')).to_have_count(0)
    expect(page.get_by_text('Showing 2 of 3 jobs')).to_be_visible()
    assert 'focus=' in page.url, 'the focus is not kept in the address'
    page.get_by_role('button',name='Show everything').click()
    expect(page.get_by_role('button',name='job readings_to_output')).to_be_visible()
    page.get_by_role('combobox',name='Cluster').select_option('mars-b')
    expect(page.get_by_role('button',name='job readings_to_output')).to_be_visible()
    expect(page.get_by_role('button',name='job enrich_events')).to_have_count(0)
    page.get_by_role('button',name='Show everything').click()
    page.get_by_role('button',name='job archive_events').click()
    page.get_by_role('button',name='Show only what connects to this').click()
    expect(page.get_by_role('button',name='job readings_to_output')).to_have_count(0)
    expect(page.get_by_role('button',name='external event-collector')).to_be_visible()
    # Job moves: optional, one quiet line on the second cluster's card, guides on demand.
    visit('/cluster')
    expect(page.get_by_text('Savepoint storage')).to_have_count(0)
    expect(page.get_by_text('Not set up')).to_be_visible()
    page.get_by_role('button',name='Set up').click()
    expect(page.get_by_role('heading',name='Set up job moves between default and mars-b')).to_be_visible()
    # The cluster already on the share needs nothing; the other gets its file once a share is picked.
    expect(page.get_by_text('already saves to a shared folder. Nothing to do here.')).to_be_visible()
    page.get_by_label('NFS server').fill('192.168.10.10')
    page.get_by_role('button',name='Find shared folders').click()
    # The share that allows mars-b's machine comes first.
    expect(page.get_by_role('radio').first).to_be_visible()
    assert 'mars.savepoints' in page.locator('fieldset label').first.inner_text()
    page.get_by_role('radio').first.check()
    expect(page.get_by_text('docker compose up -d jobmanager taskmanager').first).to_be_visible()
    expect(page.get_by_text('runs on the machine at 192.168.10.13 and saves to its own disk.')).to_be_visible()
    page.get_by_role('button',name='Check',exact=True).click()
    expect(page.get_by_role('button',name='Check',exact=True)).to_be_enabled()
    assert any(m=='POST' and p=='/api/targets/storage/check' for m,p,_ in writes), 'the check was not requested'
    page.get_by_role('button',name='Close').click()
    expect(page.get_by_role('heading',name='Set up job moves between default and mars-b')).to_have_count(0)
    # Adding a cluster: the guide fills in the form for either place it can run.
    visit('/cluster')
    page.get_by_role('button',name='Add cluster').click()
    page.get_by_role('button',name='On this machine').click()
    expect(page.get_by_text('docker compose --profile second-target up -d')).to_be_visible()
    page.get_by_role('button',name='Use these settings').click()
    expect(page.get_by_placeholder('rack-2',exact=True)).to_have_value('mars-b')
    expect(page.get_by_placeholder('http://newhost:8081',exact=True).first).to_have_value('http://jobmanager-b:8081')
    page.get_by_role('button',name='On another machine').click()
    expect(page.get_by_placeholder('rack-2',exact=True)).to_have_value('')
    page.get_by_label('Address of the new machine').fill('10.0.0.7')
    page.get_by_label('Jobs this cluster will run').fill('12')
    expect(page.get_by_text('12 task slots: one per job.')).to_be_visible()
    expect(page.get_by_text('TARGET_BIND_ADDRESS=10.0.0.7 docker compose up -d')).to_be_visible()
    page.get_by_role('button',name='Use these settings').click()
    expect(page.get_by_placeholder('http://newhost:8083')).to_have_value('http://10.0.0.7:8083')
    page.get_by_role('button',name='Cancel',exact=True).click()
    visit('/jobs')
    expect(page.get_by_role('navigation',name='Main navigation').get_by_role('link')).to_have_count(6)
    page.get_by_role('textbox',name='Search jobs').fill('does-not-exist')
    expect(page.get_by_text('No jobs match.')).to_be_visible()
    page.get_by_role('button',name='Clear filter').click()
    page.get_by_label('Filter by state').select_option('failed')
    page.get_by_label('Filter by state').select_option('all')
    offline[0]=True
    page.wait_for_timeout(10500)
    expect(page.get_by_text('Updates paused')).to_be_visible()
    expect(page.get_by_role('table')).to_be_visible()
    offline[0]=False
    page.get_by_role('button',name='Retry',exact=True).click()
    expect(page.get_by_text('Updates paused')).to_have_count(0)
    visit('/jobs/'+job+'/edit')
    expect(page.get_by_text('Unsaved changes',exact=True)).to_have_count(0)
    editor=page.get_by_role('textbox',name='SQL statement')
    editor.focus();page.keyboard.press('Escape');page.keyboard.press('Tab')
    assert not editor.evaluate('(el) => el === document.activeElement'), 'SQL keyboard exit'
    page.get_by_label('Description',exact=True).fill('UI test draft')
    page.get_by_role('navigation',name='Main navigation').get_by_role('link',name='Jobs',exact=True).click()
    expect(page.get_by_role('dialog')).to_be_visible()
    expect(page.get_by_role('button',name='Keep editing')).to_be_focused()
    page.keyboard.press('Escape')
    expect(page.get_by_role('dialog')).not_to_be_visible()
    expect(page).to_have_url(BASE+'/jobs/'+job+'/edit')
    page.get_by_role('navigation',name='Main navigation').get_by_role('link',name='Jobs',exact=True).click()
    page.get_by_role('button',name='Discard changes',exact=True).click()
    expect(page).to_have_url(BASE+'/jobs')
    visit('/catalog')
    # Entries on one Kafka topic are grouped under it, with who writes and who reads.
    expect(page.get_by_text('example-events',exact=True)).to_be_visible()
    expect(page.get_by_text('2 entries',exact=True)).to_be_visible()
    expect(page.get_by_role('link',name='enrich_events')).to_be_visible()
    expect(page.get_by_role('link',name='archive_events')).to_be_visible()
    page.get_by_label('Show').select_option('kafka')
    expect(page.get_by_role('link',name='readings',exact=True)).to_have_count(0)
    page.get_by_label('Show').select_option('all')
    page.get_by_role('link',name='New entry').click()
    expect(page.get_by_role('heading',name='New entry')).to_be_visible()
    expect(page.get_by_text('Source',exact=True)).to_have_count(0)
    visit('/catalog/new?from='+entry)
    # Clone should retain the stored columns/options, not the connector defaults.
    expect(page.get_by_role('textbox',name='Name',exact=True)).to_have_value(entry+'_copy')
    own=fixtures['/api/catalog/'+entry]
    for i,col in enumerate(own['columns']):expect(page.get_by_label(f'Column {i+1} name')).to_have_value(col['name'])
    visit('/jobs/'+job+'/edit')
    page.get_by_label('Description',exact=True).fill('Saved through the editor')
    save_fails[0]=True
    page.get_by_role('button',name='Save changes',exact=True).click()
    expect(page.get_by_text('Example save failure',exact=True)).to_be_visible()
    expect(page.get_by_label('Description',exact=True)).to_have_value('Saved through the editor')
    save_fails[0]=False
    page.get_by_role('button',name='Save changes',exact=True).click()
    expect(page).to_have_url(BASE+'/jobs/'+job)
    expect(page.get_by_text('Changes saved.',exact=True)).to_be_visible()
    saved=[json.loads(body) for method,path,body in writes if method=='PUT' and path=='/api/jobs/'+job]
    assert saved[-1]['description']=='Saved through the editor'
    visit('/jobs/'+job)
    page.get_by_role('button',name='More',exact=True).click()
    page.get_by_role('button',name='Stop without saving',exact=True).click()
    expect(page.get_by_role('dialog')).to_be_visible()
    page.get_by_role('button',name='Cancel',exact=True).click()
    assert not any(path.endswith('/cancel') for _,path,_ in writes)
    visit('/jobs/'+job+'/edit')
    page.get_by_label('Description',exact=True).fill('Keep this draft')
    page.get_by_role('button',name='operator',exact=True).click()
    page.get_by_role('button',name='Sign out',exact=True).click()
    expect(page.get_by_role('dialog')).to_be_visible()
    page.get_by_role('button',name='Keep editing',exact=True).click()
    assert not any(path.endswith('/logout') for _,path,_ in writes)
    fixtures['/api/ai']['configured']=False
    visit('/jobs/'+job+'/edit')
    expect(page.get_by_text('Draft with AI',exact=True)).to_have_count(0)
    role[0]='viewer'
    visit('/jobs');expect(page.get_by_role('link',name='New job',exact=True)).to_have_count(0)
    expect(page.get_by_role('link',name='Settings',exact=True)).to_have_count(0)
    visit('/catalog');expect(page.get_by_role('button',name='New entry')).to_have_count(0)
    visit('/jobs/'+job);expect(page.get_by_role('link',name='Edit',exact=True)).to_have_count(0)
    visit('/settings/ai');expect(page).to_have_url(BASE+'/jobs')
    role[0]='admin'
    for old,new in [('/admin','accounts'),('/ai','ai'),('/secrets','secrets')]:
        visit(old);expect(page).to_have_url(BASE+'/settings/'+new)
    visit('/jobs')
    page.get_by_role('button',name='operator',exact=True).click()
    page.get_by_role('button',name='Auto',exact=True).click()
    page.keyboard.press('Escape')
    page.emulate_media(color_scheme='dark')
    expect(page.locator('html')).to_have_class('dark')
    page.emulate_media(color_scheme='light')
    expect(page.locator('html')).not_to_have_class('dark')
    page.get_by_role('button',name='operator',exact=True).click()
    page.get_by_role('button',name='Light',exact=True).click()
    page.keyboard.press('Escape')
    page.emulate_media(color_scheme='dark')
    expect(page.locator('html')).not_to_have_class('dark')
    role[0]=None
    page.goto(BASE+'/jobs',wait_until='domcontentloaded')
    expect(page.get_by_role('button',name='Sign in',exact=True)).to_be_visible()
    page.get_by_role('textbox',name='Username',exact=True).fill('operator')
    page.get_by_label('Password',exact=True).fill('synthetic-password')
    page.get_by_role('button',name='Sign in',exact=True).click()
    expect(page.get_by_role('heading',name='Jobs',exact=True)).to_be_visible()
    browser.close()
print(json.dumps({'overflow_failures':failures,'browser_errors':errors,'mocked_mutation_count':len(writes)},indent=2))
assert not errors and not failures
print('PASS: settings navigation, legacy links, filters, stale data, unsaved changes, keyboard exit, cloning, saves, destructive-action cancellation, logout guard, save failures, viewer permissions, system appearance and sign-in.')
