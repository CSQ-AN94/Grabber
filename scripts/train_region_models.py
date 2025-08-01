#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8区域网格化抓取系统 - 线性回归训练脚本
训练uv->offset(x,y,z)的线性回归模型
"""

import os
import sys
import json
import numpy as np
import joblib
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, r2_score

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from competition_main import SHELF_REGIONS

def train_region_model(region_id):
    """训练单个区域的线性回归模型"""
    data_file = f"training_data/{region_id}_data.json"
    
    if not os.path.exists(data_file):
        print(f"❌ 数据文件不存在: {data_file}")
        return False
    
    # 加载训练数据
    with open(data_file, 'r') as f:
        data = json.load(f)
    
    if len(data) < 5:
        print(f"❌ 数据量不足({len(data)}个)，需要至少5个样本")
        return False
    
    # 准备训练数据
    X = np.array([[d['u'], d['v']] for d in data])  # 输入: (u,v)
    y = np.array([[d['offset_x'], d['offset_y'], d['offset_z']] for d in data])  # 输出: (offset_x,y,z)
    
    # 训练线性回归模型
    model = LinearRegression()
    model.fit(X, y)
    
    # 预测和评估
    y_pred = model.predict(X)
    mse = mean_squared_error(y, y_pred)
    r2 = r2_score(y, y_pred)
    
    print(f"✅ {region_id}:")
    print(f"   样本数: {len(data)}")
    print(f"   MSE: {mse:.6f}")
    print(f"   R²: {r2:.4f}")
    
    # 保存模型
    os.makedirs("models", exist_ok=True)
    model_file = f"models/{region_id}_offset_model.pkl"
    joblib.dump(model, model_file)
    print(f"   模型已保存: {model_file}")
    
    return True

def main():
    """训练所有区域的模型"""
    print("🤖 开始训练8区域线性回归模型")
    print("=" * 50)
    
    success_count = 0
    total_regions = len(SHELF_REGIONS)
    
    for region_id in SHELF_REGIONS.keys():
        if train_region_model(region_id):
            success_count += 1
        print()
    
    print("=" * 50)
    print(f"🎯 训练完成: {success_count}/{total_regions} 个区域成功")
    
    if success_count == total_regions:
        print("🎉 所有区域模型训练成功!")
    else:
        print("⚠️  部分区域缺少训练数据，请运行collect_region_data.py收集")

if __name__ == "__main__":
    main()