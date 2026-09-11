# 日常浏览功能的启动配置

personal-use 分支已解除 Camoufox 自带的表单历史和密码管理策略限制。
这是配置调整，无需重新编译 Firefox。

## 改动

settings/distribution/policies.json 中移除了 DisableFormHistory、
PasswordManagerEnabled、OfferToSaveLogins 三项硬性策略，并从扩展卸载名单
中移除了 formautofill@mozilla.org。其他策略继续按原配置执行。

策略不再锁定这些功能；具体是否启用交给每个档案的 Firefox 用户偏好。
新档案没有传入开启偏好时，仍保留 Camoufox 原有的相关默认关闭值。

## 使用

[browser-feature-options.json](browser-feature-options.json) 是需要合并到
现有启动选项的示例，包含两部分：

- config：disableTheming=true，跳过 Camoufox 的精简样式，使用 Firefox
  原生界面样式，恢复标签区域正常交互。
- firefox_user_prefs：开启表单历史、密码保存/填充、地址/银行卡填充的
  支持，以及地址栏历史建议、自动补全和最多 10 条下拉结果。

例如使用现有 Camoufox Python 接口：

    options = json.loads(Path("docs/browser-feature-options.json").read_text())
    with Camoufox(
        executable_path=kernel_path,
        persistent_context=True,
        user_data_dir=profile_directory,
        config={**saved_fingerprint_config, **options["config"]},
        firefox_user_prefs={**saved_firefox_prefs, **options["firefox_user_prefs"]},
        headless=False,
    ) as context:
        ...

上述变量由调用方提供。示例是增量选项，不要用里面的 config 替换整份
已保存的画像，否则会丢失已有种子、屏幕及 WebGPU 等输入。

直接运行可执行文件时，将 config 部分合并进既有 CAMOU_CONFIG 配置，
将 Firefox 偏好写入该档案的 user.js，再用已有 --profile 参数启动。
firefox_user_prefs 是启动器选项，不是 CAMOU_CONFIG 的一个字段。

同一档案需复用固定用户目录，才能保留浏览历史、表单历史和已保存密码。
在旧档案里关闭某项功能，应显式传入 false 或 off；仅仅不再传该项，
不会保证清除该档案已保存的用户偏好。

地址和银行卡的 supported="on" 表示明确开启支持。希望遵循 Firefox 的
地区判断时，可以选择 supported="detect"；enabled 仍是独立开关。

本示例没有开启网络搜索建议、自动恢复上次标签会话等其他功能。前进/
后退已有能力继续保留。原生主题通过已有参数选择，没有修改主题源码。

## 验证与产物

使用独立测试档案验证通过：

1. 默认状态没有相关策略锁，表单历史和密码记忆仍默认关闭。
2. 传入示例偏好后，原生表单提交能够产生表单历史记录。
3. 本地虚构登录表单触发原生密码保存提示，确认保存后页面自动填入。
4. 正常退出并复用同一测试目录，表单记录和密码保留，自动填充继续工作。
5. 显式关闭偏好后停止自动填充，既有测试数据仍保留。
6. 地址/银行卡功能的 available/enabled 状态及内置扩展激活状态正确；
   本轮对此验证的是启用状态，未覆盖实际填写流程。
7. 地址栏查询能打开下拉，并返回实际写入的历史访问条目。

原始记录在 camoufox-persistence-work/browser-features/verification/ 和 ui/。
所有登录和表单数据均为独立测试目录中的虚构数据。

已更新现有解压目录中的 distribution/policies.json：

    dist/windows-x64-persistence-v1-final/

同时生成单独的更新包：

    dist/camoufox-152.0.4-beta.31-personal-use-win.x86_64.zip

包大小为 513106089 字节，SHA-256 为：

    690040b38f0d4eea4211c52e26dc6f592d0ed6fc58c36359ad63ad13884c56e4

新包通过 CRC 校验，并逐条比较了解压后的 SHA-256：只有
distribution/policies.json 改变。camoufox.exe 和 xul.dll 均与已验收的
持久化内核一致；旧的 persistence-v1-final 压缩包保留原状。
