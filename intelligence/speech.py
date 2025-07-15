# -*- coding:utf-8 -*-
"""
智能语音合成系统 - 基于iFlytek WebAPI
提供清洁的异步接口给Agent使用

重构自原始iFlytek demo，优化为生产级别的模块化设计
"""

import asyncio
import os
import time
import logging
import subprocess
import wave
from typing import Optional, Dict, Any
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

# iFlytek WebAPI dependencies
import websocket
import datetime
import hashlib
import base64
import hmac
import json
from urllib.parse import urlencode
import ssl
from wsgiref.handlers import format_date_time
from datetime import datetime
from time import mktime
import _thread as thread


# 全局变量供WebSocket回调使用
current_output_file = None
synthesis_complete = False
synthesis_success = False


@dataclass
class SpeechConfig:
    """语音合成配置"""
    app_id: str = 'aeb60378'
    api_key: str = 'e248b59b7b21d7291702b7808ba07257'
    api_secret: str = 'MjQ1ZmM3MjkwNmEzZTQyN2ZiNTYxN2Ey'
    voice: str = 'x4_yezi'  # 发音人
    audio_format: str = 'raw'  # 音频格式
    sample_rate: int = 16000  # 采样率
    encoding: str = 'utf8'  # 文本编码
    output_dir: str = 'intelligence'  # 输出目录
    
    # 播放器配置 (按优先级排序)
    audio_players: list = None
    
    def __post_init__(self):
        if self.audio_players is None:
            self.audio_players = ['aplay', 'paplay', 'play', 'mplayer']


class WsParam:
    """WebSocket参数类 - 保持与原iFlytek实现兼容"""
    
    def __init__(self, APPID: str, APIKey: str, APISecret: str, Text: str):
        self.APPID = APPID
        self.APIKey = APIKey
        self.APISecret = APISecret
        self.Text = Text

        # 公共参数(common)
        self.CommonArgs = {"app_id": self.APPID}
        # 业务参数(business)
        self.BusinessArgs = {
            "aue": "raw", 
            "auf": "audio/L16;rate=16000", 
            "vcn": "x4_yezi", 
            "tte": "utf8"
        }
        self.Data = {
            "status": 2, 
            "text": str(base64.b64encode(self.Text.encode('utf-8')), "UTF8")
        }

    def create_url(self) -> str:
        """生成WebSocket连接URL"""
        url = 'wss://tts-api.xfyun.cn/v2/tts'
        # 生成RFC1123格式的时间戳
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))

        # 拼接字符串
        signature_origin = "host: " + "ws-api.xfyun.cn" + "\n"
        signature_origin += "date: " + date + "\n"
        signature_origin += "GET " + "/v2/tts " + "HTTP/1.1"
        
        # 进行hmac-sha256进行加密
        signature_sha = hmac.new(
            self.APISecret.encode('utf-8'), 
            signature_origin.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        signature_sha = base64.b64encode(signature_sha).decode(encoding='utf-8')

        authorization_origin = 'api_key="%s", algorithm="%s", headers="%s", signature="%s"' % (
            self.APIKey, "hmac-sha256", "host date request-line", signature_sha
        )
        authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode(encoding='utf-8')
        
        # 将请求的鉴权参数组合为字典
        v = {
            "authorization": authorization,
            "date": date,
            "host": "ws-api.xfyun.cn"
        }
        # 拼接鉴权参数，生成url
        url = url + '?' + urlencode(v)
        return url


class iFlyTekTTS:
    """iFlytek WebAPI TTS核心实现类"""
    
    def __init__(self, config: SpeechConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
    def _create_ws_params(self, text: str) -> WsParam:
        """创建WebSocket参数"""
        return WsParam(
            self.config.app_id,
            self.config.api_key, 
            self.config.api_secret,
            text
        )
    
    async def synthesize_speech(self, text: str, output_file: str) -> bool:
        """
        异步语音合成
        
        Args:
            text: 要合成的文本
            output_file: 输出PCM文件路径
            
        Returns:
            bool: 是否成功
        """
        try:
            # 清理旧文件
            if os.path.exists(output_file):
                os.remove(output_file)
            
            # 创建WebSocket参数
            ws_param = self._create_ws_params(text)
            
            # 在线程池中运行WebSocket连接 (阻塞操作)
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                None, 
                self._run_websocket_sync, 
                ws_param, 
                output_file
            )
            
            return success and os.path.exists(output_file)
            
        except Exception as e:
            self.logger.error(f"语音合成失败: {e}")
            return False
    
    def _run_websocket_sync(self, ws_param: WsParam, output_file: str) -> bool:
        """同步运行WebSocket连接"""
        try:
            # 设置全局变量供回调使用
            global current_output_file, synthesis_complete, synthesis_success
            current_output_file = output_file
            synthesis_complete = False
            synthesis_success = False
            
            # 配置WebSocket
            websocket.enableTrace(False)
            ws_url = ws_param.create_url()
            ws = websocket.WebSocketApp(
                ws_url,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close
            )
            ws.on_open = lambda ws: self._on_open(ws, ws_param)
            
            # 运行WebSocket
            ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
            
            # 等待合成完成
            timeout = 30
            start_time = time.time()
            while not synthesis_complete and (time.time() - start_time) < timeout:
                time.sleep(0.1)
            
            return synthesis_success
            
        except Exception as e:
            self.logger.error(f"WebSocket连接错误: {e}")
            return False
    
    def _on_message(self, ws, message):
        """WebSocket消息处理"""
        global current_output_file, synthesis_complete, synthesis_success
        
        try:
            message_data = json.loads(message)
            code = message_data.get("code", -1)
            
            if code != 0:
                error_msg = message_data.get("message", "未知错误")
                self.logger.error(f"TTS API错误: {error_msg} (code: {code})")
                synthesis_complete = True
                synthesis_success = False
                ws.close()
                return
            
            # 获取音频数据
            audio_data = message_data.get("data", {})
            audio_base64 = audio_data.get("audio", "")
            status = audio_data.get("status", 0)
            
            if audio_base64:
                audio_bytes = base64.b64decode(audio_base64)
                with open(current_output_file, 'ab') as f:
                    f.write(audio_bytes)
            
            # 检查是否完成
            if status == 2:  # 最后一帧
                synthesis_complete = True
                synthesis_success = True
                ws.close()
                
        except Exception as e:
            self.logger.error(f"处理TTS响应错误: {e}")
            synthesis_complete = True
            synthesis_success = False
            ws.close()
    
    def _on_error(self, ws, error):
        """WebSocket错误处理"""
        global synthesis_complete, synthesis_success
        self.logger.error(f"WebSocket错误: {error}")
        synthesis_complete = True
        synthesis_success = False
    
    def _on_close(self, ws, close_status_code=None, close_msg=None):
        """WebSocket关闭处理"""
        global synthesis_complete
        synthesis_complete = True
    
    def _on_open(self, ws, ws_param):
        """WebSocket开启处理"""
        def run():
            try:
                request_data = {
                    "common": ws_param.CommonArgs,
                    "business": ws_param.BusinessArgs,
                    "data": ws_param.Data,
                }
                ws.send(json.dumps(request_data))
            except Exception as e:
                self.logger.error(f"发送TTS请求错误: {e}")
                ws.close()
        
        thread.start_new_thread(run, ())


class SpeechSystem:
    """
    高级语音合成系统
    为Agent提供简洁的异步语音合成接口
    """
    
    def __init__(self, config: Optional[SpeechConfig] = None):
        self.config = config or SpeechConfig()
        self.tts_engine = iFlyTekTTS(self.config)
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.logger = logging.getLogger(__name__)
        
        # 确保输出目录存在
        os.makedirs(self.config.output_dir, exist_ok=True)
        
        # 音频播放器检测
        self.available_player = self._detect_audio_player()
        if not self.available_player:
            self.logger.warning("未找到可用的音频播放器，语音播放可能失败")
    
    def _detect_audio_player(self) -> Optional[str]:
        """检测可用的音频播放器"""
        for player in self.config.audio_players:
            try:
                result = subprocess.run(
                    ['which', player], 
                    capture_output=True, 
                    text=True, 
                    timeout=2
                )
                if result.returncode == 0:
                    self.logger.info(f"检测到音频播放器: {player}")
                    return player
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue
        return None
    
    async def say(self, text: str, play_audio: bool = True) -> Dict[str, Any]:
        """
        异步语音合成和播放
        
        Args:
            text: 要合成的文本
            play_audio: 是否自动播放音频
            
        Returns:
            Dict: 操作结果
        """
        if not text.strip():
            return {"success": False, "message": "文本为空"}
        
        try:
            # 生成唯一的文件名
            timestamp = int(time.time() * 1000)
            pcm_file = os.path.join(self.config.output_dir, f"tts_{timestamp}.pcm")
            wav_file = os.path.join(self.config.output_dir, f"tts_{timestamp}.wav")
            
            self.logger.info(f"开始合成语音: {text}")
            
            # 异步语音合成
            success = await self.tts_engine.synthesize_speech(text, pcm_file)
            
            if not success:
                return {"success": False, "message": "语音合成失败"}
            
            # 转换为WAV格式
            wav_success = await self._convert_pcm_to_wav(pcm_file, wav_file)
            
            if not wav_success:
                return {"success": False, "message": "音频格式转换失败"}
            
            # 播放音频
            if play_audio and self.available_player:
                play_success = await self._play_audio(wav_file)
                if not play_success:
                    self.logger.warning("音频播放失败，但合成成功")
            
            # 清理临时文件
            self._cleanup_files([pcm_file])
            
            return {
                "success": True,
                "message": "语音合成完成",
                "audio_file": wav_file,
                "text": text
            }
            
        except Exception as e:
            self.logger.error(f"语音合成系统错误: {e}")
            return {"success": False, "message": f"系统错误: {str(e)}"}
    
    async def _convert_pcm_to_wav(self, pcm_file: str, wav_file: str) -> bool:
        """异步PCM转WAV"""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                self.executor,
                self._convert_pcm_to_wav_sync,
                pcm_file,
                wav_file
            )
        except Exception as e:
            self.logger.error(f"PCM转WAV错误: {e}")
            return False
    
    def _convert_pcm_to_wav_sync(self, pcm_file: str, wav_file: str) -> bool:
        """同步PCM转WAV"""
        try:
            with wave.open(wav_file, 'wb') as wav:
                wav.setparams((1, 2, self.config.sample_rate, 0, 'NONE', 'not compressed'))
                with open(pcm_file, 'rb') as pcm:
                    wav.writeframes(pcm.read())
            return True
        except Exception as e:
            self.logger.error(f"PCM转WAV同步错误: {e}")
            return False
    
    async def _play_audio(self, audio_file: str) -> bool:
        """异步音频播放"""
        if not self.available_player:
            return False
        
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                self.executor,
                self._play_audio_sync,
                audio_file
            )
        except Exception as e:
            self.logger.error(f"异步音频播放错误: {e}")
            return False
    
    def _play_audio_sync(self, audio_file: str) -> bool:
        """同步音频播放"""
        try:
            result = subprocess.run(
                [self.available_player, audio_file],
                capture_output=True,
                timeout=30,
                check=False
            )
            return result.returncode == 0
        except Exception as e:
            self.logger.error(f"音频播放错误: {e}")
            return False
    
    def _cleanup_files(self, files: list):
        """清理临时文件"""
        for file_path in files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                self.logger.warning(f"清理文件失败 {file_path}: {e}")
    
    async def test_speech(self, test_text: str = "语音合成系统测试正常") -> Dict[str, Any]:
        """测试语音合成系统"""
        self.logger.info("开始语音系统测试")
        result = await self.say(test_text)
        self.logger.info(f"语音系统测试结果: {result}")
        return result
    
    def __del__(self):
        """清理资源"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)


# 兼容性函数 - 支持原有的文件监控方式 (可选使用)
async def monitor_ai_output_and_speak(
    file_path: str = 'intelligence/ai_output.txt', 
    check_interval: float = 1.0,
    speech_config: Optional[SpeechConfig] = None
):
    """
    持续监控AI输出文件变化并转换为语音 (兼容性函数)
    
    Args:
        file_path: AI输出文件路径
        check_interval: 检查间隔(秒)
        speech_config: 语音配置
    """
    speech_system = SpeechSystem(speech_config)
    logger = logging.getLogger(__name__)
    
    logger.info(f"开始监控AI输出文件: {file_path}")
    
    last_content = ""
    last_modified_time = 0
    
    try:
        while True:
            # 检查文件是否存在
            if not os.path.exists(file_path):
                await asyncio.sleep(check_interval)
                continue
                
            # 检查文件是否被修改
            current_modified_time = os.path.getmtime(file_path)
            if current_modified_time <= last_modified_time:
                await asyncio.sleep(check_interval)
                continue
                
            # 读取新内容
            try:
                with open(file_path, 'r', encoding='utf-8') as file:
                    current_content = file.read().strip()
                
                # 跳过空内容或相同内容
                if not current_content or current_content == last_content:
                    last_modified_time = current_modified_time
                    await asyncio.sleep(check_interval)
                    continue
                    
                logger.info(f"检测到新的AI输出: {current_content}")
                
                # 转换为语音
                result = await speech_system.say(current_content)
                if result["success"]:
                    logger.info("语音播放完成")
                else:
                    logger.error(f"语音播放失败: {result['message']}")
                
                # 更新跟踪变量
                last_content = current_content
                last_modified_time = current_modified_time
                
            except Exception as e:
                logger.error(f"读取AI输出文件错误: {e}")
                await asyncio.sleep(check_interval)
                
    except KeyboardInterrupt:
        logger.info("监控已停止")


# 测试功能
async def test_speech_system():
    """测试语音系统"""
    print("🎤 测试语音合成系统...")
    
    # 使用默认配置
    speech_system = SpeechSystem()
    
    # 测试基本功能
    test_texts = [
        "语音合成系统测试正常",
        "欢迎使用智慧零售机器人助手",
        "语音播放功能工作正常"
    ]
    
    for i, text in enumerate(test_texts, 1):
        print(f"\n测试 {i}/{len(test_texts)}: {text}")
        result = await speech_system.say(text)
        print(f"结果: {result}")
        
        if result["success"]:
            print("✅ 成功")
        else:
            print(f"❌ 失败: {result['message']}")
        
        # 等待一下再继续
        await asyncio.sleep(1)
    
    print("\n🎤 语音系统测试完成")


if __name__ == "__main__":
    # 如果直接运行此文件，则启动测试
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # 测试模式
        asyncio.run(test_speech_system())
    elif len(sys.argv) > 1 and sys.argv[1] == "monitor":
        # 兼容性监控模式
        asyncio.run(monitor_ai_output_and_speak())
    else:
        print("智能语音合成系统")
        print("使用方法:")
        print("  python speech.py test     - 测试语音合成")
        print("  python speech.py monitor  - 监控AI输出文件")
        print("  或在代码中导入SpeechSystem类使用")