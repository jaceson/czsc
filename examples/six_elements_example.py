# -*- coding: utf-8 -*-
"""
六大环节交易系统使用示例
========================

本示例展示如何使用六大环节交易系统进行股票分析。
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from czsc.six_elements import (
    IndustryResearch,
    BlockPopularity,
    TrackLeader,
    ForwardPE,
    SentimentCycle,
    PriceVolumePattern,
    SixElementSystem,
)


def example_industry_research():
    """产业研究示例"""
    print("\n" + "=" * 60)
    print("【产业研究示例】")
    print("=" * 60)
    
    # 初始化产业研究模块
    research = IndustryResearch(data_source='akshare')
    
    # 获取热门行业
    print("\n热门行业TOP 5:")
    hot_industries = research.find_hot_industries(top_n=5)
    for i, industry in enumerate(hot_industries, 1):
        print(f"{i}. {industry['name']}: 评分 {industry['total_score']:.2f}, 等级 {industry['rank']}")
    
    # 生成行业研究报告
    if hot_industries:
        report = research.get_industry_report(hot_industries[0]['name'])
        print(f"\n{report['title']}")
        print(f"综合评分: {report['summary']['total_score']:.2f}")
        print(f"投资建议: {report['recommendation']}")


def example_block_popularity():
    """板块人气龙头示例"""
    print("\n" + "=" * 60)
    print("【板块人气龙头示例】")
    print("=" * 60)
    
    # 初始化板块人气龙头模块
    block = BlockPopularity(data_source='akshare')
    
    # 寻找多概念叠加股
    print("\n多概念叠加股TOP 5:")
    multi_concept = block.find_multi_concept_stocks(min_blocks=5)
    for i, stock in enumerate(multi_concept[:5], 1):
        print(f"{i}. {stock['stock_code']}: {stock['block_count']}个概念")
        print(f"   概念: {', '.join(stock['blocks'][:3])}...")
    
    # 寻找热门板块
    print("\n热门概念板块TOP 5:")
    hot_blocks = block.find_hot_blocks(block_type='concept', top_n=5)
    for i, b in enumerate(hot_blocks, 1):
        print(f"{i}. {b['name']}: 热度 {b['heat_score']:.2f}, 等级 {b['heat_level']}")


def example_track_leader():
    """产业赛道龙头示例"""
    print("\n" + "=" * 60)
    print("【产业赛道龙头示例】")
    print("=" * 60)
    
    # 初始化产业赛道龙头模块
    track = TrackLeader(data_source='akshare')
    
    # 寻找高成长赛道
    print("\n高成长赛道TOP 5:")
    high_growth = track.find_high_growth_tracks(top_n=5)
    for i, t in enumerate(high_growth, 1):
        print(f"{i}. {t['track_name']}: 平均成长性 {t['avg_growth_score']:.2f}")
        print(f"   类别: {t['category']}, 龙头数: {t['leader_count']}")
    
    # 识别赛道龙头
    if high_growth:
        leaders = track.identify_leader(high_growth[0]['track_name'], top_n=3)
        print(f"\n{high_growth[0]['track_name']}赛道龙头:")
        for i, leader in enumerate(leaders, 1):
            print(f"  {i}. {leader['stock_name']}: 综合评分 {leader['total_score']:.2f}")


def example_forward_pe():
    """前瞻动态PE示例"""
    print("\n" + "=" * 60)
    print("【前瞻动态PE示例】")
    print("=" * 60)
    
    # 初始化前瞻动态PE模块
    pe = ForwardPE(data_source='akshare')
    
    # 计算前瞻PE
    stock_code = "600519"  # 示例：贵州茅台
    print(f"\n{stock_code}估值分析:")
    forward_pe = pe.calculate_forward_pe(stock_code, expected_growth=0.15)
    print(f"  当前PE: {forward_pe.get('current_pe', 0):.2f}")
    print(f"  1年前瞻PE: {forward_pe.get('forward_pe_1y', 0):.2f}")
    print(f"  PEG: {forward_pe.get('peg', 0):.2f}")
    print(f"  估值水平: {forward_pe.get('valuation_level', '未知')}")
    
    # 分析PE分位数
    pe_percentile = pe.analyze_pe_percentile(stock_code)
    print(f"\n  PE历史分位数: {pe_percentile.get('percentile', 0):.1f}%")
    print(f"  估值位置: {pe_percentile.get('position', '未知')}")


def example_sentiment_cycle():
    """情绪周期示例"""
    print("\n" + "=" * 60)
    print("【情绪周期示例】")
    print("=" * 60)
    
    # 初始化情绪周期模块
    sentiment = SentimentCycle()
    
    # 模拟市场数据
    import numpy as np
    np.random.seed(42)
    market_data = {
        'closes': list(np.random.uniform(3000, 3500, 100)),
        'volumes': list(np.random.uniform(1e9, 2e9, 100)),
        'opens': list(np.random.uniform(3000, 3500, 100)),
        'highs': list(np.random.uniform(3000, 3500, 100)),
        'lows': list(np.random.uniform(3000, 3500, 100)),
    }
    
    # 计算情绪评分
    sentiment_result = sentiment.calculate_sentiment_score(market_data)
    print(f"\n市场情绪评分: {sentiment_result['total_score']:.2f}")
    
    # 识别情绪阶段
    stage = sentiment.identify_sentiment_stage(sentiment_result['total_score'])
    print(f"情绪阶段: {stage['stage']}")
    print(f"描述: {stage['description']}")
    print(f"操作建议: {stage['action']}")


def example_price_volume_pattern():
    """图形量价示例"""
    print("\n" + "=" * 60)
    print("【图形量价示例】")
    print("=" * 60)
    
    # 初始化图形量价模块
    pv = PriceVolumePattern()
    
    # 模拟价格数据
    import numpy as np
    np.random.seed(42)
    closes = list(np.cumsum(np.random.randn(50)) + 100)
    opens = [c + np.random.randn() for c in closes]
    highs = [max(o, c) + abs(np.random.randn()) for o, c in zip(opens, closes)]
    lows = [min(o, c) - abs(np.random.randn()) for o, c in zip(opens, closes)]
    volumes = list(np.random.uniform(1e6, 1e7, 50))
    
    # 识别K线形态
    patterns = pv.identify_kline_patterns(opens, highs, lows, closes)
    print(f"\n识别到的K线形态: {len(patterns)}个")
    for p in patterns:
        print(f"  - {p['pattern']}: {p['signal']}")
    
    # 分析量价关系
    volume_price = pv.analyze_volume_price(closes, volumes)
    print(f"\n量价关系: {volume_price.get('relationship', '未知')}")
    print(f"描述: {volume_price.get('description', '未知')}")
    print(f"信号: {volume_price.get('signal', '未知')}")


def example_six_element_system():
    """六大环节交易系统完整示例"""
    print("\n" + "=" * 60)
    print("【六大环节交易系统完整示例】")
    print("=" * 60)
    
    # 初始化六大环节交易系统
    system = SixElementSystem(data_source='akshare')
    
    # 准备示例数据
    import numpy as np
    np.random.seed(42)
    
    market_data = {
        'closes': list(np.random.uniform(3000, 3500, 100)),
        'volumes': list(np.random.uniform(1e9, 2e9, 100)),
        'opens': list(np.random.uniform(3000, 3500, 100)),
        'highs': list(np.random.uniform(3000, 3500, 100)),
        'lows': list(np.random.uniform(3000, 3500, 100)),
    }
    
    price_data = {
        'opens': list(np.random.uniform(100, 120, 50)),
        'highs': list(np.random.uniform(100, 120, 50)),
        'lows': list(np.random.uniform(100, 120, 50)),
        'closes': list(np.cumsum(np.random.randn(50)) + 100),
        'volumes': list(np.random.uniform(1e6, 1e7, 50)),
    }
    
    # 运行完整分析
    result = system.run_full_analysis(
        stock_code="600519",
        industry_name="白酒",
        block_name="白酒",
        track_name="白酒",
        market_data=market_data,
        price_data=price_data,
    )
    
    # 生成并打印报告
    report = system.generate_report(result)
    print(report)
    
    return result


def main():
    """主函数"""
    print("六大环节交易系统使用示例")
    print("=" * 60)
    
    # 依次运行各模块示例
    example_industry_research()
    example_block_popularity()
    example_track_leader()
    example_forward_pe()
    example_sentiment_cycle()
    example_price_volume_pattern()
    
    # 运行完整系统示例
    result = example_six_element_system()
    
    print("\n" + "=" * 60)
    print("示例运行完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
