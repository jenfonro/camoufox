/* Ordinary page/Worker probes. Complete bytes are retained, never URL prefixes. */
function fpBytes(data) {
  const bytes = data instanceof ArrayBuffer ? new Uint8Array(data) :
    new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 16384)
    binary += String.fromCharCode(...bytes.subarray(i, i + 16384));
  return btoa(binary);
}

async function fpDigest(data) {
  const bytes = typeof data === 'string' ? new TextEncoder().encode(data) : data;
  const result = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  return Array.from(result, n => n.toString(16).padStart(2, '0')).join('');
}

function fpAssert(value, message) {
  if (!value) throw new Error(message);
}

function fpCanvas(offscreen, text = false) {
  const canvas = offscreen ? new OffscreenCanvas(128, 64) : document.createElement('canvas');
  canvas.width = 128;
  canvas.height = 64;
  const ctx = canvas.getContext('2d');
  fpAssert(ctx, 'Canvas 2D unavailable');
  const gradient = ctx.createLinearGradient(0, 0, 128, 64);
  gradient.addColorStop(0, '#126ac3');
  gradient.addColorStop(1, '#fa7632');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 128, 64);
  ctx.fillStyle = 'rgba(17, 241, 83, .7)';
  ctx.beginPath();
  ctx.ellipse(62, 30, 37, 19, .2, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = '#ffffff';
  ctx.lineWidth = 1.25;
  ctx.beginPath();
  ctx.moveTo(3, 52);
  ctx.bezierCurveTo(33, -8, 71, 80, 124, 11);
  ctx.stroke();
  if (text) {
    ctx.font = '16px Arial';
    ctx.fillStyle = '#14305f';
    ctx.fillText('Camoufox mW π', 2, 27);
  }
  return {canvas, ctx};
}

async function fpBlob(canvas, type) {
  const blob = canvas.convertToBlob ? await canvas.convertToBlob({type, quality: .92}) :
    await new Promise(resolve => canvas.toBlob(resolve, type, .92));
  fpAssert(blob && blob.type === type, 'Image encoder unavailable: ' + type);
  return 'data:' + type + ';base64,' + fpBytes(await blob.arrayBuffer());
}

async function fpImage(offscreen = false, text = false) {
  const {canvas, ctx} = fpCanvas(offscreen, text);
  const report = {};
  for (const type of ['image/png', 'image/jpeg', 'image/webp']) {
    const first = canvas.toDataURL ? canvas.toDataURL(type, .92) : await fpBlob(canvas, type);
    const second = canvas.toDataURL ? canvas.toDataURL(type, .92) : await fpBlob(canvas, type);
    fpAssert(first === second, 'Repeated complete export changed: ' + type);
    const blob = await fpBlob(canvas, type);
    fpAssert(first === blob, 'Data URL and Blob disagree: ' + type);
    report[type] = {bytes: first, sha256: await fpDigest(first)};
  }
  const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
  fpAssert(fpBytes(pixels) === fpBytes(ctx.getImageData(0, 0, canvas.width, canvas.height).data),
    'Repeated pixel read changed');
  const crop = ctx.getImageData(7, 11, 19, 17).data;
  report.pixels = {bytes: fpBytes(pixels), sha256: await fpDigest(pixels)};
  report.crop = {bytes: fpBytes(crop), sha256: await fpDigest(crop)};
  report.textWidth = ctx.measureText('Camoufox mW π').width;
  return report;
}

async function fpWebGL(kind) {
  const canvas = document.createElement('canvas');
  canvas.width = 32;
  canvas.height = 16;
  const gl = canvas.getContext(kind, {preserveDrawingBuffer: true});
  if (!gl) return {supported: false};
  gl.clearColor(.2, .4, .8, 1);
  gl.clear(gl.COLOR_BUFFER_BIT);
  gl.enable(gl.SCISSOR_TEST);
  gl.scissor(3, 2, 17, 9);
  gl.clearColor(.8, .1, .3, 1);
  gl.clear(gl.COLOR_BUFFER_BIT);
  gl.finish();
  const pixels = new Uint8Array(32 * 16 * 4);
  gl.readPixels(0, 0, 32, 16, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
  fpAssert(pixels.some(n => n !== 0), kind + ' did not render');
  const debug = gl.getExtension('WEBGL_debug_renderer_info');
  const report = {supported: true, pixels: fpBytes(pixels), pixelHash: await fpDigest(pixels),
    png: canvas.toDataURL(), vendor: gl.getParameter(gl.VENDOR), renderer: gl.getParameter(gl.RENDERER),
    unmaskedVendor: debug ? gl.getParameter(debug.UNMASKED_VENDOR_WEBGL) : null,
    unmaskedRenderer: debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : null,
    extensions: gl.getSupportedExtensions().sort(), maxTextureSize: gl.getParameter(gl.MAX_TEXTURE_SIZE)};
  fpAssert(report.png === canvas.toDataURL(), kind + ' export changed on reread');
  gl.getExtension('WEBGL_lose_context')?.loseContext();
  return report;
}

async function fpGPU() {
  if (!navigator.gpu) return {supported: false};
  const adapter = await navigator.gpu.requestAdapter();
  if (!adapter) return {supported: true, adapter: false};
  const info = {};
  for (const key of ['vendor', 'architecture', 'device', 'description',
    'subgroupMinSize', 'subgroupMaxSize', 'isFallbackAdapter']) info[key] = adapter.info[key];
  const limits = {};
  for (const key in adapter.limits) if (typeof adapter.limits[key] === 'number') limits[key] = adapter.limits[key];
  return {supported: true, adapter: true, info, limits,
    features: Array.from(adapter.features).sort(),
    format: navigator.gpu.getPreferredCanvasFormat(),
    wgsl: Array.from(navigator.gpu.wgslLanguageFeatures).sort()};
}

async function fpAudio() {
  const context = new OfflineAudioContext(1, 8192, 44100);
  const oscillator = context.createOscillator();
  const compressor = context.createDynamicsCompressor();
  oscillator.type = 'triangle';
  oscillator.frequency.value = 10000;
  compressor.threshold.value = -50;
  compressor.knee.value = 40;
  compressor.ratio.value = 12;
  compressor.attack.value = 0;
  compressor.release.value = .25;
  oscillator.connect(compressor).connect(context.destination);
  oscillator.start();
  const buffer = await context.startRendering();
  const copyBeforeRead = new Float32Array(buffer.length);
  const sliceBeforeRead = new Float32Array(511);
  buffer.copyFromChannel(copyBeforeRead, 0);
  buffer.copyFromChannel(sliceBeforeRead, 0, 113);
  const full = buffer.getChannelData(0).slice();
  fpAssert(full.some(n => n !== 0), 'Offline audio was silent');
  fpAssert(fpBytes(full) === fpBytes(copyBeforeRead), 'Audio read methods disagree');
  fpAssert(fpBytes(full.subarray(113, 624)) === fpBytes(sliceBeforeRead), 'Audio offset read disagrees');
  const original = fpBytes(full);
  for (let i = 0; i < 3; ++i) {
    const sink = new OfflineAudioContext(1, buffer.length, buffer.sampleRate);
    const source = sink.createBufferSource();
    source.buffer = buffer;
    source.connect(sink.destination);
    source.start();
    const after = buffer.getChannelData(0);
    fpAssert(original === fpBytes(after), 'Audio changed after acquiring channels for playback');
    const copied = new Float32Array(511);
    buffer.copyFromChannel(copied, 0, 113);
    fpAssert(fpBytes(copied) === fpBytes(sliceBeforeRead), 'Audio offset changed after acquisition');
    await sink.startRendering();
  }
  // Caller-provided channel data must also survive acquire/restore unchanged.
  const sink = new OfflineAudioContext(1, 256, 44100);
  const written = sink.createBuffer(1, 256, 44100);
  const input = Float32Array.from({length: 256}, (_, i) => Math.sin(i / 7) * .3);
  written.copyToChannel(input, 0);
  const source = sink.createBufferSource();
  source.buffer = written;
  source.connect(sink.destination);
  source.start();
  fpAssert(fpBytes(written.getChannelData(0)) === fpBytes(input), 'Caller audio data was transformed twice');
  await sink.startRendering();
  return {sampleRate: buffer.sampleRate, bytes: original, sha256: await fpDigest(full),
    slice: fpBytes(sliceBeforeRead), repeatedReads: true, acquisitionCycles: 3};
}

function fpFonts() {
  const fonts = ['Arial', 'Times New Roman', 'monospace', 'serif', 'sans-serif',
    'Segoe UI', 'system-ui', 'Arimo', 'Cousine'];
  const text = 'The quick brown fox jumps over the lazy dog';
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  const result = {};
  for (const font of fonts) {
    ctx.font = '16px ' + (font.includes(' ') ? JSON.stringify(font) : font);
    const el = document.createElement('div');
    el.style.cssText = 'position:absolute;left:-9999px;top:0;padding:0;border:0;font-size:16px;';
    el.style.fontFamily = font;
    el.textContent = text;
    document.body.appendChild(el);
    const range = document.createRange();
    range.selectNode(el);
    result[font] = {canvas: ctx.measureText(text).width,
      rects: Array.from(range.getClientRects(), r => r.toJSON()),
      available: document.fonts.check('16px ' + JSON.stringify(font))};
    el.remove();
  }
  return result;
}

function fpNavigator() {
  const result = {};
  for (const key of ['userAgent', 'appVersion', 'appName', 'appCodeName', 'product',
    'productSub', 'vendor', 'platform', 'oscpu', 'hardwareConcurrency', 'maxTouchPoints',
    'language', 'languages', 'doNotTrack', 'cookieEnabled', 'pdfViewerEnabled'])
    if (key in navigator) result[key] = navigator[key];
  result.intl = Intl.DateTimeFormat().resolvedOptions();
  return result;
}

async function fpWorkerProbe(progress = () => {}) {
  progress('fonts.ready');
  // No downloadable fonts are registered by this probe. Firefox initializes
  // an empty Worker FontFaceSet lazily; wait only when it actually has faces.
  if (globalThis.fonts && fonts.size) await fonts.ready;
  progress('image');
  const image = await fpImage(true);
  progress('text');
  const text = await fpImage(true, true);
  progress('gpu');
  return {image, text, navigator: fpNavigator(), gpu: await fpGPU()};
}

async function fpMainProbe() {
  await document.fonts.ready;
  const image = await fpImage();
  const text = await fpImage(false, true);
  const fontsBefore = fpFonts();
  const fontsAfter = fpFonts();
  fpAssert(JSON.stringify(fontsBefore) === JSON.stringify(fontsAfter), 'Font/layout metrics changed on reread');
  const screenReport = {};
  for (const key of ['width', 'height', 'availWidth', 'availHeight', 'availLeft', 'availTop', 'colorDepth', 'pixelDepth'])
    screenReport[key] = screen[key];
  for (const key of ['innerWidth', 'innerHeight', 'outerWidth', 'outerHeight', 'devicePixelRatio', 'screenX', 'screenY'])
    screenReport[key] = window[key];
  let voices = speechSynthesis.getVoices();
  if (!voices.length) {
    // A voiceschanged event may still carry an empty initial engine snapshot.
    // Compare the completed list, not an arbitrary two-second startup sample.
    await new Promise((resolve, reject) => {
      const check = () => {
        voices = speechSynthesis.getVoices();
        if (voices.length) {
          clearTimeout(timer);
          speechSynthesis.removeEventListener('voiceschanged', check);
          resolve();
        }
      };
      const timer = setTimeout(() => {
        speechSynthesis.removeEventListener('voiceschanged', check);
        reject(new Error('Speech voice list did not initialize'));
      }, 15000);
      speechSynthesis.addEventListener('voiceschanged', check);
      check();
    });
  }
  return {image, text, fonts: fontsBefore, audio: await fpAudio(),
    webgl: await fpWebGL('webgl'), webgl2: await fpWebGL('webgl2'), gpu: await fpGPU(),
    navigator: fpNavigator(), screen: screenReport,
    voices: voices.map(v => ({name: v.name, lang: v.lang, voiceURI: v.voiceURI, localService: v.localService, default: v.default})),
    mediaDevices: (await navigator.mediaDevices.enumerateDevices()).map(d => d.toJSON())};
}

if (typeof document === 'undefined') {
  if (typeof ServiceWorkerGlobalScope !== 'undefined' && self instanceof ServiceWorkerGlobalScope) {
    self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
    self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
    self.addEventListener('message', event => event.waitUntil(fpWorkerProbe(progress => event.ports[0].postMessage({progress})).then(
      result => event.ports[0].postMessage(result), error => event.ports[0].postMessage({error: String(error)}))));
  } else if (typeof SharedWorkerGlobalScope !== 'undefined' && self instanceof SharedWorkerGlobalScope) {
    self.onconnect = event => {
      const port = event.ports[0];
      port.onmessage = () => fpWorkerProbe(progress => port.postMessage({progress})).then(result => port.postMessage(result), error => port.postMessage({error: String(error)}));
      port.start();
    };
  } else {
    self.onmessage = () => fpWorkerProbe(progress => self.postMessage({progress})).then(result => self.postMessage(result), error => self.postMessage({error: String(error)}));
  }
}
