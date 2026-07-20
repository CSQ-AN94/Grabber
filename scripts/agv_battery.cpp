#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <mutex>
#include <string>

#include "woosh_robot.h"

namespace {

const char* ChargeStateName(woosh::robot::Battery::ChargeState state) {
  switch (state) {
    case woosh::robot::Battery::kNot:
      return "未充电";
    case woosh::robot::Battery::kManual:
      return "手动充电中";
    case woosh::robot::Battery::kAuto:
      return "自动充电中";
    default:
      return "未知";
  }
}

}  // namespace

int main() {
  woosh::CommuSetting setting;
  setting.addr = "169.254.128.2";
  setting.port = 5410;
  setting.identity = "agv-battery-query";
  setting.log_call_fun = [](const std::string&) {};
  setting.print_pack_call_fun = [](const std::string&) {};
  setting.connect_status_call_fun = [](const bool&) {};

  auto robot = woosh::Factory::newRobotInterface(setting);
  if (!robot->run()) {
    std::fprintf(stderr, "无法连接底盘电池接口。\n");
    return 1;
  }

  std::mutex mutex;
  std::condition_variable cv;
  bool done = false;
  bool succeeded = false;

  woosh::robot::Battery request;
  if (!robot->robotBatteryReq(
          request,
          [&](woosh::RobotBattery battery, woosh::RspOK ok,
              woosh::RspMsg message) {
            if (!ok) {
              std::fprintf(stderr, "查询电池失败：%s\n", message.c_str());
            } else {
              std::printf("电量：%u%%\n", battery.power());
              std::printf("充电状态：%s\n",
                          ChargeStateName(battery.charge_state()));
              if (battery.health() > 0) {
                std::printf("健康度：%u%%\n", battery.health());
              } else {
                std::printf("健康度：设备未报告\n");
              }
              std::printf("充电循环：%u 次\n", battery.charge_cycle());
              std::printf("额定循环寿命：%u 次\n", battery.battery_cycle());
              std::printf("最高温度：%d°C\n", battery.temp_max());
              succeeded = true;
            }
            {
              std::lock_guard<std::mutex> lock(mutex);
              done = true;
            }
            cv.notify_one();
          },
          woosh::PPLB, woosh::PPLB)) {
    std::fprintf(stderr, "电池查询请求发送失败。\n");
    return 2;
  }

  std::unique_lock<std::mutex> lock(mutex);
  if (!cv.wait_for(lock, std::chrono::seconds(8), [&] { return done; })) {
    std::fprintf(stderr, "电池查询超时。\n");
    return 3;
  }
  return succeeded ? 0 : 4;
}
