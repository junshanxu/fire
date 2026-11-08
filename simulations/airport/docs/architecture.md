# Architecture and maintenance notes

## Components

| File | Responsibility |
| --- | --- |
| `build_scene.py` | Extends the generated Airport Terminal world, creates the 8 robot models and work areas, writes the nav graph and two RMF fleet YAML files. |
| `fleet_config.py` | Single source of truth for robot namespaces, homes, work areas, RMF waypoint names, heights and cargo. |
| `plugin/motion.cpp` | Gazebo model plugin. The dog follows measured velocity commands; the UAV follows measured 3D targets and publishes odometry. It never teleports a model. |
| `controller.py` | Converts RMF dog path requests to velocity commands, handles three UAV controllers, records measured odometry and publishes `/airport/agents`. |
| `portal.py` | Flask/ROS bridge, RMF task API client, WebSocket task-state observer, camera stream and dependency-aware mission coordinator. |
| `site/` | Static operations panel. It draws labels from `/api/status` and projects world positions through the overview camera calibration. |
| `airport.launch.py` | Starts the map server, RMF schedule/dispatcher and both ground fleet adapters. |
| `start.sh` | Starts Xvfb/noVNC, Gazebo, ROS nodes and the portal inside the simulator container. |

## Runtime data flow

```text
portal.py ── ApiRequest ──> RMF fleet adapter ── fleet manager ── PathRequest ──> controller.py ── cmd_vel ──> dog Gazebo plugins
    │                                                                               ↑
    └─ air_command ──────────────────────────────────────────────────────────────────┘── target ──> UAV Gazebo plugins
RMF dispatcher / adapters ── task_state_update ──> portal.py WebSocket :7878
Gazebo cameras ── ROS Image ──> portal.py ── MJPEG ──> site/
Gazebo odometry ── controller.py ── /airport/agents ──> portal.py ── /api/status ──> site/
```

Ground robots remain under RMF's two-dimensional traffic scheduling. UAVs are coordinated by the portal because the RMF ground graph does not model aircraft airspace. The portal only advances the next activity after the previous activity has measured the required condition.

## Base image and assets

`Dockerfile` builds a complete ROS 2 Humble / Gazebo Classic 11 / Open-RMF runtime from `osrf/ros:humble-desktop` and pins the upstream `open-rmf/rmf_demos` source. For fast local iteration, pass an existing compatible runtime image with `--build-arg RUNTIME_IMAGE=<image>`; the final image is called `rmf-airport-sim:humble` by the compose file. The base image must contain the ROS packages listed in `Dockerfile` and an `/opt/rmf_ws/install` workspace with the RMF demo assets.

`generated/airport` contains the generated official airport building assets and upstream Apache-2.0 license. `fuel-models` contains the downloaded Fuel model assets used by that scene; their per-model license and author files remain in the directories. See `THIRD_PARTY_NOTICES.md` for sources. Third-party assets retain their original licenses.

## API and ROS topics

- `GET /api/status` — current fleets, mission, device telemetry and camera freshness.
- `POST /api/mission` — start one mission; a second request returns HTTP 409.
- `POST /api/physics` with `{"action":"pause"|"resume"}` — Gazebo physics control.
- `/robot_path_requests` — RMF dog routes.
- `/airport/air_command` — portal-to-UAV survey commands.
- `/airport/agents` — measured multi-device state for the portal.
- `/sensors/overview/overview/image_raw`, `/sensors/dog/dog/image_raw`, `/sensors/drone/drone/image_raw` — camera feeds.

## Rebuilding and reviewing

Use `docker compose build` after changing `plugin/motion.cpp` or scene-generation code. Use `docker compose up -d --force-recreate` after changing ROS Python nodes. The website source is volume-mounted for fast UI iteration. Keep `runtime/`, simulator logs, raw video frames and local base-image caches out of commits.
