"""Existing font/audio setter precedence, Worker propagation and context isolation."""
import argparse
import copy
import http.server
import json
import os
from pathlib import Path
import threading

from playwright.sync_api import sync_playwright

PROBE = r'''
function widths(offscreen) {
  const c=offscreen?new OffscreenCanvas(64,32):document.createElement('canvas');
  const x=c.getContext('2d');x.font='16px Arial';
  return ['mmmmmmmmmmmm','The quick brown fox jumps over the lazy dog','iiiiWWWW']
    .map(t=>x.measureText(t).width);
}
(async()=>{
  const main=widths(false),offscreen=widths(true);
  const url=URL.createObjectURL(new Blob([widths.toString()+';postMessage(widths(true));'],{type:'text/javascript'}));
  const worker=await new Promise((resolve,reject)=>{
    const w=new Worker(url);w.onmessage=e=>{w.terminate();URL.revokeObjectURL(url);resolve(e.data);};w.onerror=reject;
  });
  const shared=await new Promise((resolve,reject)=>{
    const w=new SharedWorker('/worker.js');w.port.onmessage=e=>{w.port.close();resolve(e.data);};w.onerror=reject;
    w.port.start();w.port.postMessage(1);
  });
  await navigator.serviceWorker.register('/worker.js',{scope:'/'});
  const registration=await navigator.serviceWorker.ready;
  const service=await new Promise(resolve=>{
    const channel=new MessageChannel();channel.port1.onmessage=e=>{channel.port1.close();resolve(e.data);};
    registration.active.postMessage(1,[channel.port2]);
  });
  const ctx=new OfflineAudioContext(1,4096,44100),osc=ctx.createOscillator();
  osc.frequency.value=997;osc.connect(ctx.destination);osc.start();
  const buffer=await ctx.startRendering(),samples=buffer.getChannelData(0);
  const digest=await crypto.subtle.digest('SHA-256',samples);
  return {main,offscreen,worker,shared,service,audio:Array.from(new Uint8Array(digest),n=>n.toString(16).padStart(2,'0')).join(''),
    settersHidden:typeof window.setFontSpacingSeed==='undefined'&&typeof window.setAudioFingerprintSeed==='undefined'};
})().then(value=>{const p=document.createElement('pre');p.id='result';p.textContent=JSON.stringify(value);document.body.appendChild(p);})
 .catch(error=>{const p=document.createElement('pre');p.id='result';p.textContent=JSON.stringify({error:String(error)});document.body.appendChild(p);});
'''


def env_for(config):
    env={k:v for k,v in os.environ.items() if not k.startswith('CAMOU_CONFIG')}
    raw=json.dumps(config)
    for i,p in enumerate(range(0,len(raw),2047),1):
        env['CAMOU_CONFIG_'+str(i)]=raw[p:p+2047]
    return env


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('binary',type=Path)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    config=json.loads(args.config.read_text(encoding='utf-8'))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    page_html=('<!doctype html><meta charset="utf-8"><body><script>'+PROBE+'</script>').encode()
    worker_js=(PROBE.split('(async()=>{',1)[0]+'''
      if(typeof ServiceWorkerGlobalScope!=='undefined'&&self instanceof ServiceWorkerGlobalScope){
        oninstall=e=>e.waitUntil(skipWaiting());onactivate=e=>e.waitUntil(clients.claim());
        onmessage=e=>e.ports[0].postMessage(widths(true));
      }else{onconnect=e=>{const p=e.ports[0];p.onmessage=()=>p.postMessage(widths(true));p.start();};}
    ''').encode()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            is_worker=self.path=='/worker.js'
            body=worker_js if is_worker else page_html
            self.send_response(200)
            self.send_header('Content-Type','application/javascript' if is_worker else 'text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    url='http://127.0.0.1:'+str(server.server_port)+'/'
    results={}
    try:
        with sync_playwright() as pw:
            for launch_name,launch_seed in [('global-zero',0),('global-fixed',345678912)]:
                launch_config={**copy.deepcopy(config),'fonts:spacing_seed':launch_seed,'audio:seed':launch_seed}
                browser=pw.firefox.launch(executable_path=str(args.binary.resolve()),headless=True,env=env_for(launch_config))
                try:
                    entries=[]
                    for name,seed in [('inherit',None),('zero',0),('other',123456789)]:
                        context=browser.new_context(viewport={'width':1280,'height':800})
                        if seed is not None:
                            context.add_init_script('if(typeof window.setFontSpacingSeed==="function")window.setFontSpacingSeed('+str(seed)+');'
                                'if(typeof window.setAudioFingerprintSeed==="function")window.setAudioFingerprintSeed('+str(seed)+');')
                        page=context.new_page()
                        page.goto(url)
                        page.wait_for_selector('#result',state='attached',timeout=20000)
                        result=json.loads(page.locator('#result').text_content())
                        results[launch_name+'/'+name]=result
                        entries.append((name,context,page,result))
                    # Warm other contexts first, then revisit the original zero context.
                    for name,context,page,original in reversed(entries):
                        page.reload()
                        page.wait_for_selector('#result',state='attached',timeout=20000)
                        repeated=json.loads(page.locator('#result').text_content())
                        results[launch_name+'/'+name+'-repeat']=repeated
                        assert repeated==original, 'Context drift after another profile was used: '+name
                finally:
                    browser.close()
        native=results['global-zero/inherit']
        for key,value in results.items():
            assert 'error' not in value,(key,value)
            assert value['settersHidden'],key
            assert value['main']==value['offscreen']==value['worker']==value['shared']==value['service'],('Font seed did not reach OffscreenCanvas/Worker',key,value)
        for field in ('main','offscreen','worker','shared','service','audio'):
            assert results['global-fixed/zero'][field]==native[field],('Explicit zero did not override global seed',field)
            assert results['global-fixed/inherit'][field]!=native[field],('Nonzero seed did not change output',field)
            assert results['global-fixed/other'][field]==results['global-zero/other'][field],('Context depends on launch seed',field)
        results['passed']=True
        print('Existing font/audio seed overrides, explicit zero, OffscreenCanvas, Workers and context isolation passed')
    finally:
        server.shutdown()
        args.output.write_text(json.dumps(results,indent=2),encoding='utf-8')


if __name__=='__main__':main()
