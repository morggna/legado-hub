# LegadoHub · 个人阅读版

这是 [XziXmn/legado-hub](https://github.com/XziXmn/legado-hub) 的 fork，以账号和个人书库为中心，整合搜索、管理与沉浸式阅读入口。上游基线为 `v0.4.4`（`9e8d221`），保留原有 Git 历史。当前开发分支：`feat/direct-thirdparty-reading`。

## 当前功能

- 统一入口：账号密码登录，邀请码注册；管理员管理用户、邀请码和共享书源。
- 搜索已启用的第三方源，同书结果按书名与作者聚合，添加到自己的书库。
- 默认按需阅读：加入书库不会从头抓完整本，打开章节时才获取正文。目录、来源诊断和个人阅读进度独立保存。
- 多源章节对齐与正文比较；失败时展示原因，避免静默返回错章。
- 整本下载是单独选项，支持暂停、继续与 TXT 导出，下载缓存按用户隔离。
- 基于 legado-server 的沉浸式阅读器，支持排版、主题、翻页与触控；可添加到手机主屏幕。
- 新增轻小说文库、哔哩轻小说插件，以及绑定个人论坛账号后的书香门第附件导入。

书源插件由管理员共享维护；尚不支持每个用户导入并执行私人 Legado JSON 规则。书源是否可用取决于原站，搜索索引可能漏书。手机版公开可读与 PC 版下架状态也可能不一致，不承诺全站可读。主屏幕安装不等于离线阅读，服务工作线程不缓存账号页面或正文。

## Docker 部署

这份 fork 的改动需要从源码构建。上游 `xzixmn/legado-hub:latest` 不包含这些改动；本 fork 目前没有公开预构建镜像。需要 Docker Compose 2.24 或更新版本。

```bash
git clone --branch feat/direct-thirdparty-reading https://github.com/morggna/legado-hub.git
cd legado-hub
cp deploy/direct/.env.example deploy/direct/.env
# 编辑 .env：可设置初始管理员密码；留空则首次启动随机生成。
docker compose --env-file deploy/direct/.env -f deploy/direct/compose.source.yaml up -d --build
docker compose --env-file deploy/direct/.env -f deploy/direct/compose.source.yaml logs app
```

访问 `http://127.0.0.1:8765`，管理员用户名默认为 `admin`。登录后创建邀请码供其他用户注册。密码仅用于首次创建管理员；修改 `.env` 不会重置已有账号密码。

持久数据位于 `deploy/direct/state/`，与源码分离。先备份该目录，再升级：

```bash
git pull --ff-only
docker compose --env-file deploy/direct/.env -f deploy/direct/compose.source.yaml up -d --build
```

插件挂载目录中的同名插件优先于镜像内版本，源码更新后需有选择地更新对应插件；不要删除账号数据库或整个持久目录。`deploy/direct/Dockerfile` 和 `Dockerfile.source-pacing` 是既有部署的增量覆盖工具，不是首次安装入口。

### 域名与代理

反代目标是 `http://127.0.0.1:8765`。在 `.env` 中设置域名、完整 HTTPS Origin 和实际可信代理地址后重启应用，例如：

```dotenv
LEGADOHUB_ALLOWED_HOSTS=books.example.com,127.0.0.1,localhost
LEGADOHUB_ALLOWED_ORIGINS=https://books.example.com,http://127.0.0.1:8765
```

反代需转发 Host、Cookie 和正确的协议头，并关闭搜索 SSE 的缓冲；只有声明为可信的代理才会被应用接受其转发信息。反代、公网 TLS 和访问网络由部署者管理。修改 `.env` 后使用上述 `up -d` 命令重建容器，不要用 `docker compose restart` 加载新环境变量。

哔哩插件声明必须经过宿主代理且逐请求限速，启用前须在管理设置中配置可用代理。仓库不包含现有服务器的代理凭据。可选 [Legend sidecar 模板](deploy/direct/compose.legend.yaml) 面向已有 sing-box 部署，需要自行提供配置和二进制路径。

## 来源与许可

- 后端、插件框架与原管理界面：[XziXmn/legado-hub](https://github.com/XziXmn/legado-hub)，MIT；原始许可保留在 [LegadoHub-MIT.txt](docs/licenses/LegadoHub-MIT.txt)。
- 阅读器：[lukelzlz/legado-server](https://github.com/lukelzlz/legado-server)，基于提交 `58c0de5e8adcaa13e8fe9f540867f34b671629b2`，GPL-3.0；具体改动见 [阅读器来源说明](frontend/third-party/legado-server.md)。包含该阅读器的组合版本按 [GPL-3.0](LICENSE) 分发，并提供对应源码。
- 哔哩段落排序协议参考及许可见 [THIRD_PARTY_NOTICE.md](plugins/sources/thirdparty/linovelib_com/THIRD_PARTY_NOTICE.md)。书源插件许可不授予站点书籍内容的版权。

完整上游 README 保存在 [upstream-readme.md](docs/architecture/upstream-readme.md)，其中授权码和双端口说明属于上游模式；本分支的默认部署采用账号、邀请码和单入口。

## 开发与验证

阅读 [AGENTS.md](AGENTS.md) 和 [个人阅读架构](docs/architecture/direct-reading.md)。安装 Python 3.12、Node.js 和项目依赖后运行：

```powershell
pwsh -NoProfile -File verify.ps1
```

门禁覆盖后端测试、插件契约、前端 lint/测试/构建、桌面与手机视觉比较、运行时 smoke 以及本地持久数据保护。真实站点访问另做隔离容器验收，不用 fixture 测试代替真实可用性结论。

最近部署验证：后端 640 项通过、4 项可选测试跳过，前端 107 项通过；已通过实际登录→搜索→加入书库→目录→聚合阅读，包括短章节、插图和九页长章。已验证的样本不代表全部书籍可读。
