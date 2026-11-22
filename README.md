# 滨渠计量数仓 V1

供数组冻结分站计量底账并发行固定件。仓内复核员在断开供数库后安装底账、确认疑点和撤销过时确认。结算员核对逐行金额和分站合计，签出可按号复领的成果。

## 运行

使用 Python 3.11 标准库。在项目根目录执行 `python3 -B check_project.py` 运行完整回归。控制台物化时提供该入口，本地也可执行 `python3 -B -m unittest discover -s tests -t . -v`。运行 `python3 -B demo.py` 可在独立临时库中演示冻结、断源安装、同值确认、换版、撤销和重新领取。演示不写入用户库。

## Python 接口

`lake.source.store.SourceStore(path)` 和 `lake.install.repository.WarehouseStore(path)` 打开各自的 SQLite 库并初始化。它们支持 `with` 和 `close()`。重复打开或调用 `initialize()` 保留已提交业务记录。每个调用者使用自己的连接。

| 导入模块 | 公共调用 | 返回值 |
| --- | --- | --- |
| `lake.source.revisions` | `freeze(source, stream, predecessor, default_price, rows)` | 冻结修订号 |
| `lake.source.revisions` | `read_frozen_revision(source, revision_id)` | 指定冻结修订及有序原行 |
| `lake.exchange.issue` | `issue(source, revision_id)` | UTF-8 JSON 固定件 `bytes` |
| `lake.exchange.receive` | `receive_bundle(data)` | 通过核验的固定件值 |
| `lake.install.catalog` | `install(warehouse, data)` | 已提交的活动修订号 |
| `lake.install.catalog` | `load_active_base(connection)` | 在调用方事务中读取活动底账，空仓返回 `None` |
| `lake.review.decisions` | `decide(warehouse, original_id, action='confirm', price=5)` | 已提交的独立确认 |
| `lake.review.decisions` | `decide(warehouse, original_id, action='withdraw')` | 已提交的撤销 |
| `lake.settle.publish` | `preview(warehouse)` / `publish(warehouse)` | 现账快照 / 已提交成果号 |
| `lake.settle.receipt` | `read(warehouse, receipt_id)` | 指定成果的原快照 |

`rows` 接受 `lake.source.rows.SourceRow` 或字段映射。每项需要 `original_id`、`station`、`quantity`，可选 `source_price`。传 `None` 或省略 `source_price` 表示继承默认价。流、修订、原行、站点和成果标识为非空文本。原号在同流中表示稳定身份，同版只能出现一次。源端冻结首版传 `predecessor=None`，后续传当前尾部编号。仓内空库接首版，有活动底账时接同流直接后继。空原行集合产生空明细、空分站账和总额零。

整数用量采用统一计量单位，单价采用每单位的整数记账金额。零和负整数按原值计费，布尔值和浮点数拒绝。有效价优先取最新未撤销的本地确认，其次取当前源明确价，再取当前默认价。有效确认即使与现价相等也会记录。仓内对已知原行撤销时，计价恢复到当前源口径。计算使用 Python 整数，SQLite 以十进制文本保存业务整数。金额是用量乘单价，明细保持件内顺序，分站账按站点键排序，零金额站仍保留。成果记录来源修订、发行号、默认价、逐行源价、有效价、计价来源、复核记录序号及分站金额。

结构、口径、前序和核账错误抛出 `ValueError`。未找到的修订号、原号或成果号抛出 `KeyError`。空仓执行复核、预览或签发抛出 `RuntimeError`。SQLite 错误传给调用者，失败事务会回滚。发布在一致的仓内视图中核账并固定原快照，提交成功后返回号。查阅成果直接读取已签数据。

## 固定件 V1

`samples/external-r1.json` 和 `samples/external-r2.json` 是可直接安装的独立样例。件包含 `version`、`issue_id`、`stream`、`revision_id`、`predecessor`、`ordinal`、`default_price`、`rows` 和 `evidence`。首版序号为 1 且前序为 `null`，直接后继序号加一并引用前序修订号。每行含 `original_id`、`station`、`quantity`、`price_kind` 和 `source_price`。`explicit` 需要整数价，`default` 需要 `null`。

`evidence.frozen_v1.original_ids` 是按件内顺序声明的全量原号。`evidence.frozen_v1.sha256` 是除去 `evidence` 的对象使用 `json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True)` 编码为 ASCII 后的十六进制 SHA-256。摘要可核对件内内容一致性。接收端要求 `frozen_v1`，其他具名证据不参与 V1 核验。

## 样例账

甲和乙属东站，丙属西站，三行用量各为 1。R1 中甲明确为 5，乙丙继承默认价 5，首份成果为 15。确认乙为 5 后安装默认价为 7 的 R2，逐行金额为 [5,5,7]，成果为 17。撤销乙后现账为 [5,7,7]，合计 19。重开仍可分别领取原成果 15 和 17。
