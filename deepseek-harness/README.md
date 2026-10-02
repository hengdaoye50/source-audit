# DeepSeek Harness 来源核准插件

本包是原 source-audit 的 Harness 适配入口，共用同一套证据格式、提取器、校验器和 Word 导出器。主稿支持 Word；PDF 有文字层时优先提取，必要时按页 OCR。语义由执行工作流的模型复核，不把检索分数当作核准结论。

## 安装

下载并解压 `source-audit-deepseek-0.5.0.zip`，保留整个 `source-audit-deepseek` 文件夹。源码中的 `deepseek-harness/` 只是适配模板，不能直接安装；从源码打包：

```text
python scripts/build_deepseek_bundle.py --output dist/source-audit-deepseek-0.5.0.zip
```

Python 3.10+ 及依赖需要在所用终端环境中可用。在解压后的目录执行：

```text
python -m pip install -r requirements.txt
```

在 Harness 的聊天中要求其调用官方 `plugin_manager` 工具，参数为：

```json
{"action":"install_bundle","target":"D:/your-folder/source-audit-deepseek"}
```

`target` 使用实际的绝对目录。安装涉及当前 Harness profile，应遵循宿主的权限提示。检查安装结果中的 `application`、`warnings`；遇到 `failed` 或 `restart-required` 时先处理对应状态，不能仅凭文件已复制判断启用。不要手改 profile 的 package.json 或 cordis.patch.yml。替换已安装包可能需要重启。

本插件注入 `skills` 服务：当前配置需包含官方 `@deepseek-ai/dsh-skill`，以及宿主的 Skill 调用、终端、文件访问能力；缺少这些能力时应先补全宿主配置。本包没有 npm 依赖、安装脚本、模型配置或外部 MCP 服务，不安装 OCR 语言包。

## 使用

在新会话调用 `source-audit` Skill，例如：

> 使用 source-audit 核准指定文件夹中 Word 主稿的文献和政策引用。参考全文在同一文件夹。只取来源正文，保留完整句段，标明章节及页码或 Word 段落；逐项说明支持边界和处理建议，最终生成 Word 报告。

按照 Skill 中的步骤执行。检索、读取和证据校验在本地进行；模型阅读片段使用当前 Harness 配置的模型服务，因此不保证完全离线。原稿和参考文献不打入本插件。

Windows 扫描页可按需使用附带 Windows OCR；其他平台仍可读取 Word 与 PDF 文字层，但没有可用 OCR 时须标记无法核准。报告导出后需要额外的 Word 渲染能力进行页面验收，缺少该能力必须说明未完成页面验收。

## 接口与验证

适配基于官方 [Host 插件规范](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/preset/agent-preset/skills/cordis-plugin-development/references/host-plugin.md)及 [Skill 注册接口](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill/src/index.ts)。当前 Harness 是开发预览版本，升级后应重新进行加载测试。

可在已有 Harness 安装上运行隔离测试，不调用模型，不修改 profile：

```text
node scripts/check_deepseek_host.mjs --host-root <安装的@deepseek-ai/dsh目录> --bundle <完整解压目录>
```

该检查只验证真实 Cordis/Skill 组件中的挂载、发现、资源定位与卸载，不能替代真实模型的语义核准试跑，也不代表已经装入正在使用的 profile。卸载通过宿主 Plugin Manager 移除 `@local/dsh-source-audit`，保留用户材料与报告。
