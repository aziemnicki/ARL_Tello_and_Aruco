#!/bin/bash

source /opt/ros/foxy/setup.sh
cd /home/tello_ros_ws
source install/setup.bash
ros2 service call /drone1/tello_action tello_msgs/TelloAction "{cmd: 'takeoff'}"
