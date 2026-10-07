# 哔哩轻小说

公开简体手机版适配，稳定 ID `linovelib_com`。输入书名/作者，或粘贴哔哩书籍详情/目录链接、数字书号。搜索后添加书架，按需取当前章节的全部分页；整本下载由宿主现有下载服务负责。

## 访问与正文

- 内容入口：`https://www.bilinovel.com`，规范化同站 linovelib/bilinovel 书籍链接。
- 使用移动 UA、相同版本 Chrome TLS、站点阅读设置 `night=0`。这是显示设置，不是登录凭证。2026-10-07 同一出口 A/B 检查：缺少该设置时页面返回约 500 字及“内容加载失败”，带该设置返回约 3000 字完整单页。新加坡甲骨文直连与现有 Legend 出口 77.93.91.20 均验证成功。
- 原生搜索有浏览器 guard，直接 HTTP 返回空页面。采用宿主公开索引搜索，只从真实命中 URL 提取书号，再校验详情。搜索索引可能漏新书；可粘贴书籍链接。
- 从当前页面引用的 `chapterlog.js?v…` 解析整数算术参数，不执行远程 JS。保留段落/插图槽位、恢复段落顺序，未知脚本或正文截断均报错，不返回或缓存部分章节。每次章节调用只去重该调用内相同版本脚本，没有插件自建全局缓存、重试或调度。
- 只跟随同书、同章节连续分页，最多 100 页。保留卷名及不可用目录条目：目录锚点标识不可用位置，阅读立即报原站未提供公开地址，不猜测真实章节地址。
- 公开可见插图保留 URL 与 `[插图 N]` 标记；原站隐藏的图片不返回。当前纯文本阅读器不内嵌显示图片。
- 连续直连请求实测触发 429，而 Legend 完整长章成功，因此 `proxy.mode=always`，部署需配置宿主代理。代理使用已有 Legend 出口，只在阅读容器共享网络的回环地址监听，无需公开代理端口或修改宿主 Python。浏览器刷新/挑战处理由宿主负责，插件不处理验证码、付费或登录限制。
- 宿主按每次 HTTP 请求落实 2000ms 的间隔（分页与脚本也计入），操作并发为 1。分页很多的章节首次读取较慢；宿主超时预算部署设置为 35 秒，公开索引搜索保留原预算。429 仍会正常报错，不做无限重试。

## 证据及验证

样本：雨森焚火《败北女角太多了！》3095，目录 221 个条目、12 卷，其中 9 个没有公开链接；长章 154933 共 9 页。fixtures 来自实际 HTML，包含短正文、长章全部分页、插图、截断失败页、版本化脚本。

恢复顺序的第 21～35 段对照正常桌面浏览器的可见段落，结果一致。测试覆盖搜索/订阅字段、卷/缺失目录条目、分页完整性、断页与跨书地址、脚本变化、插图与不安全 URL。

```sh
cd backend
../.venv/bin/python scripts/validate_source_plugin.py --plugin ../plugins/sources/thirdparty/linovelib_com
../.venv/bin/python -m app.source_plugins.smoke ../plugins/sources/thirdparty/linovelib_com
../.venv/bin/python -m pytest ../dev-assets/tests/test_linovelib_plugin.py -q
```

排序协议参考 [Montaro2017/bili_novel_packer](https://github.com/Montaro2017/bili_novel_packer) 的 MIT 许可实现。Python 算术解析器及适配代码自行实现；参考许可见 THIRD_PARTY_NOTICE.md。

## 2026-10-07 发布验收

- `pytest test_linovelib_plugin.py`：17 项通过；包含 HTTP 限速回归的阶段批次：44 项通过、2 项可选测试跳过。
- 最终 `verify.ps1`：637 项后端测试通过、4 项可选测试跳过；107 项前端测试通过；依赖、所有插件校验、lint、构建、视觉比较、运行时 smoke 均通过，无本地运行数据变化。
- 默认 SSH 验收资产“本地测试”不在 Termark 清单中，因此使用实际 SG-Oracle 上的隔离容器验收。连续搜索、插图、长章、短章成功；长章 9 页、27063 字、约 20.2 秒。
- 首次部署到 `book.uclau.de`，容器 `legadohub-direct`，镜像 `local/legadohub-direct:20261007-linovelib`。当时的线上认证 API 只验证了单源搜索、目录与正文（完整长章约 18.3 秒），没有覆盖加入书库后的聚合阅读接口。随后实际书库阅读出现 502，不能以单源成功代表完整用户流程成功。
- 服务目录 `/opt/docker/legadohub-direct`，现有 Compose 已整合 `legend-proxy` 服务；只在应用共享网络的 `127.0.0.1:17894` 监听，没有发布代理端口。普通 `docker compose up -d` 会管理两个容器。
- 回滚备份 `/opt/docker/legadohub-direct/backups/linovelib-20261007-080031`，含原 Compose、配置及 SQLite 快照。旧镜像保留。线上账号、书架、进度未迁移或重置；隔离验收容器与临时代理凭证文件已清理。

## 0.1.1 书库阅读修复

目录标题包含卷名，正文此前仅返回章节短标题，导致聚合层把正确正文判为章节不匹配。现在正文从真实 `.atitle h3` 提取卷名，与目录精确对应；保留章节对齐校验。聚合层按宿主目录与正文超时预算设置外层期限，合计最多 120 秒，避免固定 20 秒提前取消限速后的多页正文。

新增《无职转生》2013 的真实目录、插图和人物设定 fixture，以及搜索→加入书库→目录→聚合阅读 HTTP 回归。阶段测试使用 `pytest -c pytest.ini ../dev-assets/tests/test_linovelib_plugin.py ../dev-assets/tests/test_direct_aggregation.py -q`，38 项通过。

修复发布验收：

- `verify.ps1` 全部门禁通过：后端 640 项通过、4 项跳过；前端 107 项通过；构建、视觉与运行时检查通过，无本地运行数据变化。
- SG-Oracle 隔离容器使用真实登录，完成搜索→加入书库→目录→聚合阅读。《无职转生》目录 620 条，索引 0/10/15 返回 HTTP 200（908/9235/288 字）；《败北女角太多了！》索引 2 的九页长章返回 27062 字，约 20.1 秒。
- 线上镜像 `local/legadohub-direct:20261007-linovelib-fix1`；实际用户已有书库 ID `agg-0e6fa3686026d455a773a6f64fa5b09b` 的索引 0/10/15 均返回 HTTP 200，公网认证入口 HTTP 200，应用健康。
- 部署前后核对账号 1 个、书架 5 项、阅读进度 14 项；进度内容摘要一致。备份 `/opt/docker/legadohub-direct/backups/linovelib-fix1-20261007-082121` 含 Compose、配置、插件与 SQLite 快照，旧镜像保留。
- 验收仅覆盖上述章节，未声称全站章节均可用；原站无公开地址的条目仍明确报不可用。
