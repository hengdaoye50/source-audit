# 本地安装与使用

已在Windows本机验证：市场登记、安装、启用状态、宿主发现Skill和安装副本112项测试。安装完成不代表新聊天已完整执行新的来源核准案例。

## 安装

仓库：https://github.com/hengdaoye50/source-audit。克隆或下载仓库后，使用实际所在目录执行下列本地安装命令；本仓库根目录就是插件目录。

把插件包解压到长期保留的文件夹；目录中应有`plugin.json`、`skills/`、`.agents/plugins/marketplace.json`。路径包含中文已在本机验证。

```powershell
codex plugin marketplace add "D:/your-folder/source-audit-plugin" --json
codex plugin add source-audit@source-audit-local --json
codex plugin list --marketplace source-audit-local --available --json
```

本包市场入口指向所在目录，移动目录后需更新市场登记。以上命令不安装Python依赖或系统OCR语言包。Python依赖的实测版本见requirements.txt；已有可用环境优先复用。文档渲染需要所在宿主提供相应Word/PDF转换能力，不将Microsoft Word作为可随包分发的组件。

## 调用

刷新插件列表后，在新聊天选择“文献与政策来源核准”工作流，或明确写出“使用source-audit插件”。例如：

> 使用source-audit插件，核准指定文件夹内Word主稿的文献和政策引用。参考全文在同一文件夹。只取来源正文，标明章节及页码或Word段落，给出支持边界和处理建议，最后生成Word报告。原文件保持不变。

插件只按用户指定范围读取。Word直接读；PDF优先文字层，必要时按页OCR。来源候选、章节和印页均须复核，不自动等于核准通过。

## 验证与卸载

```text
python -m unittest discover -s tests -q
codex plugin remove source-audit@source-audit-local
```

卸载只针对插件，不删除用户原始文献和已交付报告。重启应用由用户自行安排，不为安装检查中断当前会话。

封装与市场路径依据：[官方OpenAI插件文档](https://developers.openai.com/plugins/build/plugins)。本包无外部MCP连接，文件提取及OCR在本地执行；Codex阅读文本候选仍使用当前模型服务，不承诺完全离线。
