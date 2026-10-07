# 书架与插件管理更新（2026-10-07）

书架支持个人分类的创建、改名、删除和书籍归类。分类按创建时间及插入顺序排列，不显示“全部”，未分类固定在最后；默认选中第一个自定义分类。删除当前分类后转到未分类，书籍不会被删除。分类内按最近阅读时间排序；进入阅读器后更新阅读时间，继续阅读恢复保存的章节和位置。

搜索页面只按轻小说、完结、连载筛选。轻小说文库、哔哩轻小说保持轻小说分类，全本小说网和书香门第附件归完结，其余内置源归连载。书源管理按内置/自定义分组，轻小说文库、哔哩轻小说及书香门第归自定义。

书香门第作为附件插件进入统一管理列表，支持启用/停用、Ping 和个人账号管理。停用阻止新绑定、搜索、预览及附件下载；账号解除绑定和已导入书籍阅读仍可用。账号会话继续加密并按用户隔离，下载继续使用原有确认令牌和防重复扣费流程。该集成只加入管理注册表，个人附件下载不走通用章节调度器。

数据库升级到 schema 18，增加个人分类及归类表。用户、分类和书籍的外键约束保护归属边界；删除分类使其书籍回到未分类。

## 书源启停策略

搜索无结果不等于失效，应保持启用。访问错误、持续验证拦截或目录/正文读取失败，经复查后可停用。网络和索引状态会变化，检查结论只反映当次部署环境。

本次部署检查 32 个内置源：16 个完成搜索到正文读取，5 个仅搜索无结果并保持启用，10 个访问或读取失败被停用，起点 Web 保持此前停用状态，合计 21 个启用、11 个停用。自定义源状态不变。

| 处理 | 插件标识 |
| --- | --- |
| 仅无结果，启用 | `69shuba_tw`、`ixdzs8_com`、`lingdiankanshu_com`、`yeban360_com`、`zhswx_tw` |
| 访问或读取失败，停用 | `czbooks_net`、`dongtanxs_com`、`quexs_org`、`shuhaige_net`、`sudugu_org`、`ttkan_co`、`xiaoshuohu_com`、`xinjianpan_com`、`xs63b_com`、`shumilou_co` |
| 原有停用 | `qidian_com_web` |

这些启停状态保存于部署端的持久化 `app_config.json`，不修改插件默认元数据，也不将服务器账号、会话或完整配置上传到仓库。新部署可在书源管理中按需设置。

## 验证范围

本次按用户要求采用定向测试、前端构建及实际部署检查，未执行完整 `verify.ps1` 或最终页面截图门禁。后端测试覆盖分类归属、删除和最近阅读排序，以及附件插件启停、个人会话隔离和下载确认；前端测试覆盖分类顺序和操作、进度恢复、搜索分类及插件账号入口。此前保存的截图基线不代表最终页面的完整验收。

GitHub 同步前的定向检查：

- 后端目录运行 `../.venv/bin/python -m pytest -c pytest.ini ../dev-assets/tests/test_direct_reading.py ../dev-assets/tests/test_txtnovel_import.py -q`，44 passed。
- 前端目录运行 `npx vitest run src/routes/DirectShelfPage.test.tsx src/routes/DirectReaderPage.test.tsx src/routes/DirectSearchPage.test.tsx src/routes/Plugins.test.tsx src/routes/SettingsPage.test.tsx`，24 passed。
- 最终前端实现已通过 `npm run build`；同步前 `git diff --check` 通过。
