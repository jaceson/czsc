# read_file_line_by_line.py

def read_file_line_by_line(file_path):
    """逐行读取文件并输出"""
    try:
        plus_val = 0
        minus_val = 0
        plus_num = 0
        minus_num = 0
        with open(file_path, 'r', encoding='utf-8') as file:
            for line_num, line in enumerate(file, 1):
                # 去除行尾的换行符
                line_content = line.rstrip('\n\r')
                if '收益率: ' in line_content and '回测完成' in line_content and '初始资金:' in line_content:
                    arr_contnent = line_content.split('|')
                    if len(arr_contnent) == 4:
                        final_value = arr_contnent[2]
                        final_value = final_value.replace('最终资金: ', '').replace(' ','').replace(',','')
                        final_value = float(final_value)-1000000
                        if final_value == 0:
                            continue
                        if final_value>0:
                            plus_val += final_value
                            plus_num += 1
                        else:
                            minus_val += final_value
                            minus_num += 1
                        print('{}, {}'.format(arr_contnent[1], arr_contnent[2]))
        print('交易次数：{}'.format(plus_num+minus_num))
        print('正收益：{}'.format(plus_val))
        print('负收益：{}'.format(minus_val))
        print('净收益：{}'.format(plus_val+minus_val))
        print('正收益占比：{}'.format(round(100*plus_num/(plus_num+minus_num),2)))
        
    except FileNotFoundError:
        print(f"错误：文件 {file_path} 不存在")
    except Exception as e:
        print(f"读取文件时出错：{e}")

# 使用示例
if __name__ == "__main__":
    # 替换为您的日志文件路径
    file_path = "/Users/jack/Desktop/log.txt"
    read_file_line_by_line(file_path)