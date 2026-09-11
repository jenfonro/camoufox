# WebGPU v1 Windows x64 验收记录

日期：2026-09-11。分支：`codex/webgpu-configuration`。
状态：最终 Windows x64 包已取回并完成实际运行验收。新增功能验收通过，
通用回归中已有失败另列如下，未将它们记为全通过。

## 最终产物

- 内核压缩包：`dist/camoufox-152.0.4-beta.31-webgpu-v1-final-win.x86_64.zip`。
- 大小：493157036 字节（约 470 MiB）。
- SHA-256：`d78c5a3a4cf9fcdc0393d271e1a71b8c09f481e464b74d188937dd6d33a9aa83`。
- 已解压可执行文件：`dist/windows-x64-webgpu-v1-final/camoufox.exe`。
- 包内 `xul.dll` SHA-256：
  `25843b653c5a980e33533d0f10c9e696e52ab0a0e58425cd5c5be9990609eaaf`。

压缩包 CRC、传输前后 SHA-256、包内 xul.dll / camoufox.exe 与虚拟机
实际编译产物哈希均已核对一致。最后一次完整构建日志为
`webgpu-build-7.log`，用时 5 分 47 秒；最终打包为
`webgpu-package-final.log`。源码按开发分支管理，内核包保留本机，
未发布 Release。

## 已实现范围

- `gfx:hardwareAcceleration` 只解除 Camoufox 自带的硬件加速禁用策略。
- `webgpu:enabled` 在图形与网页初始化前控制原生 WebGPU 暴露。
- `webgpu:profile` 支持标准身份字段、features、limits、WGSL 功能与
  首选画布格式，以及基于标准请求选项的特定覆盖。
- 画像作用于原生对象、设备请求验证和可选功能执行。WGSL 限制同时
  检查 requires 声明及实际扩展语法、内建函数。
- 无画像保留原生；无效配置报告路径并正常退出；与后端不兼容的画像
  只使相应适配器请求失败，不改写画像或选择其他后端。
- 修正 Windows 获取合成器设备标识的返回方式，避免没有设备时读取
  未初始化的输出参数；没有新增自动软件回退行为。

## 最终包功能验收

最终包跑完 9 组正常配置场景，均正常退出：默认、只允许
硬件加速、开放原生 WebGPU、档案 A、A 重启、档案 B、WARP、选择性
不兼容以及重新关闭暴露。
另外 5 种无效配置均输出字段路径与原因，退出码为 1，没有异常崩溃。
汇总记录将这 5 种输入合为一组，共计 10 组全部通过。

| 场景 | BrowserScan 首页 WebGPU Report |
| --- | --- |
| 默认或只允许硬件加速 | `not support` |
| 开放 WebGPU，无画像 | `F8F33FAB` |
| 档案 A | `4977D61D` |
| 档案 A 重启 | `4977D61D` |
| 档案 B | `D7A82B5B` |
| 档案 A 使用 CPU/WARP | `4977D61D` |

A 的完整哈希：`4977d61d0da0da9906cefb224ffdca7debd3607d`。
B 的完整哈希：`d7a82b5b9ab77050276436c08d7613ff09753148`。

这里 A/B 是明确标注的测试画像，不能将其示例名称当作真实设备数据库。
同一画像在本机两种后端相同，不构成任意硬件、驱动、像素或性能的
跨机器一致性保证。

原生执行验证包括：计算着色器将 `[2,3,5,7]` 变为 `[4,6,10,14]`，
渲染管线输出并读回 16 个 `[51,102,204,255]` 像素，画布呈现、
原生对象与 SameObject、派生设备身份、iframe、Worker、功能与限制
请求验证、WGSL 规则及特定请求画像。

最终新增的验证确认：即使着色器未写 requires，关闭的
`pointer_composite_access`、`readonly_and_readwrite_storage_textures`
也会产生编译/验证错误；保留的 packed 整数功能仍正常编译。
原生模式下这三项功能的合法用法均正常编译。

既有窗口功能完整回归 12 组通过，包括画像与真实尺寸分离、原生模式、
重启恢复、最大化恢复、旧式全局窗口与内视口配置。
打包的 Python wheel 通过公共 AsyncCamoufox 接口传入新配置，BrowserScan
实际显示自定义 `qa_python` 厂商，确认公共启动路径可用。

## 单元及仓库回归

- 原生 C++ 配置契约测试通过：布尔类型、无画像、部分覆盖、完整集合
  替换、请求条件优先级、顺序独立、歧义、64 位容量与无效输入。
- Python 相关测试 72 项通过，涵盖新增配置、schema、现有窗口和启动
  环境/几何回归；JSONVV 示例校验通过。
- build-tester：新内核与旧窗口版本使用相同 8 份测试画像，均为
  `1053/1054`。唯一共同失败是 Linux Global 的
  `Unstable: clientRects changed between collections`。它是旧内核也
  存在的失败，本次没有将其消除，也不能把该套件表述为全通过。
  后续持久化分支已定位并修复这个异步字体回退问题，其最终包为
  1054/1054；见[持久化验收](fingerprint-persistence-validation.md)。
- service-tester：使用打包的 Python wheel 和本机 Mihomo 代理，最终
  固定的一组启动/上下文输入为 `765/765`。
- 该套件的另一类基础画像组合会失败：固定 Windows 基础画像并创建
  macOS 上下文，3 个 macOS 上下文各出现 Direct3D renderer 与平台
  不一致、缺少 macOS 版本字体两项失败，总计 `759/765`。使用同一组
  固定输入对照旧内核，也得到完全相同的 6 项失败。该已有问题未修改；
  不能将单次随机输入通过推广为所有跨系统画像组合都通过。
- 可选 uBlock Origin 下载返回 HTTP 451，未阻断套件；本次未验证该
  扩展的安装可用性。

## 验收期间修复的交付问题

1. 无效配置原先在 XPCOM 部分初始化后返回，导致异常退出；已前移到
   主启动入口，最终包已确认退出码为 1。
2. service-tester 原先读取隔离世界不可见的页面变量，产生空结果且
   把 0/0 算为成功。现通过共享测试页面发布的 DOM 结果节点取值，
   空结果或错误明确失败；没有删除或放宽已有检查。
3. 打包脚本原先使用 `7z u`。重复构建中相同大小和时间戳可能使旧
   二进制保留在包里，实际已发现包内与编译产物的 xul.dll 哈希不同。
   现生成全新临时压缩包后原子替换；等尺寸/等时间戳内容更新及
   清除旧条目的打包回归测试通过。

## 原始记录

本机保留独立测试档案与报告于 `camoufox-webgpu-verification/`，
没有读取或修改 Nimbo/CPM 的真实档案。测试浏览器正常关闭，测试目录
保留供复查。虚拟机日志位于 `/home/zel/camoufox-work/logs/`。
最终报告：

- `final-v1/results.json` 与各场景 `result.json`：最终包功能与 BrowserScan 验收。
- `final-v1/invalid-startup.json`：5 类非法输入正常退出。
- `window-final/results.json`：12 组窗口回归。
- `python-launch-final/result.json`：打包 Python API 的真实启动验证。
- `build-tester-final.json`、`build-tester-baseline.json`：新旧同输入比较。
- `service-paired-final.json`：最终包固定输入 765/765。
- `service-windows-final.json`、`service-windows-baseline.json`：已有 6 项
  跨系统画像失败的同输入对照。

早期报告：

- `full-v1/`：默认、加速、原生模式。
- `profiles-v1/`：A/B、重启、WARP 和错误隔离。
- `build-tester-captured-v1.json`、`build-tester-baseline.json`：同画像新旧比较。
- `service-tester-v1-fixed.log`：修复采集后的真实 765/765 结果。

配置用法见 [配置规范](webgpu-configuration.md)。源码改动已导出为
`patches/zz-webgpu-configuration.patch` 并核对能精确对应构建树；这是
仓库的源码变更保存格式，交付内核已直接包含这些实现。
