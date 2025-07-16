# 端口选择说明

## 端口变更原因

原始的8888和8889端口可能与系统服务冲突：
- 8888：常用于开发服务器（如Jupyter、各种代理）
- 8889：可能被其他服务占用

## 新端口选择

**新端口：9888（麦克风）和9889（扬声器）**

### 选择理由

1. **9000+端口段**：通常用于用户应用，冲突概率低
2. **连续端口**：便于管理和防火墙配置
3. **易于记忆**：与原端口保持相似性

### 端口冲突检查

如果仍然遇到端口冲突，可以使用以下命令检查：

```bash
# 检查端口是否被占用
sudo netstat -tlnp | grep :9888
sudo netstat -tlnp | grep :9889

# 或使用ss命令
ss -tlnp | grep :9888
ss -tlnp | grep :9889
```

### 自定义端口

如果需要使用其他端口，可以通过命令行参数指定：

```bash
# 使用自定义端口
python sensors/audio_server_tcp.py --mic-port 10888 --speaker-port 10889
python sensors/audio_client_tcp.py --host 192.168.3.1 --mic-port 10888 --speaker-port 10889
```

## 推荐端口范围

- **9000-9999**：用户应用端口，冲突概率低
- **10000-19999**：用户应用端口，冲突概率更低
- **避免1024以下**：需要root权限
- **避免3000-8999**：常被各种服务占用

## 防火墙配置

如果使用防火墙，需要开放相应端口：

```bash
# Ubuntu/Debian (ufw)
sudo ufw allow 9888/tcp
sudo ufw allow 9889/tcp

# CentOS/RHEL (firewalld)
sudo firewall-cmd --add-port=9888/tcp --permanent
sudo firewall-cmd --add-port=9889/tcp --permanent
sudo firewall-cmd --reload
```

## 网络测试

使用更新后的测试脚本验证端口可用性：

```bash
python sensors/test_tcp_audio.py --host 192.168.3.1 --mic-port 9888 --speaker-port 9889
```

测试将检查：
- 端口9888（麦克风）连通性
- 端口9889（扬声器）连通性
- 基础网络连通性（端口22、80等）