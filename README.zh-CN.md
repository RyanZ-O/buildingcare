# BuildingCare

[English](README.md) | 简体中文

面向住宅住户和维护团队的构件级智能检修支持平台。住户提交房间、具体位置、问题描述和照片；维护人员在同页三维模型与因果知识图谱中定位问题、逐项排查根因，并比较维修方案的成本、时间、影响房间和舒适度变化。

## 功能

- **住户报修**：手机页面、中英文描述、照片上传、房间与独立构件选择。
- **三维定位**：真实 Rhino 模型转换为 GLB，保留 IFC 编号；支持楼层、系统、构件筛选与高亮。
- **全楼服务关系图**：实际构件、系统归属、管道与风管连接候选、设备依赖、供电候选及房间服务范围；可查看推断依据并与三维模型联动。
- **根因排查**：圆点连线知识图谱、相关路径高亮、候选原因切换、检查记录和实际构件绑定。
- **维修推演**：观察、局部检修、更换与支路停运；比较费用、工时、服务中断、房间范围及温度恢复，并播放影响传播动画。
- **报告与问答**：生成与当前分析和方案一致的报告；住户临时指导支持中英文。维护端 LLM 问答与照片识别可接入兼容 chat-completions 的服务。

## 项目结构

```text
BuildingCare/
├── backend/                 FastAPI 接口、图查询、排查、推演和数据存储
├── frontend/                React + TypeScript + Three.js 网页
├── data/
│   ├── building.json        建筑、房间、构件与网页模型映射
│   ├── model-properties.json 原始构件属性
│   ├── causal-graph.json    从 Neo4j CSV 导入的知识图谱
│   ├── service-graph.json   全楼实际构件关系及逐条证据
│   └── models/              按系统与楼层组织的 30 个 GLB 模型
├── source/                  原始 Rhino 模型与 Neo4j CSV
├── tools/                   模型转换、数据导入和本地 Neo4j 安装
├── tests/                   接口、诊断、推演与模型映射测试
├── docs/                    部署、接口和正式项目介绍
├── .env.example             本地配置模板
├── requirements*.txt        运行、测试与模型转换依赖
└── *.ps1                    Windows 安装、启动、重启和停止脚本
```

## 快速运行（Windows）

需要 Python 3.12、Node.js 22，以及 Git LFS。原始 Rhino 模型和网页 GLB 模型使用 [Git LFS](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-git-large-file-storage) 保存，克隆后应下载实际文件。

```powershell
git lfs install
git clone https://github.com/RyanZ-O/buildingcare.git
cd buildingcare
git lfs pull
.\setup.ps1
.\start.ps1
```

| 入口 | 地址 |
| --- | --- |
| 维护工作台 | http://localhost:8000/ |
| 全楼服务关系图 | http://localhost:8000/systems |
| 住户报修 | http://localhost:8000/report |
| 住户助手 | http://localhost:8000/resident |
| 正式项目资料 | http://localhost:8000/project-docs/ |
| 接口文档 | http://localhost:8000/docs |

首次运行会创建空的本地工单数据库。维护首页点击 **Open demo case** 可建立并打开 HVAC 低风量演示案例，再执行根因分析与维修推演。日常后台启动使用 `.\restart.ps1`，修改前端后使用 `.\restart.ps1 -Build`；停止使用 `.\stop-background.ps1`。

手机与电脑连接同一个可互访的网络，使用启动脚本显示的 `http://<电脑局域网 IP>:8000/report`。

## 配置与数据

`setup.ps1` 会从 `.env.example` 创建本地 `.env`。默认 `KNOWLEDGE_BACKEND=snapshot`，在随仓库提供的 Neo4j CSV 图谱快照上执行查询，无需数据库服务。配置为 `neo4j` 后执行真实参数化 Cypher；数据库失败会明确报错。

完整 Neo4j、LLM、视觉服务配置及模型重建步骤见 [部署说明](docs/deployment.md)。接口和数据流见 [接口说明](docs/api.md)。[正式项目介绍](docs/project/)保留中文、英文和中英对照的 PDF 与可编辑 Word，以及构件命名对应表。

工单、检查、方案和上传照片只保存在本地 `data/maintenance.sqlite3` 与 `data/uploads/`，不随仓库分发。`.env`、依赖环境、运行日志和临时文件均被 Git 忽略。

## 验证

```powershell
.\setup.ps1 -Dev
.\.venv\Scripts\python.exe -m pytest tests -q
npm.cmd --prefix frontend run build
```

## 当前范围

模型和知识图谱来自实际文件。全楼关系图保留 10,575 个模型实体、47 个系统网络及 71 个可选房间。系统归属来自模型属性；8,507 条重建的连接、方向、供电和服务关系明确标为推断候选，缺失连接及多重候选仍然可见。[关系图方法说明](docs/service-graph.md)介绍了依据、范围和重建步骤。

演示中的故障、服务连接、检查结论、费用、人员和热工输入是标明的假设。诊断知识、全楼重建关系与主动录入的服务传播规则分别处理；重建候选不会自动参与停运推演。

温度结果是未校准的单区空气温度情景估算。住户助手默认使用预设规则；真实 LLM 和视觉输出需配置相应服务。平台目前没有用户登录和角色权限，部署方式以本地课程演示为主。
