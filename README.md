# 青岚流域观测日批档案

松桥观测站向青岚流域观测资料中心送交有出处的原序日批。档案员冻结原报送并为原组发单。制页员可以先整理候选页，归档员随后决定实收。交班时，档案员可把未交尾段转给接班组。复核员使用正式实交记录，在批账中分别定位站点缺测和班组未交原位。

## 运行

使用 Python 3.11 和标准库，在项目根目录执行。完整回归入口由运行环境提供。

```sh
python3 -B check_project.py
python3 -B demo.py
```

两种发布胜序可单独检查。

```sh
python3 -B -m unittest tests.test_delivery.DeliveryTests.test_late_parent_page tests.test_delivery.DeliveryTests.test_split_wins tests.test_split.SplitTests.test_publish_wins
```

样例见 `samples/day_batches.json`。演示独立创建并清理临时数据目录。常规工作目录中，首次初始化建立表和索引，重开或重复初始化保留已接收的批次、工单、候选和正式页。

## Python 接口

```python
from batches.freeze import freeze
from batches.intake import BatchSubmission
from batches.reading import FrozenReading
from batches.source import SourceRef
from batches.store import BatchStore
from claims.assign import assign
from claims.receipt import SplitRequest
from claims.split import split
from claims.store import ClaimStore
from delivery.publish import publish
from delivery.receipts import get_page
from delivery.store import DeliveryStore
from pages.build import prepare
from pages.request import PageRequest
from pages.store import CandidateStore
from reconcile.report import audit
```

在同一工作目录中用两个不同的 SQLite 文件。`BatchStore(path)` 使用台账库，`ClaimStore(batches)` 与 `CandidateStore(claims)` 共用该库。`DeliveryStore(other_path)` 使用交付库。首次使用时依次调用批次、工单、候选、交付存储的 `initialize()`。每次数据库操作管理自己的连接，重开时按原路径重新构造存储对象即可。

| 入口 | 参数与结果 |
| --- | --- |
| `freeze(batches, submission)` | `BatchSubmission(submission_id, readings)` 按传入顺序冻结，返回批号。每行用 `FrozenReading(position, litres, source)`，出处为 `SourceRef(station, document, line)`。同报送号同内容返回原批号。 |
| `assign(claims, batch_id, group_id)` | 发原组工单，`claim.span` 表示当前原位区间。同组重投返回当前原组工单。 |
| `prepare(candidates, request)` | `PageRequest(request_id, claim_id, start, stop)` 返回固定候选及其原序位置。同号同参复领原候选。 |
| `split(claims, deliveries, request)` | `SplitRequest(request_id, claim_id, boundary, successor_group)` 把分界及其后的原位交给另一组。返回含原组和接班工单的 `SplitReceipt`。 |
| `publish(candidates, deliveries, page)` | 用已存 `CandidatePage` 办理发布。结果为含实交原位、读值、出处和实交归属的 `PageReceipt`，或在没有可交原位时为 `None`。发布使用候选原请求号。 |
| `get_page(deliveries, receipt_id)` | 取回签页时的固定回执，未知号返回 `None`。 |
| `read_batch_delivery(deliveries, batch_id)` | 在 `delivery/history.py` 按批读取正式实交原位。 |
| `audit(batches, deliveries, batch_id)` | 返回原序实交行、未交原位、按组号排序的组账及全批账。 |

报送至少有一行，原位从 0 连续，出处的行号为正整数。报送号、组号与出处文本为非空白字符串。升数为整数或 `None`，布尔值与小数拒收。核账保留已交缺测行，计一次缺测，升数只加有效整数，0 L 也是有效值。候选页和未交原位均不进入实交计量。参数不合法、报送或请求号改参、冲突分领和错件引发 `ValueError`，未知业务对象在需要存在时引发 `LookupError`。

工单和制页区间左闭右开，新制页须处于当前工单范围内。每批支持一次尾段拆领。仅制页时可拆，尾段有任一实交原位即拒拆。分界可以是原工单首位，接班组取走全段。旧候选保持原样，办理时以当前工单为准，已经实交的原位也会跳过。原候选若再无可交行，发布销记本次请求并返回 `None`，没有成功回执。正式回执可独立复领，后续拆领、重投和核账均保留该回执的实交范围及出处。

拆领和发布在决定资格前都取得工作台账的写锁。拆领在锁内检查交付库的正式记录，然后提交新范围和工单。发布在锁内取得当前归属，在交付库一次提交正式页、实交行与请求结果后释放资格锁。台账和交付库各自提交。发布提交前失败可用原候选续投，提交后失答可用原请求复领。

`split` 和 `publish` 的可选 `before_decision` 回调在裁定前运行，允许另一个会话先办理。`publish` 的可选 `before_commit` 回调在本次交付已写入但尚未提交时运行，抛出异常会回滚本次交付。两入口的 `after_commit` 回调在新结果提交并释放锁后运行，抛出异常可模拟已生效但调用者未收到结果。同参复领不会再次调用提交回调。

## 样例口径

- 原批 7、11、13 L。先制原组整页，从原位 1 拆领后先签接班页，再签迟到原页。两个组实交 7 和 24 L，全批 31 L。若原组整页先签，拆领拒绝，31 L 全归原组。
- 对照批 7 L、缺测、7 L、0 L、11 L。同一组先签原位 2、3，再签 0、1。批账按原位 0、1、2、3 排列，组账和全批都计 14 L，缺测 1 个，原位 4 待交。
