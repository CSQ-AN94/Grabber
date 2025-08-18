# test.py
import main_workflow
from hezhizhi.main_workflow import grab_one

if __name__ == "__main__":
    # 假设标签写死为 "red_bull"
    label_name = "Ad_calcium_milk"

    print(f"开始测试调用 main_workflow，输入标签: {label_name}")
    result = grab_one(label_name)

    print("调用结束，返回结果：")
    print(result)