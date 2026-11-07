# AGENTS.md

面向在本仓库工作的 AI 助手与人工维护者的工程规范。修改任何文件前请先读完本文件。

## 项目定位

非官方的 macOS → Linux 移植打包工程：把腾讯 macOS 版 WorkBuddy 的应用代码，嫁接到官方 Linux deb 遗留的定制 Electron 运行时和原生模块上，产出 `.deb` 与便携 `tar.gz`。应用本体归腾讯所有，本仓库 MIT 许可仅覆盖打包脚本（见 `NOTICE-linux.txt`）。

## 核心规则：打包逻辑尽量对齐官方 deb

**一切打包行为（Debian control、维护脚本、desktop、图标、文档、目录布局、压缩格式）以官方 Linux deb 为基准，尽量对齐。** 官方 deb 在构建时本来就作为「运行时捐献者」被下载并解包（`build.py` 中 `metadata("workbuddy-linux-...")` → `dpkg-deb -x`），因此对齐资产零额外下载成本。

落实为四步，缺一不可：

1. **提取优先**：图标（hicolor 9 个尺寸 16–512）、四个维护脚本、`changelog.gz`、desktop 模板、官方包 `resources/` 下的桌面集成资源（`tray-linux*.png`、`default_app.asar`、`apparmor-profile`）一律在构建时用 `extract_debian_assets()` 从官方 deb 原样提取，不做二次创作。
2. **补丁实现差异**：确需与官方不同的内容，以带守卫的正则补丁实现（`patch_postrm` / `patch_postinst` / `patch_desktop`），风格对齐 `patch_linux()`。
3. **fail-fast 守卫**：每个提取断言与补丁正则匹配失败必须抛 `ValueError` 中断构建——宁可停构建也不出坏包。
4. **manifest 记录**：提取清单（`debianAssets`）与补丁说明（`debianPatches`）写入 `port-manifest.json`，保证产物可溯源。

## 已知上游陷阱（改动打包前必读）

- **官方 postrm 的缺陷**：不判断 `$1`，无条件 `rm -f /usr/bin/workbuddy`。dpkg 升级时旧包 postrm 以 `upgrade` 参数在解包新文件之后执行，会删掉新包的启动器。因此我们的 postrm 补丁必须保留 `$1` 守卫，postinst 补丁必须保留启动器自愈块。
- 官方 control 使用 `Section: default` 与 9 项依赖；我们因 Electron 37 需要更多依赖，是超集对齐，不要删减。
- 上游 URL/ASAR 结构/压缩代码的严格匹配是**有意设计**；上游改版导致构建失败时，先复审对应提取/补丁函数，不要放松断言。

## 合规红线

- Maintainer **不写死**：构建时从 `git config remote.origin.url` 提取 GitHub 仓库所有者作为 Maintainer（`repository_owner()`）——**谁 fork 就是谁**：fork 者克隆自己的仓库构建时，remote 指向其 fork，Maintainer 自动变为 fork 者的用户名，无需任何配置；**不得**设置 Vendor 字段或冒充腾讯为维护者。脱离 git 仓库（无 remote）构建会 fail-fast。
- 不声明官方授权；MIT 仅覆盖打包脚本；应用与资源的归属声明见 `NOTICE-linux.txt`（已装入 `usr/share/doc/workbuddy/NOTICE`）。

## 维护纪律

- **开发、测试与验证环境为 Ubuntu 26.04**；其他发行版与版本未作考虑、未作验证。涉及依赖名（如 `libasound2t64`）、dpkg/debhelper 行为的改动需在 Ubuntu 26.04 上实测；不要为其他环境引入未经验证的兼容分支。

- 打包行为有任何用户可见变化 → bump `PACKAGING_REVISION`（`build.py` 顶部）。
- **产物命名由 `output_stem()` 统一生成**：`workbuddy_<上游版本>_base<官方deb版本>_unofficial_repack<N>_<架构>.deb`。`base<官方deb版本>` 取捐献者官方 Linux deb 的完整 packageVersion（可溯源到底座），`unofficial` 标识非官方，`repack<N>` 即 `PACKAGING_REVISION`（重打包修订号，放末尾让同内容各次 repack 相邻排序）。文件名里**不放** `deb` 字样（扩展名已表达）和 Electron 版本。改命名逻辑须同步 `test_build.py` 的命名测试。
- 改动以下任何文件必须同步运行 `npm test` 并保持全绿：`scripts/build.py`、`scripts/test_build.py`、`scripts/*.sh`、`scripts/*.mjs`、`scripts/*.cjs`。
- 新增/删除打包相关文件时，检查 `.github/workflows/release.yml` 的 `on.push.paths` / `on.pull_request.paths` 白名单是否覆盖（历史教训：`LICENSE`/`README.md` 曾被漏掉）。
- 新增纯函数优先做成可单测的形态（参照 `control_text`、`write_md5sums`），测试放入 `scripts/test_build.py`。
- Arch 打包已移除（原 `build-arch.py`/`PKGBUILD.in`）；如需恢复，须从便携包重建并对齐同样的四步法。

## 常用命令

```bash
npm test                     # 20 项单元测试（ASAR 安全、补丁守卫、打包字段、产物命名等）
./scripts/build-deb.sh       # 仅构建 deb（需网络，产物在 dist/）
./scripts/build-linux.sh     # 便携包 + deb
node scripts/smoke-test.mjs work/current-amd64/WorkBuddy   # Xvfb 下真实启动冒烟
scripts/verify-install.sh    # 目标机上验证已安装的 deb（完整性/自愈/守卫/桌面注册）
```

## 入库纪律

仓库公开：任何提交不得包含专有信息（内网 IP、机器名、本地路径、账号），所有脚本与文档必须保持通用性；维护者身份一律通过 `repository_owner()` 从 git 配置派生，不写死人名。
