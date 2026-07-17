# Handoff 文档

这个子文件夹是独立的交接资料，专门用来开新窗口/新会话继续这段工作，不放进
`docs/` 根目录、不改动大项目里其它文档的组织方式。三份文档：

1. **[demos_overview.md](demos_overview.md)** — 项目里所有能跑的 demo/脚本，
   每个是干什么的、怎么运行。想找"这个功能有没有现成脚本"先看这份。
2. **[obstacle_avoidance.md](obstacle_avoidance.md)** — 机械臂避障/运动规划这个
   领域是怎么回事，以及本项目的 MoveIt、后验碰撞复核、电子围栏与自动重规划
   怎么协作（含 2026-07-17 旧 selftest 误诊的复盘）。
3. **[bottle_grasp_status.md](bottle_grasp_status.md)** — 抓水瓶demo的完整现状：
   架构、三套运行流程、已知问题、下一步优先级、git提交记录。想继续写代码，
   先看这份把上下文接上。

写于 2026-07-16，dual-arm-sdk 分支，git HEAD 在 `5abb201` 之后。
