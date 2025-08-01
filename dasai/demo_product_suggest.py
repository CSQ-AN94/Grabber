import os
import requests
import json
import threading
import sys

import rospy
from xf_mic_tts_offline.srv import Play_TTS_srv

from ai_shopping import aishopping
#from online_voice.online_voice import audio

def vkbot_speak(text):
    try:
        # 调用语音合成客户端，进行语音合成操作
        vkbot_voice_client = rospy.ServiceProxy('/xf_mic_tts_offline_node/play_txt_wav', Play_TTS_srv)

        # 请求语音合成服务调用，输入具体的语音内容
        response = vkbot_voice_client(text, "xiaoyan")
        rospy.loginfo("vkbot speak ok!!")
        return response.result
    except rospy.ServiceException as e:
        print(f"Service call failed: {e}")


if __name__ == '__main__':
    rospy.init_node('online_voice', anonymous=True)
    aishopping.update_product_msg()

    while not rospy.is_shutdown():
        question = input('请输入您的问题(输入quit退出): ')

        if question == 'quit':
            sys.exit(0)

        answer = aishopping.query(question)
        print(f'chat: {answer.chat}, product_index: {answer.product_index}, product_name: {answer.product_name}')
        
        #机械臂执行任务
        aishopping.execute(answer,0)

        if answer.chat != '':
            vkbot_speak(answer.chat)
