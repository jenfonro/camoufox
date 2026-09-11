# PR #606 持久化种子接口参考

日期：2026-09-11。当前阶段：分析，未移植代码、修改内核或启动浏览器测试。

用户指定参考 [daijro/camoufox#606](https://github.com/daijro/camoufox/pull/606)，
以已有接口和实现为依据，减少为单个管理器设计独有的参数。已读取 PR
说明、14 个文件的代码差异、种子实现和测试，以及评论/评审记录。

用户明确：本 PR 与 CPM、VirtualBrowser 等均为参考资料。下面的接口
和算法是 PR 事实或可选借鉴方向，不构成必须移植的需求。实际改动
始终以 Firefox 原生机制及 Camoufox 现有字段为基础。

读取时状态为 open，未合并。作者 PopcornDev1，来源
`VulpineOS/camoufox:feat/persistent-fingerprint-seed`，
固定参考提交为 `3641acad9463bc67b55c2872a864c0226c3c2e0c`。
评论只有一条提及维护者的信息，没有已通过的代码评审记录。
因此它是上游待合并的接口提案，不应描述成已经发布的标准功能。

## PR 提出的接口

新增参数名是 `fingerprint_seed`，属于 Python 画像生成入口，支持：

- `launch_options()`，并通过 Camoufox / AsyncCamoufox 启动链使用。
- `NewContext()`、`AsyncNewContext()`。
- `generate_context_fingerprint()`。
- BrowserForge 生成/转换、预设转换与 WebGL 采样的内部参数传递。

主种子类型为 `str | int | bytes`，拒绝 bool 和其他类型。
`None` 或不传保持原有随机生成。0 是一个有效的主种子，与缺失不同；
整数 123、字符串 "123" 和对应 bytes 有不同的派生材料。

主种子由 Camoufox Python 消费，不作为 Playwright 的未知启动参数
或 context 参数继续透传。显式 config/配置覆盖仍应优先于生成值。

PR 提议的调用方式如下；当前本地持久化分支尚未移植该参数：

```python
with Camoufox(
    fingerprint_seed="profile-a",
    persistent_context=True,
    user_data_dir="profiles/profile-a",
) as context:
    ...
```

这三项分别负责生成输入、持久上下文和用户数据目录，不能彼此代替。

## 子种子与已有内核字段

| 用途 | PR 的派生命名空间 | 结果进入哪里 |
| --- | --- | --- |
| Canvas | `canvas:seed` | 现有 CAMOU_CONFIG 同名字段 |
| Audio | `audio:seed` | 现有 CAMOU_CONFIG 同名字段 |
| 字体间距 | `fonts:spacing_seed` | 现有 CAMOU_CONFIG 同名字段 |
| 字体集合 | `fonts` | 生成后的 fonts 列表 |
| 语音集合 | `voices` | 生成后的 voices 列表 |
| WebGL 采样 | `webgl` | 生成后的 webGl 厂商、型号和能力配置 |
| BrowserForge | `browserforge` | navigator、screen 等生成数据 |
| 系统、预设、屏幕偏移、历史长度 | `os`、`preset`、`screen`、`history` | 相应生成字段 |

`fingerprint_seed.py` 的派生规则已核对：

1. 版本标签为 `camoufox:fingerprint-seed:v1`。
2. 主种子编码带 `str:`、`int:` 或 `bytes:` 类型前缀；文本使用 UTF-8，
   整数使用十进制 ASCII。
3. 版本、用途命名空间、带类型的种子三部分分别加 8 字节大端长度前缀。
4. 对拼接材料计算 SHA-256，按请求取高位整数；默认 64 位。
5. `derive_uint32_seed()` 使用派生的 64 位值模 `4294967295` 再加 1，
   产生 1..4294967295 的非零子种子。它不是简单截取哈希的 32 位。

这种按用途分别派生的方式不会因为新增一个采样项目，就必然推进
其他项目共享的随机序列。移植时应保留版本标签、类型编码、命名空间
及已提供的测试向量，不能只采用相同函数名却换一个算法。

测试中的 `derive_uint32_seed("profile-a", "canvas")` 是通用帮助函数
的测试向量；实际配置调用使用命名空间 `canvas:seed`，不能混用。

主种子语义与具体字段也不同：主种子 0 可以派生非零值，不能据此
改变现有低层 audio/font 种子 0 的无自定义扰动约定。

## PR 覆盖的范围

它固定的是 Camoufox 自己生成的身份配置：包括 BrowserForge 的抽样、
字体/语音集合、WebGL 数据库采样、种子等。WebGL 查询增加了明确排序，
seeded 分支使用局部 numpy RNG。BrowserForge 分支通过锁保护临时替换
随机源并在结束时恢复，同时有 seeded/unseeded 并发测试。

PR 明确声明只修改 Python/API 层，没有 Firefox C++、网络/TLS、
实际渲染或配置画像持久存储的改动。尤其：

- 它仍然只是生成 `canvas:seed`，没有添加当前内核缺失的读取与应用。
- 它移除了 per-context 脚本中对不存在的 `setCanvasSeed()` 的调用。
- 它没有稳定 Firefox 新进程的浏览会话随机键，也没有处理 PNG deBG。
- 它不包含我们新增的 WebGPU 配置、开关和画像，不会由主种子自动
  生成一套后端可执行的 WebGPU 画像。

这与先前 CPM 分析一致：生成数据确定、保存并回放数据、内核实际
读取稳定，是三个互补环节。这个 PR 主要提供第一个环节。

## 测试能证明什么

种子帮助函数有固定测试向量、类型/命名空间分离、无效参数、局部 RNG
复现测试；其他测试覆盖 API 参数传递、生成配置相同、不同种子的变化、
未提供种子仍随机、BrowserForge 并发和 macOS 属性清单定位。

但 `tests/patches/live-fingerprint-seed.py:34` 的 Canvas 函数返回
`c.toDataURL().slice(0, 96)`。它既没有对完整 PNG 做摘要，也不能检查
位于 IDAT 后面的 deBG 元数据。该测试使用 data URL 页面，未验证
持久 user_data_dir 的 BrowserScan 完整报告；其运行还要求显式设置
`CAMOUFOX_EXECUTABLE_PATH`，否则两个 live 测试会跳过。

PR 描述的结果是 18 passed / 2 skipped，这是作者报告而非我们本轮
执行结果。不能用它证明当前 Firefox 152 的 Canvas 网站哈希已稳定。
我们继续按既定验收检查网站实际完整值、同档案正常关闭重开至少三次、
不同档案，以及 Worker/读取和导出路径的一致性。

## 可借鉴内容与实施边界

1. 若后续确有生成层接口需求，可参考 `fingerprint_seed` 的名称、
   类型与分用途派生方法；当前不能因为参考了此 PR，就把新增主种子
   入口或移植其整套 Python 生成逻辑列为必做。
2. 内核继续接受现有 `canvas:seed`、`audio:seed`、
   `fonts:spacing_seed` 及显式画像字段。重点补齐 Canvas 的原生消费
   和随机键稳定化，不让直接启动器必须依赖 Python 才能固定画像。
3. 管理器可保存主种子和生成后的完整配置。长期档案优先回放已经
   保存的配置；主种子用于可重复生成，而不是假定设备库、生成库和
   浏览器升级后重新生成的每个值永远不变。
4. 显式 config 优先；保持已有窗口模式与 WebGPU 规则。
   `webgpu:profile` 仍由管理器提供或保存，未提供时按原生语义处理。
5. 如需借鉴代码，以固定提交核对相关逻辑，不整体覆盖其旧文件：当前分支已有
   window:profile、config_overrides、按屏幕关联的 WebGL 采样、语言
   相关语音选择及 WebGPU 校验等，PR 的较早上下文没有覆盖这些路径。

这些内容只是上游提案参考，不把 Python 生成层的私有参数伪称为
Web 标准，也不要求其他语言的管理器采用 Python 的完整采样实现。
其他管理器可以直接传入明确的低层配置；若要得到与该 PR 相同的子
种子，应遵循上述逐字节算法并使用其测试向量验证。

验收标准独立于参考项目的测试强度：同档案未改配置，网站实际画像
的完整哈希必须保持不变，天然动态项预先明确列外；不能沿用只比较
数据 URL 前 96 个字符的检查来宣称完成。严格规则见持久化分析。

## 资料与状态

- [PR #606](https://github.com/daijro/camoufox/pull/606)
- [种子帮助函数（固定提交）](https://github.com/daijro/camoufox/blob/3641acad9463bc67b55c2872a864c0226c3c2e0c/pythonlib/camoufox/fingerprint_seed.py)
- [浏览器测试（固定提交）](https://github.com/daijro/camoufox/blob/3641acad9463bc67b55c2872a864c0226c3c2e0c/tests/patches/live-fingerprint-seed.py)
- [CPM 与内核分析](fingerprint-persistence-analysis.md)

原始 API 结果和固定提交文件保存在忽略目录
`camoufox-persistence-research/pr-606/`。本轮只有只读调研、静态检查
和文档更新，没有运行 PR 代码、合并 PR、修改管理器或编译内核。
