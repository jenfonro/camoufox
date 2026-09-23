# Native control v1：Windows x64 交付与验收

2026-09-23。已完成实现、VM 构建、产物取回及最终包运行验收。
实现期间的临时分支为 `codex/native-control-api`，
继承 `e46a454bc4528638128df3437f7f18a04e66afc6`；统一交付分支为 `personal-use`。
内核包在源码提交前，按确定的文件清单构建并完成验收。
用户随后授权将上游集成和本次功能一起纳入并推送至 `origin/personal-use`；
本阶段未发布 Release，产物身份仍以构建输入清单和包哈希为准。

## 交付文件

- 压缩包：`dist/camoufox-152.0.4-beta.31-native-control-v1-win.x86_64.zip`
- 解压入口：`dist/windows-x64-native-control-v1/camoufox.exe`
- 配套清单：`dist/camoufox-152.0.4-beta.31-native-control-v1-win.x86_64.manifest.json`
- 接口与启动示例：[Native control v1](native-control-api.md)
- 独立 Python 客户端：[native_control_client.py](../scripts/native_control_client.py)
- 续接清单：[工作清单](native-control-plan.md)
- 环境：[Windows x64 构建环境](windows-x64-build-environment.md)

包大小为 **493161259** 字节，SHA-256：

```text
dbb4e65e183a12dac86f51a82207cb644f7f688d7fb64ac41e229502a1f03b30
```

VM 与本机 SHA-256 一致，ZIP CRC、PE x64 架构、配置、策略及 30 项
Juggler/控制模块打包资源逐字节核对通过。最终包来自 VM 的正常构建与
打包流程；开发过程中临时更新过的 `windows-x64-native-control-dev`
不是交付目录。

## 新接口与无调试路径

接口提供 51 个方法、20 类事件。启动仍使用现有 Camoufox JSON 配置，
新增 `control:enabled`、`control:port`、`control:token`、`control:endpoint`。
默认关闭；开启后使用经令牌鉴权的本地 TCP NDJSON，端点文件不保存令牌。

最终包直接启动时，仅使用普通实例/档案参数，以及无窗口测试所需的
`-headless`。新路径测试没有使用 BiDi、Marionette、Juggler 调试会话或扩展。
静态启动链检查与运行诊断同时确认没有导入旧 Runtime、FrameTree、
PageAgent 或旧内容执行入口，没有 Juggler 页面 Actor，焦点和 BFCache
自动化覆盖项为 false。C++ 主世界执行入口直接进入内容 realm，不附着
JavaScript Debugger。

在任何客户端连接前就打开测试页面，记录网页自身的报告；连接、断开、
重连后的报告相同。未新增控制全局对象，`navigator.webdriver` 为 false，
单纯连接不改变页面焦点。双实例同时运行、跨实例令牌拒绝、正常关闭一份
而另一份继续运行均通过。不能只凭 webdriver 字段得出以上结论。

## 最终包的功能验证

| 验证组 | 结果 |
| --- | --- |
| 新接口，有窗口与无窗口 | 两套完整操作流程通过并正常退出，端点文件被移除 |
| 输入 | 可信点击、双击、右键、Unicode 文字、组合键、原生快捷键、滚轮、拖放、取消后释放、多客户端输入归属通过 |
| 布局与 frame | 跨进程 iframe、独立滚动、CSS transform、Shadow DOM、frame 创建/销毁、全页缩放与边缘坐标通过 |
| 浏览器能力 | 标签页、窗口、容器/私密隔离、导航/历史、DOM、主/隔离世界、截图、Cookie/存储、文件、权限、对话框、下载通过 |
| HTTP | 观察、响应体、初始请求暂停、继续/拒绝/响应替换、重定向观察、断线及超时释放通过 |
| 既有窗口机制 | 12 项原生/画像/全局覆盖、调整大小、最大化及重启恢复检查通过 |
| 表单/密码/历史 | 默认、启用、正常重开、再次禁用四组通过；使用测试档案与虚构数据 |
| WebGPU | 默认、仅加速、原生暴露、A 画像、重复 A、B 画像、WARP、不兼容、恢复默认、无效配置共十组通过 |
| 既有调试路径 | 九项可信事件、脚本世界、初始脚本、边缘/零位移/轨迹和应答超时 guard 通过 |
| 种子作用域 | 12 组全局/上下文继承、零值、另一画像及重放通过，包含 OffscreenCanvas 和各类页面 Worker |
| 静态/单元检查 | 237 项通过；集中输入投递与默认启动不加载 Juggler 执行模块的检查通过 |

旧协议回归使用了显式指定的同一交付二进制，其证据与新接口的无调试验收
分开记录。一次旧 guard 的初次调用遗漏了必需命令行参数，随后用明确的
二进制、配置和输出参数完成；最初调用记录仍保留。

## 窗口显示与画像保持独立

没有为指纹验收固定真实窗口，也没有把真实视口恢复变化当作画像漂移。
未设置画像视口字段时，网站对应读数跟随真实视口；只有屏幕画像也不会
固定视口高度。仅设置 `window:profile` 不改变真实窗口，旧全局几何输入
继续按原规则同时影响显示与报告。两者均未设置时由 Firefox 原生机制
管理窗口和读数，显式 `window:mode = native` 则忽略两类覆盖。

有窗口测试中，真实视口从 `1280 × 955` 经原生全页缩放变成约
`1173.333 × 875.417`，网页画像始终为 `777 × 555`、DPR `2`。
在这个条件下，远端 8px 小按钮和跨进程 iframe 点击通过。
无窗口测试也通过同样的分离检查。

投递根据真实 frame 布局与 browser rect 换算，包含 Firefox app-unit
取整造成的有效缩放差异；不使用画像 DPR 或直接假定请求的 110% 就是
精确物理比例。既有全局覆盖、`window:profile` 和 `window:mode = native`
语义均通过独立窗口回归。本机实测系统 DPI 为 96；未切换遍历所有系统 DPI。

## 完整指纹比较

固定完整配置与同一档案，正常关闭重开三次。完整 PNG/其他图像导出、
音频数据、字体/布局、WebGL、可实际取得的 WebGPU 适配器画像、navigator、
screen、语音及媒体设备报告逐值相同，不截断 data URL 或只比较前缀。
完整原生报告 SHA-256：

```text
5353e8dd1e01dbe8bdb0d5f835b504c32b0a17eeea9ee3bcdd5dbc62cc8150e5
```

该完整原生报告与上一版上游集成产物使用同一配置得到的报告也完全相同。
BrowserScan 的身份单元格、八个完整哈希、字体列表、WebGPU 数据，以及
Canvas/WebGPU 详情哈希、表格和完整图像也在三次重启中一致。

| BrowserScan 项目 | 完整哈希 |
| --- | --- |
| Canvas | `2df36cf53cd6289288b763b025317a8fdfc9c8f5` |
| WebGL | `34c27e81727dbf1199e0bf53cb477737debc1809` |
| WebGL Report | `170d25e0f28cf6d6085084fa67bc1f759380de4e` |
| Audio | `afb772e059d666433abfeec8d772ad90beabaf71` |
| Client Rects | `53a76918d934394e262015ec47f3e8f5862401bc` |
| WebGPU Report | `a31d5575b749f73d0145edc85851064cf17b2bea` |
| Fonts | `464e406ea80193ef98fb07d13b51382a5613e6af` |
| visitor ID | `9e382f91d9fef5be6fd9d9c6b3f642b173ebe877` |

网站沿用已记录的统一采集条件：加载完成后，通过可见的 Check again
复检一次，保留复检前报告，不豁免任何身份哈希。最终包这组三次初始报告
的八个哈希也相同；开发阶段仍重现过网站 SVG `id=chrome` 的加载竞态。
不能由最终这组三次通过，推断任意首屏加载顺序都相同。原因与历史记录见
[上游集成验收](upstream-integration-20260923.md)。

时钟、网络测量、IP/远程信誉、广告及请求标识等动态内容不作为稳定身份。
这些边界沿用原验收约定，没有在出现差异后豁免某个身份哈希。

## 源码与证据

构建前核对 1137 个快照文件、56 个同步到 Gecko 的文件，以及 27 个
继承的定制源码/策略文件。两份 C++ 补丁与实际源码前后差异完全对应。
本地初始保护清单中 208 个输入文件有 200 个逐字节未变，其余八个是本次
有意调整的 Juggler 注册、输入/网络复用、配置和输入投递检查文件。
此前的窗口、WebGPU、种子和策略补丁没有被覆盖。

全部证据在 `camoufox-native-control-work/`：

- `artifact.json`、`final-source-manifest.json`、`source-verification.json`：
  产物与源码来源；`build.log`、`build.exit` 为最终 VM 构建记录。
- `source-verification-final.json`：验收后补齐文档和测试脚本的 SCP
  同步复核；所有打包输入仍与最终源码清单一致。
- `final-headed/`、`final-headless/`、`final-lifecycle/`：新接口操作、启动链、
  页面自报、截图与生命周期。
- `final-persistence/`、`final-website/`：固定输入、三次正常重启的完整数据、
  网站初始/复检报告和详情数据。
- `final-window/`、`final-browser-features/`、`final-webgpu/`：
  既有功能回归；`final-seed-contexts` 是 JSON 结果文件。
- `final-legacy-guards/`、`static-final.log`：旧协议 guard 与单元/静态检查。
- `validation.json`：机器可读的最终汇总。

早期定位中的失败和临时产物保留，最终结论以以上 `final-*` 记录为准。

## 明确边界

交付验收平台为 Windows x64。没有声称 Linux/macOS 已运行验收。
v1 不提供触摸/笔输入、Worker 调试、持续录屏、桌面/VNC 控制或响应阶段
网络暂停；系统 IME 候选窗口不在本轮测试范围。同步无限循环脚本不能由
该接口抢占中断，异步等待可以取消。

本地 IPC、进程环境和明确发起的脚本/输入活动可以被具有相应权限的软件
观察到；不承诺任何站点绝对无法识别控制行为。接口的准确默认值、能力和
错误语义以 [API 文档](native-control-api.md) 为准。
