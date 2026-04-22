# 初始化策略
dragon_strategy = DragonTradingStrategy('block_list.json')

# 查看热门板块
hot_blocks = dragon_strategy.strategy.get_hot_blocks(10)
print("=== 热门板块（成分股数量） ===")
for b in hot_blocks:
    print(f"{b['block_name']}: {b['stock_count']}只")

# 查看多概念叠加股
multi_stocks = dragon_strategy.strategy.find_cross_stocks(min_blocks=5)
print("\n=== 多概念叠加股（潜在龙头） ===")
for s in multi_stocks[:15]:
    print(f"{s['code']} {s['name']}: {s['block_count']}个概念")
    print(f"  概念: {', '.join(s['blocks'][:5])}...")

# 示例：获取特定板块成分股
new_energy_stocks = dragon_strategy.strategy.get_block_stocks('新能源车')
print(f"\n=== 新能源车板块成分股数量: {len(new_energy_stocks)}")