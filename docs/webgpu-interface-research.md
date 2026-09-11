# WebGPU 画像接口通用性调研

本文件保留调研事实及定稿前的方案演变。用户已授权助手决定细节，
现已收敛为[配置规范 v1](webgpu-configuration.md)。下文出现的“待确认”
和候选建议是当时状态，最终行为以配置规范为准。用户随后已授权
完整实现与测试；实现状态见事项记录，不以本调研的历史状态为准。

日期：2026-09-11。状态：仅调研与方案建议，未开始实现、构建或浏览器测试。

用户要求内核接口面向通用管理器，不为 Nimbo 单独设计。调研结论是：
画像内部的数据优先采用 W3C WebGPU 与当前 Firefox WebIDL 的名称、类型
和对象关系；外层继续兼容 Camoufox 的配置载体。各管理器转换自己的
模式值、档案模型及生成规则。具体新参数名称尚未确定。

这些管理器的业务格式并不统一。WebGPU 标准定义的是网页 API，未定义
浏览器画像注入协议；不能将我们新增的配置包装称为现成的行业标准。
OpenAPI 标准化了接口描述方式，也不代表使用 OpenAPI 的产品具有相同
的指纹字段或模式语义。

## 对照结果

| 来源 | 已核对的数据形状 | 对内核设计的意义 |
| --- | --- | --- |
| VirtualBrowser 2.2.15 客户端及官方 API | `gpu.{mode,value}`；`webgpu.{mode,vendor,architecture}`；WebGL 使用 `webgl.{mode,vendor,render}` | 控制项与数据可以分开；数字模式值与 `render` 等命名属于产品接口约定 |
| polyackiy/camoufox-profile-manager | 管理层 `BrowserSettings`；解析后的画像保留 Camoufox 的 `webGl:vendor`、`webGl:renderer` 等原生配置键 | 管理器负责生成、保存、回放和转换，内核不依赖它的档案对象 |
| Kameleo 5.2.0 / Junglefox（Firefox） | `webglMeta.value` 为 `automatic/manual/off`，`extra` 含 `vendor/renderer`；`webgl` 另有 `noise/block/off` | 模式语义必须由管理器映射；关闭伪装和关闭 API 是不同操作 |
| Multilogin 公开 API（含 Stealthfox） | `parameters.flags.graphics_masking/graphics_noise` 与 `parameters.fingerprint.graphic.{vendor,renderer}` 分离 | 可参考控制与画像数据分离，不应复制整套管理业务对象 |
| Firefox WebDriver | `moz:firefoxOptions` 下的 `args`、`prefs`、`env` | 启动配置、偏好值和传输载体有成熟约定，但它不是完整的 GPU 画像标准 |

### VirtualBrowser 的证据边界

检查了本机 `C:/Program Files/VirtualBrowser/resources/app.asar` 中的
`package.json` 和只读客户端资源，版本为 2.2.15。相关表单对象位于
`dist/server/static/js/chunk-7655c4a1.js`。未执行这些客户端脚本，未读取
用户档案、Cookie、登录数据，也未操作 VirtualBrowser 窗口或管理接口。

客户端的 API 文档入口指向 [VirtualBrowser API](https://2uzg2znjfy.apifox.cn/)。
[获取环境完整参数](https://2uzg2znjfy.apifox.cn/288407060e0.md) 的公开示例
包含 `webgl`、`webgl-img` 和 `gpu`；该示例没有列出 WebGPU 数据。
本机客户端模型则可见 `webgpu` 的模式、厂商与架构字段。

这不能证明其全部底层 WebGPU 接口只支持这几个字段，也不能仅凭
数字 `mode` 推断其含义。它是接口形状的参考，不能直接当作完整的
WebGPU 画像规范。

### CPM 的证据边界

读取本机评估仓库，origin 为
[polyackiy/camoufox-profile-manager](https://github.com/polyackiy/camoufox-profile-manager)，
HEAD 为 `68a3256ca157eea4aebbe37e44cf293e630384da`。
`fingerprint_store.py` 另有此前的 Windows 配置分块拼接修改，本轮未改动。

- `core/models.py` 将管理层字段转换为 Camoufox 配置。
- `core/fingerprint_store.py` 保存解析后的原生配置；冻结前缀包括
  `webGl:`、`webGl2:`，本次读取版本没有 WebGPU 前缀。
- `api/models/profiles.py` 的 `additional_options` 可传入额外 Camoufox 选项。
- 本次读取的 Python 核心与接口模型没有专用 WebGPU 画像定义。

因此不能宣称新接口一经加入内核，CPM 就会自动保存并回放它。管理器可能
需要适配其持久化白名单；不应为了绕过这一步把 WebGPU 数据塞入 WebGL
命名空间。另有 `webgl_noise` 等管理字段只保存意图而不下发，字段存在
也不等于内核已支持其对应行为。

### 其他 Firefox 管理器

Kameleo 使用官方发布的
[Python SDK 5.2.0](https://pypi.org/project/kameleo.local-api-client/5.2.0/)
及[公开源仓库](https://github.com/kameleo-io/kameleo)。SDK 文档明确包含
Junglefox（Firefox）；`BrowserSettings` 支持启动参数和 preferences。
本次读取的模型未见专用 WebGPU 画像定义，不据此判断其引擎是否支持 WebGPU。

特别注意其 `webglMeta=off` 表示使用原始元数据；`webgl=block` 才表示
阻止 3D API。不能把不同产品的 `off`、`disabled`、数字模式值直接混用。

Multilogin 使用其[官方 API 入口](https://multilogin.com/help/en_US/api)链接的
[公开 Postman 文档](https://documenter.getpostman.com/view/28533318/2s946h9Cv9)。
`Launcher / Start Quick Profile v3` 示例将 graphics flags 与 `graphic`
画像数据分开。公开文档包含 Stealthfox 的启动说明，但本次没有找到完整
的 WebGPU `info/features/limits` 画像模型；也不据此承诺所有图形字段在
各引擎上都具有相同效果。

## 建议采用的标准数据模型

依据 [W3C WebGPU](https://www.w3.org/TR/webgpu/) 与当前构建对应的
[Firefox WebGPU.webidl](https://github.com/mozilla-firefox/firefox/blob/d4faced9e237d6431856c0873cb035cbbc25817b/dom/webidl/WebGPU.webidl)。

| 对象或字段 | 标准名称与类型 | JSON 表达建议 |
| --- | --- | --- |
| `GPUAdapterInfo` 身份字段 | `vendor`、`architecture`、`device`、`description` 为字符串 | 保留原名称的字符串属性 |
| `GPUAdapterInfo` 其他属性 | `subgroupMinSize`、`subgroupMaxSize` 为无符号整数；`isFallbackAdapter` 为布尔值 | 数字和布尔值，不用产品私有数字模式表示 |
| `GPUSupportedFeatures` | 功能名称集合，例如 `texture-compression-bc`、`shader-f16` | 字符串数组，按集合语义处理 |
| `GPUSupportedLimits` | `maxTextureDimension2D`、`maxBindGroups` 等标准 camelCase 名称 | 同名数值属性 |
| 大容量限制值 | `maxBufferSize`、`maxUniformBufferBindingSize`、`maxStorageBufferBindingSize` 为 64 位无符号整数 | 解析与存储不能截断为 32 位；还需明确 JSON 数值的精确范围 |
| `GPURequestAdapterOptions` | `powerPreference`、`forceFallbackAdapter`、`featureLevel`、`xrCompatible` | 将来若表达适配器请求匹配条件，沿用标准字段与值 |

`powerPreference` 使用 `low-power`、`high-performance` 等标准值。
WebGL 的 `renderer` 与 WebGPU 的 `description` 不应因为含义相近就混为
同一个字段；管理器需要根据真实的数据来源进行转换。

Firefox 的 `wgpuName`、`wgpuVendor`、`wgpuDevice`、`wgpuDriver`、
`wgpuBackend` 等在当前 WebIDL 中明确标为非标准、`ChromeOnly`。
它们可用于内部诊断，不应冒充通用网页画像字段。BrowserScan 页面上的
`Empty`、`undefined`、`Adapter #0` 等展示文字也不是标准输入值。

### 数据对象形状示意

以下仅说明标准字段如何组成数据对象，未确定 Camoufox 外层参数名，
也未确定部分字段输入的覆盖规则：

```json
{
  "info": {
    "vendor": "example-vendor",
    "architecture": "example-architecture",
    "device": "example-device",
    "description": "Example adapter",
    "subgroupMinSize": 4,
    "subgroupMaxSize": 128,
    "isFallbackAdapter": false
  },
  "features": ["texture-compression-bc", "timestamp-query"],
  "limits": {
    "maxTextureDimension2D": 8192,
    "maxBindGroups": 4,
    "maxBufferSize": 268435456
  }
}
```

例子展示结构，不代表这些示例身份值构成了某张显卡的完整、有效画像。

## 与 Camoufox 及既定职责衔接

建议继续通过现有 `CAMOU_CONFIG` JSON 与配置校验机制承载新能力，
扩展对应的 `settings/properties.json`、`settings/camoucfg.jvv` 定义。
这些是未来实现方向，本轮没有修改它们。硬件加速与 WebGPU 暴露开关
属于内核配置扩展，其名称本身并非 W3C 标准，不能混同于画像内部字段。

各管理器负责将自己的格式转换成这套明确记录的内核配置：

- Nimbo 的档案 ID、数据库结构和生成策略不进入内核协议。
- VirtualBrowser 的数字 `mode`、Kameleo 的自动画像选择、Multilogin 的
  masking flags 不直接成为内核内部的通用枚举。
- 内核不替管理器生成画像、挑选设备型号或增加自动后端选择策略。
- 已确认的缺省规则保持不变：显式开放 WebGPU 但完全未输入画像时，
  使用当前内核原生返回值，不因缺失画像增加关闭接口或报错行为。

[Firefox 的 moz:firefoxOptions](https://developer.mozilla.org/en-US/docs/Web/WebDriver/Reference/Capabilities/firefoxOptions)
也说明了 `prefs`、`env` 和启动参数可以由不同工具传入。图形设置的传输
不必依赖某一个管理器、语言、REST 服务或数据库。

## 定稿前列出的标准语义问题

1. 部分画像字段未提供时如何处理，以及 `features` 是完整集合还是覆盖片段。
   建议区分字段不存在、空字符串、`false`、`0` 与空数组，不用真假判断
   将显式输入当成“未传”。此项建议尚未作为完整覆盖规则确认。
2. 标准没有公开的适配器枚举列表 API。多个画像与不同
   `requestAdapter(options)` 请求如何对应，需要独立设计；不能直接把
   BrowserScan 的编号条目当作内核协议。
3. `GPUAdapter.info` 与 `GPUDevice.adapterInfo`、Window 与 Worker 都应遵循
   同一套配置语义。设备 features/limits 与请求校验仍按 WebGPU 规则衔接，
   不应简单让设备和适配器的所有限制值一律相同。
4. 标准版本与内核版本要明确。当前 W3C 文档中已有
   `texture-formats-tier1`、`texture-formats-tier2`、`subgroup-size-control`
   等当前 Firefox 152 WebIDL 尚未包含的功能名称。不能只复制最新标准
   全集就宣称当前构建支持。
5. `wgslLanguageFeatures`、首选画布格式等属于 `GPU` 层级，不应混放到
   `GPUAdapterInfo`。是否纳入第二项的覆盖范围仍待讨论。

## 进一步收敛的 Firefox 接口草案

用户继续确认：优先按 Firefox 内核本身进行通用支持，管理器产品只作为
参考。以下是据此收敛的设计建议，尚未确定最终参数名或开始实现。

### 复用原生控制机制

| 职责 | 当前 Firefox/Camoufox 已有机制 | 建议边界 |
| --- | --- | --- |
| 允许硬件加速 | `HardwareAcceleration` 策略、`layers.acceleration.disabled` 及图形初始化 | 新参数解除 Camoufox 自带禁用策略；保留 Firefox 的设备判断 |
| 是否开放网页 WebGPU | `dom.webgpu.enabled` 与 `Instance::PrefEnabled()` | 使用原生接口暴露机制，与硬件加速许可独立 |
| 覆盖画像数据 | Camoufox 已有 `CAMOU_CONFIG` JSON，WebGPU 暂无对应画像配置 | 只为缺少的数据覆盖能力增加配置，数据结构按 WebGPU API |

如果统一通过 Camoufox JSON 接收两个开关，JSON 只是对上述原生机制的
入口映射，不再建立另一套与 Firefox prefs 同时生效却相互冲突的状态。
参数、profile 偏好与发行策略的优先级需要写清楚。只设置
`layers.acceleration.disabled=false` 仍可能被当前锁定策略覆盖，不能
将它当作解除发行策略的完整实现。

`layers.acceleration.force-enabled` 和 `layers.d3d11.force-warp` 仍是
Firefox 自己的特定用途偏好，不应成为我们“允许硬件加速”开关的隐含
行为。管理器选择是否传入何种配置，内核不新增自动硬件挑选策略。

### 原生关闭与原生失败要区分

当前上游 Windows 构建在已测默认配置下仍有 `navigator.gpu`，
`requestAdapter()` 因设备路径失败而返回 `null`。
`dom.webgpu.enabled=false` 则通过原生 WebIDL 条件关闭网页接口的暴露。
两种状态在 BrowserScan 上都可显示 `not support`，但对网页并不等价。

因此，用户提出的“WebGPU 默认不暴露”是独立的扩展行为，不能描述成
完全没有改变上游网页 API。方案建议采用原生关闭机制，不为模拟某个
检测网站的文案另造一条始终返回 `null` 的接口路径。保留上游其他机制
与采用这一项明确的默认策略调整，应在接口文档中分别说明。

开启总开关也不自动开启 Service Worker 的 WebGPU：当前
`Instance::PrefEnabled()` 对 Service Worker 还检查
`dom.webgpu.service-workers.enabled`。保留 Firefox 已有的上下文条件、
安全上下文要求及其他原生限制。

### 原生对象语义

输入可以是通用 JSON，返回给网页的对象仍应是 Firefox 实现的
`GPUAdapterInfo`、`GPUSupportedFeatures`、`GPUSupportedLimits` 等，
不能将它们替换成带有相似字段的普通对象。应保留原型、只读属性、
集合方法、`SameObject` 和 Promise 的原生行为。

`GPUAdapter.info` 与派生设备的 `GPUDevice.adapterInfo` 应来自同一份
画像策略。Window、iframe 与支持 WebGPU 的 Worker 应使用一致配置；
是否存在接口仍由原生暴露条件决定。

### 输入覆盖的建议语义

下列是待确认建议，不能当作已新增的可调用字段：

- 完全不传画像：已由用户确认，保留当前内核原生数据。
- `info`、`limits` 的部分字段未传：建议只覆盖显式字段，其余保留原生值。
  这意味着部分画像不保证跨不同后端得到完全相同的报告，管理器按需要
  传入完整数据。
- `features` 未传：保留原生集合。显式传入数组：建议定义为完整的对外
  功能集合，而不是与本机功能取并集。集合还须符合相应 feature level
  的必要功能与依赖规则，不能任意宣称一个不成立的能力组合。
- 字段不存在、空字符串、`false`、`0`、空数组需要分别处理；后四者不能
  一律视为未传。字段类型和范围按 WebIDL 及现有配置校验机制说明。
- 对未定义参数及错误类型的处理需有统一规则；“缺失画像不兜底”不等于
  放弃语法和类型定义，也不应因此自动生成画像、改用另一设备或隐式
  关闭整个 WebGPU。

### 能力覆盖需要贯通原生请求与执行

`GPUDevice.features` 和 `GPUDevice.limits` 由页面的 `requestDevice()`
请求及原生默认能力共同决定，不是简单复制适配器上所有值。画像层须
与 `requiredFeatures`、`requiredLimits` 的校验衔接：对外声明可用的
能力应能实际使用；对外不提供的能力不应通过换一种请求绕过。

限制值还存在方向差异。例如较大的 `maxBufferSize` 表示能力更强，
较小的 `minUniformBufferOffsetAlignment` 表示对齐要求更宽松。
不能把所有限制值用相同的 `min()` 或 `max()` 合并，更不能悄悄改成
另一个值后仍称其为稳定的输入画像。

本项设计不包含为后端缺少的功能开发软件实现。管理器负责选择合适的
后端与画像；正常的设备不可用、请求验证、设备丢失等仍按 WebGPU/Firefox
行为处理。不能只改 `features.has()` 或 limits getter 而留下另一套
实际执行状态。

### 单适配器数据与多请求结果分开设计

`info/features/limits` 描述的是一次请求返回的适配器。
`powerPreference`、`forceFallbackAdapter` 等是页面的标准请求选项，
不能因输入了画像就自动解释为管理器对执行后端的选择。

怎样为普通、高性能、低功耗、fallback 请求提供稳定的画像对应关系
仍需进一步确认。标准没有 `navigator.gpu.adapters` 这样的枚举接口；
BrowserScan 的条目数量也是它根据多次请求自行整理出来的。
因此不能承诺只填写一个 `info` 对象就能稳定所有请求组合或所有站点
的报告哈希，也不应把某个网站的编号和去重逻辑写进内核协议。

本轮只核对了现有配置解析器、缓存的 W3C 文档、Firefox WebIDL 及
`Instance.cpp`，没有运行新的浏览器测试，也没有修改生产代码或配置。

## 定稿前的四项契约与建议

本次按用户“还需要什么细化”的要求检查草案。以下是建议，不自动标为
用户已经确认，也不构成开始实现的授权。此前已定的两开关独立、无画像
走原生、管理器负责生成与后端选择，不再作为待讨论问题。

| 待明确项 | 建议规则 | 为什么影响实现 |
| --- | --- | --- |
| 部分字段如何覆盖 | `info`、`limits` 按字段覆盖，未传字段保留原生；`features` 未传保留原生，传入则作为完整对外集合 | 避免同一输入在不同后端被隐式补成不同集合；区分部分覆盖与完整画像 |
| 不同适配器请求对应哪份画像 | 支持通用适配器画像，并允许按标准 `GPURequestAdapterOptions` 给出特定覆盖；无通用数据且无匹配覆盖时保留原生 | 普通、高性能、低功耗与 fallback 请求可能产生不同报告条目，只改一个型号不能覆盖这些差异 |
| 标准入口的覆盖范围 | 除 `info/features/limits`，建议把当前 Firefox 已支持的 `GPU.wgslLanguageFeatures` 与 `getPreferredCanvasFormat()` 返回值也作为可选、独立层级数据；派生设备与支持的上下文保持一致 | 不把只有适配器字段的配置误称为完整 WebGPU 画像；也不把全局字段错误放入 AdapterInfo |
| 错误与能力不兼容如何处理 | 类型、范围错误在配置校验中报告；实际能力不兼容明确反馈或沿用相应原生请求失败，不静默改值，不自动造能力 | 保留标准执行行为，避免画像只改显示却造成另一套不一致的实际能力 |

第一项的例子：只传 `info.vendor` 就只覆盖 vendor；不填写的 architecture
和 limits 仍是原生数据。显式 `false`、空字符串或空集合不能当作未传，
但它们是否有效仍取决于对应 WebIDL 类型与能力规则。部分画像本身不
承诺跨后端得到相同哈希。

第二项控制的是返回数据的匹配，不替管理器挑选执行后端。普通请求与
明确 `forceFallbackAdapter=true` 的请求仍按 Firefox 的实际设备路径
处理；后端原生返回 `null` 时不凭画像制造可执行适配器。画像匹配条件
采用标准请求字段，不采用 BrowserScan 条目编号。
通用画像与特定覆盖建议按字段叠加，特定覆盖优先；配置须保持标准
请求语义，例如显式 fallback 请求应与其返回的回退状态一致。
同一优先级条件重叠时如何校验、请求缺省值如何归一化，属于这项契约
落地时要写清的规则，不新增自动设备匹配或随机挑选功能。

第三项中的 WGSL 功能数组应与实际编译器能力一致，首选画布格式应与
画布配置、纹理使用等原生行为衔接。它们是 WebGPU 标准数据入口，不
扩展到任意网站哈希、性能时间、Canvas 像素噪声或 Firefox 的 ChromeOnly
诊断字段。具体纳入范围仍是待确认建议。

第四项需要区分缺失和无效：完全缺失画像是已支持的原生模式；明确
传错类型或宣称不可兑现的能力则不是同一情况。不以容错为由随机生成
画像、增加软件模拟或自动关闭 WebGPU；也不承诺仅靠参数能模拟任意 GPU。

参数拼写、统一配置入口、启动读取顺序、显式参数与已有偏好的优先级、
32/64 位数值处理、Window/Worker 和设备对象一致性属于实现时必须处理
的接口细节。它们需要写入接口文档，但不必全部变成新的用户选项。

本次只更新了设计记录，没有启动浏览器、修改内核实现或执行构建。

调研原始资料保存在忽略目录 `camoufox-api-research/`。以上资料来自公开
文档、公开 SDK 及只读本地代码；没有调用任何管理器的创建、修改、启动
或账号接口，也没有执行本轮浏览器指纹测试。
