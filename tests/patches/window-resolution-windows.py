"""Run the Windows kernel against real window bounds and a local probe page.

Only windows owned by the supplied test executable and bearing this run's
unique page title are inspected or resized. No desktop input is injected.
Test profiles and JSON results are retained in the requested report directory.
"""

import argparse
import asyncio
import ctypes
from ctypes import wintypes
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import traceback
import uuid

from playwright.async_api import async_playwright


HTML = r'''<!doctype html><meta charset="utf-8"><title>Window check</title>
<style>body{margin:0;padding:16px;font:14px monospace}pre{white-space:pre-wrap}</style>
<h1>Camoufox window verification</h1><pre id="probe"></pre>
<script>
document.title = new URL(location.href).searchParams.get('title');
function snapshot() {
  const s = screen;
  const value = {
    screen: {width:s.width,height:s.height,availWidth:s.availWidth,availHeight:s.availHeight},
    outer: [outerWidth,outerHeight], inner: [innerWidth,innerHeight],
    position: [screenX,screenY], dpr:devicePixelRatio,
    root: [document.documentElement.clientWidth,document.documentElement.clientHeight],
    body: [document.body.clientWidth,document.body.clientHeight],
    cssScreen: matchMedia('(device-width: '+s.width+'px) and (device-height: '+s.height+'px)').matches,
    cssDpr: matchMedia('(resolution: '+devicePixelRatio+'dppx)').matches
  };
  document.getElementById('probe').textContent = JSON.stringify(value);
}
document.addEventListener('window-check-refresh', snapshot);
addEventListener('resize', snapshot);
snapshot();
</script>'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = HTML.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


class Placement(ctypes.Structure):
    _fields_ = [('length', wintypes.UINT), ('flags', wintypes.UINT),
                ('showCmd', wintypes.UINT), ('ptMinPosition', wintypes.POINT),
                ('ptMaxPosition', wintypes.POINT), ('rcNormalPosition', wintypes.RECT)]


class MonitorInfo(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT),
                ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD)]


def rect_list(rect):
    return [rect.left, rect.top, rect.right, rect.bottom]


class Windows:
    def __init__(self, executable):
        self.executable = os.path.normcase(str(executable.resolve()))
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.user.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        self.user.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        self.user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        self.enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user.EnumWindows.argtypes = [self.enum_proc, wintypes.LPARAM]
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user.GetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(Placement)]
        self.user.GetDpiForWindow.argtypes = [wintypes.HWND]
        self.user.GetDpiForWindow.restype = wintypes.UINT
        self.user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                          ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, wintypes.UINT]
        self.user.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                          wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.monitor_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE,
                                               wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                               wintypes.LPARAM)
        self.user.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p,
                                                 self.monitor_proc, wintypes.LPARAM]
        self.user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]

    def process_matches(self, pid):
        handle = self.kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            path = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(path))
            return bool(self.kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length))) and os.path.normcase(path.value) == self.executable
        finally:
            self.kernel.CloseHandle(handle)

    def find(self, marker):
        found = []

        @self.enum_proc
        def callback(hwnd, _param):
            if not self.user.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not self.process_matches(pid.value):
                return True
            title = ctypes.create_unicode_buffer(2048)
            self.user.GetWindowTextW(hwnd, title, len(title))
            if marker in title.value:
                found.append(hwnd)
            return True

        self.user.EnumWindows(callback, 0)
        if len(found) > 1:
            raise RuntimeError(f'Multiple test windows matched {marker}')
        return found[0] if found else None

    def state(self, hwnd):
        rect = wintypes.RECT()
        placement = Placement(length=ctypes.sizeof(Placement))
        if not self.user.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not self.user.GetWindowPlacement(hwnd, ctypes.byref(placement)):
            raise ctypes.WinError(ctypes.get_last_error())
        return {'rect': rect_list(rect), 'size': [rect.right-rect.left, rect.bottom-rect.top],
                'normalRect': rect_list(placement.rcNormalPosition),
                'showCmd': placement.showCmd, 'dpi': self.user.GetDpiForWindow(hwnd)}

    def test_bounds(self):
        monitors = []

        @self.monitor_proc
        def callback(handle, _dc, _rect, _param):
            info = MonitorInfo(cbSize=ctypes.sizeof(MonitorInfo))
            if self.user.GetMonitorInfoW(handle, ctypes.byref(info)):
                monitors.append((bool(info.dwFlags & 1), rect_list(info.rcWork)))
            return True

        self.user.EnumDisplayMonitors(None, None, callback, 0)
        if not monitors:
            raise RuntimeError('No display work area is available')
        _, area = sorted(monitors, key=lambda item: item[0])[0]
        return [area[0]+48, area[1]+48, min(1120, area[2]-area[0]-96),
                min(780, area[3]-area[1]-96)]

    def resize(self, hwnd, bounds):
        if not self.user.SetWindowPos(hwnd, None, *bounds, 0x0004 | 0x0010):
            raise ctypes.WinError(ctypes.get_last_error())

    def maximize(self, hwnd):
        self.user.ShowWindowAsync(hwnd, 3)

    def restore(self, hwnd):
        self.user.ShowWindowAsync(hwnd, 9)


async def poll(predicate, timeout=15):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        value = predicate()
        if value:
            return value
        await asyncio.sleep(0.1)
    raise TimeoutError('Window state did not reach the expected value')


async def probe(page):
    await page.evaluate("document.dispatchEvent(new Event('window-check-refresh'))")
    return json.loads(await page.locator('#probe').inner_text())


def near(left, right, tolerance=3):
    return len(left) == len(right) and all(abs(a-b) <= tolerance for a, b in zip(left, right))


async def main(args):
    if sys.platform != 'win32':
        raise RuntimeError('This test requires Windows')
    executable = Path(args.executable).resolve(strict=True)
    report_dir = Path(args.report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    windows = Windows(executable)
    run_id = uuid.uuid4().hex[:10]
    report = {'executable': str(executable), 'run': run_id,
              'started': datetime.now(timezone.utc).isoformat(), 'cases': [], 'passed': False}

    def record(name, web, native):
        result = {'name': name, 'web': web, 'nativeWindow': native}
        report['cases'].append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)

    try:
        async with async_playwright() as playwright:
            @asynccontextmanager
            async def launch(name, config, profile='persistent'):
                marker = f'CamoufoxWindowCheck-{run_id}-{name}'
                env = {k: v for k, v in os.environ.items() if not k.startswith('CAMOU_CONFIG')}
                env['CAMOU_CONFIG'] = json.dumps({'showcursor': False, **config})
                context = await playwright.firefox.launch_persistent_context(
                    str(report_dir / 'profiles' / profile), executable_path=str(executable),
                    headless=False, no_viewport=True, env=env, timeout=60000)
                try:
                    page = context.pages[0] if context.pages else await context.new_page()
                    await page.goto(f'http://127.0.0.1:{server.server_port}/?title={marker}')
                    hwnd = await poll(lambda: windows.find(marker))
                    await page.wait_for_timeout(300)
                    yield page, hwnd
                finally:
                    await asyncio.wait_for(context.close(), timeout=30)

            async with launch('native-initial', {}) as (page, hwnd):
                initial = await probe(page)
                record('native-initial', initial, windows.state(hwnd))
                if not args.smoke:
                    bounds = windows.test_bounds()
                    if windows.state(hwnd)['showCmd'] == 3:
                        windows.restore(hwnd)
                        await poll(lambda: windows.state(hwnd)['showCmd'] != 3)
                    windows.resize(hwnd, bounds)
                    await poll(lambda: near(windows.state(hwnd)['size'], bounds[2:]))
                    await page.wait_for_timeout(1200)
                    native_saved = windows.state(hwnd)
                    native_after_resize = await probe(page)
                    record('native-resized', native_after_resize, native_saved)

            if not args.smoke:
                async with launch('native-restored', {}) as (page, hwnd):
                    restored = windows.state(hwnd)
                    assert near(restored['rect'], native_saved['rect']), (restored, native_saved)
                    record('native-restored', await probe(page), restored)

                portrait = {'screen.width': 2304, 'screen.height': 1296,
                            'window.outerWidth': 1680, 'window.outerHeight': 980,
                            'window.innerWidth': 1600, 'window.innerHeight': 860,
                            'window.screenX': 23, 'window.screenY': 41,
                            'window.devicePixelRatio': 1.25}
                async with launch('profile', {'window:profile': portrait}) as (page, hwnd):
                    before = windows.state(hwnd)
                    web = await probe(page)
                    assert near(before['rect'], native_saved['rect']), (before, native_saved)
                    assert web['screen']['width'] == 2304 and web['screen']['height'] == 1296, web
                    assert web['screen']['availWidth'] == 2304 and web['screen']['availHeight'] == 1296, web
                    assert web['outer'] == [1680, 980] and web['inner'] == [1600, 860], web
                    assert web['position'] == [23, 41] and web['dpr'] == 1.25, web
                    assert web['cssScreen'] and web['cssDpr'], web
                    record('profile-restored-native-window', web, before)
                    smaller = [bounds[0]+25, bounds[1]+20, bounds[2]-80, bounds[3]-40]
                    windows.resize(hwnd, smaller)
                    await poll(lambda: near(windows.state(hwnd)['size'], smaller[2:]))
                    await page.wait_for_timeout(1200)
                    profile_saved = windows.state(hwnd)
                    after = await probe(page)
                    assert after['outer'] == web['outer'] and after['inner'] == web['inner'], after
                    record('profile-real-window-resized', after, profile_saved)

                async with launch('profile-restored', {'window:profile': portrait}) as (page, hwnd):
                    assert near(windows.state(hwnd)['rect'], profile_saved['rect'])
                    record('profile-restored', await probe(page), windows.state(hwnd))
                    windows.maximize(hwnd)
                    await poll(lambda: windows.state(hwnd)['showCmd'] == 3)
                    await page.wait_for_timeout(1200)
                    record('profile-maximized', await probe(page), windows.state(hwnd))

                async with launch('profile-max-restored', {'window:profile': portrait}) as (page, hwnd):
                    assert windows.state(hwnd)['showCmd'] == 3, windows.state(hwnd)
                    record('profile-maximized-restored', await probe(page), windows.state(hwnd))

                global_config = {'screen.width': 1920, 'screen.height': 1080,
                                 'window.outerWidth': 1060, 'window.outerHeight': 760,
                                 'window:profile': portrait}
                async with launch('global-wins', global_config) as (page, hwnd):
                    web = await probe(page)
                    native = windows.state(hwnd)
                    scale = native['dpi'] / 96
                    assert native['showCmd'] != 3, native
                    assert near([v/scale for v in native['size']], [1060, 760], 16), native
                    assert web['outer'] == [1060, 760], web
                    assert web['screen']['width'] == 1920 and web['screen']['height'] == 1080, web
                    assert web['inner'] != [1600, 860], web
                    record('global-overrides-portrait-and-maximized-state', web, native)

                async with launch('explicit-native', {**global_config, 'window:mode': 'native'}) as (page, hwnd):
                    native = windows.state(hwnd)
                    scale = native['dpi'] / 96
                    web = await probe(page)
                    assert near(web['outer'], [v/scale for v in native['size']], 16), (web, native)
                    assert web['screen']['width'] == native_after_resize['screen']['width'], web
                    assert web['screen']['height'] == native_after_resize['screen']['height'], web
                    record('explicit-native-ignores-overrides', web, native)

            if not args.smoke or args.global_layout:
                legacy = {'screen.width': 1920, 'screen.height': 1080,
                          'screen.availWidth': 1920, 'screen.availHeight': 1040,
                          'window.outerWidth': 1120, 'window.outerHeight': 820,
                          'window.innerWidth': 1000, 'window.innerHeight': 680}
                async with launch('global-inner-outer', legacy, profile='global-layout') as (page, hwnd):
                    web = await probe(page)
                    native = windows.state(hwnd)
                    scale = native['dpi'] / 96
                    assert near([v/scale for v in native['size']], [1120, 820], 16), native
                    assert web['outer'] == [1120, 820] and web['inner'] == [1000, 680], web
                    assert near(web['root'], [1000, 680], 1), web
                    assert web['screen']['availWidth'] == 1920 and web['screen']['availHeight'] == 1040, web
                    record('legacy-global-pins-real-viewport', web, native)

                inner_only = {'window.innerWidth': 960, 'window.innerHeight': 640}
                async with launch('global-inner-only', inner_only, profile='global-layout') as (page, hwnd):
                    web = await probe(page)
                    native = windows.state(hwnd)
                    scale = native['dpi'] / 96
                    assert web['inner'] == [960, 640], web
                    assert near(web['root'], [960, 640], 1), web
                    assert near(web['outer'], [v/scale for v in native['size']], 16), (web, native)
                    record('legacy-inner-only-sizes-real-window', web, native)

        report['passed'] = True
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        report['traceback'] = traceback.format_exc()
        print(report['traceback'], flush=True)
    finally:
        server.shutdown()
        server.server_close()
        report['finished'] = datetime.now(timezone.utc).isoformat()
        output = report_dir / 'results.json'
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f'REPORT={output}', flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True)
    parser.add_argument('--report-dir', required=True)
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--global-layout', action='store_true')
    sys.exit(asyncio.run(main(parser.parse_args())))
