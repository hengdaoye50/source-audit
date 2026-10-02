# Source Audit｜文献与政策来源核准

本地来源核准插件开发版，版本 0.5.1，支持 Codex 与 DeepSeek Harness。

**DeepSeek Harness直接安装网址：[https://github.com/hengdaoye50/source-audit](https://github.com/hengdaoye50/source-audit)。** 将这个网址交给宿主的插件安装入口，或要求其调用 `plugin_manager` 的 `install_bundle`，`target` 为这个网址。main根目录现在声明 `dsh.bundle.patch`，不需要使用 `/tree/` 分支浏览页、选择子目录或自行打包。协议整理见 [Harness安装契约](deepseek-harness/INSTALL-CONTRACT.md)。

**当前完成：Word读取、引用候选发现、PDF提取及必要OCR、检索与定位、执行者语义核准流程、统一账本校验与Word导出。114项程序测试通过，两个真实案例已交付报告。Codex 0.4.0安装副本已验证；新增 Harness 适配包通过真实 Cordis/Skill 组件6项检查。代码仓库已公开。尚未完成：独立语义评测、新聊天完整调用验收、Harness当前profile安装与DeepSeek模型完整案例试跑。**

Codex 安装见 [INSTALL.md](INSTALL.md)。DeepSeek Harness 适配包的打包、安装、调用和兼容范围见 [专用说明](deepseek-harness/README.md)，两者共用同一套核准核心，原件不进入分发包。

## 已实现的能力

- 将来源文件、正文区段、待核子命题、证据及支持边界保存为统一 JSON 账本。
- 校验正文属性、章节与页码、字符位置、引文一致性、来源版本、跨页连续性及复核状态。
- 拒绝把检索未完成当作“未找到”，或把政策解读、二手归纳当成正式原件核验。
- 区分明确引用、建议补引和政策引用统计。
- 核对来源文件摘要，并限制读取在指定来源目录内。
- 直接读取 `.docx` 主稿的正文、表格、脚注和尾注；位置用段落、单元格及注释编号，不猜固定页码，不调用 OCR。
- PDF 文字层优先；文本不足时可启用 Windows 中文 OCR，文字正常的页不做 OCR。按文件摘要和读取器版本缓存。
- 候选检索排除已标注为摘要与书目的区段，保留未知正文边界待复核；自动分区可能漏识别，候选不得直接作为证据。精确定位工具只接受已标为正文的区段。

Word 读取、检索和账本校验器使用 Python 标准库，建议 Python 3.10 或更新版本。PDF 提取使用 `pdfplumber`，异常文字层可尝试 `pypdf`；Word报告使用 `python-docx`。Windows OCR 还需 `pypdfium2`、Pillow 与已安装的 OCR 语言包。请求语言不可用时记录实际回退语言，不伪装成原请求语言。测试环境版本见 `requirements.txt`；运行时不要自动安装系统语言包。

校验器支持本项目 JSON Schema 使用的关键字，不是通用 JSON Schema 引擎。

## 运行

在此目录运行：

```text
python -m unittest discover -s tests -v
python skills/source-audit/scripts/validate_ledger.py tests/fixtures/valid-ledger.json
python skills/source-audit/scripts/validate_ledger.py ledger.json --source-root local-data --output validation.json
python skills/source-audit/scripts/read_manuscript.py local-data/main.docx --source-root local-data --output outputs/main.json
python skills/source-audit/scripts/read_sources.py local-data/references --source-root local-data --cache-dir outputs/cache --output outputs/corpus.json
python skills/source-audit/scripts/search_sources.py outputs/corpus.json --query 技术门槛 --query 数字排斥 --output outputs/candidates.json
```

扫描 PDF 可在 `read_sources.py` 中加 `--ocr windows`；抽页测试可加 `--pages 1,2`（仅限单文件）。默认不启用 OCR。旧式 `.doc` 尚不支持直接读取，需先转换为 `.docx`。

Word 主稿账本如含 `target.docx_location`，校验时另传 `--manuscript outputs/main.json --manuscript-root local-data`；工具校验原主稿摘要、块位置和目标表述，并保留未复核状态。

读取成功不等于证据通过。自动章节、印页、页边文字与双栏识别均为候选；新提取区段均标 `unverified`。页眉、页脚及脚注候选保存在 PDF `ingestion[].pages[].ancillary_text`，不删除；主稿的政策脚注需要从这些保留文字进一步核查，不能因正文索引没有它们而称“未找到”。Word 的脚注通过原始注释 ID 关联。

本地检索当前是中文词片段与英文词的候选排序，不是完整语义检索。可添加近义查询，模型负责判断候选是否足以支持命题。它不会把检索得分转换成通过结论。

新增 `discover_citations.py` 将脚注或作者年份式引用与所供文件候选关联；支持省略作者的连续年份。文件匹配保留多个候选，不能自动确认版本。无标题书目识别采用连续书目样式段落的启发式规则，需执行者确认。

`export_report.py` 首选统一证据账本0.2输入，兼容旧0.1账本及双案例试跑数据。运行同一账本校验器，错误和待复核项阻止导出，Word来源保留段落定位，政策层级与引用类型保留在报告。参见 `skills/source-audit/references/report-format.md`。它不自行完成语义核准，页面渲染与检查由执行者完成；旧试跑数据不会自动获得新增复核记录。

```text
python skills/source-audit/scripts/export_report.py ledger.json --source-root local-data --manuscript outputs/main.json --manuscript-root local-data --output outputs/report.docx --qa-output outputs/report-qa.json
```

CLI 返回码：0 表示账本满足报告导出前置条件，2 表示存在错误或待复核项。结果区分 `errors`、`blockers`、`warnings`，统计按引用角色分别生成。

`ready_for_report` 不代表语义已经独立审定，更不代表 Word 已生成或排版通过。语义和完整句段须经阅读确认；原文件摘要校验不证明提取文字必然正确。原文中的年份、符号或否定词仍需必要原页复核。

## 文件入口

- 工作流：`skills/source-audit/SKILL.md`
- 格式：`skills/source-audit/schemas/ledger.schema.json`
- 格式解释：`skills/source-audit/references/evidence-format.md`
- 验收口径：`skills/source-audit/references/acceptance.md`
- 自制账本与语义案例：`tests/fixtures/`
- 本次自动验证记录：`tests/validation-results.json`

## 本次真实材料验证

- 29 篇 PDF 参考文献、407 页成功提取，全程未调用 OCR。
- 原报告 62 组引文均可在新提取文本中连续找回。这是提取回归检查，不是新的语义准确率。
- 扫描主稿抽测 2 页，Windows 中文 OCR 读取成功，结果仍待原页复核；未将抽测宣称为全稿 OCR 验证。
- 以用户修订报告进行真实 DOCX 读取测试，607 个非空文本块成功读取；它是报告文件的兼容性测试，不是新论文的引用识别准确率测试。

真实全文、抽取结果和缓存仅位于项目内部工作目录，不纳入插件分发包。印页候选不自动视为已核准。

## 发布与数据

本轮双案例验证：2份Word主稿不做OCR，覆盖42组引用、82种来源，选取96组不重复正文引文。两份报告的来源摘要及引文绑定检查0错误，报告全部页面检查通过。这是执行者核准的真实试跑，不能换算成总体准确率或独立评审结论。

本机通过Codex插件命令登记本目录内的市场并安装，插件ID为`source-audit@source-audit-local`。宿主`skills/list`发现已启用的`source-audit:source-audit`，没有插件解析错误；安装副本112项测试通过。没有创建额外模型任务，也不把这些检查称为新聊天的完整任务验收。安装步骤见 [INSTALL.md](INSTALL.md)。

本地登记与安装已完成。公开代码仓库：[hengdaoye50/source-audit](https://github.com/hengdaoye50/source-audit)，采用MIT许可证。无外部服务连接；仓库不包含真实论文全文或核准报告。

本目录不包含项目论文全文和用户修订报告。自制样例随代码分发；用户全文、缓存及报告留在本机。MIT许可证只覆盖本仓库代码与自制材料，不改变输入文献自身的版权。

本地工具处理不等于模型完全离线；后续通过 Codex 阅读候选文字仍涉及所用模型服务。
