from setuptools import setup
import glob

package_name = "campus_nav_llm"

setup(
    name=package_name,
    version="1.0.0",
    packages=[package_name],
    data_files=[
        (
            "share/ament_index/resource_index/packages",
            ["resource/" + package_name],
        ),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob.glob("launch/*.py")),
        ("share/" + package_name + "/config", glob.glob("config/*")),
        ("share/" + package_name + "/maps", glob.glob("maps/*")),
        ("share/" + package_name + "/semantic", glob.glob("semantic/*.json")),
    ],
    install_requires=[
        "openai",
        "jsonschema",
        "pyyaml",
    ],
    entry_points={
        "console_scripts": [
            "llm_planner = campus_nav_llm.llm_planner_node:main",
            "task_executor = campus_nav_llm.task_executor_node:main",
            "odom_tf_publisher = campus_nav_llm.odom_tf_publisher:main",
            "lifecycle_activator = campus_nav_llm.lifecycle_activator:main",
        ],
    },
)
