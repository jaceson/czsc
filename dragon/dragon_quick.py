import json
import sys
import os
import logging
from pytdx.hq import TdxHq_API

# 添加项目根目录到 Python 路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.MyTT import *
from czsc_daily_util import *

# 配置日志
logger = logging.getLogger('dragon_quick')
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
# 简化版测试 - 不依赖外部数据源
def quick_test():
    """快速测试龙头战法逻辑"""
    
    with open('../data/block_list.json', 'r', encoding='utf-8') as f:
        block_data = json.load(f)
    
    print("=" * 60)
    print("龙头战法 - 概念叠加分析")
    print("=" * 60)
    
    # 统计每只股票所属板块数量
    stock_blocks = {}
    index_codes = ['880674', '880682', '880506', '880966', '880546', '880659', '880930', '880952', '880541', '880945', '880566', '880716', '880548', '880969']
    # 初始化 通达信API
    tdx_api = TdxHq_API()
    try:
        # ping shtdx.gtjas.com 或者 hq.cjis.cn
        if tdx_api.connect('114.28.173.137', 7709):
            pass
        else:
            logger.error(f"通达信4PI 初始化失败")
            return
    except Exception as e:
        logger.error(f"通达信API 初始化失败: {e}")
        return
        
    for block_name, block_info in block_data.items():
        if block_info['block_code'] not in index_codes:
            continue
        for stock in block_info['stocks']:
            code = stock['stock_code']
            if code not in stock_blocks:
                stock_blocks[code] = {'name': stock['stock_name'], 'blocks': []}
            stock_blocks[code]['blocks'].append(block_name)
    
    # 找出多概念叠加股
    multi_concept = []
    for code, info in stock_blocks.items():
        if len(info['blocks']) >= 5:
            multi_concept.append({
                'code': code,
                'name': info['name'],
                'block_count': len(info['blocks']),
                'blocks': info['blocks'][:8]
            })
    
    multi_concept.sort(key=lambda x: x['block_count'], reverse=True)
    
    print("\n【多概念叠加股 - 潜在龙头】")
    for s in multi_concept[:20]:
        print(f"{s['code']} {s['name']}: {s['block_count']}个概念")
        print(f"  概念: {', '.join(s['blocks'])}")
        print()
    
    # 热门板块统计
    block_sizes = [(name, len(info['stocks'])) for name, info in block_data.items()]
    block_sizes.sort(key=lambda x: x[1], reverse=True)
    
    print("\n【热门板块TOP 20】")
    for i, (name, size) in enumerate(block_sizes[:20], 1):
        print(f"{i:2d}. {name}: {size}只成分股")
    
    return stock_blocks, block_sizes

if __name__ == "__main__":
    quick_test()