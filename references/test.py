# test.py
import main_workflow

if __name__ == "__main__":
    # 假设标签写死为 "red_bull"
    label_name = "Ad_calcium_milk"

    print(f"开始测试调用 main_workflow，输入标签: {label_name}")
    result = main_workflow.grab_one(label_name, use_camera=False)

    print("调用结束，返回结果：")
    print(result)