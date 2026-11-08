from launch import LaunchDescription
from launch.actions import TimerAction
from launch_ros.actions import Node

def generate_launch_description():
    sim={"use_sim_time":True}
    nodes=[
        Node(package="rmf_building_map_tools",executable="building_map_server",
             arguments=["/opt/rmf_ws/install/rmf_demos_maps/share/rmf_demos_maps/airport_terminal/airport_terminal.building.yaml"],parameters=[sim]),
        Node(package="rmf_traffic_ros2",executable="rmf_traffic_schedule",name="rmf_traffic_schedule_primary",parameters=[sim]),
        Node(package="rmf_traffic_ros2",executable="rmf_traffic_blockade",parameters=[sim]),
        Node(package="rmf_task_ros2",executable="rmf_task_dispatcher",
             parameters=[sim,{"server_uri":"ws://127.0.0.1:7878","bidding_time_window":2.}]),
        Node(package="rmf_fleet_adapter",executable="door_supervisor",parameters=[sim])]
    for index,fleet in enumerate(("logistics","inspectionDog")):
        config="/opt/airport/runtime/"+fleet+".yaml"
        graph="/opt/airport/runtime/nav_graph.yaml"
        nodes.append(TimerAction(period=3.+index,actions=[
            Node(package="rmf_demos_fleet_adapter",executable="fleet_manager",
                 arguments=["-c",config,"-n",graph],parameters=[sim],respawn=True,respawn_delay=3.),
            Node(package="rmf_demos_fleet_adapter",executable="fleet_adapter",
                 arguments=["-c",config,"-n",graph,"-sim"],
                 parameters=[sim,{"server_uri":"ws://127.0.0.1:7878"}],respawn=True,respawn_delay=3.)
        ]))
    return LaunchDescription(nodes)
