# 滨渠分站备签

结算员先核定本站待签清单，再凭备签号签发。待签期间任何已提交的清单偏离都要求重新核定。一个站的待签资格由本站的账面决定。

## 调用与返回

在 `lake.settle.publish` 提供以下三个调用，`store` 为 `WarehouseStore`。沿用 README 中的非空文本标识规则，`ticket_id`、`station` 均按传入标识比较。

| 调用 | 返回值 |
| --- | --- |
| `stage(store, ticket_id, station)` | `tuple[tuple[str, int, int], ...]`，各项为 `(original_id, quantity, unit_price)` |
| `status(store, ticket_id)` | 含 `state`、`cause`、`receipt_id` 的 `dict` |
| `sign(store, ticket_id)` | 正式结算成果号 `str`，可调用 `lake.settle.receipt.read(store, receipt_id)` 领取 |

第一次备签时，所选站须在活动底账中有行。将该站各行按底账中的相对次序列出，有效价沿用现有确认、源明确价、默认价的优先级。后续同号同站返回第一次备签的清单，即使该站已无行，或单已失效或已签。已有单号改绑其他站报 `ValueError`。

| `state` | `cause` | `receipt_id` |
| --- | --- | --- |
| `pending` | `None` | `None` |
| `invalidated` | `{'kind': 'install', 'revision_id': revision_id}` 或 `{'kind': 'review', 'sequence': sequence}` | `None` |
| `signed` | `None` | 首次签发的成果号 |

从备签成功后开始，按仓库已提交的安装、确认或撤销所形成的正式账面判定。清单比较包括成员、站内相对次序、用量及有效价。某站失去全部行时，本站清单变为空。仅其他站行的增删或换序、仅计价依据变化且有效价相同，均保持本站的待签资格。任一正式提交首次使该站清单偏离时，该待签单永久失效。原因用该次安装返回的修订号或该次复核返回的 `Decision.sequence` 表示。后来恢复原清单仍保留首因。失败提交不改变待签状态。关闭源库并重开仓库后，可以按原备签号查单。

待签单可签出本站的正式成果。按签发时的活动修订、发行及计价依据形成签存数据，沿用原 `SettlementReceipt` 的字段，明细只含本站且按站内原序，分站账只含本站。分站成果进入既有成果库供原 `read` 入口领取。核定资格、成果签存及备签转为已签一次提交。提交失败保留待签且无新成果。已签单重投始终返回原成果号。

空仓首次备签报 `RuntimeError`。活动仓首次备签未知站、查单或签发时单号未知报 `KeyError`。非法标识、改绑、签发失效单报 `ValueError`。SQLite 提交错误沿用 V1 的异常与回滚约定。旧件、原整账签发及旧成果领取继续使用。

## 两站样例

东站 `jia` 用量 1，继承默认价。西站 `yi` 用量 1，明确报 5。安装默认价为 5 的 R1 后，东单和西单分别取得 `(('jia', 1, 5),)` 和 `(('yi', 1, 5),)`。陆续安装默认价为 7 和 5 的 R2、R3，两份现行清单最终都与备签一致。重开仓库后，东单查得 `invalidated`，原因为 R2，签发拒绝。西单查得 `pending`，可签出仅有 `yi` 的 5 元成果。后来再改西站价格，仍可用原西单领回这份成果。

另一条路径从默认价 5 的 R1 开始。东站备签后确认 7 再撤销，旧单的失效原因是第一次确认的复核序号。重新备签后确认 5，仍可签发，正式明细须记这次确认的序号。若先同价确认 5，再安装默认价 7 的 R2，东单仍待签，撤销确认才使该单失效。

## 运行

原入口 `python3 -B check_project.py` 和 `python3 -B demo.py` 继续可用。`python3 -B verify_station_signoff.py baseline` 可在 V1 上查看两站逐版价。完成后将既有 `.pointwise-runtime.json` 的 `verify`、`demo` 命令分别接到 `python3 -B verify_station_signoff.py verify` 和 `python3 -B verify_station_signoff.py demo`。`verify` 运行原回归和分站业务核验，失败以非零状态退出。`demo` 输出重开后的东单首因、西单成果号及固定金额。清单中的 `version`、`kind`、`setup` 继续沿用 V1。
