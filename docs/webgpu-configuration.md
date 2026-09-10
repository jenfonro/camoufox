# 图形加速与 WebGPU 配置规范 v1

日期：2026-09-11。状态：用户已授权完整实现及 Windows x64 构建测试。
本分支已实现这些配置，Windows x64 功能验收已通过，详见
[验收记录](webgpu-validation.md)。旧的上游发行包不支持新增参数，
需要使用本分支构建。

## 目标与配置入口

在 Camoufox 现有 `CAMOU_CONFIG` JSON 中增加三个顶层键。继续支持已有
分块环境变量传输，管理器、直接启动器及 Python 包使用相同数据结构。

| 键 | 类型 | 缺省行为 |
| --- | --- | --- |
| `gfx:hardwareAcceleration` | boolean | `false`，保留 Camoufox 自带的硬件加速禁用策略 |
| `webgpu:enabled` | boolean | `false`，通过 Firefox 原生机制关闭网页 WebGPU 暴露 |
| `webgpu:profile` | object | 不覆盖画像数据；WebGPU 开放时沿用原生返回值 |

顶层键及后文的包装对象是 Camoufox 的配置扩展，不是 W3C 标准协议。
画像内部使用当前 Firefox 152.0.4 WebIDL 对应的标准名称、类型和对象
关系。配置不含任何管理器的档案 ID、数据库字段、随机模式或网站哈希。

画像和两个开关独立：仅传画像不会开启 WebGPU，也不会开启硬件加速。
管理器负责生成、保存并在每次启动时传入画像，内核不额外保存一份画像
或自动生成缺失字段。

## 两个开关的语义与优先级

`gfx:hardwareAcceleration=false` 或未传时，保留发行策略
`HardwareAcceleration=false` 的原有行为。`true` 时不再应用 Camoufox
自带的这一条禁用策略，使 Firefox 按正常机制初始化图形能力。

它是许可开关，不保证一定选中硬件 GPU；不设置
`layers.acceleration.force-enabled`、`layers.d3d11.force-warp`，也不
主动修改管理器明确设置的其他 Firefox 图形偏好。真实设备、驱动和
其他原生限制仍由 Firefox 判断。已有高级偏好仍具有其原生含义。

`webgpu:enabled` 在启动时映射到当前进程的 `dom.webgpu.enabled`，
本次开关值优先于普通 profile 中保存的旧值；未传按 `false` 处理。
这是临时启动配置，不将映射值或画像写回 profile 的持久偏好。
其他管理策略锁定、安全上下文、服务工作线程开关、域名限制以及正常
的适配器失败条件，继续沿用 Firefox 的规则，不通过该参数绕过。

所有配置在相关初始化前读取并固定到本次启动；修改需要重启。禁止
将设置延迟到 Juggler `Browser.enable` 后才生效。子进程及支持的 Worker
使用相同配置快照。v1 是浏览器启动级配置，不新增运行中逐档案切换接口。

| 合法配置 | 预期 |
| --- | --- |
| 所有新键均未传 | 保留加速禁用策略，网页 WebGPU 关闭 |
| 仅允许硬件加速 | 浏览器可按原生判断使用 GPU，网页 WebGPU 仍关闭 |
| 开放 WebGPU，没有画像 | 尝试原生设备路径，返回原生数据或正常的失败结果 |
| 开放 WebGPU，并传画像 | 在有效后端上按画像呈现数据 |

当前旧发行包是 WebGPU 接口存在但某些默认设备路径失败。本规范默认
关闭接口，会改变 API 暴露状态；不能因为两者在 BrowserScan 都显示
`not support` 就称其为 API 层面完全兼容。硬件加速的旧策略则按要求保留。

## 画像对象

`webgpu:profile` 只接受以下三个成员，均可省略：

| 成员 | 类型 | 用途 |
| --- | --- | --- |
| `gpu` | object | `GPU` 对象层级的数据 |
| `adapter` | object | 所有成功适配器请求的通用画像 |
| `adapterOverrides` | array | 按标准请求选项匹配的特定覆盖 |

`gpu` 接受：

- `wgslLanguageFeatures`：字符串集合，以 JSON 数组传入；只接受当前
  Firefox 编译器实现支持的功能，并与 WGSL `requires` 等验证相衔接。
- `preferredCanvasFormat`：`rgba8unorm` 或 `bgra8unorm`，对应
  `getPreferredCanvasFormat()` 的返回值。它是首选格式，不额外禁止
  页面在 `GPUCanvasContext.configure()` 中使用其他原生允许的格式。

`adapter` 和每项特定覆盖中的 `adapter` 接受：

- `info`：当前标准 `GPUAdapterInfo` 的七个属性：`vendor`、
  `architecture`、`device`、`description`、`subgroupMinSize`、
  `subgroupMaxSize`、`isFallbackAdapter`。
- `features`：当前 Firefox `GPUFeatureName` 名称集合，以字符串数组传入。
- `limits`：当前 Firefox `GPUSupportedLimits` 的同名数值属性。

不存在 `renderer` 到 WebGPU `description` 的隐式转换，也不接受
`wgpuDriver` 等 ChromeOnly 诊断字段、BrowserScan 条目编号、采集网站
的 `Empty/undefined` 文案或指定哈希字段。

只有上述标准入口属于 v1 覆盖范围。纹理功能通过 features 和实际
设备能力约束，不额外建立一套可随意填真假值的纹理探测结果表。
性能时间、图像像素噪声、媒体编解码能力不属于本项接口。

## 部分字段与集合

优先级为：原生数据 → 通用 `adapter` → 本次选中的特定覆盖。
`info`、`limits` 按字段叠加；`features` 在所在层级显式出现时整体替换
前一层集合。`gpu` 的两个属性同样只覆盖显式输入的值。

- 不传画像、画像为 `{}`、只传空的 `gpu/adapter` 对象：不覆盖相应数据。
- 只传 `info.vendor`：仅覆盖 vendor，其他字段保留前一层的值。
- `features` 未传：继承前一层；传入 `[]`：明确要求空集合，不表示原生。
  空集合是否符合所选 feature level 的必要功能规则仍须校验。
- 空字符串、`false`、`0` 不等于未传；是否有效取决于对应字段的规则。
- `null` 不代表继承或清除，因类型不符而报配置错误。
- features 和 WGSL 集合去重并按名称排序，以确定的顺序构造原生集合；
  不与未声明的本机功能自动取并集。

完全没有相关覆盖时，保留原生集合及其行为，不额外重排。部分画像
只能固定所覆盖的数据；未覆盖部分仍可能随环境变化，由管理器决定
是否需要准备完整画像。

## 特定适配器覆盖

每个 `adapterOverrides` 条目由 `request` 与 `adapter` 组成。
`request` 至少包含一项，只允许以下标准选项：

| 条件 | 允许值 | 页面请求缺省值 |
| --- | --- | --- |
| `powerPreference` | `low-power`、`high-performance` | 未指定，保持原生语义 |
| `forceFallbackAdapter` | boolean | `false` |
| `featureLevel` | `core`、`compatibility` | `core` |
| `xrCompatible` | boolean | `false` |

这是匹配页面请求的条件，不是选择执行后端的管理指令。
`compatibility`、`xrCompatible` 不会因此获得当前 Firefox 尚未实现
的额外能力，实际请求仍沿用原生处理。

匹配规则固定如下：

1. 按原生 WebIDL 规则转换页面请求，再按上表补齐缺省值。
2. 条件中出现的每个键都必须与本次请求相等；未写出的键不限制匹配。
   未指定 `powerPreference` 的请求不匹配显式指定该键的条件。
3. 多条匹配时，条件键更多的一条优先；只选择一条覆盖，再叠加到通用
   `adapter` 上，不同时串行应用所有匹配项。
4. 条件数量相同且可能同时匹配的条目，作为歧义配置拒绝。重复条件
   同样拒绝。数组顺序不会改变结果。
5. 没有匹配条目时只使用通用画像；通用画像也缺失时保持原生。

选中真实适配器后才应用数据覆盖。原生返回 `null` 时，不凭画像创建
虚构的可执行适配器，也不为补齐条目数量自动切换硬件或软件后端。

显式 `forceFallbackAdapter=true` 的请求须保持回退请求语义。若画像
显式设置 `isFallbackAdapter`，该请求的有效值必须为 `true`；通用画像
显式设为 `false` 时，应由相应覆盖改为 `true`。不暗中替调用方改值。
没有配置该字段时仍保留 Firefox 自身的原生处理。

## 类型、校验与正常失败

新配置自身必须在原生启动入口校验，不能只依赖 Python 包。启动器
可以预先校验同一格式；`properties.json`、`camoucfg.jvv` 等描述同步
维护。仅对本次新增键及其子树规定严格规则，不改造全局未知键行为。

类型、未知子字段、未知功能名、数值越界及条件歧义属于配置错误：
在配置阶段报告字段路径和原因，拒绝本次无效配置启动；不静默忽略
后继续使用原生画像。已传入的画像即使暂未开放 WebGPU，也需要通过
格式校验。完全不传画像不触发这类错误。

数值规则：

- 布尔值只接受 JSON 布尔值，不接受 `0/1` 或字符串。
- 32 位无符号字段接受范围内的非负整数，此外遵守字段自身约束。
- 64 位容量字段使用 64 位存储；v1 JSON 输入限定为非负安全整数，
  上限 `9007199254740991`，避免跨语言序列化丢失精度。不用字符串
  或浮点近似值扩展这个范围，不截断到 32 位。
- 子组范围与 limits 还须符合所用功能的必要边界和关联约束。
- 当前 Firefox 152 尚未实现 subgroups，显式子组大小只接受原生
  4/128 组合；已知但未实现的 features 在适配器兼容性校验时拒绝。
- 当前底层的四个 `maxStorageBuffers/TexturesInVertex/FragmentStage`
  与相应 `PerShaderStage` 共用值。显式输入须与叠加后的对应每阶段
  限制一致，不能声明本版本无法单独执行的阶段限制。
- 限制值遵守其类别：最大容量更大意味着能力更强，对齐值更小意味着
  要求更宽松。禁止统一按 `min()` 或 `max()` 合并后端与画像。

与设备有关的兼容性在取得实际适配器后验证。有效画像的 features
必须能够由当前 Firefox 实现及所选后端兑现，limits 不得宣称更强的
实际能力，也须满足标准默认能力与功能依赖。

若特定请求的画像不兼容，记录明确原因，该次 `requestAdapter()`
按无可用适配器返回 `null`。不关闭全局接口、不退回原生画像、不偷偷
删功能或改数值。其他合法请求仍按各自配置处理。

页面随后调用 `requestDevice()` 时，`requiredFeatures` 和
`requiredLimits` 对照有效画像能力验证，并由真实后端执行。超出可用
能力的页面请求按 Firefox/WebGPU 的正常错误语义处理。

## 原生对象与执行的一致性

网页返回值继续使用 Firefox 原生对象、原型和集合实现，保留只读
属性、`SameObject`、Promise、设备生命周期和正常错误行为。

`GPUAdapter.info` 和其派生设备的 `GPUDevice.adapterInfo` 使用同一份
有效画像。`GPUDevice.features/limits` 则遵循设备请求与默认能力的
原生规则，不直接复制整个适配器集合。

能力覆盖要同时参与属性读取、请求校验和可选功能使用的限制；仅改
getter 而不改变有效能力验证，不视为本项完成。

身份字段不参与真实驱动选择、设备标识匹配或纹理共享。内部诊断的
ChromeOnly 硬件字段继续描述真实执行后端。显式画像覆盖对应的网页
字段；没有覆盖的字段保留内核现有隐私处理，包括原生空值。

普通页面、iframe 和原生支持 WebGPU 的 Worker 使用一致策略；不为
某个检测网站加入分支，不关闭其他指纹防护来间接实现本项。

## 配置示例

仅允许硬件加速，网页仍不暴露 WebGPU：

```json
{
  "gfx:hardwareAcceleration": true
}
```

允许加速并开放 WebGPU，但沿用原生报告：

```json
{
  "gfx:hardwareAcceleration": true,
  "webgpu:enabled": true
}
```

通用画像加回退请求覆盖的结构示例。示例是部分画像，不是采集的
完整设备画像；相应能力必须由实际后端支持，需要本分支的新内核：

```json
{
  "gfx:hardwareAcceleration": true,
  "webgpu:enabled": true,
  "webgpu:profile": {
    "gpu": {
      "preferredCanvasFormat": "bgra8unorm"
    },
    "adapter": {
      "info": {
        "vendor": "example_vendor",
        "description": "Example GPU",
        "isFallbackAdapter": false
      },
      "features": [
        "core-features-and-limits",
        "texture-compression-bc"
      ],
      "limits": {
        "maxTextureDimension2D": 8192,
        "maxBufferSize": 268435456
      }
    },
    "adapterOverrides": [
      {
        "request": {
          "forceFallbackAdapter": true
        },
        "adapter": {
          "info": {
            "vendor": "example_software_vendor",
            "description": "Example software adapter",
            "isFallbackAdapter": true
          }
        }
      }
    ]
  }
}
```

## 后续实现的完成条件

- 两个开关独立；跨启动不被上次启动写入的临时配置影响。
- 开放但无画像时保留原生返回，部分画像遵循明确的覆盖规则。
- 条件匹配和集合结果确定，参数顺序不改变有效画像。
- Window/Worker、适配器/设备以及能力验证与执行一致。
- 验证 BrowserScan 实际显示结果，并验证原生设备、计算和渲染路径；
  不能只以某个网站哈希变化作为完成依据。
- 软件后端可单独用于验证，不能将本机 WARP 实测当作无 GPU 服务器
  完整验收；也不承诺任意硬件上的像素、性能或所有站点哈希都相同。

上述条件作为运行验收依据，测试结果与构建标识见验收记录。
背景和证据见 [事项记录](kernel-change-decisions.md)、
[接口调研](webgpu-interface-research.md) 与
[启动问题调查](webgpu-startup-findings.md)。
