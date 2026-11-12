# WorkBuddy for Linux

> **⚠️ 免责声明**：本仓库**完全由 AI 开发**，所有构建脚本、补丁与文档均未经充分的人工审查与验证，可能存在未被发现的缺陷、安全隐患或行为偏差。请在充分了解风险的前提下谨慎使用；生产环境使用前请自行完成代码审计与验证。发现问题时欢迎提交 Issue。

> **Fork 说明**：本项目 fork 自 [acgq/workbuddy-linux](https://github.com/acgq/workbuddy-linux)，在其基础上持续维护与改进；原项目思路与大部分构建代码出自原作者 acgq，感谢其开创性工作。

非官方的 macOS → Linux 移植打包工程。腾讯官方 Linux 版长期停留在 5.6.2 不再更新，大量新特性无法使用，本项目将 **macOS 版 WorkBuddy 的应用代码**嫁接到**官方 Linux deb 的定制 Electron 运行时与原生模块**之上，产出可日常使用的 Linux 包。

构建产物由 GitHub Actions 自动生成并附带校验，可在 [Releases](https://github.com/guoxiaoqiao/workbuddy-linux/releases) 下载。

## 工作原理

`scripts/build.py` 是唯一入口，一次构建完成：

1. **取源**：从 `copilot.tencent.com` 更新接口拉取 macOS zip 与 Linux deb 元数据（URL/版本/sha256 严格校验，二进制按哈希缓存）。
2. **拆包**：自研 ASAR 解包器还原 macOS 应用代码，缺失的其他平台原生文件只记录跳过。
3. **换运行时**：按 macOS `Info.plist` 的 Electron 版本，从官方 Linux deb 嫁接严格匹配的腾讯定制运行时（保留 `workbuddyStorage` API 与 loading fuses）。
4. **打补丁**：让企业 IM SDK 走上游 headless/unavailable 回退（该 SDK 仅含 Mach-O/Windows 原生件）；「内置运行时」默认改为关闭（包内不含 node/python 运行时，见下）。
5. **补依赖**：按 Electron ABI 安装 better-sqlite3 / koffi / node-pty / agent-harness / sandbox-cli，全部校验完整性。
6. **打包**：便携 `tar.gz` + `.deb`，每个产物附 `.sha256`，`port-manifest.json` 记录全链路溯源。

### Debian 包对齐官方

deb 打包逻辑**尽量对齐官方 Linux deb**，原则是「资产提取优先、差异用补丁实现、全部 fail-fast 可溯源」（详见 [AGENTS.md](AGENTS.md)）：

- **直接提取**：hicolor 全部 9 个尺寸图标、四个维护脚本（preinst/prerm/postinst/postrm）、`changelog.gz`、desktop 模板、官方包 `resources/` 下的桌面集成资源（tray 图标、`default_app.asar`、`apparmor-profile`）。
- **补丁差异**：官方 postrm 会无条件删除 `/usr/bin/workbuddy`（升级时误删新包文件），已加 `$1` 守卫；postinst 增加启动器自愈；control 对齐官方字段（Section/Homepage/Description/依赖）。Maintainer 从构建者克隆的 `remote.origin.url` 自动提取（fork 后打包即为 fork 者），不冒充腾讯。
- **有意偏离**：不打包官方内置的 `resources/runtime`（node/python，约 600MB）——包内原生模块均为 N-API 预编译，实测 node 22/24 皆兼容；control 相应增加 `nodejs` 依赖（python3 系统必装，不重复声明）；「内置运行时」设置默认关闭、可手动开启（开启后应用按需下载或用系统解释器）。
- **质量件**：生成 `md5sums`（支持 `dpkg --verify`）、xz 压缩对齐官方。

## 质量保障

- `npm test`：ASAR 解包安全、sidecar 镜像、补丁守卫、运行时版本匹配、打包字段与维护脚本补丁等单元测试。
- `verify-native.cjs`：在 Electron 与 CLI Node 两种环境实测 SQLite/FFI/PTY。
- `smoke-test.mjs`：Xvfb 下真实启动，经 CDP 确认登录页渲染、凭证存储初始化、daemon ready，并采样空闲 CPU。

> 打包会完整镜像 `app.asar.unpacked`：上游从 5.11 起把 daemon 的扩展 preload（`main/preload/*.cjs`）与 `@genie/im-channels*` 等文件只放在磁盘上、不登记进 ASAR 索引；只按索引提取会让 edge-sync / remote-desktop 等扩展服务启动失败（`EXTENSION_PRELOAD_MISSING`），进而影响「手机控制」等端云能力。

## 安装

产物命名 `workbuddy_<上游版本>_base<官方deb版本>_unofficial_repack<N>_<提交号>_<架构>.deb`：`base` 标明打包所用的官方底座 deb，`repack<N>` 是重打包修订号，末尾 6 位是本仓库的打包提交，可据此定位构建脚本。

```bash
sudo apt install ./workbuddy_<上游版本>_base<官方deb版本>_unofficial_repack<N>_<提交号>_amd64.deb
```

安装路径 `/opt/WorkBuddy`，命令行入口 `workbuddy`，配置目录 `~/.workbuddy`。从官方 5.6.2 升级安装即可直接替换。

## 运行时说明

包内**不含** node/python 运行时（相比官方包小约 1/3）。应用按以下顺序解析运行时，任何一级可用即停止：

1. **已注册版本**：`~/.workbuddy/binaries/` 中已注册的运行时；注册条目会先校验可执行性，失效即跳过。
2. **系统解释器**：系统 `nodejs`（deb 依赖自动安装，N-API 原生模块对 node 22/24 均兼容）与系统 `python3`（Ubuntu 必装）。
3. **按需下载**：仅当组件需要特定版本且上述均不满足时，应用才下载官方运行时（腾讯 COS 源）到 `~/.workbuddy/binaries/`——下载是有条件行为，并非必然发生。
4. **Electron 兜底**：daemon 等组件最终可回退到 Electron 自带的 Node 运行，应用的基础功能不依赖任何外部解释器即可启动。

补充说明：

- UI 与 daemon 使用 Electron 自带 Node，无需系统安装 node 也能运行；系统 `nodejs` 主要服务于 Agent/CLI 场景。
- 设置 → 安全中心的「内置运行时」默认关闭；该开关只影响部分组件（如附加 PATH 注入、Playwright 托管 node），核心解析链不读它。
- 从官方 5.6.2 deb 升级的用户，`~/.workbuddy/binaries/` 下可能残留指向已移除的 `/opt/WorkBuddy/resources/runtime` 的注册符号链接：应用会自动跳过失效条目，无需处理；介意者可删除这些链接并清空 `~/.workbuddy/binaries/.cache/registry.json` 中的 `binaries` 条目。

## 已知限制

- **开发、测试与验证环境为 Ubuntu 26.04**；其他发行版与版本未作考虑和验证。
- 企业 IM 使用上游回退实现（无原生 SDK）。
- 构建必须在目标架构上进行（当前 CI 仅 amd64）。
- 非官方项目，与腾讯无隶属关系；应用及资源版权归腾讯所有，本仓库 MIT 仅覆盖打包脚本。
