"""Windows acceptance for graphics startup policy and native WebGPU execution.

Uses isolated profiles, the native Marionette protocol, and BrowserScan's actual
displayed report for fingerprint assertions. Never opens manager profiles.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import partial
import http.server
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[2]
FUNCTIONAL = Path(__file__).with_name('webgpu-functional.js').read_text(encoding='utf-8')


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


class Marionette:
    def __init__(self, connection):
        self.connection, self.buffer, self.sequence = connection, b'', 0
        self.receive()

    def receive(self):
        while b':' not in self.buffer:
            self.read_more()
        header, self.buffer = self.buffer.split(b':', 1)
        size = int(header)
        while len(self.buffer) < size:
            self.read_more()
        payload, self.buffer = self.buffer[:size], self.buffer[size:]
        return json.loads(payload)

    def read_more(self):
        data = self.connection.recv(65536)
        if not data:
            raise ConnectionError('Test browser disconnected')
        self.buffer += data

    def command(self, name, parameters=None):
        self.sequence += 1
        data = json.dumps([0, self.sequence, name, parameters or {}]).encode()
        self.connection.sendall(str(len(data)).encode() + b':' + data)
        while True:
            result = self.receive()
            if result[0] == 1 and result[1] == self.sequence:
                if result[2]:
                    raise RuntimeError(f'{name}: {result[2]}')
                return result[3]

    def script(self, source, asynchronous=False):
        result = self.command('WebDriver:ExecuteAsyncScript' if asynchronous else 'WebDriver:ExecuteScript',
                              {'script': source, 'args': [], 'newSandbox': True})
        return result.get('value', result) if isinstance(result, dict) else result


class SilentHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@contextmanager
def launch(binary, root, name, config, prefs=None, profile_name=None):
    run = root / name
    profile = root / 'profiles' / (profile_name or name)
    run.mkdir(parents=True, exist_ok=True)
    profile.mkdir(parents=True, exist_ok=True)
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    preferences = {**(prefs or {}), 'marionette.port': port}
    (profile / 'user.js').write_text(''.join(
        f'user_pref({json.dumps(key)}, {json.dumps(value)});\n'
        for key, value in preferences.items()), encoding='utf-8')
    env = {key: value for key, value in os.environ.items() if not key.startswith('CAMOU_CONFIG')}
    # Exercise the same chunked configuration transport used by managers.
    serialized = json.dumps(config, ensure_ascii=False)
    for index, start in enumerate(range(0, len(serialized), 2047), 1):
        env[f'CAMOU_CONFIG_{index}'] = serialized[start:start + 2047]
    command = [str(binary), '--no-remote', '--wait-for-browser', '--profile', str(profile),
               '--marionette', '--remote-allow-system-access', 'about:blank']
    process = None
    connection = client = None
    report = {'case': name, 'config': config, 'prefs': preferences, 'profile': str(profile)}
    emit({'starting': name})
    try:
        with (run / 'browser.log').open('wb') as log:
            process = subprocess.Popen(command, cwd=binary.parent, env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    connection = socket.create_connection(('127.0.0.1', port), timeout=2)
                    break
                except OSError:
                    if process.poll() is not None:
                        raise RuntimeError(f'Test browser exited early: {process.returncode}')
                    time.sleep(0.2)
            if not connection:
                raise TimeoutError('No Marionette listener')
            connection.settimeout(55)
            client = Marionette(connection)
            client.command('WebDriver:NewSession', {'capabilities': {'alwaysMatch': {'pageLoadStrategy': 'eager'}}})
            client.command('WebDriver:SetTimeouts', {'script': 40000, 'pageLoad': 40000})
            yield client, report
    finally:
        if client:
            try:
                client.command('Marionette:Quit', {'flags': ['eAttemptQuit']})
            except Exception as error:
                report['quitError'] = str(error)
        if connection:
            connection.close()
        if process:
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)
                report['terminatedOwnedProcess'] = True
            report['exitCode'] = process.returncode
        (run / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def browser_scan(client, report):
    client.command('WebDriver:Navigate', {'url': 'https://www.browserscan.net/'})
    value = None
    for _ in range(10):
        time.sleep(2)
        excerpt = client.script("const text=document.body.innerText; const at=text.indexOf('WebGPU Report'); return at<0?'':text.slice(at,at+400);")
        match = re.search(r'WebGPU Report\s+(not support|[0-9A-Fa-f]{8})', excerpt)
        if match:
            value = match.group(1)
            break
    if value is None:
        raise AssertionError('BrowserScan did not display a WebGPU result')
    report['browserScanHome'] = {'value': value, 'excerpt': excerpt}
    client.command('WebDriver:Navigate', {'url': 'https://www.browserscan.net/webgpu'})
    time.sleep(8)
    report['browserScanDetail'] = client.script('return document.body.innerText;')
    emit({'case': report['case'], 'browserScan': value})
    return value


def graphics_decisions(client, report):
    client.command('WebDriver:Navigate', {'url': 'about:support'})
    time.sleep(3)
    report['graphicsDecisions'] = client.script("return document.getElementById('graphics-decisions-tbody').innerText;")


def functional(client, report, url):
    client.command('WebDriver:Navigate', {'url': url})
    source = FUNCTIONAL + '\nconst done=arguments[arguments.length-1]; runFunctionalChecks().then(done).catch(error=>done({failure:String(error),stack:error.stack}));'
    result = client.script(source, asynchronous=True)
    report['functional'] = result
    assert 'failure' not in result, result
    return result


def assert_execution(result):
    assert result['context']['adapter']
    assert result['context']['nativeObjects'] and result['context']['sameObjects']
    assert result['deviceInfo'] == result['context']['info']
    assert result['compute'] == [4, 6, 10, 14]
    assert all(pixel == [51, 102, 204, 255] for pixel in result['render']), result['render']
    assert result['canvasConfigured']
    assert result['tooManyBindGroups'] == 'OperationError'
    assert result['worker']['compute'] == [4, 6, 10, 14]
    for operation in result['languageOperations']:
        assert (operation['errors'] == 0) == operation['advertised'], operation
        assert operation['validationError'] != operation['advertised'], operation
    for other in (result['iframe'], result['worker']['context']):
        assert other['info'] == result['context']['info']
        assert other['limits'] == result['context']['limits']
        assert other['features'] == result['context']['features']


def make_profile(vendor):
    return {
        'gpu': {'preferredCanvasFormat': 'rgba8unorm',
                'wgslLanguageFeatures': ['packed_4x8_integer_dot_product']},
        'adapter': {
            'info': {'vendor': vendor, 'architecture': 'test_arch', 'device': 'test_device',
                     'description': vendor + ' adapter', 'subgroupMinSize': 4,
                     'subgroupMaxSize': 128, 'isFallbackAdapter': False},
            'features': ['core-features-and-limits'],
            'limits': {'maxTextureDimension2D': 8192, 'maxBindGroups': 4,
                       'maxBufferSize': 268435456, 'maxStorageBufferBindingSize': 134217728},
        },
        'adapterOverrides': [
            {'request': {'forceFallbackAdapter': True},
             'adapter': {'info': {'vendor': vendor + '_fallback', 'isFallbackAdapter': True}}},
            {'request': {'powerPreference': 'high-performance', 'forceFallbackAdapter': False},
             'adapter': {'info': {'vendor': vendor + '_high'}}},
        ],
    }


def invalid_startup_checks(binary, root):
    cases = [
        ('boolean', {'webgpu:enabled': 1}, 'webgpu:enabled'),
        ('null-profile', {'webgpu:profile': None}, 'webgpu:profile'),
        ('unknown-field', {'webgpu:profile': {'adapter': {'info': {'renderer': 'invalid'}}}}, 'renderer'),
        ('out-of-range', {'webgpu:profile': {'adapter': {'limits': {'maxBufferSize': 2**53}}}}, 'maxBufferSize'),
        ('ambiguous', {'webgpu:profile': {'adapterOverrides': [
            {'request': {'forceFallbackAdapter': True}, 'adapter': {}},
            {'request': {'powerPreference': 'high-performance'}, 'adapter': {}},
        ]}}, 'ambiguous'),
    ]
    results = []
    for name, config, message in cases:
        profile = root / 'invalid-profiles' / name
        profile.mkdir(parents=True, exist_ok=True)
        env = {key: value for key, value in os.environ.items() if not key.startswith('CAMOU_CONFIG')}
        env['CAMOU_CONFIG'] = json.dumps(config)
        process = subprocess.run([str(binary), '--headless', '--no-remote', '--profile', str(profile), 'about:blank'],
                                 cwd=binary.parent, env=env, capture_output=True, timeout=35)
        output = (process.stdout + process.stderr).decode('utf-8', errors='replace')
        (profile.parent / (name + '.log')).write_text(output, encoding='utf-8')
        assert process.returncode == 1 and message in output, (name, process.returncode, output[-3000:])
        results.append({'case': name, 'exitCode': process.returncode, 'passed': True})
    (root / 'invalid-startup.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('binary', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--cases', default='defaults,acceleration,native,profile-a,repeat-a,profile-b,warp,incompatible,reset,invalid')
    args = parser.parse_args()
    binary = args.binary.resolve()
    root = (args.output or ROOT / 'camoufox-webgpu-verification' /
            datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>WebGPU execution test</title>', encoding='utf-8')
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), partial(SilentHandler, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}/index.html'
    results = []
    selected = set(args.cases.split(','))
    hashes = {}
    cases = [
        ('defaults', {}, {}, None),
        ('acceleration', {'gfx:hardwareAcceleration': True}, {'dom.webgpu.enabled': True}, 'state'),
        ('native', {'gfx:hardwareAcceleration': True, 'webgpu:enabled': True}, {'dom.webgpu.enabled': False}, 'state'),
        ('profile-a', {'gfx:hardwareAcceleration': True, 'webgpu:enabled': True, 'webgpu:profile': make_profile('qa_alpha')}, {}, None),
        ('repeat-a', {'gfx:hardwareAcceleration': True, 'webgpu:enabled': True, 'webgpu:profile': make_profile('qa_alpha')}, {}, 'profile-a'),
        ('profile-b', {'gfx:hardwareAcceleration': True, 'webgpu:enabled': True, 'webgpu:profile': make_profile('qa_beta')}, {}, None),
        ('warp', {'gfx:hardwareAcceleration': True, 'webgpu:enabled': True, 'webgpu:profile': make_profile('qa_alpha')}, {'layers.d3d11.force-warp': True}, None),
        ('incompatible', {'gfx:hardwareAcceleration': True, 'webgpu:enabled': True,
            'webgpu:profile': {'adapterOverrides': [{'request': {'powerPreference': 'high-performance'},
                'adapter': {'features': ['core-features-and-limits', 'subgroups']}}]}}, {}, None),
        ('reset', {'gfx:hardwareAcceleration': True}, {}, 'state'),
    ]
    try:
        if 'invalid' in selected:
            invalid_startup_checks(binary, root)
            results.append({'case': 'invalid', 'passed': True})
            emit(results[-1])
        for name, config, prefs, profile_name in cases:
            if name not in selected:
                continue
            try:
                with launch(binary, root, name, config, prefs, profile_name) as (client, report):
                    if name == 'incompatible':
                        client.command('WebDriver:Navigate', {'url': url})
                        response = client.script("const done=arguments[arguments.length-1]; (async()=>({ordinary:!!(await navigator.gpu.requestAdapter()),incompatible:!!(await navigator.gpu.requestAdapter({powerPreference:'high-performance'}))}))().then(done);", True)
                        report['selectiveFailure'] = response
                        assert response == {'ordinary': True, 'incompatible': False}, response
                    else:
                        value = browser_scan(client, report)
                        hashes[name] = value
                        result = functional(client, report, url)
                        if name in ('defaults', 'acceleration', 'reset'):
                            assert value == 'not support' and result['context'] == {'api': False}
                        else:
                            assert value != 'not support'
                            assert_execution(result)
                            if 'webgpu:profile' in config:
                                assert result['context']['info']['vendor'] == config['webgpu:profile']['adapter']['info']['vendor']
                                assert result['context']['features'] == ['core-features-and-limits']
                                assert result['hiddenTimestampFeature'] == 'TypeError'
                                assert result['languagePolicy'] == {'advertised': False, 'errors': 1, 'validationError': True}
                                assert result['canvasFormat'] == 'rgba8unorm'
                                assert result['requests'][0]['vendor'].endswith('_high')
                                assert result['requests'][2]['vendor'].endswith('_fallback')
                        graphics_decisions(client, report)
                        if name == 'defaults':
                            assert 'FEATURE_FAILURE_COMP_PREF' in report['graphicsDecisions']
                        elif name in ('acceleration', 'native', 'reset'):
                            assert 'FEATURE_FAILURE_COMP_PREF' not in report['graphicsDecisions']
                    report['passed'] = True
                results.append({'case': name, 'passed': True})
                emit(results[-1])
            except Exception as error:
                results.append({'case': name, 'passed': False, 'error': repr(error)})
                emit(results[-1])
                break
        if 'profile-a' in hashes and 'repeat-a' in hashes:
            assert hashes['profile-a'] == hashes['repeat-a'], hashes
        if 'profile-a' in hashes and 'profile-b' in hashes:
            assert hashes['profile-a'] != hashes['profile-b'], hashes
    finally:
        server.shutdown()
        (root / 'results.json').write_text(json.dumps({'results': results, 'hashes': hashes}, indent=2), encoding='utf-8')
        emit({'results': str(root / 'results.json')})
    if any(not item['passed'] for item in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
