# WebGPU 启动差异调查（2026-09-10）

最新需求见[内核改动事项记录](kernel-change-decisions.md)：硬件加速开关与
网页 WebGPU 暴露开关独立，默认不暴露；开启硬件加速不隐含开放 WebGPU。
开放后的档案画像数据控制归第二项：提供画像则按配置返回，没有任何
画像输入则沿用内核原生数据，不因缺失画像关闭接口或增加报错。
后端选择和画像准备由管理器适配。
用户已授权助手决定细节，实施规则已整理为
[图形加速与 WebGPU 配置规范 v1](webgpu-configuration.md)。
用户随后已授权实现与测试；下文仍保留改动前的根因调查和实验，不代表
新内核的最终验收结果。当前实现状态见事项记录。

根因已经确认：Camoufox 的 `settings/distribution/policies.json:23` 自带
`"HardwareAcceleration": false`。Firefox 启动时据此将
`layers.acceleration.disabled` 设为 `true` 并锁定，关闭硬件合成。
Windows WebGPU 随后无法找到与合成器匹配的 D3D12 适配器，返回不支持。

移除这条发行策略后，不需要 `layers.acceleration.force-enabled=true`，
同一二进制就能正常使用 WebGPU；将画像显卡名称设为旧型号也仍然支持。
修复已在独立的内核副本中验证。正式仓库的策略、原始发行包以及 Nimbo/CPM
实现尚未修改，本次保存调查记录。

## 根因的运行与源码证据

原始内核的 `about:support` 显示：

```text
HW_COMPOSITING: user disabled
Disabled by layers.acceleration.disabled=true
FEATURE_FAILURE_COMP_PREF

D3D11_COMPOSITING: Hardware compositing is disabled
FEATURE_FAILURE_D3D11_NEED_HWCOMP

Compositing: WebRender (Software)
```

同一轮浏览器日志显示：

```text
CompositorDevice does not exist
Failed to find D3D12 adapter with the same LUID that the compositor is using!
```

实际构建源树中的相关路径：

- `browser/components/enterprisepolicies/Policies.sys.mjs:1855`：
  `HardwareAcceleration=false` 调用
  `setAndLockPref("layers.acceleration.disabled", true)`。
- `gfx/thebes/gfxPlatform.cpp:2544`：初始化硬件合成时，记录上述偏好禁用原因。
- `gfx/thebes/gfxWindowsPlatform.cpp:1356`：硬件合成关闭时，不启用 D3D11 合成。
- `dom/webgpu/ipc/WebGPUParent.cpp:1865`：缺少合成器设备时不能取得其适配器标识。
- `gfx/wgpu_bindings/src/server.rs:2812`：Windows 路径尝试选择与 WebRender
  相同的 DXGI 适配器；匹配失败后将此次请求判为失败。

此轮 `WEBGPU` 功能本身在决策日志中仍是 `default available`，失败发生在
后续设备选择阶段。诊断页的通用“Blocklisted”展示字样不能单独当作显卡
驱动黑名单的证据；本次明确的失败代码是偏好禁用及其后续影响。

## 移除禁用策略后的对照

复制原始内核至 `camoufox-webgpu-inspection/kernel-without-acceleration-disable/`，
仅从副本的 `distribution/policies.json` 删除 `HardwareAcceleration` 这一项。
副本的 `camoufox.exe` 与 `xul.dll` 的 SHA-256 均与原件一致，没有重新编译。
每轮通过 Marionette 读取 BrowserScan 首页及内核自带的 `about:support`，
新 profile 的 `user.js` 只设置调试端口，不设置任何硬件加速强制参数。

| 内核配置 | 显式 GPU 画像 | 首页 WebGPU Report | 合成状态 |
| --- | --- | --- | --- |
| 原始禁用策略 | 无 | `not support` | `WebRender (Software)` |
| 仅移除禁用策略 | 无 | `F8F33FAB` | `WebRender Layer Compositor` |
| 仅移除禁用策略 | `ATI Radeon HD 3200 Graphics` | `F8F33FAB` | `WebRender Layer Compositor` |

第三轮的 BrowserScan 同时显示 `Unmasked Vendor=ATI Technologies Inc.`、
`Unmasked Renderer=ATI Radeon HD 3200 Graphics`；WebGL Report 变为
`FCAC6AA7`，WebGPU Report 仍为 `F8F33FAB`。这验证的是画像字段的影响，
并非用真实的 Radeon HD 3200 硬件运行 WebGPU。

移除策略后的两轮中，`HW_COMPOSITING`、`D3D11_COMPOSITING`、
`D3D11_HW_ANGLE` 和 `WEBGPU` 均为默认可用，也不再出现上述合成器错误。
三轮浏览器均正常退出，原始记录为：

- `20260910-141423-graphics-default/report.json` 与 `browser.log`：原始策略。
- `20260910-142232-graphics-default/report.json`：移除禁用策略。
- `20260910-142529-graphics-default/report.json`：移除策略并传入旧型号画像。

这些记录及测试副本保留于 `camoufox-webgpu-inspection/`。

## 服务器与软件适配器可行性

进一步在同一隔离副本中使用全新 profile，启动前仅额外设置
`layers.d3d11.force-warp=true`，明确选择 Windows WARP 软件路径。
没有设置 `layers.acceleration.force-enabled`，没有修改系统显卡状态。
这次测试运行在现有 Windows 主机，不能当作无 GPU 服务器部署验收。

本机原始记录：`20260910-144841-graphics-warp/report.json`、`browser.log`。

| 观察项 | 结果 |
| --- | --- |
| BrowserScan 首页 WebGPU Report | `B6FEA75C` |
| BrowserScan 详情 Support Detection | `true` |
| 详情完整哈希 | `b6fea75cccffb65bc8745c13e8d56f52d819eaa6` |
| 详情默认适配器 | `Adapter #0 Fallback`，`isFallbackAdapter=true` |
| about:support 默认请求的后端 | `Dx12` |
| about:support 默认请求的设备类型 | `Cpu` |
| about:support 默认请求的设备名 | `Microsoft Basic Render Driver` |

内核自带诊断页确认普通的 `requestAdapter({})` 与显式 fallback 请求均
取得 CPU 适配器。这证明可工作的软件适配器路径已经存在，不能将
“没有物理 GPU”直接等同于“无法提供 WebGPU API”。但纯 CPU 路径不产生
物理硬件加速，也不具有指定实体显卡的吞吐性能。

本轮只验证了 BrowserScan 的支持检测、报告及内核设备诊断，没有做完整
渲染、计算与视频回归。诊断日志中硬件视频编解码为 `Cannot use with WARP`，
另有 `Failed to get D3D11VideoDevice` 和 `Handling webrender error 5`，因此
不能将本轮结果表述为“所有图形与媒体功能均已正常”。浏览器正常退出。

无 GPU 部署还需验证目标服务器上的软件驱动、图形设备创建和呈现路径。
具体后端选择由管理器适配，本事项的内核开关不增加自动回退逻辑。
仅移除发行禁用策略并不能保证所有服务器自动选中 WARP。Linux 部署需要
相应的 Linux 构建与软件 Vulkan 后端，未在本轮验证。

执行后端选择属于管理器职责，对网页呈现的 GPU 画像已列为第二项，细节待讨论。
软件后端负责实际执行，画像负责稳定的身份与能力读数；对外声明
的 features、limits 及设备请求必须落在执行后端能够实现的范围内，或
补充对应的软件实现。仅更改型号或 `isFallbackAdapter` 不足以保证一致性。
硬件与软件路径当前的 BrowserScan 哈希不同，也说明现有实现尚未提供
跨后端保持同一 WebGPU 画像的完整能力。

### CPU 与 GPU 报告哈希不同的已确认字段

离线比对已有的 `20260910-103029-prestart/report.json`（硬件路径）与
`20260910-144841-graphics-warp/report.json`（CPU 路径），没有重新启动测试。

| BrowserScan 展示项 | GPU 路径 | CPU 路径 |
| --- | --- | --- |
| 适配器条目 | `High-Performance` 与 `Fallback`，共 2 条 | 仅 `Fallback`，共 1 条 |
| 默认条目的 `isFallbackAdapter` | `false` | `true` |
| 首页报告哈希 | `F8F33FAB` | `B6FEA75C` |

默认适配器的页面可见字段逐项比较后，唯一字段值差异是
`isFallbackAdapter`；显示的 limits、features、纹理格式能力相同。
GPU 报告中的 fallback 条目与 CPU 报告中的默认条目，其页面可见字段
完全一致。两份报告显示的 WGSL 功能和 miscellaneous 部分也相同。

BrowserScan 对整份 WebGPU 报告数据计算哈希，适配器条目数量及布尔
标记变化已经足以产生不同哈希。因此本次差异不能直接解释成 CPU 与
GPU 算出了不同的图像，或它们显示的能力上限不同。
本节比较的是保存的页面显示内容，未逐字重建站点内部对象并重算哈希，
也不将页面没有展示的字段视为已比较。

## 前期强制启用对照

- 内核：`152.0.4-beta.31`，窗口改动提交
  `1b68676fbddad65cb0be9e22462292263ac7c00d` 的 Windows x64 构建。
- 可执行文件：`dist/windows-x64-window-resolution/camoufox.exe`。
- Playwright：1.62；有界面、持久上下文、`no_viewport=True`。
- 每轮新建独立测试 profile；没有使用 Nimbo/CPM 的档案或账号数据。
- 每轮仅传入 `CAMOU_CONFIG={"showcursor":false}`，没有传入 GPU 画像。
- 三轮可执行文件、工作目录、启动参数保持一致。
- 结果读取自 BrowserScan 首页和 `/webgpu` 页面显示内容。

“三项偏好”指：

```js
user_pref("layers.acceleration.disabled", false);
user_pref("layers.acceleration.force-enabled", true);
user_pref("webgl.force-enabled", true);
```

| 启动前的 user.js | 启动后下发 | 首页 WebGPU Report | 详情 Support Detection |
| --- | --- | --- | --- |
| 不写入 | 三项偏好 | `not support` | `false` |
| 三项偏好 | 同样三项偏好 | `F8F33FAB` | `true` |
| 仅 `layers.acceleration.force-enabled=true` | 无 | `F8F33FAB` | `true` |

两次支持的完整报告哈希均为：
`f8f33fab9a674ac74305a65a83a2359144cf14a8`。
详情页的 `Adapter #0 High-Performance` 显示 `isFallbackAdapter=false`。

本机原始页面记录保存在忽略目录 `camoufox-webgpu-inspection/`：

- `20260910-102847-late/report.json`：启动后下发，不支持；正常结束。
- `20260910-102615-prestart/report.json`：提前写入三项，支持。页面读取完成后，
  额外尝试访问 `about:support` 超时，因此该报告有一个诊断错误；已保存的
  BrowserScan 页面结果不受影响。
- `20260910-103029-prestart/report.json`：仅提前写入一个偏好，支持；正常结束。

测试浏览器已全部关闭。本轮三个目录中的临时 `profile/` 仍保留在本机，
清理操作被自动审批拒绝；没有改动 Nimbo/CPM 已有档案。

## 启动流程的源码依据

Firefox 自身的静态默认值与 Camoufox 最终运行策略不同。Firefox 152.0.4 对应提交
`d4faced9e237d6431856c0873cb035cbbc25817b` 的
`modules/libpref/init/StaticPrefList.yaml:9948` 定义：

- `layers.acceleration.disabled=false`：不禁止硬件加速。
- `layers.acceleration.force-enabled=false`：不强制启用，保留环境与黑名单判断。

两项均为 `mirror: once`；图形初始化也有只执行一次的保护。但 Camoufox
的 `HardwareAcceleration=false` 发行策略又覆盖并锁定了禁用偏好。
因此此前仅据静态默认值判断“Camoufox 默认没有关闭硬件加速”是不完整的；
当前发行配置的实际效果确实是关闭。

Nimbo 的 `backend/internal/launcher/prefs.go:47` 包含
`layers.acceleration.force-enabled=true`，`writeUserPrefs()` 将它写入
profile 的 `user.js`。`launcher.go` 在 `exec.Command()` / 启动进程之前
完成这一步，因此该设置在图形初始化时已经存在。

本次检查使用的 Playwright 1.62 普通 Firefox 路径，通过
`FFBrowser.connect()` 向 `Browser.enable` 发送 `firefoxUserPrefs`，并非
提前创建带这些偏好的 `user.js`。不要与同一驱动中会提前写 profile 的
`BidiFirefox.prepareUserDataDir()` 混淆。

内核的 `additions/juggler/protocol/BrowserHandler.js:30` 明确先等待
`_startCompletePromise`，随后才逐项执行 `Services.prefs.set*Pref()`。
这解释了为什么设置最终出现在 `prefs.js`，也不能证明首次启动的图形
初始化使用了它。实测显示，这个偏好需要在启动前生效才能改变本次结果。
`force-enabled=true` 在图形初始化中覆盖了硬件合成的禁用状态，解释了
Nimbo 的补偿参数为何有效；移除根因后不再需要这个补偿。

CPM 评估项目当前的调用链为
`BrowserSessionManager.launch()` → `AsyncCamoufox.start()` →
安装包 `AsyncNewBrowser()` → `playwright.firefox.launch_persistent_context()`。
当前模型和安装包的默认逻辑没有 Nimbo 那项提前写入硬件加速偏好的步骤；
安装包会设置 `webgl.force-enabled`，该参数与硬件合成设置不同。
因此，“通过 CPM 启动”本身不代表绕过了 Playwright/Juggler。
此前某个 CPM 档案能用 WebGPU 的具体原因，还要结合其内核版本和已保存
的偏好；本轮没有读取或修改那些已有档案。

## 对内核后续改动的含义

这次的 `not support` 不能据此归因于随机选中了旧 GPU 画像：三轮均未注入
GPU 画像，而只改变启动前偏好就改变了支持状态。
同一二进制已实际运行 WebGPU，也排除了本次构建完全缺少 WebGPU 能力的解释。

“能否取得适配器”和“画像能否决定报告值”是两个问题。支持恢复后，
`vendor`、`architecture`、`device`、`description` 仍显示 `Empty`。
此前源码检查确认 Firefox 152.0.4 的 `dom/webgpu/Adapter.h` 对这些标准
字段返回空字符串；Camoufox 当前也没有相应的 WebGPU 画像接口。

但不能把整个报告值相同只归因于四个空字段：BrowserScan 还采集 limits、
features、适配器选择和设备/纹理能力等内容，再对完整报告计算哈希。
后续设计 WebGPU 画像时应覆盖这些输入的一致性，而不是只填显卡名称。
本轮进一步验证了仅更改 WebGL 厂商、型号字符串不会改变 WebGPU 报告，
也不会因为型号字符串变旧就失去适配器。未测试完整的多画像能力矩阵。

最新方案将硬件加速与 WebGPU 暴露分开控制。硬件加速开关不传或 `false`
保留原禁用策略，`true` 解除该策略并保留 Firefox 正常的能力判断；
WebGPU 暴露默认关闭，硬件加速打开也保持网页 `not support`；单独允许
暴露后，提供画像则按画像配置返回，没有画像则直接沿用当前内核原生
返回值。内核不替管理器补画像，也不因缺少画像自动关闭接口或增加报错。
不使用 `force-enabled` 代替开关，不新增后端自动选择逻辑。第二项负责
开放后的档案画像与报告数据；具体接口已根据用户授权在配置规范 v1 中
确定。当前仅完成设计，尚未开始实现。
