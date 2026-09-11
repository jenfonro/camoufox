# CPM 与 Firefox 指纹持久化分析

日期：2026-09-11。分支：`codex/fingerprint-persistence`，继承 WebGPU
提交 `7d2e264`。本文件是实施前调研记录；当时按用户要求仅作分析。
用户随后授权了完整实现，当前功能与运行结果分别见
[配置规范](fingerprint-persistence.md)和
[最终验收](fingerprint-persistence-validation.md)。下文的原有缺口描述
保留为设计依据，不代表当前实现仍未完成。

用户随后指定参考上游 PR #606；其 `fingerprint_seed` 生成层接口和
已有子种子规则已核对，详见 [PR #606 分析](pr-606-persistence-reference.md)。
其命名、类型、派生方法和调用习惯只作为参考，不因调研就确定移植
Python 生成 API 或整套算法。实现始终以 Firefox 原生机制和 Camoufox
现有字段为基础，解决本文件列出的原生行为缺口。

## 验收目标

用户明确要求：同一份档案，在未手动更改设置时，关闭再打开，网站上
基本所有的画像值应保持不变。验收不能只比较 Canvas 一个字段，也不能
只比较管理器存储的 JSON 而不检查网页实际读数。

目标覆盖 Canvas、WebGL 及其报告、WebGPU 报告、Audio、字体、
ClientRects、屏幕画像、navigator、语言/时区配置、语音和媒体设备画像
等稳定身份与能力。不同档案可以由不同输入得到不同画像，同一档案不
因为新进程、新页面或随机重新生成配置而变成另一台机器。

基准验收保持浏览器/检测站版本、字体资源、页面内容、缩放、权限和
运行环境一致，使用同一用户目录正常退出再启动。当前时间、测量耗时、
网页会话状态以及代理实际出口变化等并非固定画像值；不冻结时钟、
历史记录或伪造实际网络连接来强求整张网页逐字相同。动态字段逐项
说明来源，不将未解释的稳定字段变化作为“正常波动”放过。

### 严格通过条件（用户再次明确）

- 同一档案未改画像配置，正常关闭重开后，纳入验收的每个画像哈希
  必须精确一致；字段值也逐项比较。不能用“基本接近”、总体评分高
  或大部分字段相同代替通过。
- 比较网站实际展示的完整报告和完整哈希。首页若只显示短哈希，要
  结合详情页能提供的完整值及底层报告核验，不能用数据 URL 前缀、
  截取的图像片段或重新计算时排除了差异字段的摘要作为替代。
- 只排除本来具有动态语义、且来源可以说明的字段，例如当前时间、
  测量耗时、实际网络出口和站点会话信息。例外清单在比较前明确；
  不能在发现画像漂移后，将该项临时归为动态值。
- Canvas、WebGL、WebGPU、Audio、Fonts、ClientRects 等画像报告，
  不能仅因底层会话随机化或已有缺陷就作为例外。若相同测试内容和
  条件下仍变化，本阶段验收失败，应继续定位和修复。
- 至少三次独立进程的正常关闭重开全部满足条件，并检查刷新、新页、
  重复读取、iframe 和相关 Worker；失败不能靠重跑后挑选一次相同
  的结果覆盖，修复前后记录均保留。
- 不为得到相同哈希而写死检测网站结果或关闭需要的功能。B 档案仍
  应能依据不同画像输入产生可控差异，原生功能继续可用。
- 环境、检测内容或版本发生变化时单独记录并恢复可比条件复验，不
  把不可比的一轮算作通过。最终结论列出实际覆盖项及任何未完成项。

## CPM 已做的两件不同的工作

检查对象是本机 `%TEMP%/cpm-eval`，origin 为
[polyackiy/camoufox-profile-manager](https://github.com/polyackiy/camoufox-profile-manager)，
HEAD 为 `68a3256ca157eea4aebbe37e44cf293e630384da`。其
`fingerprint_store.py` 有此前的 Windows 环境变量拼接改动，本轮未改变。

### 保存与回放完整画像

`core/profile_manager.py:794–829` 的实际启动过程：

1. 从档案的 BrowserSettings 生成高层启动选项。
2. 若档案尚无 fingerprint，调用 `fingerprint_store.resolve()` 解析
   Camoufox 生成的完整配置，再把指定字段冻结到档案。
3. 启动时合并固定画像与本次显式 config，显式 config 优先。
4. 将固定画像写回档案记录，随后启动浏览器。

`core/database.py:200–225` 将 fingerprint 作为 JSON 保存，
`core/models.py:264–265` 使用固定 user_data_dir 与 persistent_context。
这解决的是两个不同问题：保存 JSON 保持画像输入，复用用户目录保持
Cookie、localStorage、站点权限等浏览状态。后者本身不会令随机指纹
跨启动稳定。

`core/fingerprint_store.py:28–90` 使用前缀白名单保存
`navigator.`、`screen.`、`window.`、`webGl:`、`webGl2:`、`canvas:`、
`audio:`、`fonts`、`mediaDevices:`、`voices`、`AudioContext:` 等。
它刻意排除语言、window.history.length 等由其他设置或会话决定的字段，
不冻结代理地理信息和 WebRTC 地址。

### stable_canvas 开关

`BrowserSettings.stable_canvas` 默认 false。
`core/models.py:276–288` 在它为 true 时，仅向启动选项写入：

```python
firefox_user_prefs = {
    "privacy.baselineFingerprintingProtection": False
}
```

这并不是 Canvas 像素或随机键的档案持久化实现，而是关闭一项原生
防护总开关，再依赖保存的字体列表和 `fonts:spacing_seed` 得到稳定
文本渲染。这个 pref 的影响范围也不限于一个 Canvas seed。

CPM 文档 `docs/profile-settings.md:219–269` 明确指出
`canvas:seed` 只是属性声明与 Python 输出，当前内核未消费，
`window.setCanvasSeed()` 也不在其已测发行版中。其
`tests/browser/test_fingerprint_stability.py:158–220` 分别检查默认
跨启动变化、stable_canvas 后重启稳定及跨站相同。

这些测试证明它的兼容方式，但不能作为我们“稳定且由每个档案输入
决定”的完整实现：它们没有证明纯图形输出可按不同档案 seed 区分，
也没有覆盖新增 WebGPU。已有 Nimbo BrowserScan 对照还记录过关闭该
防护后多个档案的 Canvas 值相同，本轮没有重复做这些实验。

此外，CPM 的 `canvas_noise`、`webgl_noise`、`audio_noise` 在模型注释
中明确只保存意图、不下发配置，不能因为字段存在就认为内核支持。

## 当前 Firefox 的 Canvas 随机化链

本轮只读检查了实际构建源树
`/home/zel/camoufox/camoufox-152.0.4-beta.31`：

| 路径 | 当前行为及影响 |
| --- | --- |
| `toolkit/components/resistfingerprinting/nsRFPService.cpp`，GetBrowsingSessionKey | 按 OriginAttributes 在内存保存新生成的 UUID；浏览器新进程没有上次会话的键 |
| 同文件 GenerateKey / GenerateKeyForServiceWorker | 将会话键与顶层站点分区通过 HMAC 派生文档随机键 |
| `netwerk/cookie/CookieJarSettings.cpp:329` 及 Serialize | 向读取方提供随机键，并通过原生消息序列化传递；这不是把键持久化到 Cookie 数据库 |
| `dom/canvas/CanvasUtils.cpp:374` 附近 | 依照现有防护和权限选择 EfficientRandomize、Randomize 或正常提取路径 |
| `dom/html/HTMLCanvasElement.cpp:925` 及 `dom/base/ImageEncoder.cpp` | 在高效随机化导出时，把文档随机键传给图像编码器 |
| `image/encoders/png/nsPNGEncoder.cpp:562` | 用随机键与图像哈希生成 16 字节 deBG 元数据，插入 PNG |
| nsRFPService::GenerateCanvasKeyFromImageData / RandomizePixels / RandomizeElements | 像素扰动路径也使用 CookieJarSettings 中的文档随机键 |

因此，“画出来的像素一样”与“导出文件字节一样”不是同一个验收项。
默认高效随机化路径可以保留像素，却让 PNG 的哈希跨会话改变；
仅在 Python 层保存一个当前无人读取的 `canvas:seed` 无法改变这条链。

当前 JPEG/WebP 编码器没有 PNG 的 deBG 路径；Canvas getImageData
等在不同原生防护模式下也可能选择不同分支。不能将“PNG 固定”自动
推广为每一种编码格式、OffscreenCanvas 和 WebGL 像素接口都已覆盖。

## 字段与实现方向

建议首先复用已有字段，不新增 CPM 专属的 stable_canvas 到内核，也不
建立一个负责生成、存储、迁移整份档案的总开关。
PR #606 的 `fingerprint_seed` 及子种子派生方式是可参考的生成层设计；
是否需要采用，应由内核目标和现有接口决定。它不替代完整配置回放
和内核支持，也不增加管理器实现作为本阶段的默认工作范围。

| 输入 | 管理器应保存什么 | 内核下一步 |
| --- | --- | --- |
| `canvas:seed` | 每个档案固定的种子 | 补齐实际消费入口，让已有原生随机化链从稳定输入派生，避免随进程重新生成 |
| `audio:seed`、`AudioContext:*` | 固定种子与显式音频画像参数 | 现有接口已消费；检查各读取路径、重复调用、重启与上下文一致性，按实际缺口修复 |
| `fonts`、`fonts:spacing_seed` | 完整字体集合与间距种子 | 检查字体选择/缓存以及 DOM、Canvas 文本的种子传递，避免只保存下拉设置而仍重新抽样 |
| `webGl:*`、`webGl2:*` | 厂商、型号、完整参数/扩展/精度数据及相关控制 | 参数回放与图像随机化分别验证，保留原生读取和功能行为 |
| `gfx:hardwareAcceleration`、`webgpu:enabled`、`webgpu:profile` | 两个选择与完整嵌套画像，含特定请求覆盖 | 直接复用已完成实现，纳入每次启动的固定配置 |
| `window:profile`、`window:mode` | 屏幕/窗口画像与模式 | 复用已完成实现；真实窗口状态仍由原生用户目录恢复 |
| `navigator.*`、语言、timezone、voices、mediaDevices 等 | 实际下发的固定值/集合与显式策略 | 逐项确认是否有每次生成、缺值透传或状态残留，已有参数优先复用 |

Canvas 的优先修改位置应是原生随机键来源及其调用链，而不是额外在
页面覆写 toDataURL、写死网站哈希或关闭整个基线防护。

具体实施建议：固定 seed 时从相同输入确定性派生根材料，再沿用
Firefox 当前的站点/OriginAttributes 隔离；未提供固定输入时保留
上游会话随机化。派生材料不含进程号、当前时间、临时目录路径或其他
每次启动变化的值，并通过现有通道传递到文档、Worker 和编码器。

这首先保证“同一档案在同一网站重启稳定”。不同站点本身的原生分区
规则不因持久化需求自动取消；也不能要求采用不同采样算法的网站
显示相同哈希。seed 为 0 的约定、清除站点数据与重置画像的区别等
应在实施规范中明确，不在本轮仅分析的阶段更改既有接口语义。

## CPM 适配清单与边界

CPM 的保存模型可以参考，但不能不加检查地原样作为完整保证：

1. 当前白名单没有 `webgpu:`、`gfx:hardwareAcceleration`、
   `window:profile`、`window:mode`。`window.` 不匹配 `window:`。
   这些新接口要进入管理器保存/回放清单，不能为了配合旧白名单给
   内核字段改名或塞到 WebGL 名下。
2. 只保存硬件画像还不够；`stable_canvas` 等普通偏好与 API 暴露、
   WebRTC 策略、语言/时区也属于有效启动输入，需要保持一致。
3. 当前 stable_canvas 为 false 时只是不下发该 pref，未显式恢复
   曾写入的值；复用目录时是否残留必须纳入切换测试，不把“未传”
   默认等同于“已恢复”。此处是源码风险点，本轮未重测。
4. resolve 失败返回空画像，管理器仍可启动。这样就不能声称档案
   已固定；管理器应识别该状态。内核仍遵守“没给画像就走原生”的
   通用规则，不替管理器补数据。
5. `geoip` 与 `proxy_check.fill_what_geoip_would_have()` 会按网络重新
   解析位置、时区和 WebRTC 地址。设置不变但出口变化时，这些读数
   可能改变，属于网络跟随策略。要求固定时应显式配置并保持网络
   条件，不由内核虚构实际出口地址。
6. 浏览器版本更新/画像刷新、扩展与字体资源版本影响读数。固定测试
   应记录实际二进制版本与有效配置；更新后的兼容性另作回归，不
   默默重生成其他画像字段。

本轮未修改 CPM、Nimbo 或它们的真实档案与数据库。CPM 文档对
maxTouchPoints 等旧版本的结论不能覆盖我们已修改的内核，具体字段
以当前代码与当前构建行为核对。

## ClientRects 的已知状态

旧、新 WebGPU 构建的同一套回归记录中，Linux Global 的宽度都从
479.2667 变为 305.9167；当时 screen 和 Canvas measureText 读数没有
变化。这是同次运行的两次采样，尚不能直接定性为缺少某个持久化种子。

采集器在相同字体文本上调用 DOM Range.getClientRects；现有代码还有
字体选择与布局缓存相关处理。后续应检查 DOM 字体路径、布局/样式与
缓存状态，定位后修复；当前没有充分依据新增 clientRects:seed。

## 当前需要补齐的实现与验证闭环

需求方向和参考资料边界已经明确。当前不需要再增加管理器专属接口，
也不需要用户补充一套种子算法；剩余工作主要是以下五项。

| 项目 | 必须补齐的内容 |
| --- | --- |
| Canvas 固定输入 | 补上 canvas:seed 的原生读取、确定性派生及图像导出链路，避免新会话键继续改变完整哈希 |
| 种子语义与类型 | 明确未传、0、非零种子、允许范围、错误类型及上下文/进程配置优先级，不把字段缺失和显式零混为一谈 |
| 生命周期和隔离 | 相同输入跨重启、子进程、页面和相关 Worker 一致；不同档案互不污染；取消覆盖、清缓存或清站点状态不应被混同于重置画像 |
| 既有稳定性缺口 | Audio、字体读取路径验证及 ClientRects 漂移定位；不能因接口已有 seed 或问题上游已存在而免验 |
| 完整验收清单 | 固定有效输入，覆盖新旧画像字段、实际完整网站报告和正常退出重开；预先列明动态项，每项稳定画像均须通过 |

本轮额外确认的具体边界：schema 中三个旧种子目前只声明非负整数，
Audio/字体原生读取使用 uint32，范围和类型应在实现时对齐。
AudioFingerprintManager 与 FontSpacingSeedManager 当前都是只有上下文
seed 非零才直接返回，否则继续取进程级 seed；因此显式 0 与全局配置
同时存在时的实际优先级不能仅靠文档猜测。后续先保持已有接口兼容，
再明确修复需要的行为，不直接修改所有旧种子的含义。

管理器保存的完整配置需要包括窗口、WebGPU、字体/语音集合、已有
种子和行为偏好；这是一份通用输入清单，不是要求本阶段去改 Nimbo
或 CPM。相同输入仍有画像变化时，继续定位内核；若实际输入每次都
变化，则明确指出回放缺口，不能通过内核自动造数据掩盖。

以上为实施前的闭环清单；后续实现与验证已完成，详见本文件开头的链接。

## 最终验收流程

1. 保存同一档案的有效 CAMOU_CONFIG、实际 Firefox prefs、内核版本
   及资源版本；每次启动先核对输入是否发生变化。
2. 打开 BrowserScan，等各报告完成和字体加载稳定，保存所有稳定
   字段的原始值，包括 Canvas、WebGL/WebGL Report、WebGPU、Audio、
   Fonts、ClientRects、屏幕、UA、CPU 核数、语言/时区、媒体能力等。
3. 正常退出并复用同一用户目录，连续重开至少三次；按字段比较，
   不仅比较合并哈希。包括已关闭接口的状态也必须稳定。
4. 同次启动重复读取、刷新、开新页、iframe 与支持的 Worker，确认
   未因调用顺序或进程分配使画像变化。
5. 新建独立测试档案 B，换固定画像/种子，验证需要区分的报告具有
   可控差异；不要求每个真实能力字段都必须不同，也不把一个输入
   未生效的随机碰撞当成功。
6. 测试显式修改单项输入、取消覆盖，以及硬件加速/WebGPU 开关组合，
   确认只按定义改变相关值，窗口与其他已有功能回归通过。

原生执行及读取一致性作为补充，网站画像验收仍以 BrowserScan 实际
页面为准。所有验证使用独立测试档案，绝不清空已有账号目录。
