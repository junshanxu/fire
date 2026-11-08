# 航站楼联合巡检 · 单文件展示页

直接双击 `index.html`，或下载 `airport-ops-html-demo.zip` 后解压。页面内置三路同步画面、8 台设备状态、三个作业区、节点跳转、9 张现场记录和 JSON 导出。默认 4× 播放，一轮约 58 秒。

## 使用方式

最简单的方式是直接双击 `index.html`，或把它上传到任意静态网站托管：

- Nginx / Apache / IIS：把 `index.html` 放到站点目录；
- Vercel / Netlify / GitHub Pages：把这个文件作为静态站点入口；
- 本地预览：在当前目录运行 `python -m http.server 8093`，打开 `http://localhost:8093/`。

页面不需要 Docker、ROS、Node.js、数据库或 API Key。点击“启动联合作业”后，页面按已记录的三维机场作业时间线播放；播放速度可选 1×、2×、4×，可拖动进度条或点击右侧关键节点跳转。现场记录可单张放大查看，报告按钮会下载当前进度的 JSON。

## 文件

- `index.html`：可直接部署的完整页面，约 16 MB。
- `airport-ops-html-demo.zip`：页面、说明、构建清单及资源来源的下载包。
- `session-atlas.mp4`：三路同步画面组成的视频资源，已内嵌进 HTML。
- `build-manifest.json`：时长、设备数、任务数和记录数。
- `source/`：页面结构、脚本、样式和已录制作业数据；`build.py` 可重新生成页面。

## 修改并重新打包

修改 `source/index.template.html`、`source/app.js` 或 CSS 后，在本目录运行 `python build.py`。使用 Python 3.8 或更新版本的标准库即可；素材已随仓库提交，不需要原始录屏目录或其他 Python 包。命令会更新 HTML、构建清单和 ZIP。

新建 Vercel / Netlify 静态站点时，将本目录设为项目根目录；不需要构建命令。父仓库主平台有独立路由，提交本目录不会自动替换主平台首页。

视频与图片的资源来源和作者信息见 `THIRD_PARTY_NOTICES.md`。

这是已录制三维场景与同步遥测的离线展示版，用于路演时稳定呈现机场协同作业。完整 ROS 2 / Open-RMF / Gazebo 服务入口见上级目录的 `README.zh-CN.md`。
