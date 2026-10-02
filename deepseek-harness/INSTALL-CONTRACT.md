# Harness GitHub 安装契约

依据 DeepSeek 官方仓库，核对日期：2026-10-02。适用本仓库0.5.1根目录安装入口。

1. **网址格式**：使用仓库地址 `https://github.com/hengdaoye50/source-audit`。`/tree/分支` 是浏览页，不是官方 `parseInstallSpec` 接受的仓库形式。Git分支可用 `#分支`，但本插件普通安装无需指定分支。
2. **包身份**：仓库根目录必须存在合法 `package.json`。Codex的 `plugin.json` 不能代替它。
3. **组合包声明**：根 `package.json` 中声明 `dsh.bundle.patch`，指向包内存在的YAML补丁。本仓库为 `./deepseek-harness/cordis.patch.yml`。官方 `bundleManifest` 以此识别可管理的组合包。
4. **可分发资源**：`files` 包含补丁、JavaScript入口、Skill及其Python工具和说明；安装后的包不能仅有模板。根包的JavaScript `exports` 指向 `./index.js`，入口把资源基目录绑定到安装包中的 `skills/source-audit`。
5. **补丁与加载**：补丁通过 `insert` 注册唯一行，`name`与已安装包名一致。Host模块导出 `apply` 与 `inject=['skills']`；注册资源绑定Cordis生命周期。当前宿主还需具备Skill服务、调用和文件/终端能力。
6. **实际结果**：下载安装成功、组合包识别、补丁组合、模块加载、Skill发现是不同检查点。安装器的 `application` 和 `warnings` 决定当前profile是否生效；组件测试不能替代GitHub安装测试。

官方来源：

- [网址解析源码](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/boot/plugin-manager/src/install-spec.ts)
- [组合包识别与安装操作源码](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/boot/plugin-manager/src/operations.ts)
- [Host组合包与模块规范](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/preset/agent-preset/skills/cordis-plugin-development/references/host-plugin.md)
- [Plugin Manager说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/boot/plugin-manager/README.md)

历史缺陷：0.5.0的main根目录只提供Codex插件；Harness声明仅在子目录模板和专用分支。给用户分支浏览网址，或让其安装普通仓库地址，会指向不具备组合包声明的根。0.5.1改为同一仓库根同时支持Codex和Harness，普通GitHub网址即可获取完整Harness包。Python依赖仍需当前终端环境提供；不在安装脚本中悄悄安装。
