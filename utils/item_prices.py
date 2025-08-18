#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
商品价格数据库
从world_state.py迁移的商品价格映射
"""

# 商品价格映射表
ITEM_PRICES = {
    "可口可乐": 3.5,
    "百事可乐": 3.5,
    "红牛": 6.0,
    "农夫山泉矿泉水": 2.5,
    "营养快线": 6.0,
    "娃哈哈 AD钙奶": 5.5,
    "纯牛奶": 2.5,
    "雀巢咖啡": 4.0,
    "牙膏": 7.0,
    "洗发水": 12.0,
    "薯片": 3.5,
    "洽洽瓜子": 5.0,
    "奥利奥饼干": 6.0,
    "维达纸巾": 4.0,
    "橘子": 1.5,
    "苹果": 2.0
}

def get_item_price(item_name: str) -> float:
    """获取商品价格"""
    return ITEM_PRICES.get(item_name, 0.0)

def get_all_items_with_prices() -> dict:
    """获取所有商品及其价格"""
    return ITEM_PRICES.copy()