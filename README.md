# WorkBuddy for Linux

> **Fork 说明**：本项目 fork 自 [acgq/workbuddy-linux](https://github.com/acgq/workbuddy-linux)，在其基础上持续维护与改进；原项目思路与大部分构建代码出自原作者 acgq，感谢其开创性工作。

非官方的 macOS → Linux 移植打包工程。腾讯官方 Linux 版长期停留在 5.6.2 且空闲 CPU 占用偏高，本项目将 **macOS 版 WorkBuddy 的应用代码**嫁接到**官方 Linux deb 的定制 Electron 运行时与原生模块**之上，产出可日常使用的 Linux 包。

构建产物由 GitHub Actions 自动生成并附带校验，可在 [Releases](https://github.com/guoxiaoqiao/workbuddy-linux/releases) 下载。

## 工作原理

`scripts/build.py` 是唯一入口，一次构建完成：

1. **取源**：从 `copilot.tencent.com` 更新接口拉取 macOS zip 与 Linux deb 元数据（URL/版本/sha256 严格校验，二进制按哈希缓存）。
2. **拆包**：自研 ASAR 解包器还原 macOS 应用代码，缺失的其他平台原生文件只记录跳过。
3. **换运行时**：按 macOS `Info.plist` 的 Electron 版本，从官方 Linux deb 嫁接严格匹配的腾讯定制运行时（保留 `workbuddyStorage` API 与 loading fuses）。
4. **打补丁**：让企业 IM SDK 走上游 headless/unavailable 回退（该 SDK 仅含 Mach-O/Windows 原生件）。
5. **补依赖**：按 Electron ABI 安装 better-sqlite3 / koffi / node-pty / agent-harness / sandbox-cli，全部校验完整性。
6. **打包**：便携 `tar.gz` + `.deb`，每个产物附 `.sha256`，`port-manifest.json` 记录全链路溯源。

### Debian 包对齐官方

deb 打包逻辑**尽量对齐官方 Linux deb**，原则是「资产提取优先、差异用补丁实现、全部 fail-fast 可溯源」（详见 [AGENTS.md](AGENTS.md)）：

- **直接提取**：hicolor 全部 9 个尺寸图标、四个维护脚本（preinst/prerm/postinst/postrm）、`changelog.gz`、desktop 模板、官方包 `resources/` 下的桌面集成资源（tray 图标、`default_app.asar`、`apparmor-profile`）。
- **补丁差异**：官方 postrm 会无条件删除 `/usr/bin/workbuddy`（升级时误删新包文件），已加 `$1` 守卫；postinst 增加启动器自愈；control 对齐官方字段（Section/Homepage/Description/依赖）。Maintainer 从构建者克隆的 `remote.origin.url` 自动提取（fork 后打包即为 fork 者），不冒充腾讯。
- **质量件**：生成 `md5sums`（支持 `dpkg --verify`）、xz 压缩对齐官方。

## 质量保障

- `npm test`：ASAR 解包安全、补丁守卫、运行时版本匹配、打包字段与维护脚本补丁等单元测试。
- `verify-native.cjs`：在 Electron 与 CLI Node 两种环境实测 SQLite/FFI/PTY。
- `smoke-test.mjs`：Xvfb 下真实启动，经 CDP 确认登录页渲染、凭证存储初始化、daemon ready，并采样空闲 CPU。

## 安装

```bash
sudo apt install ./workbuddy_<版本>_amd64.deb
```

安装路径 `/opt/WorkBuddy`，命令行入口 `workbuddy`，配置目录 `~/.workbuddy`。从官方 5.6.2 升级安装即可直接替换。

## 已知限制

- **开发、测试与验证环境为 Ubuntu 26.04**；其他发行版与版本未作考虑和验证。
- 企业 IM 使用上游回退实现（无原生 SDK）。
- 构建必须在目标架构上进行（当前 CI 仅 amd64）。
- 非官方项目，与腾讯无隶属关系；应用及资源版权归腾讯所有，本仓库 MIT 仅覆盖打包脚本。
