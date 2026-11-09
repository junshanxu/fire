# Default builds a complete ROS/RMF runtime. An existing compatible runtime can
# be selected explicitly with --build-arg RUNTIME_IMAGE=... for local iteration.
ARG RUNTIME_IMAGE=build-runtime
FROM osrf/ros:humble-desktop AS build-runtime
ENV DEBIAN_FRONTEND=noninteractive
SHELL ["/bin/bash", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake curl ca-certificates \
    ros-humble-rmf-fleet-adapter ros-humble-rmf-fleet-adapter-python \
    ros-humble-rmf-task-ros2 ros-humble-rmf-traffic-ros2 \
    ros-humble-rmf-building-map-tools ros-humble-rmf-visualization \
    ros-humble-rmf-robot-sim-gz-classic-plugins \
    ros-humble-rmf-building-sim-gz-classic-plugins \
    ros-humble-gazebo-ros-pkgs python3-colcon-common-extensions \
    python3-pip python3-flask python3-websockets python3-opencv python3-pil \
    fonts-dejavu-core xvfb x11vnc novnc websockify fluxbox wmctrl mesa-utils xfonts-base \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m pip install --no-cache-dir \
    'fastapi==0.99.1' 'pydantic==1.10.24' 'uvicorn==0.30.6' \
    'python-socketio==5.11.4' 'websockets==10.4'
# Pin the upstream demo code; vendored scene/model assets retain their notices.
ARG RMF_DEMOS_REF=d79ac6f03baeedbf8ee572347428b4a817098446
RUN mkdir -p /opt/rmf_ws/src/rmf_demos \
    && curl --fail --location --retry 3 \
      "https://codeload.github.com/open-rmf/rmf_demos/tar.gz/${RMF_DEMOS_REF}" \
      | tar -xz --strip-components=1 -C /opt/rmf_ws/src/rmf_demos
WORKDIR /opt/rmf_ws
# All original map sources are installed, but build only the Office demo's
# generated targets. This airport example uses the checked-in generated world.
RUN python3 -c "from pathlib import Path; p=Path('src/rmf_demos/rmf_demos_maps/CMakeLists.txt'); p.write_text(p.read_text().replace('maps/*.building.yaml', 'maps/office/office.building.yaml'))" \
    && source /opt/ros/humble/setup.bash \
    && colcon build --packages-up-to rmf_demos_gz_classic \
      --cmake-args -DNO_DOWNLOAD_MODELS=ON --event-handlers console_direct+

FROM ${RUNTIME_IMAGE} AS simulator
SHELL ["/bin/bash", "-c"]
COPY plugin /tmp/airport-plugin-source
RUN source /opt/ros/humble/setup.bash \
    && cmake -S /tmp/airport-plugin-source -B /tmp/airport-build \
    && cmake --build /tmp/airport-build -j2
COPY . /opt/airport/
RUN python3 /opt/airport/build_scene.py \
    && cp /tmp/airport-build/libairport_motion.so /opt/airport/runtime/ \
    && chmod +x /opt/airport/start.sh
ENV ROS_DOMAIN_ID=43
EXPOSE 8080
ENTRYPOINT ["/opt/airport/start.sh"]
