# 部署与配置

## 本地安装

Windows 环境需要 Python 3.12、Node.js 22 和 Git LFS。使用仓库 README 的克隆命令，再执行 `setup.ps1`。模型与知识图谱已随仓库提供，无需重建即可运行。

前台启动：`start.ps1`；后台启动或重启：`restart.ps1`；重新构建前端并启动：`restart.ps1 -Build`；停止后台平台：`stop-background.ps1`。

## 真实 Neo4j

本地独立 Neo4j Community 安装还需 Java 25。安装器使用固定版本 2026.09.0，并校验官方压缩包 SHA256。

```powershell
.\.venv\Scripts\python.exe tools\setup_local_neo4j.py
.\start-neo4j.ps1
# 等待数据库完成启动后执行导入。
.\.venv\Scripts\python.exe tools\import_neo4j.py
.\restart.ps1
```

安装器生成随机密码写入本地 `.env`，设置 `KNOWLEDGE_BACKEND=neo4j`，使用 Bolt `17687` 和 Browser `17474`，仅监听本机。浏览器入口为 `http://localhost:17474/`。后续启动脚本会自动启动已安装的项目数据库。

连接已有本地或远程 Neo4j 时，在 `.env` 配置下列项目，再执行 `tools/import_neo4j.py` 并重启平台：

```dotenv
KNOWLEDGE_BACKEND=neo4j
NEO4J_URI=bolt://127.0.0.1:17687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<本地填写>
NEO4J_DATABASE=neo4j
```

Aura 地址一般为 `neo4j+s://<instance>.databases.neo4j.io`。导入按数据集 SHA256 建立命名空间，可重复执行，不删除已有图。浏览器通过后端访问数据库。

## LLM 与照片识别

在现有 `.env` 中填写服务配置：

```dotenv
LLM_BASE_URL=https://your-provider.example/v1
LLM_API_KEY=<本地填写>
LLM_MODEL=<服务模型名称>
VISION_BASE_URL=
VISION_API_KEY=
VISION_MODEL=<支持图像的模型名称>
```

服务需兼容 chat-completions；独立视觉地址和密钥留空时使用 LLM 的配置。视觉模型必须明确填写。照片识别会将所选工单最多前三张图片发送到配置的服务，结果作为待验证观察，不自动确认根因或绑定 IFC 构件。

未配置时，报修、定位、图谱查询和推演仍可运行；维护端 AI 问答和视觉识别显示不可用，住户助手使用已有规则指导。

## 数据重建

从原始 Rhino 文件重新生成模型：

```powershell
.\setup.ps1 -PrepareModel
```

原始文件为 `source/Concrete_Housing_BuildingPermit_Combined.3dm`。默认输出到 `data/`，不改写原始模型。自定义输入和输出可使用：

```powershell
.\.venv\Scripts\python.exe tools\prepare_model.py --source '<模型路径>' --output '<输出目录>'
```

重新导入知识图谱快照：

```powershell
.\.venv\Scripts\python.exe tools\import_knowledge.py source\neo4j_query_table_data_2026-9-24.csv
```

快照包含 1,433 个节点、4,959 条关系。原 CSV 恰好 5,000 行，程序保留覆盖不足的提示。`HAS_ROOT_CAUSE` 是故障模式到候选原因的诊断关系，不用作实际设备的物理传播关系。

## 保存与备份

本地运行后备份 `data/maintenance.sqlite3`、`data/uploads/` 和 `.env`；使用 Neo4j 时另行备份其数据目录。迁移电脑时克隆项目、下载 LFS 文件、安装依赖，再恢复本地数据与配置。备份 SQLite 前先停止平台，避免遗漏尚未写入主数据库的 WAL 数据。

可用 `MAINTENANCE_DATA_DIR` 指定独立数据目录；该目录需同时包含 `building.json`、`model-properties.json`、`causal-graph.json` 和 `models/`，工单与照片也会写入其中。

## 开发

```powershell
.\setup.ps1 -Dev
.\.venv\Scripts\python.exe -m pytest tests -q
npm.cmd --prefix frontend run build
```

前端开发服务器使用 `npm.cmd --prefix frontend run dev`，后端使用 `start.ps1`。Vite 将 API、模型和照片请求代理到 `127.0.0.1:8000`。
