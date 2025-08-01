import rospy
from xf_mic_tts_offline.srv import Play_TTS_srv

from ai_shopping import aishopping
from online_voice.online_voice import online_voice



if __name__ == '__main__':
    #调用扫描货架函数
    product_msg = aishopping.scan_shelves()

    print(product_msg)

    try:
        # 调用语音合成客户端，进行语音合成操作
        vkbot_voice_client = rospy.ServiceProxy('/xf_mic_tts_offline_node/play_txt_wav', Play_TTS_srv)
        # 请求语音合成服务调用，输入具体的语音内容
        response = vkbot_voice_client(product_msg, "xiaoyan")
        rospy.loginfo("vkbot speak ok!!")
    except rospy.ServiceException as e:
        print(f"Service call failed: {e}")
