# intelligence/gemini_agent.py

import asyncio
import logging
from typing import Callable, Dict, Any, Optional
from dataclasses import dataclass

from google import genai
from google.genai import types

from utils.config import AgentConfig, LLMConfig
from sensors.microphone_thread import MicrophoneThread


@dataclass
class RobotCommand:
    """Represents a structured command from Gemini Live API"""
    action: str
    parameters: Dict[str, Any]
    response_text: str
    confidence: float = 1.0




class GeminiAgent:
    """
    Real-time voice interaction agent using Google Gemini Live API.
    
    Uses simplified network audio input for maximum stability and containerization compatibility.
    Focuses on competition tasks: inventory scan, recommendation, item selection, checkout.
    """
    
    def __init__(self, llm_config: LLMConfig, agent_config: AgentConfig, tool_registry=None):
        self.llm_config = llm_config
        self.agent_config = agent_config
        self.tool_registry = tool_registry  # Tool registry
        
        # Initialize client - use gemini-2.0-flash-live-001 for stability  
        self.client = genai.Client(api_key=llm_config.gemini_api_key)
        self.model = "gemini-2.0-flash-live-001"  # Semi-cascade model, supports tool calling, more stable
        
        # Simplified audio input using MicrophoneThread
        self.microphone = MicrophoneThread(
            port=8888,  # Fixed port for network audio
            sample_rate=agent_config.audio_sample_rate,  # 16000Hz for Gemini
            chunk_size=agent_config.audio_chunk_size
        )
        
        # Session management
        self.session = None
        self.is_running = False
        self.command_callback: Optional[Callable[[RobotCommand], None]] = None
        
        # Competition context - item prices for competition
        self.item_prices = {
            "牙膏": 7, "雀巢咖啡": 4, "洗发水": 12, "可口可乐": 3.5, "百事可乐": 3.5,
            "橘子": 1.5, "苹果": 2, "纯牛奶": 2.5, "农夫山泉矿泉水": 2.5, "维达纸巾": 4,
            "薯片": 3.5, "洽洽瓜子": 5, "奥利奥饼干": 6, "娃哈哈 AD钙奶": 5.5,
            "营养快线": 6, "红牛": 6
        }
        
        # Logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
    
    def _create_session_config(self) -> Dict:
        """Create configuration for Gemini Live API session - simplified"""
        config = {
            "response_modalities": ["TEXT"],
            "system_instruction": "You are an intelligent retail robot assistant participating in the China Robot and AI Competition. Please respond in Chinese in a friendly manner."
        }
        
        # Add tool definitions
        if self.tool_registry:
            config["tools"] = self.tool_registry.get_tool_definitions()
            
        return config
    
    async def start_interactive_session(self, command_callback: Callable[[RobotCommand], None]):
        """
        Start interactive session with Gemini Live API - pure audio in, JSON text out
        
        Args:
            command_callback: Function to call when receiving structured commands
        """
        if self.is_running:
            self.logger.warning("Session already running")
            return
        
        self.command_callback = command_callback
        self.is_running = True
        
        try:
            # Start microphone thread for network audio input
            await self.microphone.start_server()
            
            # Create Live API session with proper config
            config_dict = self._create_session_config()
            config = types.LiveConnectConfig(**config_dict)
            async with self.client.aio.live.connect(model=self.model, config=config) as session:
                self.session = session
                self.logger.info("Gemini Live API session established")
                self.logger.info(f"等待网络音频输入，端口: {self.microphone.port}")
                
                # Run concurrent tasks
                await asyncio.gather(
                    self._audio_input_loop(),
                    self._response_processing_loop(),
                    return_exceptions=True
                )
                
        except Exception as e:
            self.logger.error(f"Session error: {e}")
            raise
        finally:
            await self.stop_session()
    
    async def _audio_input_loop(self):
        """Continuously send audio input to Gemini Live API"""
        while self.is_running and self.session:
            audio_chunk = await self.microphone.get_audio_chunk()
            if audio_chunk:
                try:
                    # Validate audio data size - Gemini has requirements for audio chunk size
                    if len(audio_chunk) < 64:  # Increase minimum audio chunk size to avoid 1007 errors
                        continue
                    
                    # Ensure audio data is even bytes (16-bit PCM requirement)
                    if len(audio_chunk) % 2 != 0:
                        audio_chunk = audio_chunk[:-1]  # Remove last byte
                    
                    # Validate audio data is not empty and reasonable size
                    if len(audio_chunk) == 0 or len(audio_chunk) > 8192:  # Max 8KB to avoid oversized chunks
                        continue
                    
                    await self.session.send_realtime_input(
                        audio=types.Blob(
                            data=audio_chunk,
                            mime_type="audio/pcm;rate=16000"  # Fix 1007 error: must include sample rate
                        )
                    )
                    
                except Exception as e:
                    self.logger.error(f"Audio sending error: {e}")
                    # If it's a 1007 error, audio format is problematic, stop session
                    if "1007" in str(e):
                        self.logger.error("Detected 1007 error - audio format issue:")
                        self.logger.error(f"  - Audio chunk size: {len(audio_chunk) if 'audio_chunk' in locals() else 'N/A'}")
                        self.logger.error(f"  - MIME type: audio/pcm;rate=16000")
                        self.logger.error("  - Stopping session to avoid continuous errors")
                        self.is_running = False
                        break
                    # Continue trying for other errors
                    continue
            
            await asyncio.sleep(0.01)  # Small delay to prevent overwhelming the API
    
    async def _response_processing_loop(self):
        """Process JSON text responses from Gemini Live API"""
        try:
            async for response in self.session.receive():
                await self._handle_response(response)
        except Exception as e:
            self.logger.error(f"Error processing responses: {e}")
    
    async def _handle_response(self, response):
        """Handle individual response from Gemini Live API - text and function calls"""
        try:
            # Handle text responses
            if hasattr(response, 'text') and response.text:
                text_response = response.text.strip()
                self.logger.info(f"Received text: {text_response}")
                
                # For direct text responses (non-function calls)
                command = RobotCommand(
                    action="speak",
                    parameters={"text": text_response},
                    response_text=text_response,
                    confidence=1.0
                )
                
                if self.command_callback:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self.command_callback, command)
            
            # Handle server content and function calls
            if hasattr(response, 'server_content') and response.server_content:
                if hasattr(response.server_content, 'model_turn') and response.server_content.model_turn:
                    if hasattr(response.server_content.model_turn, 'parts'):
                        for part in response.server_content.model_turn.parts:
                            if hasattr(part, 'function_call'):
                                await self._handle_tool_call(part)
                
        except Exception as e:
            self.logger.error(f"Error handling response: {e}")
    
    async def _handle_tool_call(self, part):
        """Handle function calls from Gemini Live API"""
        try:
            function_call = part.function_call
            function_name = function_call.name
            parameters = dict(function_call.args) if hasattr(function_call, 'args') else {}
            
            self.logger.info(f"Tool call: {function_name} with params: {parameters}")
            
            # Execute the tool function
            if self.tool_registry:
                result = await self.tool_registry.execute_tool(function_name, parameters)
                
                # Send result back to Gemini using client_content
                await self.session.send_client_content(
                    turns=[{
                        "role": "function",
                        "parts": [{
                            "function_response": {
                                "name": function_name,
                                "response": result
                            }
                        }]
                    }],
                    turn_complete=True
                )
                
                # Create command for main application
                command = RobotCommand(
                    action=function_name,
                    parameters=parameters,
                    response_text=result.get("message", "Operation completed"),
                    confidence=1.0 if result.get("success") else 0.5
                )
                
                # Send to main application
                if self.command_callback:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self.command_callback, command)
            else:
                # No tool registry - send error response
                await self.session.send_client_content(
                    turns=[{
                        "role": "function", 
                        "parts": [{
                            "function_response": {
                                "name": function_name,
                                "response": {"success": False, "message": "Tool registry not initialized"}
                            }
                        }]
                    }],
                    turn_complete=True
                )
                
        except Exception as e:
            self.logger.error(f"Error handling tool call: {e}")
            
            # Send error response back to Gemini
            try:
                await self.session.send_client_content(
                    turns=[{
                        "role": "function",
                        "parts": [{
                            "function_response": {
                                "name": function_name if 'function_name' in locals() else "unknown", 
                                "response": {"success": False, "message": f"Tool execution error: {str(e)}"}
                            }
                        }]
                    }],
                    turn_complete=True
                )
            except:
                pass
    
    async def stop_session(self):
        """Stop the interactive session"""
        self.is_running = False
        await self.microphone.stop_server()
        if self.session:
            self.session = None
        self.logger.info("Gemini Agent session stopped")
    
    def update_context(self, context: str):
        """Update agent context (e.g., current inventory, position, etc.)"""
        # This could be used to provide context about robot state
        # For now, we keep the agent stateless as designed
        self.logger.info(f"Context update: {context}")


# Utility function for testing
async def test_gemini_agent():
    """Test function for Gemini Agent"""
    from utils.config import load_config
    
    def command_handler(command: RobotCommand):
        print(f"\n=== Received Command ===")
        print(f"Action: {command.action}")
        print(f"Parameters: {command.parameters}")
        print(f"Response text: {command.response_text}")
        print(f"Confidence: {command.confidence}")
        print("=======================\n")
    
    config = load_config()
    agent = GeminiAgent(config.llm, config.agent)
    
    try:
        print("Starting Gemini Agent test...")
        print("Please speak to test voice recognition and command parsing...")
        await agent.start_interactive_session(command_handler)
    except KeyboardInterrupt:
        print("Stopping test...")
        await agent.stop_session()


if __name__ == "__main__":
    # Test the agent
    asyncio.run(test_gemini_agent())