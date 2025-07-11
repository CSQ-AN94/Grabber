import google.generativeai as genai
import json

class LLMParser:
    """
    封装与Google Gemini模型的交互，用于解析用户指令。
    """
    def __init__(self, llm_config):
        """
        初始化时，配置Gemini API。
        """
        genai.configure(api_key=llm_config.gemini_api_key)
        self.model = genai.GenerativeModel('gemini-pro')
        # 这是我们为机器人设计的“系统提示”，用于指导LLM的行为
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self):
        # 通过精心设计的Prompt，我们可以让LLM稳定地输出我们想要的JSON格式
        return """
        You are the command center for a retail robot. Your task is to understand the user's spoken command and convert it into a structured JSON object.

        The JSON object must have an "action" field. Valid actions are:
        - "fetch": When the user wants to get a specific item.
        - "recommend": When the user is asking for a suggestion.
        - "tally": When the user wants to know what's in the settlement area.
        - "greet": For simple greetings or chitchat.

        The JSON object can also have these optional fields:
        - "item_name": The specific name of the product (e.g., "可口可乐", "苹果").
        - "category": The category of the product (e.g., "饮料", "水果").
        - "location_hint": Any location-based words used (e.g., "左边", "上面").
        
        Analyze the user's text and respond ONLY with the JSON object.

        Here are some examples:
        User: "你好啊"
        {"action": "greet"}
        
        User: "帮我拿一瓶可乐"
        {"action": "fetch", "item_name": "可口可乐"}
        
        User: "我想喝点东西"
        {"action": "recommend", "category": "饮料"}
        
        User: "左边那个红色的苹果"
        {"action": "fetch", "item_name": "苹果", "location_hint": "左边"}
        
        User: "看看我买了些什么"
        {"action": "tally"}
        """

    def parse_user_command(self, user_text: str) -> dict:
        """
        接收用户语音识别后的文本，返回结构化的JSON指令。
        """
        print(f"[LLM] Parsing text: '{user_text}'")
        # 将系统提示和用户输入组合成完整的请求
        full_prompt = self.system_prompt + f"\nUser: \"{user_text}\""
        
        try:
            response = self.model.generate_content(full_prompt)
            # Gemini的响应可能包含额外字符，我们需要稳健地提取JSON
            json_text = response.text.strip().replace("```json", "").replace("```", "")
            parsed_json = json.loads(json_text)
            print(f"[LLM] Parsed command: {parsed_json}")
            return parsed_json
        except Exception as e:
            print(f"[LLM] ERROR parsing command: {e}")
            # 如果解析失败，返回一个表示未知操作的字典
            return {"action": "unknown", "error": str(e)}
            
    # (可以保留 get_text_response 用于其他通用聊天)
    def get_text_response(self, prompt:str) -> str:
        # ...
        pass