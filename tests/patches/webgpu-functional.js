async function inspectNativeContext() {
  if (!navigator.gpu) return { api: false };
  const adapter = await navigator.gpu.requestAdapter();
  if (!adapter) return { api: true, adapter: false };
  const info = {};
  for (const name of ['vendor', 'architecture', 'device', 'description',
                      'subgroupMinSize', 'subgroupMaxSize', 'isFallbackAdapter']) {
    info[name] = adapter.info[name];
  }
  const limits = {};
  for (const name of ['maxTextureDimension2D', 'maxBindGroups', 'maxBufferSize',
                      'maxStorageBufferBindingSize', 'minUniformBufferOffsetAlignment']) {
    limits[name] = adapter.limits[name];
  }
  return {
    api: true, adapter: true, info, limits,
    features: [...adapter.features], wgsl: [...navigator.gpu.wgslLanguageFeatures],
    format: navigator.gpu.getPreferredCanvasFormat(),
    nativeObjects: Object.prototype.toString.call(adapter) === '[object GPUAdapter]' &&
      Object.prototype.toString.call(adapter.info) === '[object GPUAdapterInfo]' &&
      Object.prototype.toString.call(adapter.features) === '[object GPUSupportedFeatures]' &&
      Object.prototype.toString.call(adapter.limits) === '[object GPUSupportedLimits]',
    sameObjects: adapter.info === adapter.info && adapter.limits === adapter.limits &&
      adapter.features === adapter.features && navigator.gpu === navigator.gpu,
  };
}

async function calculateOnDevice(device) {
  const input = new Uint32Array([2, 3, 5, 7]);
  const storage = device.createBuffer({size: input.byteLength,
    usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST | GPUBufferUsage.COPY_SRC});
  const readback = device.createBuffer({size: input.byteLength,
    usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST});
  device.queue.writeBuffer(storage, 0, input);
  const module = device.createShaderModule({code:
    '@group(0) @binding(0) var<storage,read_write> data: array<u32>; ' +
    '@compute @workgroup_size(1) fn main(@builtin(global_invocation_id) id: vec3u) {' +
    'data[id.x] = data[id.x] * 2u; }'});
  const pipeline = device.createComputePipeline({layout:'auto',compute:{module,entryPoint:'main'}});
  const bindings = device.createBindGroup({layout:pipeline.getBindGroupLayout(0),
    entries:[{binding:0,resource:{buffer:storage}}]});
  const encoder = device.createCommandEncoder();
  const pass = encoder.beginComputePass();
  pass.setPipeline(pipeline); pass.setBindGroup(0, bindings); pass.dispatchWorkgroups(4); pass.end();
  encoder.copyBufferToBuffer(storage,0,readback,0,input.byteLength);
  device.queue.submit([encoder.finish()]);
  await readback.mapAsync(GPUMapMode.READ);
  const values = [...new Uint32Array(readback.getMappedRange())];
  readback.unmap(); readback.destroy(); storage.destroy();
  return values;
}

async function renderOnDevice(device) {
  const texture = device.createTexture({size:[4,4],format:'rgba8unorm',
    usage:GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.COPY_SRC});
  const buffer = device.createBuffer({size:1024,usage:GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST});
  const module = device.createShaderModule({code:
    '@vertex fn vs(@builtin(vertex_index) i: u32) -> @builtin(position) vec4f {' +
    'var p = array<vec2f,3>(vec2f(-1.0,-1.0),vec2f(3.0,-1.0),vec2f(-1.0,3.0)); ' +
    'return vec4f(p[i],0.0,1.0); } ' +
    '@fragment fn fs() -> @location(0) vec4f { return vec4f(0.2,0.4,0.8,1.0); }'});
  const pipeline = device.createRenderPipeline({layout:'auto',
    vertex:{module,entryPoint:'vs'},fragment:{module,entryPoint:'fs',targets:[{format:'rgba8unorm'}]}});
  const encoder = device.createCommandEncoder();
  const pass = encoder.beginRenderPass({colorAttachments:[{view:texture.createView(),
    clearValue:{r:1,g:0,b:0,a:1},loadOp:'clear',storeOp:'store'}]});
  pass.setPipeline(pipeline); pass.draw(3); pass.end();
  encoder.copyTextureToBuffer({texture},{buffer,bytesPerRow:256},[4,4]);
  device.queue.submit([encoder.finish()]);
  await buffer.mapAsync(GPUMapMode.READ);
  const data = new Uint8Array(buffer.getMappedRange());
  const pixels = [];
  for (let y=0;y<4;y++) for (let x=0;x<4;x++) pixels.push([...data.slice(y*256+x*4,y*256+x*4+4)]);
  buffer.unmap(); buffer.destroy(); texture.destroy();
  return pixels;
}

async function runFunctionalChecks() {
  const result = {context:await inspectNativeContext()};
  if (!result.context.adapter) return result;
  const adapter = await navigator.gpu.requestAdapter();
  const device = await adapter.requestDevice();
  result.deviceInfo = {};
  for (const key of Object.keys(result.context.info)) result.deviceInfo[key] = device.adapterInfo[key];
  result.compute = await calculateOnDevice(device);
  result.render = await renderOnDevice(device);

  const canvas = document.createElement('canvas'); canvas.width=4; canvas.height=4;
  document.body.appendChild(canvas);
  const context = canvas.getContext('webgpu');
  const format = navigator.gpu.getPreferredCanvasFormat();
  context.configure({device,format,alphaMode:'opaque'});
  const encoder = device.createCommandEncoder();
  const pass = encoder.beginRenderPass({colorAttachments:[{view:context.getCurrentTexture().createView(),
    clearValue:{r:0,g:1,b:0,a:1},loadOp:'clear',storeOp:'store'}]});
  pass.end();device.queue.submit([encoder.finish()]);await device.queue.onSubmittedWorkDone();
  result.canvasConfigured = true;

  const configured = context.getConfiguration();
  result.canvasFormat = configured.format;
  context.unconfigure();canvas.remove();
  const requestError = async options => {
    try { const value=await adapter.requestDevice(options); value.destroy(); return null; }
    catch (error) { return error.name; }
  };
  result.tooManyBindGroups = await requestError({requiredLimits:{maxBindGroups:adapter.limits.maxBindGroups+1}});
  result.hiddenTimestampFeature = adapter.features.has('timestamp-query') ? 'available' :
    await requestError({requiredFeatures:['timestamp-query']});

  const wgsl = 'pointer_composite_access';
  device.pushErrorScope('validation');
  const languageModule = device.createShaderModule({code:
    'requires /* comment */ pointer_composite_access; @compute @workgroup_size(1) fn main() {}'});
  const languageInfo = await languageModule.getCompilationInfo();
  const languageError = await device.popErrorScope();
  result.languagePolicy = {
    advertised:navigator.gpu.wgslLanguageFeatures.has(wgsl),
    errors:languageInfo.messages.filter(message=>message.type==='error').length,
    validationError:!!languageError,
  };
  result.languageOperations = [];
  const languageShaders = [
    ['pointer_composite_access',
      '@compute @workgroup_size(1) fn main(){ var a:array<u32,2>; let p=&a; let x=p[0]; }'],
    ['readonly_and_readwrite_storage_textures',
      '@group(0) @binding(0) var t:texture_storage_2d<r32uint,read>; ' +
      '@compute @workgroup_size(1) fn main(){ let x=textureLoad(t,vec2i(0,0)); }'],
    ['packed_4x8_integer_dot_product',
      '@compute @workgroup_size(1) fn main(){let x=dot4U8Packed(1u,2u); let y=pack4xU8(vec4u(1u)); }'],
  ];
  for (const [feature,code] of languageShaders) {
    device.pushErrorScope('validation');
    const module=device.createShaderModule({code});
    const info=await module.getCompilationInfo();
    const error=await device.popErrorScope();
    result.languageOperations.push({feature,advertised:navigator.gpu.wgslLanguageFeatures.has(feature),
      errors:info.messages.filter(item=>item.type==='error').length,validationError:!!error});
  }
  result.requests = [];
  for (const options of [{powerPreference:'high-performance'}, {powerPreference:'low-power'},
                         {forceFallbackAdapter:true}]) {
    const value = await navigator.gpu.requestAdapter(options);
    result.requests.push({options, adapter:!!value, vendor:value?.info.vendor,
      fallback:value?.info.isFallbackAdapter});
  }

  const frame=document.createElement('iframe');frame.src=location.href;
  const ready=new Promise(resolve=>frame.onload=resolve);document.body.appendChild(frame);await ready;
  result.iframe = await frame.contentWindow.eval('(' + inspectNativeContext.toString() + ')()');
  frame.remove();
  const workerSource = inspectNativeContext.toString() + '\n' + calculateOnDevice.toString() +
    '\nonmessage=async()=>{try{const context=await inspectNativeContext();' +
    'const adapter=await navigator.gpu.requestAdapter();const device=await adapter.requestDevice();' +
    'const compute=await calculateOnDevice(device);device.destroy();postMessage({context,compute});' +
    '}catch(error){postMessage({error:String(error)});}};';
  const url=URL.createObjectURL(new Blob([workerSource],{type:'text/javascript'}));
  const worker=new Worker(url);
  result.worker = await new Promise((resolve,reject)=>{
    worker.onmessage=event=>resolve(event.data);worker.onerror=event=>reject(new Error(event.message));worker.postMessage({});
  });
  worker.terminate();URL.revokeObjectURL(url);
  device.destroy();
  return result;
}
