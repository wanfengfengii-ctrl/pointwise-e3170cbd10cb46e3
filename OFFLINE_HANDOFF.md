# 未完日批离线交班

继续使用 README 中的两库配对和原接口。工作台账和交付库分别提交。交班只办理同一配对中的一个已领工单的冻结日批，每批至多交班一次。工作台账在交班成功前供裁决和续办使用。交班成功后，接班员只需交付库。交班清单以外的候选不能在接班端使用。

## 调用和结果

在 `delivery.handoff` 提供以下 Python 入口。`candidates` 和 `deliveries` 分别沿用 `CandidateStore` 和 `DeliveryStore`。

```python
handoff(candidates, deliveries, handoff_id, batch_id, request_ids,
        *, before_decision=None, after_checkpoint=None)
publish_offline(deliveries, handoff_id, request_id,
                *, before_commit=None, after_commit=None)
```

`handoff` 返回 `HandoffReceipt`，公开属性为 `handoff_id`、`batch_id` 和 `request_ids`。输入 `request_ids` 是非空、无重复的候选号序列，单个字符串不能当作清单。标识沿用 V1 的非空白字符串规则。回执中的 `request_ids` 是按字符串升序排列的元组。同号同批同集合复领原回执，改变清单顺序也一样。改绑、同批另号、未知对象、错批候选和覆盖不足均抛出 `ValueError`。校验拒绝不占交班号、不改变旧流程。成功后的同参调用可在工作台账已关闭时凭交付库复领。

在同一个裁决截点核对正式实交、工单范围和指定候选。每个未交原位须在一个尚未办结的指定候选中，且当时属于该候选的工单。坐标重叠允许。已经办结的候选可列入清单，其既有结果照领，它们不提供待交覆盖。只要清单有权办完余账，就可以交班。

资格转出后，原 `split` 和 `publish` 拒绝本批的首次办理，抛出 `ValueError`。两入口已办的请求照常复领。其他日批沿用原流程。交付库在接班材料生效前拒绝离线首发。若资格已转出而接班材料尚未生效，两端均暂不首发，原交班号可按相同参数续办，仍沿用转出时的截点。调用中断发生在转出前时，旧裁决仍可进行。

`publish_offline` 只办理已生效交班清单内的候选。无生效交班、候选不在清单或参数无效时抛出 `ValueError`。候选号和回执格式沿用 V1。尚未办结的候选只交截点工单仍有权签发、且当时尚未实交的原位。正页使用 `PageReceipt`，保留原序、读值、缺测、出处和工单归属。无可交行时正式销记并返回 `None`。实交与请求终局一起提交，重开后同参复领正页或空结果。原 `get_page` 和 `read_batch_delivery` 继续从交付库读正式记录。

## 中断与交错

新入口的可选回调均无参数，异常照传。`before_decision` 在取得裁决锁前运行，可让另一个在线会话先拆领或发页。每次实际提交资格转出或接班生效后，在释放该阶段的锁后调用 `after_checkpoint`。两者同次提交时只调用一次。回调抛错可模拟已提交但未收到结果。离线签页的 `before_commit` 与 `after_commit` 沿用在线签页的时机，前者在正式写入尚未提交时调用，后者在提交及释放锁后调用。复领不重复触发提交回调。

## 样例与运行

`offline_fixture.py` 用原接口冻结 `offline-day`，前三个原位的读值依次为 7 L、缺测、11 L，出处为松桥站 `offline-day` 的第 101、102、103 行。原组 `day` 先制整页 `wide`，再用 `first` 正式交出原位 0。另一候选 `spent` 请求同一原位，已经销记为空。此时批账只有 7 L。默认从原位 1 拆尾给 `night`，由夜班制好 `tail`。`seed(work, split_tail=False)` 保留未拆领情形，可用于让拆领与交班交错。`detach_catalogue(work)` 移走整个工作台账目录，返回重开的交付库。直接运行夹具可观察 V1 在这种隔离下仍能复领首执。

在默认夹具中，清单只列 `wide` 或只列 `spent` 均漏掉原位 1、2。用 `wide` 和 `tail` 办理交班后，移走工作台账，先办 `tail` 得到夜班原位 1、2，再办 `wide` 得到 `None`。`page:first` 仍是原组的 7 L 首执。按批读取的正式原位顺序是 0、1、2，共 18 L，其中原位 1 交付了缺测。

沿用根目录的 `.pointwise-runtime.json` 交付。现有清单的 `version` 为 1，`kind` 为 `cli`，`setup` 是准备命令数组的列表，可继续为空。`verify` 和 `demo` 各是一条命令的 argv。校验入口跑原完整回归，核对覆盖拒绝、交班与原入口的胜序、提交边界的续办和离线实交。校验失败应退出非零。演示实际操作该样例，显示断开工作台账后签出的夜班行、旧整页的空结果和复领的首执。