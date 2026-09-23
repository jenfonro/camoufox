# 上游合并与 Windows x64 验证

上游集成最初在 `codex/sync-upstream-20260923` 完成；当时 `personal-use`
位于 `cc9f5250a2002426e6988cb2decb17ccaa501425`。
集成与验证结果已提交为 `e46a454bc4528638128df3437f7f18a04e66afc6`，
并按用户要求推送至 `origin/codex/sync-upstream-20260923`；未发布 Release。
用户随后要求将该上游集成与原生控制接口一并汇总到 `personal-use`，
以自用分支作为最终推送目标，再清理已合并的临时分支。
历史分支清理后，可通过以上提交在自用分支历史中检索本次集成。
2026-09-23 续接时已核对远端提交；当前环境与复用方法见
[Windows x64 构建环境](windows-x64-build-environment.md)。

- 上游提交：`5e59b70bdd4765a76f2ca50899707ef0622b9368`。
- 共同基线：`b6aa72ea5a97851bb9f56164efa974d751e36b31`。
- 上游新增四个提交：三个 README 更新，以及 PR #772 的测试流水线、
  Juggler 与 Python 修正。
- Firefox 版本仍为 `152.0.4-beta.31`，没有升级 Firefox。

## 保留的自用功能

以下路径与合并前逐字节相同：

```text
patches/
additions/camoucfg/
settings/
scripts/package.py
.github/workflows/build.yml
```

因此窗口全局覆盖／画像／原生模式、WebGPU 画像与硬件加速开关、
Canvas／Audio／字体种子、默认随机行为，以及可由偏好开启的表单历史、
密码保存策略均保留。

此前自用开发涉及的 52 个文件中，49 个在本次合并后完全相同。
其余三个文件的变化为：

| 文件 | 合并处理 |
| --- | --- |
| `build-tester/src/lib/checks/collectors.ts` | 唯一文本冲突；保留完整导出 SHA-256 和完整字体列表，同时纳入上游像素读回哈希 |
| `pythonlib/camoufox/utils.py` | 上游修改自动合并，已有自用参数逻辑保留 |
| `tests/patches/fingerprint-persistence-windows.py` | 排除有明确 DOM 标记的站点广告文字，并保存原始单元格和广告文字；没有删除画像比较项 |

VM 上复用的 Firefox 源码在构建前核对了 27 个已有定制源码／配置文件。
实际更新的 Juggler 资源为 `TargetRegistry.js` 的录屏视口信息和
`content/FrameTree.js` 的销毁时 sandbox 释放逻辑。打包后的两个资源又与
Git 中的内容逐字节核对。

## CI 处理

原有手动 `build.yml` 不变：选择哪个 ref，就使用哪个 ref 的源码、
补丁和配置构建。

新增的上游 `Tests` 流水线在 fork 中使用当前分支的源码构建／原生输入缓存。
官方仓库仍可对仅修改 Python 的 PR 下载官方发行版。
这避免 fork 的自动测试漏掉该分支此前已有的内核改动。

补充的兼容处理：

- 按四个自用 guard 各自的 CLI 传入二进制、输出目录和固定种子配置。
- 三个 Windows guard 在其他系统明确记录跳过；全部不适用或名称拼错返回错误。
- Juggler 资源映射与原生输入哈希采用统一的 `/` 路径，修复 Windows 自测失败。
- Canvas 和 Emoji 同时比较完整导出和完整像素读回；错误占位值不能作为稳定结果通过。

用法见 [CI 文档](../ci/README.md)。

## 实际验证

所有浏览器测试使用独立测试档案；没有读取或修改管理器的真实档案。

| 检查 | 结果 |
| --- | --- |
| CI 脚本自测 | 177/177 |
| Linux 仓库规范检查 | 24/24 |
| C++ 窗口、图形配置、种子检查 | 3/3 |
| 定向 Python 测试 | 115/115；实际集成源码的启动几何测试另有 19/19 |
| TypeScript 类型检查与检查脚本打包 | 通过 |
| 固定八档案 build-tester | 1054/1054 |
| 固定六上下文 service-tester，使用当前 Python 源码 | 765/765 |
| 通过 CI guard 入口运行窗口测试 | 12 组通过 |
| 通过 CI guard 入口运行 WebGPU 测试 | 10 组通过 |
| 通过 CI guard 入口运行种子上下文测试 | 12 个输出对照通过 |
| 持久化完整阶段 | 12 组通过，其中非法输入检查 12 项 |
| 表单／密码默认、开启、重开、关闭 | 4/4 |

持久化阶段覆盖正常关闭后重开、刷新、新标签页、iframe、三类 Worker、
种子单项修改、第二档案、未传／零种子、全随机化及上下文生命周期。
表单和密码使用本地虚构数据验证；地址与银行卡仅验证模块及偏好启用状态，
没有声称完成真实网站上的填写测试。

新旧内核使用同一份冻结配置，配置文件 SHA-256 为：

```text
eece5d37a6f9d56e725797fa2bac20e566541a418f47b9b2a20a0749b3c8dced
```

新旧版各正常重启三次后，原生报告、Worker、iframe、网站完整身份报告、
详情表格及图像导出共 17 组跨版本直接比较全部相同。
网站比较采用下节说明的页面加载后复检条件。

| BrowserScan 报告 | 新旧版共同的完整哈希 |
| --- | --- |
| Canvas | `2df36cf53cd6289288b763b025317a8fdfc9c8f5` |
| WebGL | `34c27e81727dbf1199e0bf53cb477737debc1809` |
| WebGL Report | `170d25e0f28cf6d6085084fa67bc1f759380de4e` |
| Audio | `afb772e059d666433abfeec8d772ad90beabaf71` |
| Client Rects | `53a76918d934394e262015ec47f3e8f5862401bc` |
| WebGPU Report | `a31d5575b749f73d0145edc85851064cf17b2bea` |
| Fonts | `464e406ea80193ef98fb07d13b51382a5613e6af` |
| visitor ID | `9e382f91d9fef5be6fd9d9c6b3f642b173ebe877` |

本次构建和运行验证针对 Windows x64。没有执行完整的 Linux Playwright
浏览器流水线，也没有触发 GitHub 云端测试。

## BrowserScan 首屏差异与验证边界

保留了两次未通过的初始记录，没有把它们改写为通过：

1. Google 广告将文字插入 Languages 等报告值中。采集器现在只临时隐藏
   `.google-anno-skip.google-anno-sc` 标记的广告节点来读取报告，随后原样恢复。
   原始文字和被排除的广告文字均留在输出中；广告本来就是预先声明的动态项。
2. 一次首屏 visitor ID 为 `a6b242d3b973a7a692ba362ede4d0f415876bf1d`，
   刷新后为 `9e382f91d9fef5be6fd9d9c6b3f642b173ebe877`。
   32 个哈希输入中，唯一数据差异是 `vendorFlavors` 从 `[]` 变成 `["chrome"]`。

进一步在未注入属性的页面上确认，`window.chrome` 实际是网站异步插入的
`<symbol id="chrome">` SVG 图标，类型为 `SVGSymbolElement`。
这是 Firefox 原生 Window 按元素 ID 查找属性的行为。网站的检测器将这个
元素计作浏览器厂商对象，图标和指纹采集的先后顺序因此影响 visitor ID。
即使稍后页面加载完成，首次检测缓存的哈希也不会自动重算。

从网站公开脚本提取 32 项输入和序列化规则后，离线重算准确复现了两个
完整 SHA-1；仅替换 `vendorFlavors` 就能从第一个得到第二个。
没有为这个站点改变内核的原生属性行为。

追加对照采用固定流程：每次导航都先等待网站各模块和图标加载完成，
保留初始报告，再通过可见的 **Check again** 按钮复检一次。
新旧内核均执行同样流程，随后运行原有完整比较，包括 visitor ID、
全部八个完整哈希和 32 个身份单元格。

这个条件下的通过不等于“网站首屏在任意加载顺序下都稳定”。
默认持久化 guard 仍严格比较首次报告的 visitor ID，没有新增哈希豁免。
追加复检脚本和所有初始失败证据保存在本地工作目录。

## 产物与证据

压缩包：

```text
dist/camoufox-152.0.4-beta.31-personal-use-upstream-20260923-win.x86_64.zip
```

解压目录：`dist/windows-x64-upstream-20260923/`。
压缩包大小为 `493135784` 字节，SHA-256：

```text
d6130eaa895b358e59b005700a1f892bd208a78bd49658ab5ae49a6560c28864
```

相对于前一个 Windows 包，没有新增或删除文件；变化仅为
`camoufox.exe`、`xul.dll`、`omni.ja` 及两个 INI 文件的 BuildID。
策略、配置和其余资源相同。ZIP CRC 与打包资源核对均通过。

构建使用的暂存源码树为 `c91465e824213642fdfe2fb2790bef49dcf3d1c9`；
后续修改仅涉及测试采集、工作流注释与文档，不改变打包的内核源码。

本地证据根目录：
`camoufox-persistence-work/upstream-integration-20260923/`。
其中 `artifact.json`、`source-preservation.json`、
`baseline-candidate-comparison.json`、`ci-guards/`、`browser-features/`、
`baseline-settled/`、`candidate-settled/`、`site-diagnostic/`
分别保留产物、源码保护、直接对照、功能回归与网站诊断记录。
八档案及服务回归的完整结果位于 `camoufox-persistence-work/regressions/`。
