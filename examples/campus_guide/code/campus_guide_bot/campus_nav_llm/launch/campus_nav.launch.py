"""Phase 1 MVP launch file.

Launches Task Executor and LLM Planner only.
No person detection, no dialogue manager, no battery monitoring.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, TimerAction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    pkg_share = get_package_share_directory("campus_nav_llm")

    default_map = os.path.join(pkg_share, "semantic", "semantic_map.json")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "semantic_map",
                default_value=default_map,
                description="Path to semantic_map.json",
            ),
            # Task Executor (needs Nav2 active — delay 5s for stability)
            TimerAction(
                period=5.0,
                actions=[
                    Node(
                        package="campus_nav_llm",
                        executable="task_executor",
                        parameters=[
                            {
                                "semantic_map_path": LaunchConfiguration(
                                    "semantic_map"
                                )
                            }
                        ],
                    ),
                ],
            ),
            # LLM Planner (needs Task Executor ready — delay 8s)
            TimerAction(
                period=8.0,
                actions=[
                    Node(
                        package="campus_nav_llm",
                        executable="llm_planner",
                        parameters=[
                            {
                                "semantic_map_path": LaunchConfiguration(
                                    "semantic_map"
                                )
                            }
                        ],
                    ),
                ],
            ),
        ]
    )
