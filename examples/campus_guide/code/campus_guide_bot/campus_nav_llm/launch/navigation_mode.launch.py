"""Navigation launch for TurtleBot4.

Launches localization (map_server + AMCL), the full Nav2 stack, and the
campus_nav_llm Phase 1 nodes (task_executor + llm_planner).

Lifecycle managers are NOT included — under FastDDS Discovery Server they
cannot reliably discover lifecycle services (Nav2 #3560, rmw_fastrtps #392,
#499, #706). Instead, deploy.sh runs lifecycle_activator: a persistent
Python node that discovers all services once and transitions nodes in the
correct order (10-20x faster than CLI-based activation).

Usage:
    ros2 launch campus_nav_llm navigation_mode.launch.py
    ros2 launch campus_nav_llm navigation_mode.launch.py namespace:=turtlebot468
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, TimerAction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, PushRosNamespace
from launch_ros.descriptions import ParameterFile
from nav2_common.launch import RewrittenYaml


def generate_launch_description():
    pkg_share = get_package_share_directory("campus_nav_llm")

    # -- Default paths --
    default_map = os.path.join(pkg_share, "maps", "my_map.yaml")
    default_params = os.path.join(pkg_share, "config", "nav2_combined_params.yaml")
    default_semantic_map = os.path.join(pkg_share, "semantic", "semantic_map.json")

    # -- Launch arguments --
    declare_ns = DeclareLaunchArgument(
        "namespace", default_value="turtlebot468",
        description="Robot namespace (match TurtleBot4 config)")
    declare_map = DeclareLaunchArgument(
        "map", default_value=default_map,
        description="Full path to map YAML")
    declare_params = DeclareLaunchArgument(
        "params_file", default_value=default_params,
        description="Nav2 combined parameters file")
    declare_semantic_map = DeclareLaunchArgument(
        "semantic_map", default_value=default_semantic_map,
        description="Semantic map JSON for LLM planner")

    namespace = LaunchConfiguration("namespace")
    map_yaml = LaunchConfiguration("map")
    params_file = LaunchConfiguration("params_file")
    semantic_map = LaunchConfiguration("semantic_map")

    # -- TF remappings --
    tf_remappings = [("/tf", "tf"), ("/tf_static", "tf_static")]

    # -- Rewrite YAML with runtime substitutions --
    configured_params = ParameterFile(
        RewrittenYaml(
            source_file=params_file,
            root_key=namespace,
            param_rewrites={
                "use_sim_time": "False",
                "yaml_filename": map_yaml,
            },
            convert_types=True,
        ),
        allow_substs=True,
    )

    # -- Odom TF bridge --
    # Ref: Nav2 PR #2910 — respawn for crash recovery (non-composed nodes)
    odom_tf_pub = GroupAction([
        PushRosNamespace(namespace),
        Node(
            package="campus_nav_llm",
            executable="odom_tf_publisher",
            name="odom_tf_publisher",
            output="screen",
            respawn=True,
            respawn_delay=2.0,
            remappings=tf_remappings,
        ),
    ])

    # -- Localization nodes (map_server + AMCL) --
    # No lifecycle_manager — activation handled by lifecycle_activator via deploy.sh
    localization_nodes = GroupAction([
        PushRosNamespace(namespace),

        Node(
            package="nav2_map_server",
            executable="map_server",
            name="map_server",
            output="screen",
            parameters=[configured_params],
            remappings=tf_remappings,
        ),
        Node(
            package="nav2_amcl",
            executable="amcl",
            name="amcl",
            output="screen",
            parameters=[configured_params],
            remappings=tf_remappings,
        ),
    ])

    # -- Nav2 stack --
    # No lifecycle_manager — activation handled by lifecycle_activator via deploy.sh
    nav2_nodes = GroupAction([
        PushRosNamespace(namespace),

        Node(
            package="nav2_controller",
            executable="controller_server",
            name="controller_server",
            output="screen",
            parameters=[configured_params],
            remappings=tf_remappings + [("cmd_vel", "cmd_vel_nav")],
        ),
        Node(
            package="nav2_smoother",
            executable="smoother_server",
            name="smoother_server",
            output="screen",
            parameters=[configured_params],
            remappings=tf_remappings,
        ),
        Node(
            package="nav2_planner",
            executable="planner_server",
            name="planner_server",
            output="screen",
            parameters=[configured_params],
            remappings=tf_remappings,
        ),
        Node(
            package="nav2_behaviors",
            executable="behavior_server",
            name="behavior_server",
            output="screen",
            parameters=[configured_params],
            remappings=tf_remappings,
        ),
        Node(
            package="nav2_bt_navigator",
            executable="bt_navigator",
            name="bt_navigator",
            output="screen",
            parameters=[configured_params],
            remappings=tf_remappings,
        ),
        Node(
            package="nav2_waypoint_follower",
            executable="waypoint_follower",
            name="waypoint_follower",
            output="screen",
            parameters=[configured_params],
            remappings=tf_remappings,
        ),
        Node(
            package="nav2_velocity_smoother",
            executable="velocity_smoother",
            name="velocity_smoother",
            output="screen",
            parameters=[configured_params],
            remappings=tf_remappings + [
                ("cmd_vel", "cmd_vel_nav"),
                ("cmd_vel_smoothed", "cmd_vel"),
            ],
        ),
    ])

    # -- LLM Planner (with embedded task executor) --
    # The planner now includes TaskExecutorCore in-process, eliminating
    # DDS topic round-trips for tool execution (ROSA pattern).
    # Standalone task_executor is no longer needed in the launch.
    # Ref: Nav2 PR #2910 — respawn for crash recovery
    llm_planner = TimerAction(
        period=10.0,
        actions=[
            Node(
                package="campus_nav_llm",
                executable="llm_planner",
                parameters=[{
                    "semantic_map_path": semantic_map,
                }],
                respawn=True,
                respawn_delay=5.0,
            ),
        ],
    )

    # -- Assemble --
    ld = LaunchDescription()

    ld.add_action(declare_ns)
    ld.add_action(declare_map)
    ld.add_action(declare_params)
    ld.add_action(declare_semantic_map)

    # Odom TF bridge (must run before AMCL)
    ld.add_action(odom_tf_pub)

    # Localization (map_server + AMCL — no lifecycle_manager)
    ld.add_action(localization_nodes)

    # Nav2 stack (controller, planner, etc. — no lifecycle_manager)
    ld.add_action(nav2_nodes)

    # LLM planner with embedded executor (delayed for Nav2 to start)
    ld.add_action(llm_planner)

    return ld
