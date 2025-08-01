#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GLM Agent - 基于智谱AI GLM-4V-Flash的简洁文本代理
专注于text in/text out基本功能，使用免费的glm-4v-flash模型
"""

import asyncio
import logging
from typing import Dict, Any

import zhipuai
from zhipuai import ZhipuAI

from utils.config import load_config

logger = logging.getLogger(__name__)


class GLMAgent:
    """GLM代理 - 纯文本输入输出"""
    
    def __init__(self, config_path: str = "config.yaml"):
        """初始化GLM客户端"""
        self.client = None
        self.model_name = "glm-4v-flash"  # 使用免费的flash模型
        
        try:
            # 加载配置
            config = load_config(config_path)
            api_key = getattr(config.llm, 'zhipu_api_key', None)
            
            if not api_key or api_key == "your_zhipu_api_key":
                raise ValueError("请在config.yaml中设置有效的zhipu_api_key")
            
            # 初始化客户端
            self.client = ZhipuAI(api_key=api_key)
            
            logger.info(f"GLM客户端初始化成功，模型: {self.model_name}")
            
        except Exception as e:
            logger.error(f"GLM客户端初始化失败: {e}")
            raise
    
    async def process_text(self, user_input: str) -> Dict[str, Any]:
        """处理文本输入，返回AI响应"""
        
        if not self.client:
            return {
                "success": False,
                "error": "GLM客户端未初始化",
                "text": ""
            }
        
        if not user_input.strip():
            return {
                "success": False,
                "error": "输入文本为空",
                "text": ""
            }
        
        try:
            # 调用API
            logger.debug(f"发送请求到GLM: {user_input[:50]}...")
            response = await self._call_glm_api(user_input.strip())
            
            if response and response.choices and len(response.choices) > 0:
                result_text = response.choices[0].message.content.strip()
                logger.info(f"收到GLM响应: {result_text[:100]}...")
                
                return {
                    "success": True,
                    "text": result_text,
                    "model": self.model_name,
                    "usage": {
                        "total_tokens": response.usage.total_tokens if response.usage else 0,
                        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                        "completion_tokens": response.usage.completion_tokens if response.usage else 0
                    }
                }
            else:
                return {
                    "success": False,
                    "error": "API返回空响应",
                    "text": ""
                }
                
        except Exception as e:
            logger.error(f"处理文本时发生错误: {e}")
            return {
                "success": False,
                "error": str(e),
                "text": ""
            }
    
    async def _call_glm_api(self, user_input: str, max_retries: int = 3):
        """调用GLM API，带重试机制"""
        
        for attempt in range(max_retries):
            try:
                # 准备消息
                messages = [
                    {
                        "role": "system", 
                        "content": "你是一个智能零售机器人助手。请用简洁、友好的方式回答用户问题。"
                    },
                    {
                        "role": "user", 
                        "content": user_input
                    }
                ]
                
                # 使用executor包装同步API为异步
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.client.chat.completions.create(
                        model=self.model_name,
                        messages=messages,
                        temperature=0.8,
                        top_p=0.6,
                        max_tokens=1024
                    )
                )
                return response
                
            except zhipuai.APIStatusError as e:
                logger.warning(f"GLM API状态错误 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.info(f"等待 {wait_time} 秒后重试...")
                    await asyncio.sleep(wait_time)
                else:
                    raise e
                    
            except zhipuai.APITimeoutError as e:
                logger.warning(f"GLM API超时 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.info(f"等待 {wait_time} 秒后重试...")
                    await asyncio.sleep(wait_time)
                else:
                    raise e
                    
            except Exception as e:
                logger.warning(f"GLM API调用失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.info(f"等待 {wait_time} 秒后重试...")
                    await asyncio.sleep(wait_time)
                else:
                    raise e
    
    def is_ready(self) -> bool:
        """检查代理是否就绪"""
        return self.client is not None


async def main():
    """简单的测试函数"""
    print("=== GLM Agent 简单测试 ===")
    
    try:
        # 初始化代理
        agent = GLMAgent()
        
        if not agent.is_ready():
            print("❌ 代理初始化失败")
            return
        
        print("✅ 代理初始化成功")
        
        # 交互式测试
        while True:
            user_input = input("\n请输入文本 (输入 'quit' 退出): ").strip()
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                break
            
            if not user_input:
                continue
            
            print("🤖 处理中...")
            result = await agent.process_text(user_input)
            
            if result["success"]:
                print(f"✅ AI回复: {result['text']}")
                if 'usage' in result:
                    print(f"   Token使用: {result['usage']['total_tokens']}")
            else:
                print(f"❌ 错误: {result['error']}")
    
    except KeyboardInterrupt:
        print("\n👋 用户中断，退出")
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 设置日志级别
    logging.basicConfig(level=logging.INFO)
    
    # 运行测试
    asyncio.run(main())