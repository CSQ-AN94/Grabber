# controllers/rail_controller.py - Implementation with Config Support

import time
from utils.config import RailConfig

class RailController:
    def __init__(self, rail_config: RailConfig):
        self.home_position = rail_config.home_position
        self.scan_start = rail_config.scan_start
        self.scan_end = rail_config.scan_end
        self.scan_speed = rail_config.scan_speed
        self._is_moving = False
        self._position = self.home_position

    def move_to(self, position, wait=True):
        self._is_moving = True
        # 模拟移动耗时，速度由scan_speed决定
        travel_time = abs(position - self._position) / max(self.scan_speed, 1e-3)
        if wait:
            time.sleep(travel_time)
            self._is_moving = False
        self._position = position

    def is_moving(self):
        return self._is_moving

    def get_current_position(self):
        return self._position

    def disconnect(self):
        pass