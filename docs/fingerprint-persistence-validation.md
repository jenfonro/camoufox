# 指纹持久化 Windows x64 验收

日期：2026-09-11。分支：codex/fingerprint-persistence，继承窗口与 WebGPU
实现。状态：源码实现、Windows x64 构建、取回和最终包运行验收均已完成。

接口及缺省语义见[持久化配置规范](fingerprint-persistence.md)。继续使用
canvas:seed、audio:seed、fonts:spacing_seed 三个已有字段；完整画像由调用方
保存并回放，内核负责固定输入的确定性行为。

## 最终产物

| 项目 | 值 |
| --- | --- |
| Windows x64 压缩包 | dist/camoufox-152.0.4-beta.31-persistence-v1-final-win.x86_64.zip |
| 大小 | 493136049 字节 |
| 包 SHA-256 | 261e9bc1109152c04d7c468cb9bb89734b5133679d392b6c1b7ff0153295cae9 |
| 已解压内核 | dist/windows-x64-persistence-v1-final/camoufox.exe |
| xul.dll SHA-256 | 4c88c4943bd035ea6d91ed6628aefd64081111507223cdfb0a3f400d79ab959c |
| camoufox.exe SHA-256 | 6a37d6ddbf18c479b4238057565de1443df02bfdb3c18a4df55da7e6d84322fc |

使用既有 Ubuntu 构建机交叉编译，通过 SCP 同步源码和取回产物。
最终构建日志为 persistence-build-v3.log，打包日志为 persistence-package-v3.log。
压缩包 CRC、传输前后 SHA-256、两项二进制与构建目录的字节哈希均已核对。
包内 camoucfg.jvv 与本分支的配置 schema 完全相同。
仓库改动已通过 SCP 同步回构建机；使用仓库相同的 GNU patch 参数在
修改前快照上重建，16 个源文件与实际编译源树的 SHA-256 全部一致。

## 严格画像验收

测试从一次生成的完整配置开始，保存到 profile-a.config.json。三个独立
浏览器进程复用同一测试用户目录，均正常退出后重开。每次比较：

- BrowserScan 实际页面的 32 个静态身份/能力字段。
- 页面使用的八个完整哈希、完整字体检测列表（71 项）及 WebGPU 报告数据。
- Canvas、WebGPU 详情页的完整哈希、数据表及可用的完整 PNG 数据。
- 原生探针的完整图像导出、像素和音频 Float32 字节，以及字体/布局、
  navigator、屏幕、语音列表和当前权限状态下的媒体设备结果。

读取页面当前用于展示的报告状态，核对它与页面的八位缩写相符，再比较
完整值；不使用缩写、data URL 前缀或总体评分替代验收。

下列 A 档案完整哈希在三次重启中逐项完全一致，刷新和新页面也一致：

| 报告 | A 档案完整哈希 |
| --- | --- |
| Canvas | 2df36cf53cd6289288b763b025317a8fdfc9c8f5 |
| WebGL | 34c27e81727dbf1199e0bf53cb477737debc1809 |
| WebGL Report | 170d25e0f28cf6d6085084fa67bc1f759380de4e |
| Audio | afb772e059d666433abfeec8d772ad90beabaf71 |
| Client Rects | 53a76918d934394e262015ec47f3e8f5862401bc |
| WebGPU Report | a31d5575b749f73d0145edc85851064cf17b2bea |
| Fonts | 464e406ea80193ef98fb07d13b51382a5613e6af |
| visitor ID | 396a5b6f0f22f2c382d2f147e56c5f42e973bfc1 |

B 档案改变三个种子及 WebGPU 测试画像，Canvas、WebGL 图像、Audio、
Client Rects、WebGPU 和 visitor ID 均按输入变化。字体集合及 WebGL 参数
画像没有更换，它们的报告哈希继续相同，符合输入含义。例如 B 的完整值为：

| 报告 | B 档案完整哈希 |
| --- | --- |
| Canvas | 59d8881e00a9deeccb6bb5fb2f104df9e07abbc0 |
| Audio | 644a2e324009c26e98001c3b2494be87ff5c0234 |
| Client Rects | f00882518ed7652013cfd64dc71f697ef3a04f99 |
| WebGPU Report | 1fb70aece21fb81b81906d7ceb557b652a68bbbb |

A/B 都是验收用固定配置；这些哈希由网站计算，不是传给内核的参数。

## 功能、生命周期及兼容性

持久化套件共 12 组通过，包含 15 次正常启动/退出及 12 个非法输入拒绝：

- A 档案三次重启；完整数据反复读取、刷新、新页面和同源 iframe。
- DedicatedWorker、SharedWorker、ServiceWorker 的图像、身份与 WebGPU 数据。
- 分别更换 Canvas、Audio、字体种子，以及独立 B 档案的可控差异。
- Canvas 种子缺省与显式零均保留跨进程的原生会话随机化。
- 显式启用原生完整 Canvas/WebGL 像素随机化后，三次重启仍稳定；
  同时确认像素确实受到扰动，没有误测成默认 PNG 元数据路径。
- 清除测试站点 Cookie 和原生随机键缓存后，固定画像不变；换站点产生
  原生分区差异，返回原站点又得到原值。
- 旧用户分支中的上下文 seed/disabled 值不污染新的启动画像。
- 三个字段各覆盖布尔、负数、溢出与浮点数输入，均报告键名并退出 1。

另外，现有 font/audio 上下文接口共检查 12 次读取（六种组合及重读）：
显式零覆盖非零启动值、非零覆盖缺省/零启动值、不同上下文先后使用不
污染结果。HTML Canvas、主线程 OffscreenCanvas 和三类 Worker 的字体
测量一致；这些 setter 在普通页面脚本运行前保持隐藏。

音频验证包含 copyFromChannel 非零偏移、与 getChannelData 的字节一致性、
三次播放节点接管/恢复，以及调用者直接写入数据后不被重复变换。
图像验证保存完整 PNG/JPEG/WebP、Blob/data URL、完整像素及区域读取。

## 仓库及已有功能回归

| 验证 | 最终包结果 |
| --- | --- |
| 原生种子契约与音频序列测试 | 通过 |
| Python 种子、窗口、schema、WebGPU 相关单测 | 107/107 |
| build-tester，固定八份输入，完整 Canvas 哈希 | 1054/1054 |
| service-tester，当前 Python wheel，固定六份上下文输入 | 765/765 |
| 窗口模式、实际窗口恢复及最大化 | 12 组通过 |
| WebGPU 默认/开放/画像/重启/WARP/兼容性/取消覆盖 | 10 组通过 |

WebGPU 回归仍得到前一阶段的 A=4977D61D、B=D7A82B5B，A 的 GPU/WARP
报告一致；关闭暴露时仍为 not support。这里使用前一阶段专用测试画像，
因此其值与上表持久化测试画像的值不同。

这些套件结果对应本次保存的具体输入。前一阶段另有 Windows 基础画像
配合 macOS 上下文的静态平台/字体一致性问题；本次没有将其认定为已经
解决，也不把固定六份输入通过推广为任意跨系统组合均通过。该问题不属于
本次观察到的同画像跨重启漂移。

## 定位和修复记录

1. Canvas 原来的会话根键由 UUID 生成，已有 canvas:seed 未进入该路径。
   现在只在显式非零种子时使用固定派生，继续走原生分区和编码链。
2. Linux Global 的旧 ClientRects 漂移来自异步字体字符映射回退：首次
   查找可能跳过尚未加载的候选字体。相同输入的同步加载对照消除了差异；
   修复后冷/热读取均为 305.91668701171875，原先失败的回归现已通过。
3. 音频切片的种子序列原先从头开始；JS 通道被接管再恢复时还会重复
   变换。频谱读取也会修改 FFT 历史。这些路径已分别修正。
4. 上下文字体 seed 在 Worker 中原先回落到启动 seed。最终包改为读取
   Worker 原生 OriginAttributes，三类 Worker 均验证通过。

早期测试记录保留在工作目录。两处采集时序问题也有独立记录：空 Worker
字体集的 ready 等待，以及语音引擎初始空列表。采集器现按 API 的初始化
状态等待完整结果；没有将已经完成的画像报告差异当作动态值忽略。

## 比较边界与原始记录

比较前已列明动态项：当前时间/测量时长、真实网络及 IP 衍生状态、广告、
站点会话请求标识、导航历史，以及有动态语义的实验挑战输入。BrowserScan
visitor ID 作为画像哈希明确纳入比较。字体/语音和页面报告完成初始化后
才采样；摄像头、麦克风权限没有在测试中更改。

所有测试使用独立目录，没有读取、清理或改写 Nimbo/CPM 的真实档案。
原始报告、完整字节和失败排查记录保留于 camoufox-persistence-work/：

- final-v1/results.json：十二组最终验收汇总。
- final-v1/profile-a-run-1 至 profile-a-run-3：每次的完整 BrowserScan、
  详情、原生字节和 Worker 结果；profile-a.config.json 为固定输入。
- context-seeds-all-workers-final.json：上下文与三类 Worker 覆盖。
- window-final/results.json、webgpu-final/results.json：已有功能回归。
- regressions/build-final.json、regressions/service-final.json：仓库回归。
- final-artifact.json、validation-summary.json：产物哈希及汇总。

重放命令：

    python tests/patches/fingerprint-persistence-windows.py dist/windows-x64-persistence-v1-final/camoufox.exe --output camoufox-persistence-work/acceptance-rerun

需要复用此处的同一配置时，先把 final-v1/profile-a.config.json 复制到新的
输出目录。测试将新建自己的用户目录，不使用真实帐号目录。
