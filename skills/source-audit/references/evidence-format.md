# 证据账本 0.2（兼容0.1）

权威字段定义见 [ledger.schema.json](../schemas/ledger.schema.json)。严格拒绝未知字段，升级字段时同步变更版本和迁移策略。

## 三层关系

1. `sources`：来源元数据、文件 SHA-256、提取覆盖程度，以及按页、区段组织的正文。
2. `claims`：主稿被引表述、引用角色、子命题、支持程度、检索记录和处理建议。
3. `evidence`：绑定来源文件版本、区段字符位置和完整原文；`assessments` 将证据对应到子命题。

原文只在来源区段和证据中保存；模型解释不得填入原文字段。双页码分别存储，缺失印页用 `null`，不猜测。

### Word 主稿位置

主稿通常是 Word。`target.pdf_page` 和 `target.print_page` 均为空，新增可选 `target.docx_location`：包含主稿文件 `manuscript_sha256`、读取结果 `block_id` 与原样 `location`。`location` 使用段落、表格单元格、脚注或尾注位置；必须与主稿读取结果一致。现有 PDF 账本无需增加该字段，兼容账本版本 0.1。

验证 Word 目标时提供主稿读取 JSON 和原件目录，检查文件版本、块定位、目标文字及该块复核状态。主稿处于未复核状态会阻止导出前置条件通过，不因读取成功自动解除。

空白或不可读 PDF 页允许保留空区段列表；它们不能据此判为完成正文检索。`full` 仅表示所选全文文字层通过初步可读性检查，不等于正文边界与文字已经审定。

## 关键字段

Word来源证据可使用`evidence.docx_location`，包含`block_id`与原始`location`；PDF页码、印页、字符跨度数组必须为空。校验实际来源文件摘要、完整段落、位置和章节；不推测原书页码。PDF证据仍必须有非空页码和跨度。新任务使用0.2，已有0.1账本保持兼容。

校读后的来源segment可保存安全相对路径`verification_image`，通过`--image-root`核查图像存在；仍须执行者实际对照，不等于独立逐字核验。顶层可选`report`保存报告标题和重点问题，claim可选heading；这些字段不替代子命题或政策检查。

| 字段 | 含义 |
|---|---|
| `source.sha256` | 原始文件字节摘要；网页用保存的正文快照文件摘要 |
| `source.coverage` | `full` 全文提取完成；`partial` 部分；`unreadable` 无法可靠读取 |
| `origin.locator` | 本地来源目录内相对路径，或网页完整 URL |
| `origin.snapshot_path` | 网页在来源目录内的快照相对路径；非网页可为空 |
| `segment.region` | `body`、`abstract`、`bibliography`、`other`、`unknown` |
| `segment.review_status` | 文字顺序、正文边界和疑难字符是否经阅读确认 |
| `span.start/end` | Python Unicode 字符下标，0 起算、末端不含；不是 UTF-8 字节下标 |
| `evidence.pdf_pages/print_pages` | 由证据跨度对应的来源页推导，数组必须准确对应 |
| `completeness_review/context_review` | 完整句段与上下文是否经阅读确认；程序不能代为判断 |
| `assessment.boundaries` | 对象、时间、地域、因果强度是否匹配；未知用 `null`，不默认填真 |
| `claim.verbatim_text` | 主稿引号内需要检查的文字，与主稿整句分开 |
| `search` | 检索状态、实际核查来源、区段、查询词与覆盖说明 |
| `policy_checks` | 正式文件、解读或二手层级；日期及原件核验情况 |

每条证据的跨度必须连续；跨页时前页取到区段末尾、后页从区段开头继续，页码连续。跳过中间文字不得合成一条连续引文，可拆成两条证据。当前一条证据只对应一个章节；跨章节论述分别摘录。

程序只移除空白后比较引文，不删除标点、数字或否定词。OCR 修正须先回看原页并更新已确认的来源区段，再据该区段记录跨度；未来提取工具应保留原 OCR 及修正日志。

## 核准状态

| 状态 | 使用条件 |
|---|---|
| `direct` | 全部子命题有相符证据，范围与强度均匹配 |
| `partial` | 部分子命题或部分含义获支持，其余边界明确说明 |
| `insufficient` | 找到相关正文，但不足以支撑待核命题 |
| `not_found` | 已完成所指来源正文检索，未找到支持证据 |
| `unable` | 来源缺失、不可读或其他原因导致无法完成核准 |

负面结果也可以是完成的核准结果。`unable` 必须明示原因，不能合并进 `not_found`。校验器在所列真实来源文件未核对时保留阻断状态；缺件需明确记录可核查范围，不为导出改成通过。报告展示五类判定，政策层级核准及引用角色由统一账本传入。

`reviewed` 和 `verified` 是执行者对实际阅读工作的记录，不是可防伪签名。SHA-256 可识别文件变化，但不能证明来源内容的学术真实性、正文分区正确或语义判断无误。

## 合成样例

测试来源的 `origin.kind=synthetic`。摘要计算为各页各区段文字按保存顺序用一个换行连接后的 UTF-8 SHA-256。这是专用于自制样例的约定，真实 PDF 不采用该摘要算法替代文件字节摘要。

可参考 `tests/fixtures/valid-ledger.json` 和 `cross-page-ledger.json`。这些样例不包含用户论文或参考文献文字。
