# 通用本地控制接口：工作清单与决策记录

更新：2026-09-23。状态：v1 范围的实现、Windows x64 最终构建、取回、
运行验收与既有功能回归均已完成。
接口见 [Native control v1](native-control-api.md)，
产物、证据及限制见 [最终验收](native-control-verification.md)。

统一交付分支为 `personal-use`。本功能在临时分支 `codex/native-control-api`
完成，继承完整上游集成基线；用户要求将两阶段工作一起纳入
`personal-use` 并推送到 `origin/personal-use`。
Windows 内核包保留本机，不随 Git 提交或发布 Release。

后续完成的功能应汇总回自用分支，不能只推送临时功能分支。
清理分支前，必须确认其提交已被远端自用分支完整包含。
`main` 保留；`codex/publish-personal-artifacts` 含尚未合并的旧产物发布流程，
不随已合并的功能分支删除。

## 恢复工作时先读

1. 本文件：当前目标、已确认约束、未决设计、执行清单。
2. [Windows x64 构建环境](windows-x64-build-environment.md)：SSH、代理、
   源码目录、增量编译、产物提取和当前环境差异。
3. [上游集成结果](upstream-integration-20260923.md)：当前基线、已保留功能、
   旧产物与验证边界。
4. [既有内核决策](kernel-change-decisions.md)、窗口、WebGPU 和持久化规范。

当前本地仓库：`C:\Users\79917\Desktop\codex\camoufox`。
会话默认工作目录仍可能指向旧 Nimbo 目录，所有命令显式指定 Camoufox 路径。

## 已确认的目标与范围

交付 Camoufox/Firefox 内置的通用控制能力。外部程序能够控制浏览器，
同时该控制路径不启动 BiDi、Marionette、Juggler 调试会话，
也不附着 JavaScript Debugger。

- 只修改 Camoufox 内核仓库；本阶段不修改 auto-manager、Nimbo、CPM。
- auto-manager 代码仅用于了解常见浏览器操作，不是协议或字段的设计中心。
  其 Agent、扩展/BiDi 移除、VNC 连接与统一调度属于管理器后续适配。
- 不考虑 Chrome/Chromium 兼容层。
- 不依赖用户安装普通 WebExtension，不以扩展转发调试命令完成实现。
- VNC/RFB、桌面画面服务和其他应用的系统输入控制不搬进内核。
  调用方可以自行组合这些能力与内核接口。
- “完整”包括输入、页面读取与执行、浏览器对象管理、状态和事件；
  不能只替换鼠标点击，其他能力仍暗中使用 BiDi。
- 内核只提供浏览器原语。业务流程、找哪个按钮、轨迹策略、重试、
  档案生成与持久化由调用方负责。
- 首个实际构建与运行验收目标仍为 Windows x64。

## “没有额外标记”的具体含义

1. 新控制路径不需要 `--remote-debugging-port`、`--marionette`、
   `--juggler-pipe` 等调试开关，也不启用相应调试会话。
2. 不向网页新增控制用的全局对象、DOM 标记、扩展桥接入口或可查询的
   控制状态。内部协议字段不成为网页指纹字段。
3. 实际核查初始化与调用链；仅修改 `navigator.webdriver` 等检测结果、
   或把调试端口换成 pipe，不算实现目标。
4. 连接、断开控制客户端本身不应改变画像、真实窗口、页面权限、
   图形模式或正常焦点规则。明确的操作命令仍有正常浏览器副作用。
5. 内部通信组件、进程句柄和连接可以存在，并仅供获授权的本地客户端使用。
   不承诺操作系统看不到它们，也不承诺任何网站绝对无法识别操作行为。
6. 浏览器内部输入、DOM 的 `.click()`、真实系统鼠标、`isTrusted` 和
   transient user activation 是不同语义，必须分别验证。

编译选项 `--disable-debug` / `--disable-debug-symbols` 与运行时是否启动
调试设施不是同一件事，不能作为上述要求的验收证据。

## 通用字段与协议原则

- 优先沿用 Firefox、DOM、UI Events、Pointer Events 等已有的对象和语义。
  可以参考标准动作模型，不等于启动或复用 BiDi 服务。
- 按浏览上下文、页面、输入、存储、网络事件等能力组织接口；
  不引入管理器名称、任务编号、账号业务或站点专用动作。
- 启动配置与运行时命令分开。前者控制连接入口，后者表达操作与结果；
  保持与 `CAMOU_CONFIG` 现有使用习惯协调。
- 明确协议版本、能力声明、请求关联、参数类型、返回值、错误、
  超时/取消和对象失效规则。
- 键盘优先采用 `key` / `code` / `modifiers` 等标准概念；
  指针明确按钮编号、按下状态、坐标空间和单位。
- 所有输入和截图几何以真实布局为依据。网页画像中的
  `window:profile`、DPR 或 `screen.*` 不能用于反推真实点击位置。
- 没有能力或参数无效时返回明确错误；不偷偷改用调试器、VNC、
  DOM 点击或另一种输入路径。
- 现有 `humanize` 等字段的行为需单独检查，避免调用方已经提交动作序列，
  内核又无条件生成另一套轨迹。

配置键和命令名称已记录在 [v1 接口文档](native-control-api.md)。
旧发行产物不支持这些接口，需使用本分支构建。

## 需要覆盖的浏览器能力

| 能力 | 实施与验收内容 |
| --- | --- |
| 连接与生命周期 | 本地客户端授权、版本/能力协商、请求应答、订阅、取消、断开、重连、多实例隔离 |
| 浏览上下文 | 列出/创建/关闭/选择标签页，窗口、frame 生命周期与稳定的运行时对象引用 |
| 导航 | 打开地址、刷新、前进后退、导航与新窗口事件、等待条件 |
| 页面读取 | CSS/文本等查询所需的通用 DOM 能力、属性/文本、可见性、真实布局和命中测试 |
| 页面脚本 | 必要的主世界/隔离世界执行、异步结果、异常与返回值；实现不依赖 `Debugger` |
| 输入 | 移动、按下/松开、各鼠标按钮、双击、滚轮、拖拽、键盘组合、文字输入、输入状态释放 |
| 跨 frame 与布局 | 跨进程 iframe、Shadow DOM、滚动/APZ、缩放、DPI、窗口边缘、页面重排 |
| 截图 | 视口、区域、完整页面的适用范围与实际像素/坐标；持续录屏需求另行界定 |
| 页面与会话状态 | Cookie、local/session storage、OriginAttributes/容器/私密上下文等原生隔离 |
| 网络与事件 | 导航、重定向、请求观察及所需的请求/响应干预；保留网页正常安全语义 |
| 浏览器交互 | 下载、文件输入、页面对话框、权限等原生对象的控制边界 |

触摸/笔输入、Worker 执行、持续录屏等支持范围应在能力表中逐项明确。
浏览器 UI 与操作系统文件对话框不得因“完整”一词被默认为任意桌面控制。
不能用能力声明掩盖已经承诺的核心功能未实现。

## 已完成的源码分析

| 位置 | 已确认事实与实施影响 |
| --- | --- |
| `additions/juggler/input/MouseDispatch.js` | 已集中处理鼠标/滚轮、真实 browser rect、边缘取整与应答超时；优先复用这些正确性保障 |
| `additions/juggler/protocol/PageHandler.js` | 输入包含标签页激活、APZ 刷新、拖拽状态和事件应答，不能只复制最底层一次调用 |
| `additions/juggler/content/FrameTree.js` | 键盘使用 `nsITextInputProcessor`；但构造 FrameTree 会创建 Runtime，不能整套引入新路径 |
| `additions/juggler/content/Runtime.js` | 构造函数创建 `new Debugger()`，`invisibleToContent` 不等于没有调试器 |
| `additions/juggler/components/Juggler.js` | 页面 Actor 在模块顶层注册，早于 `juggler-pipe` 判断；关闭一个启动参数不足以证明相关组件未初始化 |
| `additions/juggler/content/main.js` | 有强制焦点、active state、关闭 BFCache 等自动化行为，需要审计与分离 |
| `patches/playwright/0-playwright.patch` | 包含输入及其他 Gecko 改动；需区分必要原生输入能力与自动化状态覆盖 |
| `ChromeUtils.camouGetNativeViewportSize` | 已有真实视口读取机制，可作为窗口画像分离约束的参考 |

`MouseDispatch` 的集中投递约束和
[`scripts/check-input-dispatch.py`](../scripts/check-input-dispatch.py) 必须同步维护；
不能为新入口复制一套坐标计算，重新引入已有边缘死锁。

auto-manager 的 Firefox 实现目前用 BiDi 做输入、脚本、标签页、截图、
Cookie 和事件。其“先定位再 VNC 点击”中的定位仍依赖页面控制通道。
这些只是能力梳理依据，本工作不改它的代码。

## 必须保留的既有功能

本功能的基线为原 `codex/sync-upstream-20260923` 的
`e46a454bc4528638128df3437f7f18a04e66afc6`。
本次自用分支整合包含该提交，不能从旧发行提交
`cc9f5250a2002426e6988cb2decb17ccaa501425` 重新开始而丢掉上游集成。
临时分支清理后，以上提交仍保留在 `personal-use` 历史中。

- [窗口规范](window-resolution-modes.md)：旧全局覆盖保持兼容；
  `window:profile` 只覆盖报告；`window:mode = native` 使用原生几何。
- [图形/WebGPU](webgpu-configuration.md)：`gfx:hardwareAcceleration`、
  `webgpu:enabled`、`webgpu:profile` 的独立控制与既定缺省语义。
- [指纹持久化](fingerprint-persistence.md)：`canvas:seed`、`audio:seed`、
  `fonts:spacing_seed` 的类型、零值、进程/上下文作用域及原生分区规则。
  没有新增 `window.setCanvasSeed()`。
- [表单、密码与历史](browser-feature-preferences.md)：已解除的策略锁定、
  按档案偏好启用的机制。旧主题的标签页命中问题仍通过
  `disableTheming: true` 使用原生界面绕开，不能写成旧主题 CSS 已修复。
- 与上游自动化调用的共存方式需明确；新路径无调试依赖不等于本次要删除
  全部上游 Playwright/Juggler 功能。任何默认语义变化单独列明。

## 已落定的实现细节

- 默认关闭的 loopback TCP NDJSON，令牌鉴权；端点文件独占创建，只保存
  版本、端口、进程及实例身份，不保存令牌。连接关闭不关闭浏览器。
- 四个启动字段为 `control:enabled`、`control:port`、`control:token`、
  `control:endpoint`。运行期按浏览上下文、输入、存储、网络等域分组。
- 多进程窗口 Actor 与旧 Juggler Actor 独立。主世界执行由 ChromeOnly
  C++ 方法进入内容 realm，隔离世界采用 content-principal sandbox。
  不附着 Debugger；页面自身的 CSP 和权限规则继续生效。
- 鼠标和滚轮经原生 APZ 完成回调确认；键盘和文字从浏览器 widget 的
  TextInputProcessor 投递，支持原生快捷键。输入共享队列、归属、取消与
  断线释放均有边界。缓存于 BFCache 的文档也释放连接状态。
- 画像几何与实际布局保持独立。父进程坐标换算集中在 MouseDispatch，
  使用实测 viewport/browser rect 比例，覆盖 fullZoom 的 app-unit 取整，
  不把画像 DPR 或请求的缩放百分比当成实际物理比例。
- 保留显式旧 Juggler 启动；默认/新路径不初始化其执行模块及焦点覆盖。
- v1 不提供触摸/笔、Worker 调试、录屏或桌面/VNC；HTTP 干预支持初始请求，
  重定向可观察，不能在响应阶段或重定向跳转处暂停。

## 执行清单

### 0. 接手与准备

- [x] 读取原“内核”会话和本会话保存的构建交接记录。
- [x] 核对本地分支、远端提交、旧产物 SHA-256。
- [x] 验证 VM、专用 SSH 密钥、工作目录、工具链和代理隧道。
- [x] 复核 VM 上 27 个继承文件及两个已更新 Juggler 资源。
- [x] 记录现存 20 GiB 构建 swap 文件未启用的差异。
- [x] 建立本清单和独立构建环境文档。

### 1. 建立实施基线与接口契约

- [x] 从完整集成基线创建英文功能分支 `codex/native-control-api`。
- [x] 建立独立源码前快照、修改清单、测试输出和 VM 日志目录。
- [x] 完成通用能力清单及协议/配置规范，注明所有默认值和坐标单位。
- [x] 确定本地传输、客户端授权、对象生命周期、订阅及错误规则。
- [x] 审计 Juggler 注册、Debugger、焦点/BFCache 等启动链，
  区分新路径与需要保留的上游路径。

### 2. 内核实现

- [x] 增加不依赖普通扩展或调试会话的内置控制组件。
- [x] 实现多进程页面/上下文管理、查询与所需脚本执行。
- [x] 接入原生输入并保留边缘、APZ、应答超时、状态释放保障。
- [x] 补齐导航、截图、存储、网络和浏览器交互能力。
- [x] 实现能力声明、严格参数/错误处理、断开/重连与实例身份校验。
- [x] 沿仓库流程同步 additions/settings；C++ 改动从实际源码差异导出补丁。
- [x] 提供独立最小客户端与用法示例，名称和数据不含管理器业务。

### 3. 构建与取回

- [x] 首次编译前核验并恢复额外构建 swap，检查可用内存、磁盘、工具链。
- [x] 通过 SCP 同步确定的源码快照和清单，保存继承源码前像。
- [x] 复用现有 Windows x64 objdir/ccache，保存 build.log 和独立退出状态。
- [x] 在对应快照根目录打包，取回新名称产物，不覆盖旧基准。
- [x] 校验源码来源、包内资源、SHA-256、ZIP CRC 和版本信息。

### 4. 严格验收

- [x] 用独立客户端验收 v1 浏览器操作；不接入 auto-manager。
- [x] 新路径的测试过程不以 BiDi/Marionette/Juggler 作为隐藏的控制或检查通道。
  可用测试网页自报、测试服务器记录、内部测试钩子和进程状态取证。
- [x] 验证未连接、连接、断开、重连时的启动链和网页可见属性；
  不能只检查 `navigator.webdriver` 一个值。
- [x] 验证真实输入事件顺序、可信状态、用户激活、焦点、Unicode 文字提交、
  取消后的按键/按钮释放及超时错误。
- [x] 验证多标签、多实例、跨进程 iframe、Shadow DOM、本机 DPI 与缩放、
  窗口与视口边缘、真实尺寸和画像不一致时的操作。
- [x] 回归窗口、WebGPU、种子、表单/密码等已有功能；
  旧调试路径的兼容回归与新路径的无调试验收分别记账。
- [x] 固定完整档案至少正常重启三次，完整图片/音频数据和完整网站
  画像哈希一致；动态项提前列明，不接受截断 URL、总分或“多数一致”。
- [x] 按实际改动运行仓库要求的测试；记录未测平台和能力，不虚报覆盖。

### 5. 交付与续接

- [x] 更新字段规范、调用示例、验证报告、源码/产物清单和本工作清单。
- [x] 清点测试浏览器与构建任务；已正常退出，无本任务临时代理隧道。
- [x] 记录 Windows x64 产物位置、校验值、已验收能力和明确限制。
- [x] 明确交付边界：用户已授权将上游集成与本功能汇总到 `personal-use`
  后提交、推送，并清理已合并的临时分支；
  内核包及本地测试档案不纳入 Git，本阶段不发布 Release。

## 验收资料的历史边界

旧测试已经完成，不因建立清单再次启动。旧验收使用过调试工具，
其通过记录不能证明本次新路径已经满足无调试要求。

BrowserScan 曾将异步插入的 `<symbol id="chrome">` 通过 Firefox 原生
named access 得到的 `window.chrome` 误计入 vendorFlavors，影响首屏
visitor ID。上游集成报告保留首轮失败和加载后统一复检的区别，
默认持久化 guard 没有豁免该哈希。后续沿用明确的采集条件，不改写
历史结果，也不为某个站点添加内核属性伪装。
