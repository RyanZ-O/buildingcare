# 接口与数据流

完整参数、响应结构及可交互接口文档由 FastAPI 提供：`http://localhost:8000/docs`；OpenAPI JSON：`http://localhost:8000/openapi.json`。

## 工作流程

1. 住户选择房间和具体构件，提交描述与照片，生成工单。
2. 维护团队确认报修位置，在建筑模型中定位和高亮。
3. 根据描述与观察匹配故障模式，查询候选根因及检查方法。
4. 将假设绑定到实际构件，记录正在检查、排除或人工确认的结论。
5. 选择维修动作和参数，通过有依据的服务关系推演影响。
6. 比较当前分析下保存的方案，生成对应报告并进行问答。

## 接口分组

| 模块 | 主要接口 |
| --- | --- |
| 配置与模型 | `GET /api/config`、`GET /api/building` |
| 构件目录 | `GET /api/elements`、`POST /api/identify` |
| 工单 | `GET/POST /api/issues`、`GET/PATCH /api/issues/{id}`、`PUT /api/issues/{id}/location` |
| 图谱 | `GET /api/knowledge/summary`、`GET /api/knowledge/graph`、`POST /api/knowledge/connection` |
| 分析与排查 | `GET/POST /api/issues/{id}/analysis`、`POST /api/issues/{id}/bindings`、`POST /api/issues/{id}/inspections`、`GET /api/issues/{id}/trace` |
| 视觉识别 | `POST /api/issues/{id}/identify`、`GET /api/issues/{id}/identifications` |
| 服务关系 | `GET/POST /api/topology`、`DELETE /api/topology/{id}` |
| 方案与推演 | `GET /api/issues/{id}/plans`、`GET/POST /api/issues/{id}/simulations` |
| 报告与问答 | `GET /api/issues/{id}/report`、`POST /api/issues/{id}/chat`、`POST /api/resident/chat` |
| 演示案例 | `POST /api/demo/case-study`、`POST /api/demo/seed` |

## 核心规则

- 保留源 IFC 编号、`roomId`、`assetId` 和 GLB 中的 `entityId`，用统一标识连接模型、工单与分析。
- 报修位置变化使当前分析失效；绑定与检查变化生成新的分析版本。旧方案保留，但不会混入当前比较。
- 被排除的原因不能继续推演；未绑定的原因不能借用报修构件替代。
- 服务传播使用明确录入的有向条件关系，按 `(构件, 服务状态)` 去重，处理循环与跨系统服务依赖。
- 成本、工时、占用、服务损失和热工输入均随方案保存；维修成功与恢复服务是推演条件。
- 工单、检查、识别、服务关系、分析和方案保存到 SQLite，照片保存到本地文件目录。
