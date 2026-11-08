# Open-RMF Airport Heterogeneous Collaboration Simulation

This example adds a runnable, local three-dimensional airport demonstration to the Fire platform repository. It is intentionally isolated from the existing web dispatch demo under `web/` and `platform_app/`.

The scenario uses an official Open-RMF Airport Terminal map as the building context and adds:

- three inspection dogs (`DOG-01` to `DOG-03`),
- three inspection UAVs (`UAV-01` to `UAV-03`),
- two RMF logistics robots (`AMR-01` and `AMR-02`), and
- three work areas for electrical equipment, baggage handling and security systems.

The web panel is served at `http://localhost:8092` after startup. It shows the Gazebo camera, measured robot positions, active motion indicators, target links, dependency chains and evidence images.

## Quick start on Windows

1. Install and start Docker Desktop.
2. Open PowerShell in this directory.
3. Run:

```powershell
.\start-windows.ps1 -Build
```

4. Open [http://localhost:8092](http://localhost:8092) and click **启动 8 机协同演示**.

The first build downloads the ROS 2 Humble packages and pins the Open-RMF demo sources, so the initial build can take several minutes and needs network access. If a compatible runtime image is already available, pass it with `--build-arg RUNTIME_IMAGE=<image>` to speed up local iteration. See [`README.zh-CN.md`](README.zh-CN.md) and [`docs/architecture.md`](docs/architecture.md) for the base-image and asset requirements.

## Demonstration flow

The mission is condition-driven rather than a fixed animation:

1. The three dogs receive RMF patrol routes and arrive at separate areas.
2. A clearly labeled scenario-injected event unlocks the matching UAV inspection.
3. Each UAV follows its own altitude and route. Only a measured verification unlocks delivery.
4. A shared pool of two AMRs is assigned to three delivery jobs; an area can display **等待运力** while both AMRs are busy.
5. A delivery is confirmed only after the dog and AMR are measured at their separate handoff points and remain there for the dwell period.
6. All ground robots return through RMF and the UAVs land. The portal stores the task state, telemetry snapshot and camera evidence.

The included roadshow cut is [`media/airport-collaboration-roadshow.mp4`](media/airport-collaboration-roadshow.mp4), with a cover and subtitle file beside it.

## Validation

After the simulator is ready, run the end-to-end check from PowerShell:

```powershell
node .\tests\verify_live.mjs
```

The check starts a fresh mission, rejects a duplicate start, pauses and resumes Gazebo, checks the dependency ordering, confirms 12 RMF tasks and verifies that all eight devices moved and returned home.

## Scope and safety boundary

This is a computer simulation for a roadshow. The airport building is an official example scene, not a survey of a real airport. The dog model is a planar base with visual gait joints; it is not full leg-contact dynamics. The UAV model is a Gazebo rigid body with a gravity-compensating controller; it is not PX4 and has no aviation deconfliction. Alerts are explicit scenario-injected demo events; the images are Gazebo camera evidence and are not AI defect detections. Handoff is measured co-location plus a simulated work-order acknowledgement; it does not perform mechanical loading or repair.

The project does not connect physical hardware or require an InOrbit API key.
