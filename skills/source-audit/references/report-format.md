# Word报告预览接口

## 首选：统一证据账本

从0.4.0起，`export_report.py`直接接受`ledger.schema.json`定义的证据账本（schema_version 0.1或0.2），先执行同一账本校验器，错误或待复核项均阻止导出。政策层级与引用类型保留在报告，不绕过原件、日期、引号连续性等检查。

0.2增加Word来源证据的`docx_location`；对应`pdf_pages`、`print_pages`、`spans`必须为空，校验实际来源Word摘要、段落原文与位置。PDF证据仍必须有页码和非空字符跨度。校读转写可在来源segment记录`verification_image`，需要提供`--image-root`校验，图像存在性仍不等于独立逐字核验。

顶层可选`report`，包含title、manuscript_title、highlights、additional_notes；claim可选heading。报告元数据不修改原语义判定。Word主稿仍需要主稿读取结果及原件目录，段落复核状态不得自动改为通过。

```text
python scripts/export_report.py ledger.json --source-root local-data --manuscript main.json --manuscript-root local-data --image-root page-checks --output report.docx --qa-output report-qa.json
```

## 兼容：旧双案例试跑数据

版本 `trial-report-0.1`，为既有双案例数据保留的兼容输入。新任务首选统一账本。真实文献数据留在任务目录，不放入插件。

顶层字段：`title`、`manuscript`（title、locator、sha256）、`sources`、`claims`；可选 `highlights`、`additional_notes`。

来源字段：唯一 `id`、`title`、`sha256`、`origin.locator`（相对来源目录），Word来源另设 `format: docx`。

每项：唯一 `id`、`block_id`、`section`、`target_text`（须出自主稿块）、`status`、`reason`、`recommendation`、`source_ids`、`evidence`。可选短标题 `heading`。`未找到`必须有 `search_complete`，不能掩盖缺件或未检索完。

证据：`source_id`、完整 `quote`、`section`、`region: body`、`context_review: 执行者复核`。绑定方式三选一：

- PDF：`pdf_page`、可选 `pdf_pages`、可确认的 `print_page`；`spans` 的每项含 `segment_id`、整数 `start` 与 `end`，区间闭开，严禁负值及越界。
- Word：`docx_location.block_id` 和原始 `location`，引用完整原段落，章节与原书页码另核。
- 校读转写：保留PDF定位与安全相对路径 `verification_image`，多个图像用分号分隔。图像存在性不证明逐字正确，必须执行者对照原页。

```text
python scripts/export_report.py report-data.json --corpus corpus.json --manuscript main.json --source-root local-data --image-root page-checks --output report.docx --qa-output report-qa.json
```

程序检查原件摘要、正文标记、主稿表述和引文绑定，失败返回2；成功仅表示可进入排版检查。正式交付仍需执行者核查语义、完整性、版本、正文位置、统计及实际Word页面。报告不得把仅由二手资料支持的政策断言表述成政策原件核准。
