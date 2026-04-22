#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
解析通达信导出的板块成分股数据
将 block 目录下的 txt 文件解析为 JSON 格式
"""

import os
import json
import glob


def is_valid_stock(stock_code):
    """
    判断是否为有效的股票（排除科创板和北证）
    
    Args:
        stock_code: 股票代码
        
    Returns:
        bool: True表示有效，False表示需要过滤
    """
    # 科创板：688开头
    if stock_code.startswith('688'):
        return False
    
    # 北证：8、4、9开头（8xxxxx, 4xxxxx, 9xxxxx）
    if stock_code[0] in ['8', '4', '9']:
        return False
    
    return True


def parse_block_file(file_path, encoding='gbk'):
    """
    解析单个板块文件
    
    Args:
        file_path: 文件路径
        encoding: 文件编码，默认为 gbk
        
    Returns:
        list: 解析后的数据列表（已过滤科创板和北证股票）
    """
    data = []
    filtered_count = 0
    
    try:
        with open(file_path, 'r', encoding=encoding) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                    
                # 按制表符分割
                parts = line.split('\t')
                if len(parts) >= 4:
                    block_code = parts[0].strip()
                    block_name = parts[1].strip()
                    stock_code = parts[2].strip()
                    stock_name = parts[3].strip()
                    
                    # 过滤科创板和北证股票
                    if is_valid_stock(stock_code):
                        data.append({
                            'block_code': block_code,
                            'block_name': block_name,
                            'stock_code': stock_code,
                            'stock_name': stock_name
                        })
                    else:
                        filtered_count += 1
    except UnicodeDecodeError:
        # 如果 gbk 编码失败，尝试其他编码
        try:
            with open(file_path, 'r', encoding='gb2312') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                        
                    parts = line.split('\t')
                    if len(parts) >= 4:
                        block_code = parts[0].strip()
                        block_name = parts[1].strip()
                        stock_code = parts[2].strip()
                        stock_name = parts[3].strip()
                        
                        # 过滤科创板和北证股票
                        if is_valid_stock(stock_code):
                            data.append({
                                'block_code': block_code,
                                'block_name': block_name,
                                'stock_code': stock_code,
                                'stock_name': stock_name
                            })
                        else:
                            filtered_count += 1
        except Exception as e:
            print(f"解析文件 {file_path} 时出错: {e}")
            return [], 0
    except Exception as e:
        print(f"解析文件 {file_path} 时出错: {e}")
        return [], 0
    
    return data, filtered_count


def transform_data_format(all_data):
    """
    转换数据格式：以板块名称为key，包含板块代码和成分股列表
    
    Args:
        all_data: 原始数据列表
        
    Returns:
        dict: 转换后的数据字典
    """
    result = {}
    
    for item in all_data:
        block_name = item['block_name']
        
        # 如果板块不存在，初始化
        if block_name not in result:
            result[block_name] = {
                'block_code': item['block_code'],
                'stocks': []
            }
        
        # 添加成分股
        result[block_name]['stocks'].append({
            'stock_code': item['stock_code'],
            'stock_name': item['stock_name']
        })
    
    return result


def main():
    """主函数"""
    # block 目录路径
    block_dir = './block'
    
    # 获取所有 txt 文件
    txt_files = glob.glob(os.path.join(block_dir, '*.txt'))
    
    if not txt_files:
        print("未找到任何 txt 文件")
        return
    
    print(f"找到 {len(txt_files)} 个板块文件:")
    for file in txt_files:
        print(f"  - {os.path.basename(file)}")
    
    # 存储所有数据
    all_data = []
    total_filtered = 0
    
    # 解析每个文件
    for file_path in txt_files:
        print(f"\n正在解析: {os.path.basename(file_path)}")
        file_data, filtered_count = parse_block_file(file_path)
        print(f"  解析到 {len(file_data)} 条记录，过滤 {filtered_count} 条（科创板/北证）")
        all_data.extend(file_data)
        total_filtered += filtered_count
    
    print(f"\n总共解析到 {len(all_data)} 条记录")
    print(f"总共过滤 {total_filtered} 条记录（科创板/北证股票）")
    
    # 转换数据格式
    transformed_data = transform_data_format(all_data)
    print(f"转换后共有 {len(transformed_data)} 个板块")
    
    # 保存到 JSON 文件
    output_path = './data/block_list.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(transformed_data, f, ensure_ascii=False, indent=2)
    
    print(f"数据已保存到: {output_path}")
    
    # 显示一些示例数据
    if transformed_data:
        print("\n示例数据（前3个板块）:")
        for i, (block_name, block_info) in enumerate(transformed_data.items()):
            if i >= 3:
                break
            print(f"\n  板块: {block_name}")
            print(f"    板块代码: {block_info['block_code']}")
            print(f"    成分股数量: {len(block_info['stocks'])}")
            print(f"    前3只股票:")
            for stock in block_info['stocks'][:3]:
                print(f"      - {stock['stock_code']} | {stock['stock_name']}")


if __name__ == '__main__':
    main()
