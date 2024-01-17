from tello_msgs.srv import TelloAction
from tello_msgs.msg import TelloResponse
from tello_interface.srv import TelloState

import rclpy
from rclpy.node import Node

from std_msgs.msg import Empty
from geometry_msgs.msg import Twist, Pose
from gazebo_msgs.msg import ModelStates
from ros2_aruco_interfaces.msg import ArucoMarkers

import time
from enum import Enum
from scipy.spatial.transform import Rotation
import numpy as np
from threading import Timer
from tello_controller.pid import PIDController


class ControllerNode(Node):

    class TelloState(Enum):
        LANDED = 1
        TAKINGOFF = 2
        HOVERING = 3
        FLYING = 4
        LANDING = 5
        NONE = 0

    state = TelloState.LANDED
    next_state = TelloState.NONE
    action_done = False

    pos_x = pos_y = pos_z = ori_roll = ori_pitch = ori_yaw = 0.0

    pid_x = PIDController(0.6, 0.001, 0.25)
    pid_y = PIDController(0.6, 0.001, 0.25)
    pid_z = PIDController(0.6, 0.001, 0.25)
    pid_yaw = PIDController(0.7, 0.0, 0.25, rotation=True)

    index = 0
    visited_aruco = []
    points = [[2.15, -1.0, 0.75,  3.14]]
    aruco_dict = {
        0: [[0.0, 0.65, 0.0, -4.71], [-1.15, 0.0, 0.0, 0.0]],
        1: [[-0.35, 0.0, 0.0, 4.71], [ 0.0, 0.27, 0.0, 0.0]],
        2: [[0.0, 0.67, 0.0, 0.0]],
        3: [[0.0, 1.07, 0.0, -4.71], [-1.15, 0.0, 0.0, 0.0]],
        4: [[-1.15, 0.0, 0.0, 1.57], [0.0, -0.65, 0.0, 0.0]],
        5: [[0.0, -0.65, 0.0, 1.57], [0.9, 0.0, 0.0, 0.0]],
        6: [[0.1, 0.0, 0.0, -1.57], [0.0, -0.35, 0.0, 0.0]]
        }

    return_points = []
    return_done = False

    def __init__(self):
        super().__init__('controller_node')
        self.tello_controller = self.create_subscription(Empty, '/iisrl/tello_controller', self.main_callback, 10)
        self.tello_response = self.create_subscription(TelloResponse, '/drone1/tello_response', self.tello_response_callback, 10)
        self.position_sub = self.create_subscription(ModelStates, '/gazebo/model_states', self.position_callback, 10)
        self.aruco_sub = self.create_subscription(ArucoMarkers, '/aruco_markers', self.aruco_callback, 10)

        self.tello_service_server = self.create_service(TelloState, '/iisrl/tello_state', self.state_callback)
        self.tello_service_client = self.create_client(TelloAction, '/drone1/tello_action')
        self.service_request = TelloAction.Request()

        self.get_logger().info('Node initialized')


    def position_callback(self, msg):
        idx = msg.name.index('tello_1')

        self.pos_x = msg.pose[idx].position.x
        self.pos_y = msg.pose[idx].position.y
        self.pos_z = msg.pose[idx].position.z

        rot = Rotation.from_quat([msg.pose[idx].orientation.x,
                                  msg.pose[idx].orientation.y,
                                  msg.pose[idx].orientation.z,
                                  msg.pose[idx].orientation.w])
        roll, pitch, yaw = rot.as_euler('xyz')

        self.ori_roll = roll
        self.ori_pitch = pitch
        self.ori_yaw = yaw


    def aruco_callback(self, markers):
        for i, marker_id in enumerate(markers.marker_ids):
            if marker_id == 7:
                break
                # self.last_marker = True
            if marker_id not in self.visited_aruco and markers.poses[i].position.z < 0.5:
                self.visited_aruco.append(marker_id)
                for next_move in self.aruco_dict[marker_id]:
                    self.points.append([x + y for x, y in zip(self.points[-1], next_move)])


    def state_callback(self, request, response):
        response.state = str(self.state)
        response.value = int(self.state.value)

        return response


    def main_callback(self, msg):
        self.get_logger().info('Node activated')
        self.action_done = False

        self.state = self.TelloState.LANDED
        self.next_state = self.TelloState.TAKINGOFF

        self.controller()


    def controller(self):
        if self.state == self.TelloState.LANDED and self.next_state == self.TelloState.TAKINGOFF:
            self.taking_off_func()

        if self.state == self.TelloState.HOVERING:
            if self.action_done and self.return_done:
                self.landing_func()
            elif self.action_done:
                self.return_function()
            else:
                self.flying_func()


    def tello_response_callback(self, msg):
        if msg.rc == 1:
            self.state = self.next_state
            self.next_state = self.TelloState.NONE

        self.controller()


    def taking_off_func(self):
        self.state = self.TelloState.TAKINGOFF
        self.next_state = self.TelloState.HOVERING

        # start drona
        while not self.tello_service_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().info("Oczekuje na dostepnosc uslugi Tello...")

        self.service_request.cmd = 'takeoff'
        self.tello_service_client.call_async(self.service_request)


    def flying_func(self):            
        self.state = self.TelloState.FLYING
        self.next_state = self.TelloState.FLYING

        if self.action_done:
            self.state = self.TelloState.HOVERING
            self.next_state = self.TelloState.NONE
            self.controller()
        else:
            self.mission_func()
    

    def return_path(self):
        self.get_logger().info(f"POINTS{self.points}")
        self.return_points = list(reversed(self.points))
        to_del = []
        for i in range(len(self.return_points)-2):
            self.return_points[i][3]=self.ori_yaw
            if self.return_points[i][0] ==  self.return_points[i+1][0] == self.return_points[i+2][0]: 
                to_del.append(i+1)
            if self.return_points[i][1] ==  self.return_points[i+1][1] == self.return_points[i+2][1]: 
                    to_del.append(i+1)
        self.return_points[-1][3]=self.ori_yaw
        self.return_points[-2][3]=self.ori_yaw
        for i, j in enumerate(to_del):
            del self.return_points[j-i]
        
        self.get_logger().info(f"RETURN POINTS{self.return_points}")



    def mission_func(self):
        # misja do wykonania
        while not self.tello_service_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().info("Oczekuje na dostepnosc uslugi Tello...")

        self.pid_x.setpoint, self.pid_y.setpoint, self.pid_z.setpoint, self.pid_yaw.setpoint = self.points[self.index]

        dist = np.sqrt((self.pos_x - self.pid_x.setpoint)**2 + (self.pos_y - self.pid_y.setpoint)**2 + (self.pos_z - self.pid_z.setpoint)**2)
        angle_diff = abs(self.pid_yaw.setpoint - self.ori_yaw)

        if dist > 0.05 or angle_diff > 0.018:
            vel_x_glob = self.pid_x(self.pos_x)
            vel_y_glob = self.pid_y(self.pos_y)
            vel_z_glob = self.pid_z(self.pos_z)
            vel_yaw = self.pid_yaw(self.ori_yaw)
            
            vel_x_loc = (vel_x_glob * np.cos(self.ori_yaw)) + (vel_y_glob * np.sin(self.ori_yaw))
            vel_y_loc = (-vel_x_glob * np.sin(self.ori_yaw)) + (vel_y_glob * np.cos(self.ori_yaw))

            self.service_request.cmd = f'rc {vel_x_loc } {vel_y_loc} {vel_z_glob} {vel_yaw}'
            self.tello_service_client.call_async(self.service_request)
            Timer(0.1, self.mission_func).start()
        else:    
            self.get_logger().info(f'Goal position reached')
            self.service_request.cmd = f'rc 0 0 0 0.0'
            self.tello_service_client.call_async(self.service_request)

            if self.index <= len(self.points)-2:
                self.index += 1
            else:
                self.return_path()
                self.action_done = True
                self.index = 0

            self.state = self.TelloState.HOVERING
            self.controller()
            

    def return_function(self):
        
        while not self.tello_service_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().info("Oczekuje na dostepnosc uslugi Tello...")

        self.pid_x.setpoint, self.pid_y.setpoint, self.pid_z.setpoint, self.pid_yaw.setpoint = self.return_points[self.index]
        self.get_logger().info(f"SETPOINT {self.return_points[self.index]}")

        dist = np.sqrt((self.pos_x - self.pid_x.setpoint)**2 + (self.pos_y - self.pid_y.setpoint)**2 + (self.pos_z - self.pid_z.setpoint)**2)
        angle_diff = abs(self.pid_yaw.setpoint - self.ori_yaw)

        if dist > 0.05 or angle_diff > 0.018:
            vel_x_glob = self.pid_x(self.pos_x)
            vel_y_glob = self.pid_y(self.pos_y)
            vel_z_glob = self.pid_z(self.pos_z)
            vel_yaw = self.pid_yaw(self.ori_yaw)
            
            vel_x_loc = (vel_x_glob * np.cos(self.ori_yaw)) + (vel_y_glob * np.sin(self.ori_yaw))
            vel_y_loc = (-vel_x_glob * np.sin(self.ori_yaw)) + (vel_y_glob * np.cos(self.ori_yaw))

            self.service_request.cmd = f'rc {vel_x_loc } {vel_y_loc} {vel_z_glob} {vel_yaw}'
            self.tello_service_client.call_async(self.service_request)
            Timer(0.1, self.mission_func).start()
        else:    
            self.get_logger().info(f'Goal position reached: {self.pos_z}')
            self.service_request.cmd = f'rc 0 0 0 0.0'
            self.tello_service_client.call_async(self.service_request)

            if self.index < len(self.return_points)-1:
                self.index += 1
            else:
                self.return_done = True
                self.index = 0

            self.state = self.TelloState.HOVERING
            self.controller()

    def landing_func(self):
        self.state = self.TelloState.LANDING
        self.next_state = self.TelloState.LANDED

        # ladowanie drona
        while not self.tello_service_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().info("Oczekuje na dostepnosc uslugi Tello...")

        self.service_request.cmd = 'land'
        self.tello_service_client.call_async(self.service_request)


def main(args=None):
    rclpy.init()

    cn = ControllerNode()

    rclpy.spin(cn)
    cn.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
