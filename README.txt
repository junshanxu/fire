异构无人自主设备统一管理平台 Demo

运行环境
- Python 3.10 或更高版本
- 不需要安装第三方 Python 包

启动
千问 AI 调度
通过环境变量 DASHSCOPE_API_KEY 配置 API Key。默认模型为 qwen-plus。

添加任务
前端模块包括运行总览、设备管理、任务管理、统一调度、运行监控和系统管理。设备新增、编辑、分类筛选、详情查看、任务创建与分配、反馈提交、设备类型和协议配置均提供演示交互。

模拟数据目前包含“巡检”任务 4 条路线；路线起点和终点均为同一个匿名坐标，路线名称统一为“巡检”。航点使用演示坐标，不对应真实地点。可编辑 sample_data/tasks.json 和 routes.json 调整任务与线路。

可调度资源为真人、机器人、机器狗和无人机各 5 个，数据放在 sample_data/resources.json。首页显示各类空余资源数量。

公司级总控首页集中展示三块内容：任务列表、可调度资源、任务反馈与异常。点击任务可进入对应的任务子平台。资源区按人员、机器人、机器狗和无人机统计空余数量；“资源台账”中，待命资源可派发同场站、同类型的待调度任务。派发记录保存在 platform_app/data/dispatches.json。

反馈模块会展示任务完成信息和异常告警，也可通过“提交反馈”上报任务完成情况或问题；用户提交的反馈保存在 platform_app/data/feedback.json。

方式一：启动服务后，在页面点击“新建任务”并保存。新增任务会写入 platform_app/data/tasks.json，与 sample_data 中的模拟任务分开。
方式二：直接编辑 platform_app/data/tasks.json。文件内容为 JSON 数组，每条真实录入任务示例：

[
  {
    "task_id": "task-001",
    "name": "主变设备例行巡检",
    "station": "示例场站",
    "task_type": "robot",
    "executor": "机器狗 SD-01",
    "planned_time": "2026-11-02T09:00",
    "points": "主变区外观检查\\n开关柜温度采集",
    "status": "待调度",
    "created_at": "2026-11-02T01:00:00+00:00"
  }
]

task_type 可用值：robot（机器狗）、team（人员协同）、drone（无人机）。保存 JSON 后刷新页面即可加载。

模拟数据说明
- sample_data/tasks.json 中的任务只用于演示，不会被“新建任务”覆盖。
- sample_data/stations.json 控制态势地图上的场站卡片；x、y 为地图区域百分比位置。
- sample_data/resources.json 控制资源在线状态表格。
- sample_data/alarms.json 控制待处置告警列表。

代码修改指南
- 调整字段与校验：platform_app/models/task.py
- 调整任务保存和查询：platform_app/services/task_service.py
- 增加或修改 API：platform_app/routes/tasks.py
- 调整页面结构、样式、浏览器交互：web/ 下对应文件
- 修改端口：platform_app/config.py
