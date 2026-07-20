# 商品多类别 YOLO 模型 — 数据采集/打标/训练/接回流程

写于 2026-07-20，dual-arm-sdk 分支。这份文档只回答一件事："`--target-product`
要用的多类别商品识别模型，从零开始怎么做出来"。`--target-product` 本身的
代码链路和货架多格位/真出货架构见 `bottle_grasp/SAFETY_PROFILES.md`
"Real dispensing vs. table_demo's place-back cycle"一节和
`docs/handoff/bottle_grasp_status.md` 2026-07-20 那节。

## 现状（2026-07-20 确认）

`config.yaml` 的 `vision.model_path` 指向 `intelligence/yolo_models/8_17.pt`，
`intelligence/vision.py`/`bottle_grasp/perception.py` 都读这同一个模型文件。
用户已确认这个模型**现在只能识别通用"瓶子"**，不区分具体商品——虽然
`intelligence/vision.py` 里的 `product_chinese_name` 映射表和
`utils/items_info.py` 的价格表列了15个商品类别，那是旧版本/旧架构遗留的
参照，不代表现在部署的 `8_17.pt` 真的还认得这些类别。

`bottle_grasp/perception.py` 的 `target_classes` 参数和
`scripts/bottle_grasp_demo.py` 的 `--target-product` 已经写好（见
`test/bottle_grasp/test_target_classes.py`），**这份文档产出的新模型接上去
不需要再改代码**，只需要换 `model_path` + 确认类别名对得上。

## 训练环境：推荐用户自己的 RTX 4060 游戏本

对比过 Mac(Apple Silicon MPS)/机器人本体/带GPU的服务器(5090)/用户的 RTX 4060
游戏本：机器人本体没有训练级GPU且会占用现场验收资源，排除；Mac 的 MPS
后端能跑但历史上算子回退/兼容问题更多；5090 服务器算力最强但接入成本
（远程环境、数据传输）不确定；**RTX 4060 游戏本**是真正的 CUDA GPU，
`pip install ultralytics` 在 NVIDIA 上是最成熟的路径，这次只是给几十个
epoch 的nano/small模型做迁移学习微调，8GB显存的4060绰绰有余，而且是
用户自己现成能用的机器。以后如果5090服务器确实随手可用，换机器跑同一套
脚本即可，不用改代码。

## 完整流程

### 第一步：采集原始图片（机器人上跑）

```bash
python scripts/collect_product_images.py \
  --label coke_bottle --camera head --interval 2
```

- `--label` 用后面 `--target-product` 要传的英文/拼音 slug（比如
  `coke_bottle`），不要用中文——避免类别名在某些终端/YOLO版本下的编码
  麻烦。中文商品名只在下面的"类别对照表"里记录。
- 每个商品单独跑一次（一次只放一个商品在镜头前）。图片自动存进
  `intelligence/data/raw/<label>/`。
- **关键**：要覆盖多角度——正面/侧面/背面/倾斜、不同距离、不同光照都要拍。
  只在一个角度连拍是已知的坑（见 `docs/handoff/bottle_grasp_known_risks.md`
  "自训模型对朝向敏感，标签背对相机置信度从0.85骤降到0.09"那条），新模型
  不能重蹈覆辙。
- 建议每个类别至少150-200张，这是微调（不是从零训练）常见的够用量级，
  脚本结束时会按这个门槛给提示（不阻断，只是提醒）。
- `--camera` 可选 `head`/`right_wrist`/`left_wrist`：实际识别时头部和腕部
  相机都会跑这个模型，两个相机各采一批效果更稳。

### 第二步：人工打框标注

用 [LabelImg](https://github.com/HumanSignal/labelImg) 或
[CVAT](https://github.com/cvat-ai/cvat) 打开
`intelligence/data/raw/<label>/`，标注格式选 **YOLO**（不是 Pascal VOC/
CreateML）：

- LabelImg：左侧选 "YOLO" 格式后保存，会在每张图旁边生成同名 `.txt`，
  一行 `class_id cx cy w h`（归一化坐标）。
- 每个类别一个 `.txt` 标注框，只框商品本体，不要把手/背景框进去。
- LabelImg 需要一个 `classes.txt` 列出类别顺序对应 `class_id`——用下面
  "类别对照表"里定好的顺序，跟 `--label` 用的名字完全一致。
- CVAT 导出时选 "YOLO 1.1" 格式，导出结果同样是图片+同名txt，可以直接
  丢进 `intelligence/data/raw/<label>/`。

标完检查：每张 `.jpg` 都要有同名 `.txt`，缺一个 `prepare_yolo_dataset.py`
就会直接报错拒绝往下走（不会静默漏掉）。

### 第三步：整理数据集（Mac 或训练机上跑）

```bash
python scripts/prepare_yolo_dataset.py \
  --raw-root intelligence/data/raw \
  --output-root intelligence/data/product_yolo \
  --val-fraction 0.15
```

- 按类别分层切 train/val（每个类别单独切，保证小类别也不会在验证集里
  缺席），复制（不移动）到 `images/{train,val}/` + `labels/{train,val}/`。
- 生成 `data.yaml`，`class_id` 顺序 = 类别文件夹名排序，可复现。
- 输出会列出每个类别最终 train/val 各多少张，明显不够的类别会有提示。
- 缺标注文件会在这一步直接报错列出具体文件名，不会跳过继续整理。

### 第四步：训练（在训练机，即 RTX 4060 笔记本上跑）

```bash
python scripts/train_product_yolo.py \
  --data intelligence/data/product_yolo/data.yaml \
  --base-model yolov8n.pt \
  --epochs 100 --imgsz 640 --batch 16 --device cuda:0
```

- 默认从公开 COCO 预训练的 `yolov8n.pt` 开始迁移学习，**不基于**现在的
  `8_17.pt` 继续训练——新类别列表的检测头维度/顺序跟旧模型对不上，干净地
  从预训练骨干开始更简单可靠。`yolov8n.pt` 首次运行 ultralytics 会自动
  下载；如果训练机没有外网，需要提前手动放一份到本地再用
  `--base-model <本地路径>`。
- `--device` 按训练机实际情况填：CUDA 显卡填 `cuda:0`，不填让 ultralytics
  自动选。
- 训练产出 `best.pt`（脚本会打印具体路径），**不会自动替换**
  `intelligence/yolo_models/8_17.pt`。
- 2026-07-20 已用一个2类、每类12张图的合成小数据集在本机 CPU 上跑通全流程
  （1 epoch，仅验证脚本机制不代表训练效果），确认参数/API调用没问题；
  真实15类+每类150-200张图的训练规模和时长没有实测过，第一次正式训练
  自己先留够时间盯着看。

### 第五步：验证 + 接回

```bash
python scripts/verify_yolo_model.py <best.pt路径> --image 一张真实测试图.jpg
```

- 打印类别列表（人工确认数量/名字都对），给一张图能看到画框和置信度。
- 满意后：把 `best.pt` 复制到 `intelligence/yolo_models/`，改
  `config.yaml` 的 `vision.model_path` 指向它；跑
  `--target-product coke_bottle` 时这个字符串必须跟 `data.yaml` 里的类别名
  完全一致（区分大小写）。
- 换模型后，`bottle_grasp` 那边现有的 `--target-product`/`target_classes`
  代码不需要改，但**没在真机上验证过换模型后端到端识别的效果**——先用
  `--task-mode ... --target-product ... --plan-only` 跑一遍确认视觉链路正常，
  再实际执行。

## 类别对照表（示例，按实际要支持的商品修改）

| `--label`/`--target-product` | 中文商品名 |
|---|---|
| `coke_bottle` | 可口可乐 |
| `sprite_bottle` | 雪碧 |
| `mineral_water` | 矿泉水 |

这张表只是示例——实际商品清单由现场货架决定，采集时按需增删类别，不用
照抄这三行。

## 还没做/还不知道的事

- 这轮只产出了脚本和文档，**一张真实商品照片都还没采集**。
- 训练/验证脚本只用合成小数据集在本机 CPU 上跑通过机制，真实规模的训练
  时长、显存占用、最终识别准确率都没有实测。
- 现有 `8_17.pt` 的确切类别列表其实也从没在这轮会话里用
  `scripts/verify_yolo_model.py` 实测确认过（用户凭经验判断"现在只认瓶子"，
  没有跑那行诊断命令）——如果以后想复核，直接用这个脚本查。
