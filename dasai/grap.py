import requests
import json
import time
#from online_voice.online_voice import audio
from collections import OrderedDict
import roslib
import rospy
import actionlib
#from arm.robotic_arm import arm_ins
#from voice.voice import voice
# 加载语音识别需要的模块文件
from xf_mic_asr_offline.srv import Get_Offline_Result_srv, Get_Offline_Result_srvRequest
from xf_mic_asr_offline.srv import Set_Major_Mic_srv
from xf_mic_asr_offline.srv import Get_Major_Mic_srv
from xf_mic_asr_offline.msg import Pcm_Msg
from xf_mic_asr_offline.msg import VKA

# 加载语音合成需要的模块文件
from xf_mic_tts_offline.srv import Play_TTS_srv, Play_TTS_srvRequest
import re




#去掉字符串的数字
def remove_numbers(string):
    return ''.join([char for char in string if not char.isdigit()])


 
def remove_digits(s):
    return re.sub(r'\d+', '', s)



#def extract_numbers(s):
#    return re.findall(r'\d+', s)


#机械臂是否自带带视觉
Arm_vision=0



#放置初始位置 共用
place_position_common=[0.032533999532461166, -0.031119000166654587, 0.3789600133895874, -0.05900000035762787, 1.5099999904632568, 2.1670000553131104]
#图片  
img_place_position_1=[-0.01246699970215559, -0.002495999913662672, 0.34981998801231384, -2.996999979019165, 1.2100000381469727, 0.11500000208616257] 
img_place_position_2=[-0.0994969978928566, 0.1497890055179596, 0.46837499737739563, 1.4190000295639038, 1.5549999475479126, -2.7060000896453857]
img_place_position_3=[-0.3206779956817627, 0.3727239966392517, 0.10629499703645706, -2.055999994277954, 1.5440000295639038, 0.26499998569488525]
img_place_position_3_1=[-0.3206779956817627, 0.3727239966392517, 0.00629499703645706, -2.055999994277954, 1.5440000295639038, 0.26499998569488525]
img_place_position_4=[-0.3206779956817627, 0.3727239966392517, -0.018788000732660294, -2.055999994277954, 1.5440000295639038, 0.26499998569488525]
##########打开夹爪
#-0.3080810010433197, 0.36062899231910706, -0.008528999984264374, -1.9600000381469727, 1.5390000343322754, 0.37700000405311584
img_place_position_4_1=[-0.3206779956817627, 0.3727239966392517, -0.006788000732660294, -1.9600000381469727, 1.5390000343322754, 0.37700000405311584]
img_place_position_5=[-0.2545570135116577, 0.30546098947525024, -0.004788000732660294, -2.055999994277954, 1.5440000295639038, 0.26499998569488525]
img_place_position_6=[-0.2545570135116577, 0.30546098947525024, 0.050788000732660294, -2.055999994277954, 1.5440000295639038, 0.26499998569488525]
img_place_position_7=[0.07152500003576279, -0.0029060000088065863, 0.34343698620796204, 2.6610000133514404, 1.5529999732971191, -0.4950000047683716]

#商品推荐
  #第一个放置位置
product_place_position0_1=[-93.9749984741211, 99.42400360107422, -117.42400360107422, 12.595000267028809, 90.47899627685547, 90.14900207519531]
product_place_position0_2=[-0.2239460051059723, 0.3475880026817322, 0.07762400060892105, 0.04100000113248825, 1.4980000257492065, 2.128000020980835]
product_place_position0_3=[-0.2246679961681366, 0.35541200637817383, -0.018058999821543694, -0.04399999976158142, 1.559999942779541, 2.0490000247955322]
#######打开夹爪
product_place_position0_3_1=[-0.2246679961681366, 0.35541200637817383, -0.008058999821543694, -0.04399999976158142, 1.559999942779541, 2.0490000247955322] 
product_place_position0_4=[-0.157492995262146, 0.2366109937429428, 0.0118699999675154686, -1.6430000066757202, 1.5140000581741333, 0.4399999976158142]
product_place_position0_5=[-0.07112699747085571, 0.2799609899520874, 0.0028520000632852316, -1.1579999923706055, 1.5360000133514404, 0.6050000190734863]
product_place_position0_6=[-0.1042179986834526, 0.37959301471710205, 0.29085901379585266, 0.453000009059906, 1.5190000534057617, 2.184999942779541]
product_place_position0_7=[0.07152500003576279, -0.0029060000088065863, 0.34343698620796204, 2.6610000133514404, 1.5529999732971191, -0.4950000047683716]

  #第二个放置位置
product_place_position1_1=[0.014275000430643559, -0.005394999869167805, 0.39501500129699707, 2.634000062942505, 1.5369999408721924, -1.6779999732971191]
product_place_position1_2=[-0.1272359937429428, 0.36227700114250183, 0.09684299677610397, 1.4459999799728394, 1.5360000133514404, -2.868000030517578]
product_place_position1_3=[-0.11847899854183197, 0.34384000301361084, -0.020474999263882637, 2.5829999446868896, 1.5110000371932983, -1.7259999513626099]
########打开夹爪
product_place_position1_4=[-0.0982469990849495, 0.2823919951915741, 0.019767999596893787, 1.3899999856948853, 1.4980000257492065, -2.943000078201294]
product_place_position1_5=[0.0012679999927058816, 0.3190779983997345, 0.049150998651981354, -0.04800000041723251, 1.4630000591278076, 1.472000002861023]
product_place_position1_6=[-0.0031250000465661287, 0.343766987323761, 0.2638019919395447, -3.0460000038146973, 1.4869999885559082, -1.496999979019165]
product_place_position1_7=[0.07152500003576279, -0.0029060000088065863, 0.34343698620796204, 2.6610000133514404, 1.5529999732971191, -0.4950000047683716]

  #第三个放置位置
product_place_position2_1=[0.004838000051677227, -0.07169599831104279, 0.349481999874115, 0.26600000262260437, 1.5429999828338623, 1.9240000247955322]
product_place_position2_2=[-0.05351199954748154, 0.3240010142326355, 0.13723699748516083, -2.194000005722046, 1.5499999523162842, -0.5109999775886536]
product_place_position2_3=[-0.05351199954748154, 0.3240010142326355, -0.019788000732660294, -2.194000005722046, 1.5499999523162842, -0.5109999775886536]
#########打开夹爪
product_place_position2_4=[-0.057764001190662384, 0.3060060143470764, 0.07526000118255615, -0.20499999821186066, 1.534999966621399, 1.534999966621399]
product_place_position2_5=[-0.058736998587846756, 0.3082909882068634, 0.1326549974679947, -0.04699999839067459, 1.472000002861023, 1.6959999799728394]
product_place_position2_6=[-0.06074900180101395, 0.3187269866466522, 0.3036780059337616, 0.017999999225139618, 0.9459999799728394, 1.7589999437332153]
product_place_position2_7=[-0.21832400560379028, 0.15085899829864502, 0.40344300866127014, 1.8910000324249268, 1.5329999923706055, -1.8589999675750732]
product_place_position2_8=[0.07152500003576279, -0.0029060000088065863, 0.34343698620796204, 2.6610000133514404, 1.5529999732971191, -0.4950000047683716]

#放置最终位置 共用
position=[0.07152500003576279, -0.0029060000088065863, 0.34343698620796204, 2.6610000133514404, 1.5529999732971191, -0.4950000047683716]
initposition=[-2.2279999256134033, 99.43399810791016, -123.93099975585938, 23.847999572753906, 91.34300231933594, 90.1780014038086]








flagflag=0


pose_left=590
pose_middle=300
pose_right=1
place=0
pick_off_dict={
 'first' : [] ,
 'second': []
}

#初始更新备份货架摆放顺序字典
response = requests.post('http://127.0.0.1:8000/getplacementorder')
response_json = json.loads(response.text)
result = response_json['result']
reason = response_json['reason']
#print(f'result={result}')
pick_off_dict=result
#print(pick_off_dict)






innovate_chengshu=0
innovate_slider=0


innovate_position2_1=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
innovate_position2_2=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
innovate_position2_3=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
innovate_position2_4=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
innovate_position2_5=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
innovate_position2_6=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]




innovate_position1_1=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
innovate_position1_2=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
innovate_position1_3=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
innovate_position1_4=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
innovate_position1_5=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
innovate_position1_6=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]




#
img_fishl=0
#

def vkbot_speak(text):
    try:
        # 调用语音合成客户端，进行语音合成操作
        vkbot_voice_client = rospy.ServiceProxy('/xf_mic_tts_offline_node/play_txt_wav', Play_TTS_srv)

        # 请求语音合成服务调用，输入具体的语音内容
        response = vkbot_voice_client(0,text, "xiaoyan")
        rospy.loginfo("vkbot speak ok!!")
        return response.result
    except rospy.ServiceException as e:
        print(f"Service call failed: {e}")












class GRAP:

 def __init__(self):
      pass

 #返回备份货架摆放顺序字典的内容
 def get_backup_dict(self):
    return pick_off_dict


 #更新备份货架摆放顺序字典
 def update_backup_dict(self,id_num,id_name):
    id_analysis=[]

    #解析物品所在的层数与编号
    id_analysis.append(int(id_num[0]))
    id_analysis.append(int(id_num[2]))   

    if id_analysis[0] == 1:
       layer='first'
    elif id_analysis[0] == 2:
       layer='second'    
    
    pick_off_dict[layer][id_analysis[1]-1]='NULL'
    print('更新的货架信息:'+str(pick_off_dict))
  

 #检测视觉内货物信息，返回检测数据（格式：字典，包含商品名称+相对位置信息）
 def detect(self):
    response = requests.get('http://127.0.0.1:8000/detect')
    #print(f'get detect response: {response.text}')
    response_json = json.loads(response.text)
    detect_result = response_json['result']
    #print(f'detect result: {detect_result}')
    return detect_result


 #获取机械臂信息，返回机械臂状态+坐标信息
 def getcurrentarmstate(self):
    response = requests.post('http://127.0.0.1:8000/getcurrentarmstate')
    #print(f'readGripperPostion response: {response.text}')
    response_json = json.loads(response.text)
    result = response_json['result']
    reason = response_json['reason']
    print(f'result={result}')
    #print(f'reason={reason}')
    return result


 #获取货架物体的摆放信息，返回两层货架的物体摆放信息（格式：字典）
 def getplacementorder(self):
    response = requests.post('http://127.0.0.1:8000/getplacementorder')
    #print(f'readGripperPostion response: {response.text}')
    response_json = json.loads(response.text)
    result = response_json['result']
    reason = response_json['reason']
    print(f'result={result}')
    #print(f'reason={reason}')
    return result


 #获取滑轨的位置，返回整型值，单位mm
 def getSlidePosition(self):
    ####getSlidePosition interface################
    response = requests.post('http://127.0.0.1:8000/getSlidePosition')
    response_json = json.loads(response.text)
    result = response_json['result'] 
    return result   


 #设置滑轨的位置值，输入整型值，单位mm
 def setSlidePosition(self,value):
    data = {
          'position': value,
          'speed': 2500,
          'acc': 200
    }
    response = requests.post('http://127.0.0.1:8000/setSlidePosition',  json=data)
    response_json = json.loads(response.text)
    result = response_json['result']
    reason = response_json['reason']
    #print(f'result={result}')
    #print(f'reason={reason}')


 #设置夹爪张开位置值，输入整型值，单位mm
 def setGripperPostion(self,value):
    ####setGripperPostion interface################
    data = {
      'position': value
    }
    response = requests.post('http://127.0.0.1:8000/setGripperPostion',  json=data)
    #print(f'setGripperPostion response: {response.text}')
    response_json = json.loads(response.text)
    gri_status = response_json['result']
    reason = response_json['reason']
    #print(f'result={gri_status}')
    #print(f'reason={reason}')
    return gri_status



 def movej(self,joints):
    data = {"joints": joints}
    response = requests.post('http://127.0.0.1:8000/movej', json=data)
    response_json = json.loads(response.text)
    run_status = response_json['result']
    reason = response_json['reason']


 #设置机械臂姿态值，输入姿态列表（包含目标位姿与姿态，目标位姿，位置单位：米，姿态单位：弧度）
 def movejp(self,position):
    data = {"base_postion": position}
    response = requests.post('http://127.0.0.1:8000/movejp', json=data)
    response_json = json.loads(response.text)
    run_status = response_json['result']
    reason = response_json['reason']


 #抓取目标物品，输入物体名称和坐标值（格式：名称必须是货架上的物体，坐标值是需要抓取的物体坐标值）
 def pick_targe(self,check_name,targe_position):
    global innovate_chengshu
    global innovate_position2_1
    global innovate_position2_2
    global innovate_position2_3
    global innovate_position2_4
    global innovate_position2_5
    global innovate_position2_6


    global innovate_position1_1
    global innovate_position1_2
    global innovate_position1_3
    global innovate_position1_4
    global innovate_position1_5
    global innovate_position1_6
    
    
    
   
    
    pick_position=targe_position
    
    #pick_position[1]=0.0    
    #pick_position=detect_result[check_name]['base_postion']
    
    name = str(remove_digits(str(list(check_name))))
    
    print('物品具体位置：'+str(pick_position))    

    pick_name=name[2:-2]

    print('物品名字：'+str(pick_name) )  

    if Arm_vision == 1:
      #固定机械臂的欧拉角，也就是抓取方向位姿
      pick_position[3]=2.8499999046325684
      pick_position[4]=1.5230000019073486   
      pick_position[5]=-0.3070000112056732
    
    else: 
      #固定机械臂的欧拉角，也就是抓取方向位姿
      pick_position[3]=2.6610000133514404
      pick_position[4]=1.5529999732971191   
      pick_position[5]=-0.4950000047683716    
    #0.07152500003576279, -0.0029060000088065863, 0.34343698620796204, 2.6610000133514404, 1.5529999732971191, -0.4950000047683716

    #根据物体在基坐标系得x正或者负方向 减去 夹爪长度 0.158m
    if pick_position[0] < 0:
            pick_position[0] += 0.158
    else:
            pick_position[0] -= 0.158

    #获取机械臂当前信息（机械臂状态+姿态信息）
    result = self.getcurrentarmstate()
    error_code, joints, curr_pose, arm_err_ptr, sys_err_ptr = result
    print("curr:"+str(curr_pose))
    
    #松开夹爪
    gri_status=self.setGripperPostion(100)
    #夹爪松开失败
    if gri_status != 0:
       pass  

    #移动到目标物体前方8cm处
    if pick_position[0] < 0:
            before_position = [pick_position[0] + 0.09,*pick_position[1:]]
    else:
            before_position = [pick_position[0] - 0.09,*pick_position[1:]]          
    print("目标抓取物pick:"+str(before_position))  
 
    #第二层
    if before_position[2] <= 0.4 :  
       print("目标抓取物在第二层") 
       
      
       if Arm_vision == 1:       
          data = [-0.24276599287986755, 0.0014230000087991357, 0.4501259922981262, 0.47600001096725464, 1.5190000534057617, -2.674999952316284]
       else:
          data = [-2.2090001106262207, 106.97599792480469, -129.5050048828125, 19.58799934387207, 91.24500274658203, 90.19999694824219]       

     
       self.movej(data)
       time.sleep(1)  

            
                
       #如果是雀巢咖啡，需要下降多一点
       if pick_name == 'Nescafe':
          before_position[0]-=0.06       
          before_position[1]-=0.005
          before_position[2]+=0.05
          print("雀巢咖啡")       
       #如果是橙子或者苹果比较矮的物体，需要下降多一点
       elif pick_name ==  'Orange':
          before_position[0]-=0.08
          before_position[1]-=0.07          
          before_position[2]+=0.045
          print("橘子")
       elif pick_name ==  'apple':
          before_position[0]-=0.053
          before_position[1]-=0.051          
          before_position[2]+=0.052
          print("苹果")
       elif pick_name ==  'Milk':
          before_position[0]-=0.06
          before_position[1]-=0.05
          before_position[2]+=0.06
          print("牛奶") 
       elif pick_name ==  'Coke':
          before_position[0]-=0.06
          before_position[1]-=0.02
          before_position[2]+=0.06
          print("百事可乐") 
       elif pick_name ==  'Coca_Coke':
          before_position[0]-=0.06
          before_position[1]-=0.02
          before_position[2]+=0.06
          print("可口可乐") 
       elif pick_name ==  'Sprite':
          before_position[0]-=0.06
          before_position[1]-=0.01
          before_position[2]+=0.045
          print("雪碧")  
       elif pick_name ==  'chips':
          before_position[0]-=0.06
          before_position[1]-=0.07
          before_position[2]+=0.06
          print("乐事薯片")
       elif pick_name ==  'red_bull':
          before_position[0]-=0.06
          before_position[1]-=0.01
          before_position[2]+=0.065
          print("红牛")                                                 
       elif pick_name == 'toothpaste':
          before_position[0]-=0.05
          before_position[1]-=0.008
          before_position[2]+=0.04 
          print("牙膏")
       elif pick_name ==  'Orea':
          before_position[0]-=0.05
          before_position[1]-=0.015
          before_position[2]+=0.04
          print("奥利奥饼干")
       elif pick_name ==  'tissue':
          before_position[0]-=0.04
          before_position[1]+=0
          before_position[2]+=0.055
          print("维达纸巾") 
       elif pick_name == 'Nutri_express':
          before_position[0]-=0.08      
          before_position[1]-=0.0
          before_position[2]+=0.08
          print("营养快线")                           
       else:
          #往前移动    
          before_position[0]-=0.05
          before_position[1]-=0.005
          before_position[2]+=0.043   
             
       #运动到合适位置
       self.movejp(before_position)
       time.sleep(1) 

    
       #如果是雀巢咖啡，需要前进多一点
       if pick_name == 'Nescafe':
          before_position[0]-=0.06       
       else:
          before_position[0]-=0.06
   
       #运动到合适位置
       self.movejp(before_position)
       time.sleep(1) 


       #关闭夹爪
       gri_status=self.setGripperPostion(5)
       if gri_status != 0:
           pass 
           
                 

       time.sleep(4) 
       before_position[0]+=0.06
       before_position[1]+=0
       before_position[2]+=0.04
       self.movejp(before_position)           
       time.sleep(1) 


       #如果是雀巢咖啡，需要前进多一点
       if remove_numbers(check_name) == 'Nescafe':
          before_position[0]+=0.09
          before_position[2]+=0.03      
       else:
          before_position[0]+=0.12
          before_position[1]+=0         
          before_position[2]+=0.03      
       print(before_position)  
       
       self.movejp(before_position)           
       time.sleep(1)        
       
       
     
       if Arm_vision == 1:       
          curr_pose=[0.0016159999649971724, -0.008661000058054924, 0.40723899006843567, 1.2660000324249268, 1.527999997138977, -1.8389999866485596]
       else:
          curr_pose=[-2.2279999256134033, 99.43399810791016, -123.93099975585938, 23.847999572753906, 91.34300231933594, 90.1780014038086]
 
       #运动到合适位置
       self.movej(curr_pose)

     
       time.sleep(1)

    #第一层
    else:
       print("目标抓取物在第一层") 
       
       
       if pick_name == 'Sprite':
          before_position[0]+=0.0058    
          before_position[1]-=0.005
          before_position[2]+=0.0055
          print("雪碧")  
       if pick_name == 'chips':
          before_position[0]-=0.04       
          before_position[1]-=0.07
          before_position[2]+=0.07
          print("乐事薯片")                
       #如果是橙子或者苹果比较矮的物体，需要下降多一点
       elif pick_name ==  'Orange':
          before_position[0]-=0.036
          before_position[1]+=0.000         
          before_position[2]+=0.075
          print("橘子")
       elif pick_name ==  'apple':
          before_position[0]-=0.063
          before_position[1]-=0.053          
          before_position[2]+=0.087
          print("苹果")
                    
          #0.015 0.085
       elif pick_name == 'Nescafe':
          before_position[0]-=0.013
          before_position[1]+=0.0
          before_position[2]+=0.062  
          print("雀巢咖啡") 
       elif pick_name == 'toothpaste':
          before_position[0]+=0.0015
          before_position[1]-=0.005
          before_position[2]+=0.05  
          print("牙膏")  
       elif pick_name ==  'Milk':
          before_position[0]-=0.05
          before_position[1]-=0.01
          before_position[2]+=0.06
          print("纯牛奶") 
       elif pick_name ==  'Coke':
          before_position[0]-=0.005
          before_position[1]-=0.045
          before_position[2]+=0.065
          print("百事可乐")
       elif pick_name ==  'Coca_Coke':
          before_position[0]-=0.01
          before_position[1]+=0.015
          before_position[2]+=0.045
          print("可口可乐")          
       elif pick_name ==  'tissue':
          before_position[0]-=0.06
          before_position[1]+=0.0
          before_position[2]+=0.055
          print("维达纸巾") 
       elif pick_name ==  'red_bull':
          before_position[0]-=0.06
          before_position[1]+=0.0
          before_position[2]+=0.055
          print("红牛") 

       elif pick_name == 'Nutri_express':
          before_position[0]-=0.03       
          before_position[1]-=0.0
          before_position[2]+=0.08
          print("营养快线")
       elif pick_name == 'Orea':
          before_position[0]-=0.047
          before_position[1]-=0.059
          before_position[2]+=0.05  
          print("奥利奥饼干")           
       elif pick_name == 'mineral_water':
          before_position[0]-=0.062
          before_position[1]-=0.06
          before_position[2]+=0.06  
          print("矿泉水")                  
       else:
          #往前移动    
          before_position[0]-=0.007
          before_position[1]-=0.0
          before_position[2]+=0.05       
              
       self.movejp(before_position)
       time.sleep(1) 



      
       before_position[0]-=0.07  
       self.movejp(before_position)           
       time.sleep(1)  

       if flagflag ==1 :
         time.sleep(1)        
         result = self.getcurrentarmstate()
         error_code, joints, curr_pose, arm_err_ptr, sys_err_ptr = result       
         innovate_position1_2= curr_pose

       #关闭夹爪
       gri_status=self.setGripperPostion(10)
       if gri_status != 0:
          pass  
       time.sleep(4) 

       before_position[0]+=0.15
       before_position[1]+=0
       before_position[2]+=0.02
       self.movejp(before_position)           
       time.sleep(1)  
       
       
       if flagflag ==1 :
         time.sleep(1)        
         result = self.getcurrentarmstate()
         error_code, joints, curr_pose, arm_err_ptr, sys_err_ptr = result       
         innovate_position1_3= curr_pose

       if Arm_vision == 1:       
          curr_pose=[0.0016159999649971724, -0.008661000058054924, 0.40723899006843567, 1.2660000324249268, 1.527999997138977, -1.8389999866485596]
       else:
          curr_pose=[-2.2090001106262207, 106.97599792480469, -129.5050048828125, 19.58799934387207, 91.24500274658203, 90.19999694824219]
       #运动到合适位置
       self.movej(curr_pose) 
       if flagflag ==1 :
         time.sleep(1)        
         result = self.getcurrentarmstate()
         error_code, joints, curr_pose, arm_err_ptr, sys_err_ptr = result       
         innovate_position1_4= curr_pose
         
         

 #根据物体编号控制滑轨运动，输入第一层、第二层货架摆放信息、抓取物体编号（比如‘1-2’）
 def check_class_slide(self,first_all,second_all,id_num):
    class_length=0
    id_analysis=[]

    Shelves_length=1200
    #解析物品所在的层数与编号
    id_analysis.append(int(id_num[0]))
    id_analysis.append(int(id_num[2])) 
    
    if id_analysis[0] == 1:
       class_length = len(first_all)    
    else:
       class_length = len(second_all)  
       
    cal_pos=(class_length+1-id_analysis[1])*(Shelves_length/(class_length+1))-300

    print(class_length)   

    if cal_pos<=0:
       cal_pos=0
    elif cal_pos>=pose_left :
       cal_pos=pose_left     
    
    print(cal_pos)    
    
    result1 = self.getSlidePosition() 

    #设置滑轨的运动值
    self.setSlidePosition(cal_pos)

    #根据滑轨的位置差决定等待多久时间    
    if cal_pos-result1<=100:
        time.sleep(4)    
    elif cal_pos-result1<200 and cal_pos-result1>=100:
        time.sleep(4)  
    elif cal_pos-result1>-200 and cal_pos-result1<=-100:
        time.sleep(4)                         
    elif cal_pos-result1<300 and cal_pos-result1>=200:
        time.sleep(6) 
    elif cal_pos-result1>-300 and cal_pos-result1<=-200:
        time.sleep(6)                                  
    elif cal_pos-result1<400 and cal_pos-result1>=300:
        time.sleep(8)           
    else:
        time.sleep(9)


    '''

    if id_analysis[1] == class_length:
      cal_pos=0  
      


      print('cal_pos:'+str(cal_pos))
      print('result1:'+str(result1)) 



      #根据滑轨的位置差决定等待多久时间    
      if result1-cal_pos<=100:
        time.sleep(4)    
      elif result1-cal_pos<200 and result1-cal_pos>=100:
        time.sleep(4)              
      elif result1-cal_pos<300 and result1-cal_pos>=200:
        time.sleep(6)                        
      elif result1-cal_pos<400 and result1-cal_pos>=300:
        time.sleep(8)           
      else:
        time.sleep(9) 

          
    else:
      cal_pos=pose_left-int(((id_analysis[1]-1)/float(class_length))*pose_left)
      result1 = self.getSlidePosition() 
      #设置滑轨的运动值
      self.setSlidePosition(cal_pos)
      time.sleep(2)
      
      print('cal_pos:'+str(cal_pos))
      print('result1:'+str(result1))      
      
      #根据滑轨的位置差决定等待多久时间    
      if cal_pos-result1<=100:
        time.sleep(4)    
      elif cal_pos-result1<200 and cal_pos-result1>=100:
        time.sleep(4)  
      elif cal_pos-result1>-200 and cal_pos-result1<=-100:
        time.sleep(4)                         
      elif cal_pos-result1<300 and cal_pos-result1>=200:
        time.sleep(6) 
      elif cal_pos-result1>-300 and cal_pos-result1<=-200:
        time.sleep(6)                                  
      elif cal_pos-result1<400 and cal_pos-result1>=300:
        time.sleep(8)           
      else:
        time.sleep(9) 
      
      
    print(cal_pos) 
    '''    
    
      
    return class_length


 #获取目标物品的位置信息，输入物体名称、位置编号、同一层货架同类型物体序号（格式：‘apple’,’1-2’,1）
 def check_targe_position(self,name,number,repeat_index):
    height=0.40
    targe={}
    dealth_list=[]
    ll_list=[]
    slide_value=0
    targe_position=[]
    targe_dict={}  
    id_analysis=[]

    id_analysis.append(int(number[0]))
    id_analysis.append(int(number[2])) 

    time.sleep(2)

    #再找出详细的位置
    detect_result = self.detect()
    #print('mubiao：'+str(detect_result))



    #先对物体进行分层
    for key, value in detect_result.items():
        #print(f'detect object: {key}')
        base_position = value['base_postion']
        num = value['num']
        #print(f'base_position: {base_position}')
        #print(f'num: {num}')
        key1=remove_numbers(key)
        if key1 == name and id_analysis[0] == 1:
           if base_position[2]>height:
              targe[str(key)]=base_position
        elif key1 == name and id_analysis[0] == 2:
           if base_position[2]<=height:        
              targe[str(key)]=base_position           
    #print('mubiao：'+str(targe))        

    if len(targe) == 1:
        for key, value in targe.items():
              dealth_list.append(value)
              slide_value=value[1]
              targe_position=value
        targe_dict=targe   
    else :
        for key, value in targe.items():
              dealth_list.append(value)
        print(dealth_list)
        
        for key in dealth_list:
          ll_list.append(key[1])
        #print(ll_list)  
        ll_list=  sorted(ll_list)    
        #print(ll_list)    
 
        slide_value=ll_list[repeat_index]
        
        for value in  dealth_list:
           if slide_value == value[1]:
              targe_position=value
     
        for key, value in targe.items():
           if slide_value == value[1]:
              targe_dict[str(key)]=value
           
    #print(slide_value)   
    #print(targe_position)  
    print(targe_dict) 

    return slide_value,targe_position,targe_dict



 #检测时初始位姿
 def init_position(self):
    if Arm_vision==1:
       pick_start_position=[0.04256200045347214, -0.0022619999945163727, 0.3316650092601776, 3.072999954223633, 1.3890000581741333, -0.0820000022649765]
       self.movejp(pick_start_position)
    else:
       pick_start_position=[-2.2300000190734863, 99.43299865722656, -123.93199920654297, 23.844999313354492, 91.34100341796875, 90.1780014038086]
       self.movej(pick_start_position)


 #检测目标物体的合法性，输入位置编号与物体名称（‘1-2’，‘apple’），返回数据（是否在货架中、第一层摆放顺序、第二层摆放顺序、同一层重复物体的个数，目标物体在重复物体的位置）
 def check_and_get_goods_order(self,id_num,id_name):
    id_analysis=[]
    repeat_number=0
    repeat_index=0     
    
    #获取货架的摆放顺序
    result = self.get_backup_dict()
    first_all  =  result['first']
    second_all =  result['second']     

    #解析物品所在的层数与编号
    id_analysis.append(int(id_num[0]))
    id_analysis.append(int(id_num[2]))   

    if id_analysis[0] == 1:
       layer='first'
    elif id_analysis[0] == 2:
       layer='second'    
    
    #判断物品名称是否在货架中
    if id_name == result[layer][id_analysis[1]-1]:
       print('输入的商品名称在货架中!!!!')
       state=True
       #pick_off_dict[layer][id_analysis[1]-1]='NULL'
    else  :    
       print('输入的商品名称不在货架中!!!!')  
       state=False   

    #第一层  
    if id_analysis[0] == 1:
       for index,value in enumerate(first_all):
           if value == id_name :
             if (index+1) == id_analysis[1]:
                 repeat_index=repeat_number
             repeat_number+=1
    #第二层
    elif id_analysis[0] == 2:
       for index,value in enumerate(second_all):
           if value == id_name :
             if (index+1) == id_analysis[1]:
                 repeat_index=repeat_number
             repeat_number+=1

    print(repeat_number)
    print(repeat_index)      
    
    return state,first_all,second_all,repeat_number,repeat_index


 #输入英文名称，将物体英文名称转化为中文名称
 def switch_case(self,case):
    switch_dict = {
        'mineral_water': '矿泉水',
        'Orea'         : '奥利奥饼干',
        'Milk'         : '纯牛奶',
        'Nescafe'      : '雀巢咖啡',
        'Sprite'       : '雪碧',        
        'Orange'       : '橘子',
        'chips'        : '薯片',         
        'toothpaste'   : '牙膏',        
        'tissue'       : '维达纸巾',
        'apple'        : '苹果', 
        'Coke'         : '百事可乐',
        'Coca_Coke'    : '可口可乐', 
        'Nutri_express' : '营养快线', 
        'red_bull'      : '红牛',    
             
    }
    return switch_dict.get(case, '未知物品')


 #输入物体英文名称，返回物体英文名称对应的价格
 def switch_case_price(self,case):
    switch_dict = {
        'mineral_water': '2',
        'Orea'         : '6',
        'Milk'         : '3',
        'Nescafe'      : '4',
        'Sprite'       : '3',        
        'Orange'       : '2',
        'chips'        : '3',         
        'toothpaste'   : '10',        
        'tissue'       : '4',
        'apple'        : '2', 
        'Coke'         : '3',
        'Coca_Coke'    : '3', 
        'Nutri_express' : '6', 
        'red_bull'     : '6',

            
    }
    return switch_dict.get(case, '未知物品')


 #结算函数
 def checkout(self):
   #dict1={'0': '零', '1': '一', '2': '二', '3': '三','4': '四','5': '五', '6': '六', '7': '七', '8': '八', '9': '九'}
   #获取当前的滑轨值
   current_slide=self.getSlidePosition()
   time.sleep(1) 
   
   #移动滑轨到靠近结算区的位置
   slide_point=0
   self.setSlidePosition(slide_point)   
         
   #根据滑轨的位置差决定等待多久时间    
   if current_slide-slide_point<=100:
      time.sleep(2)    
   elif current_slide-slide_point<200 and current_slide-slide_point>=100:
      time.sleep(6)              
   elif current_slide-slide_point<300 and current_slide-slide_point>=200:
      time.sleep(7)                        
   elif current_slide-slide_point<400 and current_slide-slide_point>=300:
      time.sleep(8)           
   else:
      time.sleep(9)                 

   if Arm_vision == 1:
      #旋转机械臂
      data = [0.008766000159084797, 0.0027759999502450228, 0.3813610076904297, -3.0859999656677246, 0.7730000019073486, -1.059999942779541]    
   else:
      #旋转机械臂
      data = [-2.2300000190734863, 99.43099975585938, -123.93199920654297, 23.8439998626709, 91.33799743652344, 90.1780014038086]  
      self.movej(data)
      time.sleep(1) 
      
      #旋转机械臂
      data = [-93.9749984741211, 99.42400360107422, -117.42400360107422, 12.595000267028809, 90.47899627685547, 90.14900207519531]  
      self.movej(data)
      time.sleep(1) 
       
   #旋转机械臂
   data = [-78.677001953125, 32.130001068115234, -69.65699768066406, -34.402000427246094, 93.87200164794922, 90.16000366210938]  
   self.movej(data)
   time.sleep(4)  
   #检测结算区的物体
   detect=(self.detect()).keys()
   print(detect) 
   time.sleep(1) 
   #将识别到的物体添加到一个列表当中
   class_list=[]
   for key in detect:
     class_list.append(self.switch_case(remove_numbers(key)))

   #累加每个物体的价格，得出总价
   price_list=0
   for key in detect:
     price_list+=float(self.switch_case_price( remove_numbers(key) ))

   print(class_list)   
   print(price_list) 
   
   #输出语音播报内容
   class_list_str='结算区域的物品为'+str(class_list)+','+'一共是'+str(price_list)+'元，'+'谢谢惠顾，欢迎下次光临！祝您生活愉快，期待下次再见！'
   #audio.vkbot_speak(class_list_str)
   time.sleep(1)


   self.init_position()
   time.sleep(2)
   
   return class_list_str
   












 #创新函数
 def innovate_pick(self):

      global innovate_slider
      global innovate_chengshu
 
      global innovate_position2_1
      global innovate_position2_2
      global innovate_position2_3
      global innovate_position2_4
      global innovate_position2_5
      global innovate_position2_6


      global innovate_position1_1
      global innovate_position1_2
      global innovate_position1_3
      global innovate_position1_4
      global innovate_position1_5
      global innovate_position1_6






      #打开夹爪
      self.setGripperPostion(100)
      time.sleep(1)


      data = img_place_position_1
      self.movejp(data)
      time.sleep(0)
     
      data =img_place_position_2
      self.movejp(data)
      time.sleep(0)
      
      data =img_place_position_3
      self.movejp(data)
      time.sleep(1)
             
      data =img_place_position_4
      self.movejp(data)
         

      #关闭夹爪
      self.setGripperPostion(0)
      time.sleep(3)

      data = img_place_position_5
      self.movejp(data)
      time.sleep(0)          
      
      data = img_place_position_6
      self.movejp(data)
      time.sleep(0)  

      data = img_place_position_7
      self.movejp(data)
      time.sleep(1)  


      time.sleep(5)  

    
      print('lllllllllllllll:'+str(innovate_slider))
      self.setSlidePosition(innovate_slider)
      time.sleep(3)        


 
       #根据滑轨位置差确定等待的时间
      if innovate_slider<=100:

         time.sleep(3)
         print('111')

      elif innovate_slider<200 and innovate_slider>=100:
         time.sleep(4) 
         print('222')        
      elif innovate_slider<300 and innovate_slider>=200:
         time.sleep(6)
         print('333')                 
      elif innovate_slider<400 and innovate_slider>=300:
         time.sleep(6)
         print('444')    
      else:
         time.sleep(9)
         print('555')  

    

      print('kkkkkkkkkkkkkk:'+str(innovate_chengshu))

      if innovate_chengshu == 2:

          print(innovate_position2_1)
          print(innovate_position2_2)
          print(innovate_position2_3)          
          print(innovate_position2_4)
          print(innovate_position2_5)          
          print(innovate_position2_6)
          
          
          self.movejp(innovate_position2_1)           
          time.sleep(2) 
      
          self.movejp(innovate_position2_2)           
          time.sleep(2)       

          self.movejp(innovate_position2_3)           
          time.sleep(2) 
      
      
          #打开夹爪
          gri_status=self.setGripperPostion(100)
          if gri_status != 0:
             pass       
          time.sleep(3)  
 
      
          self.movejp(innovate_position2_4)           
          time.sleep(2) 
      
          self.movejp(innovate_position2_5)           
          time.sleep(2)       

          self.movejp(innovate_position2_6)           
          time.sleep(2)    
      
      
      elif innovate_chengshu == 1:      
      
      
          print(innovate_position1_1)
          print(innovate_position1_2)
          print(innovate_position1_3)          
          print(innovate_position1_4)
      
      
          self.movejp(innovate_position1_1)           
          time.sleep(2) 
      
          self.movejp(innovate_position1_2)           
          time.sleep(2)    
          
           #打开夹爪
          gri_status=self.setGripperPostion(100)
          if gri_status != 0:
             pass  
                        
          time.sleep(3)               

          self.movejp(innovate_position1_3)           
          time.sleep(2) 
      
          self.movejp(innovate_position1_4)           
          time.sleep(2) 
      
      
         

 def pick_number(self):
    global place
    return place





 def img_value(self):
    global img_fishl
    return img_fishl




 #抓取目标物体，输入目标物体编号+物体名称（grap_good('2-2','Orange')），最重要的函数，会调用以上其他的函数接口，完成整个抓取的任务
 def grap_good(self,id_num,id_name=None,flag=0):
    id_analysis=[]
    first_all=[]
    second_all=[]
    repeat_number=0
    repeat_index=0  
    global place
    
    
    print('flag='+str(flag))
    
    
    #输入格式是否有误
    if (len(id_num) != 3) or (id_num[1] != '-' ):
      print('ERROR:参数输入错误！')
      return 0
    #是否为空
    elif id_name == None:
      print('ERROR:请输入产品名称！')    
      return 0
    #输入格式正确
    else:
      #运行到初始检测位姿
      self.init_position()
      time.sleep(2)  
      #print('11')
      #解析物品所在的层数与编号
      id_analysis.append(int(id_num[0]))
      id_analysis.append(int(id_num[2]))   
 
      #检测物体是否在货架中
      state,first_all,second_all,repeat_number,repeat_index=self.check_and_get_goods_order(id_num,id_name)
      
      #如果存在的话，则进行抓取准备工作
      if state == True:
      
        
         #print(pick_off_dict)
         #移动滑轨到大概位置
         class_length=self.check_class_slide(first_all,second_all,id_num)
         #time.sleep(3)    
         #获取目标物体的滑轨偏差值和位置值
         slide_value, targe_position,targe_dict=self.check_targe_position(id_name,id_num,repeat_index)
         time.sleep(1)
         

         #获取滑轨的位置值
         check_name=id_name
         result = self.getSlidePosition()
         
         
         print(slide_value, targe_position,result)
         


         if id_analysis[1] == 1 or id_analysis[1] == class_length:
            pass
         else: 
            self.setSlidePosition(result-slide_value*1000)
            time.sleep(3)  
             
             
         #再次获取目标物体的位置值
         slide_value, targe_position,targe_dict=self.check_targe_position(id_name,id_num,repeat_index)
         time.sleep(1)
          
         print('抓取物品') 
         
         #抓取目标物体
         self.pick_targe(targe_dict.keys(),targe_position)   
         time.sleep(1)
         #更新备份货架摆放顺序字典
         self.update_backup_dict(id_num,id_name)   
         time.sleep(1) 

         #获取当前滑轨的位置
         current_slide=self.getSlidePosition()
         time.sleep(1) 
         #移动滑轨到靠近结算区
         slide_point=0
         self.setSlidePosition(slide_point)   
         #print('kkk='+str(slide_point-current_slide)) 
         #根据滑轨位置差确定等待的时间
         if current_slide-slide_point<=100:
            time.sleep(10)
            print('111')
         elif current_slide-slide_point<200 and current_slide-slide_point>=100:
            time.sleep(10) 
            print('222')        
         elif current_slide-slide_point<300 and current_slide-slide_point>=200:
            time.sleep(10)
            print('333')                 
         elif current_slide-slide_point<400 and current_slide-slide_point>=300:
            time.sleep(12)
            print('444')    
         else:
            time.sleep(15)
            print('555')             
         
         print('放置好')         
         
           

         if Arm_vision == 1:
         #$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$#        
 
           #旋转机械臂1
           data = [-0.05088299885392189, 0.07531999796628952, 0.5423349738121033, -0.5989999771118164, 1.5449999570846558, 1.7899999618530273]
           self.movejp(data)
           time.sleep(1)           

           #旋转机械臂2
           data = [-0.014841999858617783, 0.10147500038146973, 0.5375310182571411, 1.4160000085830688, 1.5269999504089355, -3.0429999828338623]
           self.movejp(data)
           time.sleep(1)      

           point=0.0     
         
           if flag == 1:
              #调整放置姿态1
              data = [-0.21817000210285187, 0.4075399935245514, -0.015600999817252159, 0.8980000019073486, 1.4800000190734863, 2.8399999141693115]
              self.movejp(data)
              time.sleep(1) 
           
         
              #调整放置姿态2
              data = [-0.21817000210285187, 0.4075399935245514, -0.015600999817252159, 0.8980000019073486, 1.4800000190734863, 2.8399999141693115]
              self.movejp(data)
              time.sleep(1)     
             
              #打开夹爪
              self.setGripperPostion(100)
              time.sleep(2)         

              #调整放置姿态1
              data = [-0.21817000210285187, 0.4075399935245514, 0.325600999817252159, 0.8980000019073486, 1.4800000190734863, 2.8399999141693115]
              self.movejp(data)
              time.sleep(1)  
            
              #旋转机械臂2
              data = [-0.014841999858617783, 0.10147500038146973, 0.5375310182571411, 1.4160000085830688, 1.5269999504089355, -3.0429999828338623]
              self.movejp(data)
              time.sleep(2)          
         
              #旋转机械臂
              data = [0.11996699869632721, -0.01281100045889616, 0.3642970025539398, -0.3199999928474426, 1.5520000457763672, 2.865999937057495]
              self.movejp(data)
              time.sleep(1)          
         
              #回到滑轨的初始位置
              self.setSlidePosition(current_slide)
              time.sleep(12)             
            
      
           else:
            
              if place ==0 :
                #调整放置姿态1
                data = [-0.12387800216674805, 0.20340600609779358, 0.4378589987754822, 0.3269999921321869, 1.5429999828338623, 2.444999933242798]
                print("here")
                while True:
                	pass
                self.movejp(data)
                time.sleep(1)
           

                #调整放置姿态1
                data = [-0.12982000410556793, 0.37282198667526245, -0.010716998279094696, 1.5800000429153442, 1.4900000095367432, -2.8469998836517334]
                self.movejp(data)
                time.sleep(1)            

                #打开夹爪
                self.setGripperPostion(100)
                time.sleep(2)

                #调整放置姿态1
                data = [-0.12982000410556793, 0.37282198667526245, 0.1601116998279094696, 1.5800000429153442, 1.4900000095367432, -2.8469998836517334]
                self.movejp(data)
                time.sleep(1)   

         
              if place ==1 :
                #调整放置姿态1
                data = [-0.22076700627803802, 0.33422398567199707, 0.04788200184702873, 1.6490000486373901, 1.4869999885559082, -2.5299999713897705]
                self.movejp(data)
                time.sleep(1)  
              
                #调整放置姿态1
                data = [-0.22076700627803802, 0.33422398567199707, -0.01788200184702873, 1.6490000486373901, 1.4869999885559082, -2.5299999713897705]
                print("here1")
                while True:
                	pass
                self.movejp(data)
                time.sleep(1)                
              
                #打开夹爪
                self.setGripperPostion(100)
                time.sleep(2)
              
                #调整放置姿态1
                data = [-0.22076700627803802, 0.33422398567199707, 0.16788200184702873, 1.6490000486373901, 1.4869999885559082, -2.5299999713897705]
                self.movejp(data)
                time.sleep(1)                                       
         
         
              if place ==2 :
                #调整放置姿态1
                data = [-0.2922619879245758, 0.27390000224113464, 0.04992799833416939, 1.4819999933242798, 1.4869999885559082, -2.4609999656677246]
                self.movejp(data)
                time.sleep(1)             
         
                #调整放置姿态1
                data = [-0.2922619879245758, 0.27390000224113464, -0.014992799833416939, 1.4819999933242798, 1.4869999885559082, -2.4609999656677246]
                self.movejp(data)
                time.sleep(1)           
         
                #打开夹爪
                self.setGripperPostion(100)
                time.sleep(2)         
         
                #调整放置姿态1
                data = [-0.2922619879245758, 0.27390000224113464, 0.16992799833416939, 1.4819999933242798, 1.4869999885559082, -2.4609999656677246]
                self.movejp(data)
                time.sleep(1)           
         
         
         
         
              #旋转机械臂2
              data = [-0.014841999858617783, 0.10147500038146973, 0.5375310182571411, 1.4160000085830688, 1.5269999504089355, -3.0429999828338623]
              self.movejp(data)
              time.sleep(2)          
         
              #旋转机械臂
              data = [0.11996699869632721, -0.01281100045889616, 0.3642970025539398, -0.3199999928474426, 1.5520000457763672, 2.865999937057495]
              self.movejp(data)
              time.sleep(1)          
         

              place+=1      
  
         #$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$#          
         
         else:
         #***********************************************************************************#          
         
           point=0.0     
         
           if flag == 1:
              data = product_place_position0_1
              self.movej(data)
              time.sleep(1)
                
                
              joints=[-90.75900268554688, 42.577999114990234, -117.40799713134766, 12.571999549865723, 90.45800018310547, 90.1709976196289]
              self.movej(joints)
              time.sleep(1)
                
                
              joints=[-83.6510009765625, -33.14500045776367, -108.76799774169922, 50.97600173950195, 89.85700225830078, 90.1780014038086]
              self.movej(joints)
              time.sleep(1)   
                             
              #打开夹爪
              self.setGripperPostion(100)
              time.sleep(1)                                
                
              joints=[-90.75900268554688, 42.577999114990234, -117.40799713134766, 12.571999549865723, 90.45800018310547, 90.1709976196289]
              self.movej(joints)
              time.sleep(1)                


              data = product_place_position0_1
              self.movej(data)
              time.sleep(1)        



              data = initposition
              self.movej(data)
              time.sleep(0)               

              img_fishl=2
           
                
           else:
            
                     
              if place ==0 :
                data = product_place_position0_1
                self.movej(data)
                time.sleep(1)
                
                
                joints=[-71.82099914550781, 31.31599998474121, -117.41300201416016, 23.509000778198242, 90.40899658203125, 90.16400146484375]
                self.movej(joints)
                time.sleep(1)
                
                
                joints=[-71.04299926757812, -35.667999267578125, -106.5, 57.29100036621094, 90.25599670410156, 90.15899658203125]
                self.movej(joints)
                time.sleep(1)   
                             
                #打开夹爪
                self.setGripperPostion(100)
                time.sleep(1)                                
                
                joints=[-71.82099914550781, 31.31599998474121, -117.41300201416016, 23.509000778198242, 90.40899658203125, 90.16400146484375]
                self.movej(joints)
                time.sleep(1)                


                data = product_place_position0_1
                self.movej(data)
                time.sleep(1) 
                
                data = initposition
                self.movej(data)
                time.sleep(0)                  
         
              if place ==1 :
                data = product_place_position0_1
                self.movej(data)
                time.sleep(1)
                
                
                joints=[-60.18000030517578, 18.402000427246094, -114.48699951171875, 30.731000900268555, 88.6520004272461, 90.1709976196289]
                self.movej(joints)
                time.sleep(1)
                
                
                joints=[-58.816001892089844, -39.308998107910156, -88.95899963378906, 43.374000549316406, 90.23600006103516, 90.14199829101562]
                self.movej(joints)
                time.sleep(1)   
                             
                #打开夹爪
                self.setGripperPostion(100)
                time.sleep(1)                                
                
                joints=[-60.18000030517578, 18.402000427246094, -114.48699951171875, 30.731000900268555, 88.6520004272461, 90.1709976196289]
                self.movej(joints)
                time.sleep(1)                


                data = product_place_position0_1
                self.movej(data)
                time.sleep(1)                                   
                
                data = initposition
                self.movej(data)
                time.sleep(0)          
         
              if place ==2 :
              
                data = product_place_position0_1
                self.movej(data)
                time.sleep(1)
                
                
                joints=[-55.630001068115234, 21.56800079345703, -113.99800109863281, 34.362998962402344, 89.60700225830078, 90.17400360107422]
                self.movej(joints)
                time.sleep(1)
                
                
                joints=[-49.858001708984375, -47.63600158691406, -75.96600341796875, 43.64099884033203, 94.447998046875, 90.1449966430664]
                self.movej(joints)
                time.sleep(1)   
                
                         
                #打开夹爪
                self.setGripperPostion(100)
                time.sleep(1)                                
                
                joints=[-55.630001068115234, 21.56800079345703, -113.99800109863281, 34.362998962402344, 89.60700225830078, 90.17400360107422]
                self.movej(joints)
                time.sleep(1)                


                data = product_place_position0_1
                self.movej(data)
                time.sleep(1)    
         
                data = initposition
                self.movej(data)
                time.sleep(0)                     
         
         

              place+=1  
              print('8888888888888888888888888888888888888place:'+str(place))            
        
            
         #***********************************************************************************#          
         
               
      else:
        pass
      
      
      



