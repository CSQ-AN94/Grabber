1. 拉取仓库到本地
2. 根据具体IP和端口修改你的docker-compose.yml中的http_proxy和https_proxy
3. 一键构建镜像 `docker compose build`
4. 一键运行镜像 `docker compose run --rm grabber_dev bash`
5. 验证
    - `nvidia-smi` 验证显卡
    - `python3 test_arm.py` 验证机械臂连接