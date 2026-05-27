#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# flake8: noqa
#
# Copyright 2023 Herman Ye @Auromix
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Description:
# This example demonstrates simulating function calls for any robot,
# such as controlling velocity and other service commands.
# By modifying the content of this file,
# A calling interface can be created for the function calls of any robot.
# The Python script creates a ROS 2 Node
# that controls the movement of the TurtleSim
# by creating a publisher for cmd_vel messages and a client for the reset service.
# It also includes a ChatGPT function call server
# that can call various functions to control the TurtleSim
# and return the result of the function call as a string.
#
# Author: Herman Ye @Auromix

# ROS related
import rclpy
from rclpy.node import Node
from llm_interfaces.srv import ChatGPT
from std_msgs.msg import Float64MultiArray, MultiArrayDimension, MultiArrayLayout
from std_srvs.srv import Empty

# LLM related
import json
from llm_config.user_config import UserConfig

# Global Initialization
config = UserConfig()


class ArmRobot(Node):
    def __init__(self):
        super().__init__("arm_robot")

        # Publisher for target_pose
        self.target_pose_publisher = self.create_publisher(
            Float64MultiArray, "/target_pose", 10
        )

        # Server for function call
        self.function_call_server = self.create_service(
            ChatGPT, "/ChatGPT_function_call_service", self.function_call_callback
        )
        # Node initialization log
        self.get_logger().info("ArmRobot node has been initialized")

    def function_call_callback(self, request, response):
        try:
            req = json.loads(request.request_text)
            function_name = req["name"]
            function_args = json.loads(req["arguments"])
        except (json.JSONDecodeError, KeyError) as e:
            self.get_logger().error(f"Invalid function call request: {e}")
            response.response_text = f"Invalid request format: {e}"
            return response

        func_obj = getattr(self, function_name, None)
        if func_obj is None or not callable(func_obj):
            self.get_logger().error(f"Unknown function: {function_name}")
            response.response_text = f"Unknown function: {function_name}"
            return response

        try:
            function_execution_result = func_obj(**function_args)
        except Exception as error:
            self.get_logger().info(f"Failed to call function: {error}")
            response.response_text = str(error)
        else:
            response.response_text = str(function_execution_result)
        return response

    def publish_target_pose(self, **kwargs):
        """
        Publishes target_pose message to control the movement of arx5_arm
        """

        x_value = float(kwargs.get("x", 0.2))
        y_value = float(kwargs.get("y", 0.2))
        z_value = float(kwargs.get("z", 0.2))

        roll_value = float(kwargs.get("roll", 0.2))
        pitch_value = float(kwargs.get("pitch", 0.2))
        yaw_value = float(kwargs.get("yaw", 0.2))

        msg = Float64MultiArray()
        msg.data = [x_value, y_value, z_value, roll_value, pitch_value, yaw_value]
        self.target_pose_publisher.publish(msg)
        self.get_logger().info(f"Published target pose: {msg.data}")
        return str(msg.data)



def main():
    rclpy.init()
    arm_robot = ArmRobot()
    rclpy.spin(arm_robot)
    rclpy.shutdown()


if __name__ == "__main__":
    main()
