# Open-RMF 机场异构协同仿真

这个目录是 Fire 仓库中的一个可复现路演示例：在 Open-RMF 的机场航站楼三维场景里，同时调度 3 台机器狗、3 架无人机和 2 台运输机器人。网页操作面板会显示 Gazebo 画面、每台设备的实时位置和速度、任务阶段、告警、交接状态以及相机证据。

## 运行环境

- Windows 10/11 + Docker Desktop（建议给 Docker 分配至少 8 GB 内存）
- Docker Desktop 的 Linux containers 模式
- 首次构建需要访问 Docker Hub、ROS 软件源和 GitHub；后续启动可以离线使用已构建镜像

## Windows 快速启动

在 PowerShell 中执行：

```powershell
cd <仓库路径>\simulations\airport
.\start-windows.ps1 -Build
```

脚本会构建 `rmf-airport-sim:humble`，启动 Gazebo、ROS 2、Open-RMF 调度器和网站，并打开 <http://localhost:8092>。页面加载后点击“启动 8 机协同演示”。停止服务：

```powershell
.\stop-windows.ps1
```

如果 Windows 提示脚本执行策略限制，可仅对本次进程放行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-windows.ps1 -Build
```

如果只修改了 Python 或网页文件，可以不加 `-Build`，Compose 会使用已有镜像并挂载这些文件。也可以直接运行：

```powershell
docker compose -p rmf-airport up -d
docker compose -p rmf-airport logs -f simulator
```

### 已有兼容基础镜像

完整构建默认从 `osrf/ros:humble-desktop` 安装依赖并编译 RMF demo，时间较长。已有包含 ROS 2 Humble、Gazebo Classic、RMF 包和 `/opt/rmf_ws/install` 的镜像时，可使用：

```powershell
docker build -t rmf-airport-sim:humble `
  --build-arg RUNTIME_IMAGE=<已有镜像名> .
```

镜像需要提供 `ros2`、`gzserver`、`gzclient`、`python3` 和 `libgazebo_ros_*`。不能把只有网页运行时的镜像作为基础镜像。

## 路演任务

点击启动后，控制器按依赖自动推进三处作业区：

1. 机器狗分别沿 RMF 路网到达配电设备、行李输送和安防设施区域。
2. 对应的场景注入告警解锁无人机；无人机分别飞到 6、7、8 米执行定点复核。
3. 复核通过后，从共享的 2 台运输机器人中分配运力；没有空闲车辆的区域会显示“等待运力”。
4. 机器狗和运输机器人都在交接点实测到位并驻留 4 秒，系统才确认模拟工单。
5. 地面设备返航、无人机降落，系统归档 12 个 RMF 任务和 9 张相机证据图。

页面中的“运行中”、速度、目标、阶段和交接倒计时用于让观众能看懂当前谁在移动。暂停/恢复按钮会控制 Gazebo 物理时钟；重复点击启动会返回 409，避免重复创建任务。

## 验证

容器启动后，安装 Node.js 18 或更新版本，在本目录执行：

```powershell
node .\tests\verify_live.mjs
```

验证脚本会检查网站就绪、重复任务拒绝、暂停/恢复、依赖顺序、12 个 RMF 任务、8 台设备真实移动和返航、无人机高度、三次交接驻留以及 9 张证据图。报告写入 `runtime/reports/verification.json`。

本次打包沿用已通过验证的场景和控制代码，基准运行报告保存在 [`docs/validation-report.json`](docs/validation-report.json)。报告记录的是本机演示实例的一轮实际运行；更换基础镜像、设备配置或宿主机后应重新执行上述验证。

## 文件索引

- `build_scene.py`：从官方机场航站楼场景生成世界文件、8 台设备、三个作业区、RMF 路网和车队配置。
- `fleet_config.py`：设备名称、坐标、航点、作业区、无人机高度和货物的唯一配置来源。
- `plugin/motion.cpp`：Gazebo 运动插件；机器狗使用速度控制，无人机使用三维目标控制，位置来自 Gazebo 测量值而不是瞬移。
- `controller.py`：将 RMF 机器狗路径请求转为速度指令，管理无人机控制器，并发布 `/airport/agents`。
- `portal.py`：Flask/ROS 桥、RMF 任务 API、WebSocket 状态监听、相机证据和依赖感知的任务编排器。
- `site/`：静态操作面板，读取 `/api/status` 绘制设备标签、阶段和告警。
- `airport.launch.py`：启动地图服务器、RMF 交通/任务调度器和两个地面车队适配器。
- `start.sh`：容器入口，启动 Xvfb/noVNC、Gazebo、ROS 节点和网站后端。
- `docs/代码注释与架构.md`：面向中文读者的联动逻辑、接口和排错说明。
- `docs/roadshow-script.md`：58 秒视频及现场讲解节奏。
- `web-demo/index.html`：可直接上传静态托管的单文件展示页；不依赖 Docker、ROS 或 API Key。

## 静态展示页

需要快速路演时，直接打开或部署 [`web-demo/index.html`](web-demo/index.html)。它内置同步机场画面、设备状态、作业节点、现场记录和 JSON 导出，不需要启动服务；页面上的播放速度和节点跳转适合现场讲解。

## 边界说明

这是电脑仿真路演，不是实体机场或真实机场测绘。机器狗是平面底盘近似模型；无人机是带重力补偿控制的 Gazebo 刚体，不是 PX4 飞控，也没有航空避碰；告警是明确标注的场景注入事件，不是 AI 缺陷识别；交接是双方到位后的模拟工单确认，不会执行机械臂装卸。本示例不连接实体硬件，也不需要 InOrbit API key。

机场模型和 Fuel 资源目录保留各自的 `LICENSE` 文件；使用或再分发资源时应同时遵守对应上游许可证。
