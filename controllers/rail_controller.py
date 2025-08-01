# controllers/rail_controller.py - Implementation with Config Support

import time

class RailController:
    def __init__(self):
        self._is_moving = False
        self._position = 0 # 米为单位，增大时对应着base frame在y轴正方向移动

    def move_to(self, position):
        self._is_moving = True
        time.sleep(2)
        self._position = position

    def is_moving(self):
        return self._is_moving

    def get_current_position(self):
        return self._position