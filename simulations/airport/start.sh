#!/usr/bin/env bash
set -eo pipefail
mkdir -p /var/log/airport
# The IPC namespace belongs only to this simulator. Remove dead FastDDS locks
# left by Docker stop/restart before any ROS processes are launched.
rm -f /dev/shm/fastrtps* /dev/shm/sem.fastrtps*
export DISPLAY=:99 QT_X11_NO_MITSHM=1 LIBGL_ALWAYS_SOFTWARE=1
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
Xvfb :99 -screen 0 1440x900x24 -ac +extension GLX +render -noreset >/var/log/airport/xvfb.log 2>&1 &
for i in $(seq 1 50); do glxinfo -B >/dev/null 2>&1 && break; sleep .2; done
fluxbox >/var/log/airport/fluxbox.log 2>&1 &
x11vnc -display :99 -forever -shared -rfbport 5900 -localhost -nopw -noxrecord -noxfixes -noxdamage >/var/log/airport/vnc.log 2>&1 &
websockify --web /usr/share/novnc 6080 localhost:5900 >/var/log/airport/novnc.log 2>&1 &
source /opt/ros/humble/setup.bash
source /opt/rmf_ws/install/setup.bash
export GAZEBO_MODEL_PATH="/opt/airport/generated/airport/models:/opt/airport/fuel-models:/opt/rmf_ws/install/rmf_demos_assets/share/rmf_demos_assets/models:/usr/share/gazebo-11/models"
export GAZEBO_PLUGIN_PATH="/opt/airport/runtime:/opt/ros/humble/lib:/opt/ros/humble/lib/rmf_robot_sim_gz_classic_plugins:/opt/ros/humble/lib/rmf_building_sim_gz_classic_plugins"
export GAZEBO_RESOURCE_PATH="/opt/rmf_ws/install/rmf_demos_assets/share/rmf_demos_assets:/usr/share/gazebo-11"
export GAZEBO_MODEL_DATABASE_URI=""
python3 /opt/airport/controller.py --ros-args -p use_sim_time:=true >/var/log/airport/controller.log 2>&1 &
python3 /opt/airport/portal.py >/var/log/airport/portal.log 2>&1 &
ros2 launch /opt/airport/airport.launch.py >/var/log/airport/rmf.log 2>&1 &
gzserver --verbose -s libgazebo_ros_init.so -s libgazebo_ros_factory.so /opt/airport/runtime/airport.world >/var/log/airport/gazebo.log 2>&1 &
sim_pid=$!
sleep 3
gzclient --verbose >/var/log/airport/gui.log 2>&1 &
for i in $(seq 1 90); do wmctrl -r Gazebo -b add,maximized_vert,maximized_horz 2>/dev/null || true; sleep 1; done &
wait "$sim_pid"
