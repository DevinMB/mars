"""Run against a local frontend; all API traffic is intercepted with synthetic fixtures.

    pip install playwright==1.49.0
    playwright install chromium
    UI_BASE_URL=http://127.0.0.1:5173 python tests/browser_smoke.py

Set UI_SCREENSHOTS to a directory to include the full responsive screenshot matrix.
"""
import json, os
from copy import deepcopy
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
    role=['admin']; offline=[False]; save_fails=[False]; batch_state={}
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
            elif path.endswith('/move'):body={'moved':True,'summary':'readings_to_output now runs on mars-b.','savepoint':None}
            elif path=='/api/batches':
                sent=json.loads(req.request.post_data)
                batch_state['b']={'id':1,'kind':sent['kind'],'cluster':sent['cluster'],'status':'running','created_by':'admin',
                    'created_at':'2026-10-11T21:00:00Z','finished_at':None,
                    'items':[{'job':n,'status':'working' if i==0 else 'waiting','note':''} for i,n in enumerate(sent['jobs'])]}
                return req.fulfill(status=201,json=batch_state['b'])
            elif req.request.method in ['POST','PUT'] and path.startswith('/api/jobs'):
                body={'ok':True}
            else:body={}
        elif path=='/api/batches/1' and batch_state.get('b'):
            b=dict(batch_state['b']); b['status']='done'; b['finished_at']='2026-10-11T21:00:05Z'
            b['items']=[dict(i,status='done',note=f"{i['job']} now runs on mars-b.") for i in b['items']]
            body=b
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
    # Removing an external connection is explicit and cancellable, and only
    # touches its map entry after confirmation.
    visit('/pipeline')
    page.get_by_role('button',name='kafka topic raw-events').click()
    deletes_before = len([w for w in writes if w[0] == 'DELETE'])
    page.get_by_role('button',name='Remove from map',exact=True).click()
    dialog = page.get_by_role('dialog')
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text('event-collector')
    expect(dialog).to_contain_text('The actual system and its data are not changed, and no jobs are stopped.')
    dialog.get_by_role('button',name='Cancel',exact=True).click()
    assert len([w for w in writes if w[0] == 'DELETE']) == deletes_before
    page.get_by_role('button',name='Remove from map',exact=True).click()
    dialog.get_by_role('button',name='Remove from map',exact=True).click()
    expect(dialog).not_to_be_visible()
    assert [w[:2] for w in writes if w[0] == 'DELETE'][deletes_before:] == [('DELETE', '/api/pipeline/external/1')]
    visit('/pipeline')
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
    # Hidden selections: all filter types report them; clearing hidden selections
    # preserves the visible selection and excludes hidden jobs from bulk actions.
    original_jobs = fixtures['/api/jobs']
    other = deepcopy(original_jobs[0])
    other.update(id=2, name='archived_orders', description='Archived orders', tags=['commerce'], target_name='mars-b')
    other['latest_run'].update(id=2, job=other['name'], state='finished')
    fixtures['/api/jobs'] = [*original_jobs, other]
    for filter_kind in ['search', 'state', 'tag', 'cluster']:
        visit('/jobs')
        page.get_by_role('checkbox',name='Select all shown jobs').check()
        if filter_kind == 'search': page.get_by_role('textbox',name='Search jobs').fill(job)
        elif filter_kind == 'state': page.get_by_role('combobox',name='Filter by state').select_option('running')
        elif filter_kind == 'tag': page.get_by_role('combobox',name='Filter by tag').select_option('sensors')
        else: page.get_by_role('button',name='default1',exact=True).click()
        expect(page.get_by_text('2 selected',exact=True)).to_be_visible()
        expect(page.get_by_text('· 1 hidden by filters',exact=True)).to_be_visible()
        page.get_by_role('button',name='Clear hidden selections',exact=True).click()
        expect(page.get_by_text('1 selected',exact=True)).to_be_visible()
        expect(page.get_by_role('checkbox',name='Select '+job,exact=True)).to_be_checked()
        expect(page.get_by_role('button',name='Clear hidden selections')).to_have_count(0)
        if filter_kind == 'search': page.get_by_role('textbox',name='Search jobs').fill('')
        elif filter_kind == 'state': page.get_by_role('combobox',name='Filter by state').select_option('all')
        elif filter_kind == 'tag': page.get_by_role('combobox',name='Filter by tag').select_option('')
        else: page.get_by_role('button',name='All clusters2',exact=True).click()
        expect(page.get_by_role('checkbox',name='Select archived_orders',exact=True)).not_to_be_checked()
    page.get_by_role('textbox',name='Search jobs').fill('no matching pipeline')
    expect(page.get_by_text('· 1 hidden by filters',exact=True)).to_be_visible()
    page.get_by_role('button',name='Clear hidden selections',exact=True).click()
    expect(page.get_by_role('button',name='Clear selection',exact=True)).to_have_count(0)
    fixtures['/api/jobs'] = original_jobs
    # Tags: chips filter the list, the address keeps the filter, and the selection can be tagged.
    visit('/jobs')
    page.get_by_role('button',name='sensors').first.click()
    expect(page.get_by_role('combobox',name='Filter by tag')).to_have_value('sensors')
    assert 'tag=sensors' in page.url, 'the tag filter is not kept in the address'
    page.get_by_role('combobox',name='Filter by tag').select_option('')
    page.get_by_role('checkbox',name='Select all shown jobs').check()
    page.get_by_role('button',name='Tag…').click()
    page.get_by_label('Tags').fill('Demo, phase1')
    page.get_by_role('button',name='Add',exact=True).click()
    assert any(m=='POST' and p=='/api/jobs/tags' and '"add":["demo","phase1"]' in (d or '').replace(' ','') for m,p,d in writes), 'tags were not sent'
    page.get_by_role('button',name='Close').click()
    page.get_by_role('button',name='Clear selection').click()
    visit('/pipeline')
    page.get_by_role('combobox',name='Tag').select_option('sensors')
    expect(page.get_by_role('button',name='job readings_to_output')).to_be_visible()
    expect(page.get_by_role('button',name='job enrich_events')).to_have_count(0)
    # Bulk actions: tick jobs (or all shown), then move them one at a time.
    visit('/jobs')
    page.get_by_role('checkbox',name='Select all shown jobs').check()
    total=len(fixtures['/api/jobs'])
    expect(page.get_by_text(f'{total} selected')).to_be_visible()
    page.get_by_role('checkbox',name='Select '+job).uncheck()
    expect(page.get_by_role('button',name='Clear selection')).to_have_count(0)
    page.get_by_role('checkbox',name='Select '+job).check()
    page.get_by_role('button',name='Move to cluster…').click()
    page.get_by_role('radio',name='mars-b').check()
    page.get_by_role('button',name=f'Move {total} to mars-b').click()
    # Handed to the console: progress comes from the server, then the result.
    expect(page.get_by_role('heading',name=f'Moving {total} job{"" if total==1 else "s"} to mars-b')).to_be_visible()
    assert any(m=='POST' and p=='/api/batches' for m,p,_ in writes), 'the batch was not started on the server'
    expect(page.get_by_role('status').get_by_text('Finished')).to_be_visible(timeout=10000)
    expect(page.get_by_text(f'{job} now runs on mars-b.')).to_be_visible()
    page.get_by_role('status').get_by_role('button',name='Dismiss').click()
    expect(page.get_by_role('heading',name=f'Moving {total} job{"" if total==1 else "s"} to mars-b')).to_have_count(0)
    # Resources: each cluster's machines and the jobs using them, on demand.
    visit('/cluster')
    resources = page.get_by_role('button',name='Resources & jobs CPU, memory, slots, and job usage').first
    expect(resources).to_have_attribute('aria-expanded', 'false')
    resources.focus()
    page.keyboard.press('Enter')
    expect(resources).to_have_attribute('aria-expanded', 'true')
    expect(page.get_by_text('TaskManager · 4 cores · 1 of 12 slots used · CPU 12%')).to_be_visible()
    expect(page.get_by_text('Managed memory')).to_be_visible()
    expect(page.get_by_role('link',name='readings_to_output')).to_be_visible()
    expect(page.get_by_text('4% busy')).to_be_visible()
    resources.click()
    expect(resources).to_have_attribute('aria-expanded', 'false')
    # Rolling upgrade: offered once job moves are ready; the empty cluster goes first.
    fixtures['/api/targets/storage']['moves'][0]['state']='ready'
    visit('/cluster')
    page.get_by_role('button',name='Upgrade one cluster at a time…').click()
    expect(page.get_by_role('heading',name='Upgrade without stopping the pipeline')).to_be_visible()
    expect(page.get_by_text('No jobs on mars-b.')).to_be_visible()
    move_all=page.get_by_role('button',name='Move 1 job to mars-b')
    expect(move_all).to_be_disabled()
    page.get_by_role('checkbox',name='mars-b runs the new image').check()
    expect(move_all).to_be_enabled()
    move_all.click()
    expect(page.get_by_role('heading',name='Moving 1 job to mars-b')).to_be_visible()
    fixtures['/api/targets/storage']['moves'][0]['state']='off'
    # Moving a job: from the job's menu, to a cluster MARS says is ready.
    visit('/jobs/'+job)
    page.get_by_role('button',name='More').click()
    page.get_by_role('button',name='Move to cluster…').click()
    expect(page.get_by_role('heading',name='Move to another cluster')).to_be_visible()
    expect(page.get_by_role('radio')).to_be_checked()
    expect(page.get_by_text('of state: expect it to be stopped for a few seconds')).to_be_visible()
    # Small state: the native format would make no difference, so it is not offered.
    expect(page.get_by_text('Use the native savepoint format')).to_have_count(0)
    page.get_by_role('button',name='Move to mars-b').click()
    expect(page.get_by_text('readings_to_output now runs on mars-b.').first).to_be_visible(timeout=10000)
    assert any(m=='POST' and p=='/api/batches' and '"jobs":["'+job+'"]' in (d or '').replace(' ','') for m,p,d in writes), \
        'the move was not handed to the console'
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
    visit('/pipeline')
    page.get_by_role('button',name='kafka topic raw-events').click()
    expect(page.get_by_role('button',name='Remove from map',exact=True)).to_have_count(0)
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
