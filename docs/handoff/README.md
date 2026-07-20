# Handoff 文档

这是仓库里**抓水瓶技术验证路线**（双臂 SDK，`bottle_grasp/`）的交接资料，
跟仓库里另一条"单臂+UGV直接识别抓取"（`direct_grab.py`）路线互不依赖——
两条路线的关系见根目录 [README.md](../../README.md) 顶部说明。**要具体的
启动命令/怎么跑，先看 [bottle_grasp/README.md](../../bottle_grasp/README.md)**；
这个子文件夹是更深入的交接资料，专门用来开新窗口/新会话继续这段工作，不放进
`docs/` 根目录、不改动大项目里其它文档的组织方式。四份文档：

1. **[demos_overview.md](demos_overview.md)** — 项目里所有能跑的 demo/脚本，
   每个是干什么的、怎么运行。想找"这个功能有没有现成脚本"先看这份。
2. **[obstacle_avoidance.md](obstacle_avoidance.md)** — 机械臂避障/运动规划这个
   领域是怎么回事，以及本项目的 MoveIt、后验碰撞复核、电子围栏与自动重规划
   怎么协作（含 2026-07-17 旧 selftest 误诊的复盘）。
3. **[bottle_grasp_status.md](bottle_grasp_status.md)** — 抓水瓶demo的完整现状：
   架构、三套运行流程、已知问题、下一步优先级、git提交记录。想继续写代码，
   先看这份把上下文接上。
4. **[product_yolo_training.md](product_yolo_training.md)** — 2026-07-20新增：
   给 `--target-product` 用的多类别商品识别模型，从数据采集/人工打框/训练/
   验证到接回 `config.yaml` 的完整流程，只是脚本和文档，还没有实际采集/
   训练过。

写于 2026-07-16，dual-arm-sdk 分支，git HEAD 在 `5abb201` 之后。
