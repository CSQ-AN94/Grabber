#!/bin/zsh
# 在Mac本地Terminal中运行；机器人端不创建任何GUI窗口。

ssh -t rm@192.168.3.68 \
  'cd /home/rm/Grabber && python3 scripts/collect_calibration_poses.py 169.254.128.18 \
    --snapshot-url http://127.0.0.1:8875/snapshot.jpg \
    --board-type charuco --square 0.030 --marker 0.0225 \
    --squares-x 12 --squares-y 9 \
    --out left_wrist_poses.json --target 13'

echo
read "REPLY?采集程序已结束，按 Enter 关闭窗口。"
