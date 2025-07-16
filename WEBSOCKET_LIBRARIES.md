# WebSocket库使用说明

## 两个WebSocket库的区别

### 1. `websockets` (复数)
- **用途**: 现代异步WebSocket库
- **特点**: 专为asyncio设计，支持async/await
- **使用场景**: 我们的音频流系统（虽然目前已改为TCP）
- **示例**:
```python
import websockets
import asyncio

async def client():
    async with websockets.connect("ws://localhost:8765") as websocket:
        await websocket.send("Hello!")
        response = await websocket.recv()
```

### 2. `websocket-client` (单数)
- **用途**: 传统同步WebSocket库
- **特点**: 基于回调函数的同步模式
- **使用场景**: 科大讯飞TTS WebAPI
- **示例**:
```python
import websocket

def on_message(ws, message):
    print(f"Received: {message}")

def on_open(ws):
    ws.send("Hello!")

ws = websocket.WebSocketApp("ws://localhost:8765", 
                           on_message=on_message,
                           on_open=on_open)
ws.run_forever()
```

## 项目中的使用情况

### intelligence/speech.py
```python
import websocket  # 使用websocket-client
# 用于科大讯飞TTS WebAPI，同步回调模式
```

### sensors/音频流系统 (已弃用WebSocket)
```python
# 原本计划使用websockets，但已改为TCP音频流
# 当前TCP系统不依赖任何WebSocket库
```

## 兼容性和冲突

**✅ 两个库可以共存**:
- 不同的包名：`websockets` vs `websocket-client`
- 不同的导入名：`import websockets` vs `import websocket`
- 不同的使用模式：异步 vs 同步

**📋 requirements.txt**:
```
websockets        # 异步WebSocket库（备用）
websocket-client  # 同步WebSocket库（TTS必需）
```

## 最佳实践

1. **TTS系统**: 继续使用`websocket-client`，因为：
   - 科大讯飞官方示例使用此库
   - 回调模式适合TTS的流式处理
   - 已有稳定的实现

2. **音频流系统**: 使用TCP原始音频流，因为：
   - 更低的延迟
   - 更简单的协议
   - 不需要WebSocket开销

3. **未来扩展**: 如果需要WebSocket，使用`websockets`，因为：
   - 更现代的异步设计
   - 更好的asyncio集成
   - 更清晰的API

## 依赖管理

```bash
# 安装两个库
pip install websockets websocket-client

# 验证安装
python -c "import websockets; print('websockets OK')"
python -c "import websocket; print('websocket-client OK')"
```

## 总结

- **无冲突**: 两个库可以同时安装和使用
- **明确分工**: websocket-client用于TTS，websockets备用于其他WebSocket需求
- **当前状态**: 音频流系统已使用TCP，不依赖WebSocket