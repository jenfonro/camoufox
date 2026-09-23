# Windows x64 构建环境与续接流程

复核日期：2026-09-23。用途：复用已有 Ubuntu VM 构建 Camoufox，
将 Windows x64 产物取回本机。当前需求见[工作清单](native-control-plan.md)。

资料来自：

- [内核](codex://threads/01a085c0-f793-7ca0-b2b4-92e32c46e20a)
  原会话：窗口、WebGPU、指纹持久化、初期 VM 环境。
- [内核](codex://threads/01a0c99d-c0b2-72a2-804a-ce65592d48d2)
  当前会话：上游集成、专用密钥、代理隧道及本次环境复核。
- 仓库既有脚本、产物清单，以及本次 SSH 只读检查。

保存的本机会话记录位于
`C:\Users\79917\Desktop\codex\codex\codex-config\sessions`：

```text
2026\09\09\rollout-2026-09-09T18-40-11-01a085c0-f793-7ca0-b2b4-92e32c46e20a.jsonl
2026\09\22\rollout-2026-09-22T22-55-54-01a0c99d-c0b2-72a2-804a-ce65592d48d2.jsonl
```

这些记录用于恢复历史信息，历史“正在构建/测试”的描述不是当前状态。
原生控制接口的实现、Windows x64 构建、取回及最终包验收
现已完成；最终 `build.exit` 为 `0`，没有本任务正在运行的构建或代理隧道。
统一交付到 `personal-use`，包含上游集成与原生控制接口；
用户已授权推送到 `origin/personal-use` 并清理已合并的临时分支。
本次记录和输出位于 `camoufox-native-control-work/`；
VM 日志位于 `/home/zel/camoufox-work/native-control-api/`。
交付清单和验证边界见[最终验收](native-control-verification.md)。

## 仓库与基线

| 项目 | 当前值 |
| --- | --- |
| 本机仓库 | `C:\Users\79917\Desktop\codex\camoufox` |
| 统一交付分支 | `personal-use` |
| 实现阶段临时分支 | `codex/native-control-api`（继承上游集成基线，整合后清理） |
| 继承的已推送基线提交 | `e46a454bc4528638128df3437f7f18a04e66afc6` |
| 旧自用发行提交 | `cc9f5250a2002426e6988cb2decb17ccaa501425`，保留旧标签 |
| origin | `git@github.com:jenfonro/camoufox.git` |
| upstream | `https://proxy.zelt.cn/https://github.com/daijro/camoufox` |
| 已集成上游提交 | `5e59b70bdd4765a76f2ca50899707ef0622b9368` |
| Firefox/发行号 | `152.0.4` / `beta.31` |

准备阶段已用 `git ls-remote` 核对旧自用与上游集成分支的远端提交。
后续开发从汇总后的 `personal-use` 开始，保留完整集成基线。
环境默认 cwd 可能是旧 Nimbo 目录；所有命令显式指定正确仓库。

## 连接构建虚拟机

| 项目 | 2026-09-23 初始环境复核 |
| --- | --- |
| 地址、主机名 | `10.0.0.142`，`vmserver` |
| 用户 | `zel` |
| 系统 | Ubuntu 24.04.3 LTS；Linux `6.8.0-139-generic` |
| CPU | 16 vCPU |
| 内存 | 7.7 GiB（约 8 GB） |
| 根文件系统 | 195 GiB，已用约 82 GiB，可用约 105 GiB |
| 当前启用 swap | 合计约 24 GiB |
| 已启用的构建 swap | `/var/lib/camoufox-build/swapfile`，20 GiB，权限 `0600` |

专用 SSH 密钥路径：
`C:\Users\79917\.ssh\id_ed25519_camoufox_build`。
主机密钥通过已有 known_hosts 校验，显式使用该密钥的批处理登录已通过。
本轮不带 `-i` 的默认批处理登录失败；不要沿用更早记录中“直接 ssh 即可”的假设。
只记录凭据位置，不把私钥内容或会话密码写入仓库。

```powershell
ssh -i C:\Users\79917\.ssh\id_ed25519_camoufox_build -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=8 zel@10.0.0.142 "hostname"
scp -i C:\Users\79917\.ssh\id_ed25519_camoufox_build -o BatchMode=yes -o StrictHostKeyChecking=yes <local-file> zel@10.0.0.142:<remote-path>
```

SCP 示例中的占位符须换成实际任务文件。普通 VM SSH 直连局域网，
不需要绕 GitHub 使用的 SOCKS 代理。

### 首次重新编译前的内存准备

已核验并恢复旧的 20 GiB 文件，当前合计约 24 GiB swap。
`/etc/fstab` 仍只包含 `/swap.img`，本轮未改变开机挂载配置。
重启 VM 后先检查启用状态，不要重复创建或覆盖已有文件。

```sh
free -h
swapon --show
stat /var/lib/camoufox-build/swapfile
# 本轮已核验执行；VM 重启后需要再次检查：
sudo swapon /var/lib/camoufox-build/swapfile
```

## VM 工作目录

| 路径 | 用途与注意点 |
| --- | --- |
| `/home/zel/camoufox` | 原构建仓库根目录，含继承的窗口/WebGPU/持久化改动 |
| `/home/zel/camoufox/camoufox-152.0.4-beta.31` | 完整生成的 Firefox 源码，实际编译位置 |
| 上一目录下 `obj-x86_64-pc-windows-msvc` | 已有 Windows x64 增量编译目录 |
| `/home/zel/camoufox-native-control-api` | 本次已验收 native control v1 源码快照；通过 SCP 同步 |
| 上一目录下 `camoufox-152.0.4-beta.31` | 指向完整生成源码的符号链接 |
| `/home/zel/camoufox-work/native-control-api` | 本次源码前像、清单、更新脚本、最终构建日志与退出码 |
| `/home/zel/camoufox-upstream-integration-20260923` | 上一版已验收上游集成快照，保留作基线 |
| 上一目录下 `camoufox-152.0.4-beta.31` | 指向完整生成源码的符号链接 |
| `/home/zel/camoufox-work/upstream-integration-20260923` | 最近一次准备记录、构建脚本、日志、退出码及 Linux 测试环境 |
| 上一目录下 `previous-juggler` | 集成前两个 Juggler 资源的备份 |
| `/home/zel/.cache/camoufox-ccache` | 本任务指定的编译缓存 |
| `/home/zel/.mozbuild` | 已下载的 Clang、Windows SDK、MSVC、其他 bootstrap 工具 |
| `/home/zel/.cargo/env` | Rust 环境入口 |

生成源码内部 Git HEAD 是
`1f3bb6a76775deac711eae9883ce84c38cf026fa`；
其工作树包含已构建的定制修改，HEAD 本身不是完整产物身份。
**不能 reset/clean/revert 这个树，也不要为了新需求重新 make dir 覆盖它。**

上一版上游集成的准备记录 `prepared.json`：

- 源码快照树：`c91465e824213642fdfe2fb2790bef49dcf3d1c9`。
- 27 个继承源码/配置文件已再次按清单校验，无差异。
- `juggler/TargetRegistry.js` 和 `juggler/content/FrameTree.js`
  与集成后的已记录哈希一致。
- `build.exit` 为 `0`，`build.log` 结尾记录 Windows 打包成功。

本次 native control 的 `source-verification.json` 在构建时核验了
1137 个快照文件、56 个生成源码文件、27 个继承的定制文件，
两份 C++ 导出补丁与实际源码差异一致。打包输入的最终身份另存于本机
`camoufox-native-control-work/final-source-manifest.json`；不能用基线
Git HEAD 代替这份构建时尚未提交的源码快照清单。

验收后仅补齐文档和测试脚本，并通过小型 SCP 更新同步到本次快照。
`source-verification-final.json` 保存同步后的复核结果；打包输入仍与
构建时的最终清单完全一致，不因此重新编译。原构建时核验记录保留。

策略文件的位置：

```text
<snapshot-root>/settings/distribution/policies.json
/home/zel/camoufox/camoufox-152.0.4-beta.31/lw/policies.json
/home/zel/camoufox/camoufox-152.0.4-beta.31/obj-x86_64-pc-windows-msvc/dist/bin/distribution/policies.json
```

最后一项是指向 `lw/policies.json` 的符号链接。
生成树中不是 `lw/distribution/policies.json`。

## 工具链

| 项目 | 本次复核 |
| --- | --- |
| Python | `python3`，3.12.3 |
| Rust / Cargo | 1.98.1；通过 `/home/zel/.cargo/env` 加入环境 |
| Rust Windows 目标 | 已安装 `x86_64-pc-windows-msvc` |
| Clang | `/home/zel/.mozbuild/clang/bin/clang`，20.1.8 |
| MSVC / Windows SDK | `/home/zel/.mozbuild/vs/{VC,Windows Kits,DIA SDK}` |
| ccache | 4.9.1；指定缓存约 0.3 GB / 10 GB |
| 其他 | make、git、GCC、7z、zstd、curl、wget 已安装 |

系统 PATH 中没有普通 `clang` 命令不代表工具链缺失，实际使用
`.mozbuild` 的 bootstrap 工具。读取缓存状态也必须指定 `CCACHE_DIR`，
否则看到的是另一个默认的空缓存。

```sh
CCACHE_DIR=/home/zel/.cache/camoufox-ccache CCACHE_MAXSIZE=10G ccache --show-stats
```

现有 `mozconfig` 名称**没有前导点**，目标为
`x86_64-pc-windows-msvc`，启用了 bootstrap，未开启跨语言 LTO。
没有源码/版本变更需求时，不要重新下载或升级工具链。

## 代理与 GitHub

| 链路 | 本次结果 |
| --- | --- |
| Windows `127.0.0.1:7890` Mihomo HTTP 代理 → GitHub | HTTP 200 |
| Windows 局域网地址 | `10.0.0.210` |
| VM → `10.0.0.210:7890` | Connection refused，当前不能直用 |
| SSH 反向隧道 → Windows 本地代理 → GitHub | HTTP 200 |
| `https://proxy.zelt.cn/https://github.com/daijro/camoufox` 的 Git 协议 | `git ls-remote upstream HEAD` 成功 |

代理站对仓库网页 URL 的普通 HTTP 请求返回 403，但 Git smart HTTP
查询成功。不能用网页响应判断 Git 加速是否可用。其他下载路径需按实际 URL 检查。

需要 VM 下载时，复用已验证的临时反向隧道：

```powershell
ssh -i C:\Users\79917\.ssh\id_ed25519_camoufox_build -o BatchMode=yes -o StrictHostKeyChecking=yes -o ExitOnForwardFailure=yes -N -R 127.0.0.1:17890:127.0.0.1:7890 zel@10.0.0.142
```

该命令保持连接。用独立终端/任务会话运行，任务结束后结束自己创建的隧道；
若用 Windows `Start-Process` 管理后台进程，使用 `-WindowStyle Hidden`。
不要修改 Mihomo 全局配置，也不要把 VM 的 `127.0.0.1:7890` 当成宿主机代理。

仅在需要联网的 VM 命令/会话中设置：

```sh
export HTTP_PROXY=http://127.0.0.1:17890
export HTTPS_PROXY=http://127.0.0.1:17890
export NO_PROXY=localhost,127.0.0.1
```

本地 origin 的 Git SSH 已有仓库级 `core.sshCommand`：
Windows OpenSSH 通过
`C:/Program Files/Git/mingw64/bin/connect.exe -S 127.0.0.1:7890 %h %p`
走 SOCKS。它与 VM 的专用密钥是两个用途，不要混用。

## 源码同步、编译与打包

用户已指定：本机准备修改，通过 SCP 同步到 VM，**不在 VM 重新 git pull**。
仓库是 Firefox 源码的构建/补丁系统：修改实际源码后导出差异到 `patches/`，
完整新文件放 `additions/`。不能只改生成树而遗漏可重建的仓库输入。

本任务使用独立的 `camoufox-native-control-work/` 本地证据目录、
`/home/zel/camoufox-native-control-api` 源码快照、
`/home/zel/camoufox-work/native-control-api` 日志和源码前像目录。
复用现有生成树和 objdir；旧基准、脚本和日志保持原样。

1. 先保存将修改文件的真实源码前快照和哈希。Windows 上的
   `camoufox-152.0.4-beta.31` 只是曾取回的部分源码，不是完整 Linux 编译树。
2. 创建包含本次实际修改的源码快照和 manifest。仅归档旧 HEAD 会遗漏
   未提交改动；快照身份必须明确，排除缓存、产物、档案和 `.git`。
3. SCP 上传并校验。在新快照根下指向已有生成树时先检查目标路径；
   不递归复制旧 objdir，不覆盖旧备份。
4. 对需要更新的生成文件与 additions/settings 建立明确映射，
   检查继承修改，再应用本次修改。旧 `prepare_vm.py` 有一次性检查，
   **不可直接重复执行**或当成新任务通用准备器。
5. 构建、打包、记录退出码、取回并校验。

旧的实际成功构建命令如下；先完成上面的内存与源码准备：

```sh
cd /home/zel/camoufox/camoufox-152.0.4-beta.31
. /home/zel/.cargo/env
export BUILD_TARGET=windows,x86_64
export MOZCONFIG=$PWD/mozconfig
export CARGO_BUILD_JOBS=1
export CCACHE_DIR=/home/zel/.cache/camoufox-ccache
export CCACHE_MAXSIZE=10G
./mach build -j4
```

16 vCPU 不等于可以开 16 路编译；历史配置为 `-j4`、Cargo 1 路，
且使用了额外 swap。并发按实际内存调整。

本次打包位置与命令：

```sh
cd /home/zel/camoufox-native-control-api
. /home/zel/.cargo/env
make package-windows arch=x86_64
```

后续任务应在它自己的源码快照根目录打包，不把旧快照当作新源码。
长期编译使用独立后台任务、`build.log` 和 `build.exit`；
`running` 与数值退出码分开记录，不能只按日志中出现成功文字判断。
不要连续刷新屏幕；有意义的进展约每分钟汇报，结束后核对任务已退出。

可参考但不要覆盖/照搬的本地历史脚本：

```text
camoufox-persistence-work/upstream-integration-20260923/build.sh
camoufox-persistence-work/upstream-integration-20260923/prepare_vm.py
camoufox-persistence-work/stage_sources.py
camoufox-persistence-work/export_patch.py
camoufox-persistence-work/build-persistence.sh
camoufox-persistence-work/package-persistence.sh
```

## 已验收的产物与提取方法

本次 native control v1 的 VM 产物：

```text
/home/zel/camoufox-native-control-api/camoufox-152.0.4-beta.31-win.x86_64.zip
```

本机交付压缩包、解压目录和配套清单：

```text
dist/camoufox-152.0.4-beta.31-native-control-v1-win.x86_64.zip
dist/windows-x64-native-control-v1/camoufox.exe
dist/camoufox-152.0.4-beta.31-native-control-v1-win.x86_64.manifest.json
```

大小 `493161259` 字节，SHA-256：

```text
dbb4e65e183a12dac86f51a82207cb644f7f688d7fb64ac41e229502a1f03b30
```

本机与 VM 哈希一致，ZIP CRC、Windows x64 PE、配置/策略及 30 项
打包模块已核验。最终产物不是开发阶段的 `windows-x64-native-control-dev`
临时覆盖目录。最终源码、产物和全部验收汇总分别见：

```text
camoufox-native-control-work/final-source-manifest.json
camoufox-native-control-work/artifact.json
camoufox-native-control-work/validation.json
```

以下是保留的上一版上游集成基线，不能误当成本次新接口的交付包。
其 VM 产物为：

```text
/home/zel/camoufox-upstream-integration-20260923/camoufox-152.0.4-beta.31-win.x86_64.zip
```

本机：

```text
dist/camoufox-152.0.4-beta.31-personal-use-upstream-20260923-win.x86_64.zip
dist/windows-x64-upstream-20260923/camoufox.exe
```

大小 `493135784` 字节。本轮重新读取本机压缩包计算 SHA-256，与旧记录一致：

```text
d6130eaa895b358e59b005700a1f892bd208a78bd49658ab5ae49a6560c28864
```

源码、打包资源、产物与测试证据在：

```text
camoufox-persistence-work/upstream-integration-20260923/artifact.json
camoufox-persistence-work/upstream-integration-20260923/source-manifest.json
camoufox-persistence-work/upstream-integration-20260923/source-preservation.json
camoufox-persistence-work/upstream-integration-20260923/baseline-candidate-comparison.json
camoufox-persistence-work/regressions/
```

旧对照目录 `dist/windows-x64-persistence-v1-final/` 保留。
提取新产物时使用独立文件名/目录，示意：

```powershell
scp -i C:\Users\79917\.ssh\id_ed25519_camoufox_build -o BatchMode=yes -o StrictHostKeyChecking=yes zel@10.0.0.142:<new-archive-path> <new-local-archive-path>
Get-FileHash -LiteralPath <new-local-archive-path> -Algorithm SHA256
```

除传输哈希外，还应检查 ZIP CRC、文件清单、包内修改资源与源码的对应关系。
构建后直接取回内核包即可，不自动发布 Release。

## Windows 运行验证环境

- Python：仓库 `.venv\Scripts\python.exe`，已安装 Playwright 等历史测试依赖。
- Node：`C:\Users\79917\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe`。
- Git Bash：`C:\Program Files\Git\bin\bash.exe`。
- 历史测试使用 `PYTHONPATH=<repo>\pythonlib`、`PYTHONUTF8=1`、
  `CAMOUFOX_TEST_BASH=<Git Bash>`；需要网络时使用 Windows 本地 7890 代理，
  localhost/127.0.0.1 不走代理。
- JSON 显式 UTF-8 读写；不要用 `Get-Content -TotalCount` 打印巨大单行 JSON，
  只解析所需元数据。
- 使用独立测试档案和虚构数据，不读取或改动管理器真实档案、数据库、
  Cookie、密码。不使用 computer-use 技能控制用户桌面。

历史窗口/WebGPU guard 中有 Marionette 辅助代码。这些可用于既有能力回归，
不能作为新控制接口“无需调试”的证明。新接口的测试需要独立客户端和
不依赖上述调试会话的证据链。
