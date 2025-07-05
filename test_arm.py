from Robotic_Arm.rm_robot_interface import *

robot = RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
handle = robot.rm_create_robot_arm("192.168.1.18", 8080)
print("机械臂ID：", handle.id)

software_info = robot.rm_get_arm_software_info()
if software_info[0] == 0:
    print("\n================== Arm Software Information ==================")
    print(software_info[1])
    print("Arm Model: ", software_info[1]['product_version'])
    print("Algorithm Library Version: ", software_info[1]['algorithm_info']['version'])
    print("Control Layer Software Version: ", software_info[1]['ctrl_info']['version'])
    # print("Dynamics Version: ", software_info[1]['dynamic_info']['model_version'])
    # print("Planning Layer Software Version: ", software_info[1]['plan_info']['version'])
    print("==============================================================\n")
else:
    print("\nFailed to get arm software information, Error code: ", software_info[0], "\n")

print("当前关节状态：", robot.rm_get_current_arm_state())
print("关节温度：", robot.rm_get_current_joint_temperature())

# 关节5步进3°
print(robot.rm_set_joint_step(5, 3, 20, 1))