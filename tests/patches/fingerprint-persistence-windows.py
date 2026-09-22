"""Strict fixed-input persistence checks in isolated, normally closed profiles.

BrowserScan's own full hashes and report values are retained alongside complete
Canvas/audio bytes and native page/iframe/Worker execution checks.
"""
import argparse
import copy
import hashlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
JS = Path(__file__).with_name('fingerprint-persistence.js').read_text(encoding='utf-8')
spec = importlib.util.spec_from_file_location('graphics_test', Path(__file__).with_name('webgpu-windows.py'))
graphics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(graphics)

# Defined before collecting results; no fingerprint hash is exempted on failure.
DYNAMIC_FIELDS = {
    'clock': 'Current time and measurement durations describe the current run.',
    'network': 'Actual IP, IP-derived geography/timezone, network scans and remote reputation.',
    'site': 'Ads, recommendations, account/session tokens and generated request IDs.',
    'window_session': 'History length and the deliberate iframe viewport are navigation/layout state.',
    'experimental_probes': 'Random challenge inputs/noise diagnostics are not the displayed identity report.',
}
SITE_LABELS = (
    'visitor ID', 'Canvas', 'WebGL', 'WebGL Report', 'Unmasked Vendor', 'Unmasked Renderer',
    'Audio', 'Client Rects', 'WebGPU Report', 'Screen Resolution', 'Available Screen Size',
    'Color Depth', 'Touch Support', 'Hardware Concurrency', 'Media devices', 'Incognito mode',
    'OS', 'Browser', 'Browser Version', 'Header', 'JavaScript', 'Time Zone', 'Languages',
    'Accept-Language header', 'Internationalization API', 'Do Not Track', 'Javascript',
    'Flash', 'ActiveX', 'Java', 'Cookie', 'Fonts',
)
SITE_HASH_FIELDS = {
    'Canvas': ('hardware', 'canvasHash'), 'WebGL': ('hardware', 'webGLHash'),
    'WebGL Report': ('hardware', 'webGLReportHash'), 'Audio': ('hardware', 'audioHash'),
    'Client Rects': ('hardware', 'clientRectHash'), 'WebGPU Report': ('hardware', 'webGPUHash'),
    'visitor ID': ('hardware', 'visitorId'), 'Fonts': ('software', 'fontsHash'),
}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def digest_file(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(message)


def freeze_config(root):
    destination = root / 'profile-a.config.json'
    if destination.exists():
        return json.loads(destination.read_text(encoding='utf-8'))
    from camoufox.fingerprints import generate_context_fingerprint
    config = generate_context_fingerprint(os='windows')['config']
    for key in ('screen.width', 'screen.height', 'screen.availWidth', 'screen.availHeight',
                'screen.availLeft', 'screen.availTop', 'window.outerWidth', 'window.outerHeight',
                'window.innerWidth', 'window.innerHeight', 'window.screenX', 'window.screenY',
                'window.devicePixelRatio', 'document.body.clientWidth', 'document.body.clientHeight',
                'document.body.clientLeft', 'document.body.clientTop'):
        config.pop(key, None)
    config.update({
        'canvas:seed': 123456789, 'audio:seed': 234567891, 'fonts:spacing_seed': 345678912,
        'gfx:hardwareAcceleration': True, 'webgpu:enabled': True,
        'webgpu:profile': graphics.make_profile('persistence_alpha'),
        'window:profile': {'screen.width': 1920, 'screen.height': 1080,
            'screen.availWidth': 1920, 'screen.availHeight': 1040,
            'window.innerWidth': 1280, 'window.innerHeight': 800,
            'window.outerWidth': 1280, 'window.outerHeight': 900,
            'window.screenX': 30, 'window.screenY': 40, 'window.devicePixelRatio': 1},
        'timezone': 'Asia/Shanghai',
    })
    save(destination, config)
    return config


def serve():
    page = ('<!doctype html><meta charset="utf-8"><title>Persistence check</title>'
        '<body><script src="/fingerprint-persistence.js"></script><script>'
        'fpMainProbe().then(value=>{const n=document.createElement("pre");n.id="result";'
        'n.textContent=JSON.stringify(value);document.body.appendChild(n);}).catch(error=>{'
        'const n=document.createElement("pre");n.id="result";n.textContent=JSON.stringify('
        '{error:String(error),stack:error.stack});document.body.appendChild(n);});</script>')

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            is_script = self.path.split('?')[0] == '/fingerprint-persistence.js'
            body = (JS if is_script else page).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/javascript' if is_script else 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def page_probe(client, url, navigate=True):
    if navigate:
        client.command('WebDriver:Navigate', {'url': url})
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        raw = client.script('return document.getElementById("result")?.textContent || null;')
        if raw:
            result = json.loads(raw)
            if 'error' in result:
                raise AssertionError(result)
            return result
        time.sleep(.15)
    raise TimeoutError('Native persistence probe did not finish')


def worker_probe(client, kind):
    sources = {
        'dedicated': 'const worker=new Worker("/fingerprint-persistence.js");worker.onmessage=e=>{if(e.data.progress){stage=e.data.progress;return;}worker.terminate();finish(e.data);};worker.onerror=e=>finish({error:e.message});worker.postMessage(1);',
        'shared': 'const worker=new SharedWorker("/fingerprint-persistence.js");worker.port.onmessage=e=>{if(e.data.progress){stage=e.data.progress;return;}worker.port.close();finish(e.data);};worker.onerror=e=>finish({error:e.message});worker.port.start();worker.port.postMessage(1);',
        'service': '(async()=>{await navigator.serviceWorker.register("/fingerprint-persistence.js",{scope:"/"});const r=await navigator.serviceWorker.ready;const c=new MessageChannel();c.port1.onmessage=e=>{if(e.data.progress){stage=e.data.progress;return;}c.port1.close();finish(e.data);};r.active.postMessage(1,[c.port2]);})().catch(e=>finish({error:String(e)}));',
    }
    graphics.emit({'worker':kind})
    result = client.script('const done=arguments[arguments.length-1];let stage="starting";'
        'const timer=setTimeout(()=>done({error:"Worker timed out",stage}),15000);'
        'const finish=value=>{clearTimeout(timer);done(value);};' + sources[kind], True)
    if 'error' in result:
        raise AssertionError({kind: result})
    return result


def browser_scan_home(client, destination, navigate=True):
    if navigate:
        client.command('WebDriver:Navigate', {'url': 'https://www.browserscan.net/'})
    deadline = time.monotonic() + 45
    snapshot = None
    while time.monotonic() < deadline:
        time.sleep(1)
        raw = client.script(r'''
          const w=window.wrappedJSObject||window;
          const root=w.document.getElementById('browserscan');
          const app=root?.__vue_app__ || root?.__vueParentComponent?.appContext?.app;
          const nuxt=app?.config?.globalProperties?.$nuxt;
          const cells={}, rawCells={}, excludedAds={};
          for (const cell of document.querySelectorAll('div._11xj7yu')) {
            const label=cell.querySelector('h3')?.textContent.trim();
            if (!label) continue;
            const value=cell.lastElementChild;
            rawCells[label]=value.innerText.trim();
            // Google inserts unrelated ad chips inside report values. Ads are
            // an existing dynamic exclusion; retain their raw text as evidence.
            // Hide only marked ad nodes while reading rendered report text,
            // then restore their exact styles. No identity field is omitted.
            const ads=Array.from(value.querySelectorAll('.google-anno-skip.google-anno-sc'));
            const styles=ads.map(ad=>ad.getAttribute('style'));
            if (ads.length) excludedAds[label]=ads.map(ad=>ad.innerText);
            try {
              for (const ad of ads) ad.style.setProperty('display','none','important');
              cells[label]=value.innerText.trim();
            } finally {
              ads.forEach((ad,index)=>{
                if (styles[index]===null) ad.removeAttribute('style');
                else ad.setAttribute('style',styles[index]);
              });
            }
          }
          return JSON.stringify({cells,rawCells,excludedAds,state:nuxt?.payload?.state,
            rootProperties:root?Object.getOwnPropertyNames(root):[],
            appProperties:app?Object.keys(app.config.globalProperties):[],
            text:document.body.innerText,
            modules:Array.from(document.querySelectorAll('link[rel="modulepreload"]'),l=>l.href)});
        ''')
        snapshot = json.loads(raw)
        if all(re.search(r'[0-9a-fA-F]{8}', snapshot['cells'].get(label, '')) for label in SITE_HASH_FIELDS):
            break
    save(destination, snapshot)
    assert snapshot and 'state' in snapshot, 'BrowserScan report state unavailable; raw DOM saved'
    state = {key.removeprefix('$s'): value for key, value in snapshot['state'].items()}
    stable = {'cells': {}, 'hashes': {}}
    for label in SITE_LABELS:
        assert label in snapshot['cells'], 'Missing BrowserScan identity field: ' + label
        stable['cells'][label] = snapshot['cells'][label]
    for label, (section, key) in SITE_HASH_FIELDS.items():
        value = state[section][key]
        assert re.fullmatch(r'[0-9a-fA-F]{32,128}', value), (label, value)
        assert value[:8].upper() in snapshot['cells'][label].upper(), (label, value)
        stable['hashes'][label] = value
    stable['fontsList'] = state['software']['fontsList']
    stable['webGPU'] = state['hardware']['webGPU']
    save(destination.with_name(destination.stem + '-identity.json'), stable)
    return stable


def browser_scan_details(client, destination):
    result = {}
    for path, marker in [('canvas', 'Canvas Fingerprint'), ('webgpu', 'WebGPU Report Hash')]:
        client.command('WebDriver:Navigate', {'url': 'https://www.browserscan.net/' + path})
        snapshot = None
        for _ in range(25):
            time.sleep(1)
            snapshot = client.script('return {text:document.body.innerText,tables:Array.from(document.querySelectorAll("table"),t=>Array.from(t.rows,r=>Array.from(r.cells,c=>c.innerText))),images:Array.from(document.images).filter(i=>i.src.startsWith("data:image/png")).map(i=>i.src)};')
            hashes = [line.strip() for line in snapshot['text'].splitlines()
                      if re.fullmatch('[0-9a-fA-F]{32,128}', line.strip())]
            if marker in snapshot['text'] and hashes:
                break
        save(destination / (path + '-detail.json'), snapshot)
        assert marker in snapshot['text'] and hashes, 'BrowserScan full detail hash missing: ' + path
        result[path] = {'hash': hashes[0], 'tables': snapshot['tables'], 'images': snapshot['images']}
    return result


def frame_probe(client, url):
    return client.script('''const done=arguments[arguments.length-1];
      const frame=document.createElement('iframe');frame.src=''' + json.dumps(url) + ''';
      frame.onload=()=>{const poll=()=>{const n=frame.contentDocument.getElementById('result');
        if(n){const r=JSON.parse(n.textContent);frame.remove();done(r);}else setTimeout(poll,50);};poll();};
      document.body.appendChild(frame);''', True)


def assert_common_navigation(main, related):
    for key in ('userAgent', 'platform', 'hardwareConcurrency', 'language', 'languages', 'intl'):
        equal(related['navigator'][key], main['navigator'][key], 'Frame/Worker navigator differs: ' + key)
    equal(related['gpu'], main['gpu'], 'Frame/Worker WebGPU profile differs')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('binary', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--iterations', type=int, default=3)
    parser.add_argument('--phases', default='native,website,defaults,variants,full-randomization,lifecycle,invalid')
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    config = freeze_config(root)
    binary = args.binary.resolve()
    phases = set(args.phases.split(','))
    prefs = {'intl.accept_languages': 'en-US,en', 'intl.locale.requested': 'en-US'}
    save(root/'environment.json', {'binary':str(binary), 'exeSHA256':digest_file(binary),
        'xulSHA256':digest_file(binary.with_name('xul.dll')), 'configSHA256':digest_file(root/'profile-a.config.json'),
        'dynamicExclusions':DYNAMIC_FIELDS, 'siteIdentityFields':SITE_LABELS,
        'requestedIterations':args.iterations, 'phases':sorted(phases)})
    server = serve()
    url = 'http://127.0.0.1:' + str(server.server_port) + '/main.html'
    baseline = site_baseline = detail_baseline = workers_baseline = None
    results = []
    try:
        for index in range(args.iterations):
            name = 'profile-a-run-' + str(index + 1)
            with graphics.launch(binary, root, name, config, prefs, 'profile-a') as (client, report):
                core = page_probe(client, url)
                report['core'] = core
                save(root/name/'native.json', core)
                assert core['gpu']['adapter'], 'Configured WebGPU adapter missing'
                assert core['webgl']['supported'] and core['webgl2']['supported'], 'WebGL execution missing'
                if baseline is None:
                    baseline = core
                else:
                    equal(core, baseline, 'Stable native identity drifted after normal restart')
                sentinel = client.script('return localStorage.getItem("kernel-persistence-sentinel");')
                if index:
                    equal(sentinel, 'fixed-profile-data', 'Normal profile storage was not retained')
                client.script('localStorage.setItem("kernel-persistence-sentinel","fixed-profile-data");')
                if 'native' in phases:
                    workers = {}
                    for kind in ('dedicated','shared','service'):
                        workers[kind] = worker_probe(client, kind)
                        save(root/name/('worker-'+kind+'.json'),workers[kind])
                    report['workers'] = workers
                    save(root/name/'workers.json', workers)
                    for related in workers.values():
                        assert_common_navigation(core, related)
                    if workers_baseline is None:
                        workers_baseline = workers
                    else:
                        equal(workers, workers_baseline, 'Worker image bytes changed after restart')
                    frame = frame_probe(client, url.replace('main.html','frame.html'))
                    report['iframe'] = frame
                    assert 'error' not in frame, frame
                    assert_common_navigation(core, frame)
                    for key in ('image','text','fonts','audio','webgl','webgl2'):
                        equal(frame[key], core[key], 'Same-origin iframe fingerprint differs: ' + key)
                    client.command('WebDriver:Refresh')
                    refreshed = page_probe(client, url, navigate=False)
                    save(root/name/'refreshed-native.json', refreshed)
                    equal(refreshed, core, 'Native fingerprint changed on refresh')
                if 'website' in phases:
                    site = browser_scan_home(client, root/name/'browserscan-home.json')
                    report['website'] = site
                    if site_baseline is None:
                        site_baseline = site
                    else:
                        equal(site, site_baseline, 'BrowserScan complete identity report drifted after restart')
                    if index == 0:
                        client.command('WebDriver:Refresh')
                        refreshed = browser_scan_home(client, root/name/'browserscan-refresh.json', navigate=False)
                        equal(refreshed, site, 'BrowserScan report changed on refresh')
                        tab = client.command('WebDriver:NewWindow', {'type':'tab'})
                        client.command('WebDriver:SwitchToWindow', {'handle':tab['handle']})
                        new_page = browser_scan_home(client, root/name/'browserscan-new-page.json')
                        equal(new_page, site, 'BrowserScan report changed in a new page')
                    details = browser_scan_details(client, root/name)
                    report['details'] = details
                    if detail_baseline is None:
                        detail_baseline = details
                    else:
                        equal(details, detail_baseline, 'BrowserScan detail hashes/bytes/tables drifted')
                report['passed'] = True
            assert report['exitCode'] == 0 and not report.get('terminatedOwnedProcess') and not report.get('quitError'), report.get('quitError')
            results.append({'case':name,'passed':True})
            graphics.emit({'case':name,'passed':True,'canvas':core['image']['image/png']['sha256'],
                'audio':core['audio']['sha256'], 'siteHashes':report.get('website',{}).get('hashes')})

        if 'variants' in phases:
            variants = [('canvas', {'canvas:seed':987654321}), ('audio', {'audio:seed':876543219}),
                        ('fonts', {'fonts:spacing_seed':765432198}),
                        ('profile-b', {'canvas:seed':987654321,'audio:seed':876543219,'fonts:spacing_seed':765432198,
                                       'webgpu:profile':graphics.make_profile('persistence_beta')})]
            for name, overrides in variants:
                changed = {**copy.deepcopy(config), **overrides}
                with graphics.launch(binary,root,'changed-'+name,changed,prefs,
                                     'profile-b' if name=='profile-b' else 'profile-a') as (client, report):
                    core = page_probe(client,url)
                    report['core'] = core
                    save(root/('changed-'+name)/'native.json',core)
                    key = {'canvas':('image',),'audio':('audio',),'fonts':('fonts',),'profile-b':('image','audio','fonts','gpu')}[name]
                    for field in key:
                        assert core[field] != baseline[field], 'Changed input had no effect: '+name+'/'+field
                    if name=='canvas':
                        for field in ('audio','fonts','gpu','webgl'):
                            if field!='webgl':equal(core[field],baseline[field],'Canvas seed changed unrelated '+field)
                    if name=='profile-b' and 'website' in phases:
                        site = browser_scan_home(client,root/'changed-profile-b/browserscan-home.json')
                        for label in ('Canvas','Audio','Client Rects','WebGPU Report'):
                            assert site['hashes'][label] != site_baseline['hashes'][label], 'Profile B did not change '+label
                    report['passed']=True
                results.append({'case':'changed-'+name,'passed':True})
                graphics.emit(results[-1])

        if 'defaults' in phases:
            for mode in ('absent','zero'):
                default = copy.deepcopy(config)
                for key in ('canvas:seed','audio:seed','fonts:spacing_seed'):
                    if mode=='zero':default[key]=0
                    else:default.pop(key,None)
                hashes=[]
                for index in range(2):
                    name=mode+'-'+str(index+1)
                    with graphics.launch(binary,root,name,default,prefs,mode) as (client, report):
                        core=page_probe(client,url)
                        report['core']=core
                        hashes.append(core['image']['image/png']['sha256'])
                        report['passed']=True
                assert hashes[0]!=hashes[1], 'Default native session randomization was frozen: '+mode
                results.append({'case':mode,'passed':True,'canvasHashes':hashes})
                graphics.emit(results[-1])

        if 'full-randomization' in phases:
            full_prefs={**prefs,'privacy.fingerprintingProtection':True,
                'privacy.fingerprintingProtection.overrides':'+CanvasRandomization,+WebGLRandomization,-EfficientCanvasRandomization'}
            first=None
            for index in range(3):
                name='full-randomization-'+str(index+1)
                with graphics.launch(binary,root,name,config,full_prefs,'full-randomization') as (client,report):
                    core=page_probe(client,url)
                    report['core']=core
                    assert core['image']['pixels'] != baseline['image']['pixels'], 'Full Canvas randomization was not exercised'
                    assert core['webgl']['pixels'] != baseline['webgl']['pixels'], 'Full WebGL randomization was not exercised'
                    if first is None:first=core
                    else:equal(core,first,'Full pixel randomization drifted across restart')
                    report['passed']=True
            results.append({'case':'full-randomization','passed':True})
            graphics.emit(results[-1])

        if 'lifecycle' in phases:
            legacy_prefs={**prefs,'roverfox.s.seed_0':'42','roverfox.s.audioFingerprintSeed_0':'43',
                          'roverfox.s.disabled_0':'1','roverfox.s.audio_disabled_0':'1'}
            with graphics.launch(binary,root,'lifecycle',config,legacy_prefs,'profile-a') as (client,report):
                before=page_probe(client,url)
                report['before']=before
                equal(before,baseline,'Old per-context user preferences polluted launch configuration')
                client.script('document.cookie="persistence-check=1;path=/";')
                client.command('WebDriver:DeleteAllCookies')
                client.command('Marionette:SetContext',{'value':'chrome'})
                try:
                    client.script('Cc["@mozilla.org/rfp-service;1"].getService(Ci.nsIRFPService).cleanAllRandomKeys();')
                finally:
                    client.command('Marionette:SetContext',{'value':'content'})
                after=page_probe(client,url)
                report['afterClearingKeys']=after
                equal(after,before,'Clearing native keys/cookies reset an explicitly seeded identity')
                other_site=page_probe(client,url.replace('127.0.0.1','localhost'))
                report['otherSite']=other_site
                assert other_site['image']['image/png']!=before['image']['image/png'],'Native site partitioning was lost'
                equal(other_site['image']['pixels'],before['image']['pixels'],'Changing site changed source pixels')
                restored=page_probe(client,url)
                report['restored']=restored
                equal(restored,before,'Returning to the same site changed its seeded identity')
                report['passed']=True
            results.append({'case':'lifecycle','passed':True})
            graphics.emit(results[-1])

        if 'invalid' in phases:
            cases=[]
            for key in ('canvas:seed','audio:seed','fonts:spacing_seed'):
                for tag,value in [('boolean',True),('negative',-1),('overflow',4294967296),('float',1.0)]:
                    name=key.replace(':','-')+'-'+tag
                    profile=root/'invalid-profiles'/name
                    profile.mkdir(parents=True,exist_ok=True)
                    env={k:v for k,v in os.environ.items() if not k.startswith('CAMOU_CONFIG')}
                    env['CAMOU_CONFIG']=json.dumps({key:value})
                    process=subprocess.run([str(binary),'--headless','--no-remote','--profile',str(profile),'about:blank'],
                        cwd=binary.parent,env=env,capture_output=True,timeout=25)
                    output=(process.stdout+process.stderr).decode('utf-8',errors='replace')
                    (profile.parent/(name+'.log')).write_text(output,encoding='utf-8')
                    assert process.returncode==1 and key in output,(name,process.returncode,output)
                    cases.append({'case':name,'passed':True,'exitCode':process.returncode})
            save(root/'invalid-startup.json',cases)
            results.append({'case':'invalid','passed':True,'checks':len(cases)})
            graphics.emit(results[-1])
    except Exception as error:
        results.append({'case':'failure','passed':False,'error':repr(error)})
        graphics.emit(results[-1])
        raise
    finally:
        server.shutdown()
        save(root/'results.json',results)
    graphics.emit({'passed':True,'results':str(root/'results.json')})


if __name__=='__main__':
    main()
