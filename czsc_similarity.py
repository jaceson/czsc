#!/usr/bin/env python3
"""
基于K线图像相似度的股票筛选工具

流程：
  1. 将每只股票的K线走势渲染为标准图像（含均线、成交量）
  2. 使用预训练 ResNet18 提取图像特征向量 (512-dim)
  3. 通过余弦相似度检索最相似的股票

用法：
  python czsc_similarity.py build                       # 构建全市场特征索引
  python czsc_similarity.py query <symbol> [-n 20]      # 查询相似股票
  python czsc_similarity.py query <symbol> --from <策略> # 在指定策略结果中查询
  python czsc_similarity.py query <symbol> --start 2024-01-01 --end 2024-03-01  # 按历史区间匹配最新走势
  python czsc_similarity.py list-strategies             # 列出可用策略
  python czsc_similarity.py list-stocks [--search 关键词] # 列出/搜索股票
"""

import argparse
import json
import os
import ssl
import time
import warnings
ssl._create_default_https_context = ssl._create_unverified_context

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from PIL import Image
from tqdm import tqdm

warnings.filterwarnings('ignore')

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
CACHE_DIR = os.path.join(DATA_DIR, '.cache')
STOCK_LIST_FILE = os.path.join(DATA_DIR, 'sh_sz_stock.json')
EMBEDDING_FILE = os.path.join(DATA_DIR, 'embeddings.npz')
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
LOOKBACK = 60
IMG_SIZE = (224, 224)


# ─── 图像变换 ──────────────────────────────────────────
from torchvision import transforms as T

IMG_TRANSFORM = T.Compose([
    T.ToPILImage(),
    T.Resize(256),
    T.CenterCrop(224),
    T.ToTensor(),
    T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])

# mplfinance 暗色主题风格
_MPF_MC = mpf.make_marketcolors(
    up='#ff4d4d', down='#33cc33',
    wick={'up': '#ff4d4d', 'down': '#33cc33'},
    edge={'up': '#ff4d4d', 'down': '#33cc33'},
    volume={'up': '#ff4d4d', 'down': '#33cc33'},
)
MPF_STYLE = mpf.make_mpf_style(
    base_mpl_style='dark_background',
    marketcolors=_MPF_MC,
    gridaxis='both',
    gridstyle=':',
    gridcolor='#555555',
    y_on_right=True,
)


# ════════════════════════════════════════════════════════
#  1. 数据加载
# ════════════════════════════════════════════════════════

def load_stock_list():
    with open(STOCK_LIST_FILE, encoding='utf-8') as f:
        return json.load(f)


def get_stock_symbols():
    stock_list = load_stock_list()
    return [list(s.keys())[0] for s in stock_list]


def get_stock_name_map():
    stock_list = load_stock_list()
    return {list(s.keys())[0]: list(s.values())[0] for s in stock_list}


def load_cached_data(symbol):
    for fname in os.listdir(CACHE_DIR):
        if fname.startswith(symbol + '_') and fname.endswith('.csv'):
            df = pd.read_csv(os.path.join(CACHE_DIR, fname))
            df = df.dropna()
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            return df
    return None


def load_cached_data_by_range(symbol, start_date, end_date):
    for fname in os.listdir(CACHE_DIR):
        if fname.startswith(symbol + '_') and fname.endswith('.csv'):
            df = pd.read_csv(os.path.join(CACHE_DIR, fname))
            df = df.dropna()
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            mask = (df['date'] >= start_date) & (df['date'] <= end_date)
            return df[mask]
    return None


def df_to_mpf_range(df, start_date, end_date):
    df = df[(df['date'] >= start_date) & (df['date'] <= end_date)].copy()
    df = df.rename(columns={
        'open': 'Open', 'high': 'High', 'low': 'Low',
        'close': 'Close', 'volume': 'Volume',
    })
    df = df.set_index('date')
    df.index.name = 'Date'
    return df[['Open', 'High', 'Low', 'Close', 'Volume']]


def df_to_mpf(df, lookback=LOOKBACK):
    df = df.tail(lookback).copy()
    df = df.rename(columns={
        'open': 'Open', 'high': 'High', 'low': 'Low',
        'close': 'Close', 'volume': 'Volume',
    })
    df = df.set_index('date')
    df.index.name = 'Date'
    return df[['Open', 'High', 'Low', 'Close', 'Volume']]


# ════════════════════════════════════════════════════════
#  2. 图表渲染
# ════════════════════════════════════════════════════════

def render_kline_image(df_mpf):
    dpi = 70
    figsize_inch = (IMG_SIZE[0] / dpi, IMG_SIZE[1] / dpi)

    try:
        fig, axes = mpf.plot(
            df_mpf,
            type='candle',
            volume=True,
            mav=(5, 10, 20, 60),
            style=MPF_STYLE,
            returnfig=True,
            figsize=figsize_inch,
            tight_layout=True,
            axisoff=True,
        )
    except Exception:
        return None

    fig.set_dpi(dpi)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    fig.canvas.draw()

    rgba = np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8)
    w, h = fig.canvas.get_width_height()
    rgba = rgba.reshape((h, w, 4))
    img = rgba[:, :, :3].copy()
    plt.close(fig)
    return img


# ════════════════════════════════════════════════════════
#  3. 特征提取
# ════════════════════════════════════════════════════════

_model = None


def load_model(device=DEVICE):
    global _model
    if _model is None:
        import torchvision.models as models
        m = models.resnet18(weights=models.ResNet18_Weights.IMAGENET1K_V1)
        m.fc = nn.Identity()
        m = m.to(device)
        m.eval()
        _model = m
    return _model


def extract_embedding(image, model, device=DEVICE):
    tensor = IMG_TRANSFORM(image).unsqueeze(0).to(device)
    with torch.no_grad():
        feat = model(tensor).cpu().numpy().flatten()
    feat = feat / (np.linalg.norm(feat) + 1e-10)
    return feat


# ════════════════════════════════════════════════════════
#  4. 索引构建与查询
# ════════════════════════════════════════════════════════

def build_index(symbols, lookback=LOOKBACK, model=None, device=DEVICE):
    if model is None:
        model = load_model(device)

    embeddings = []
    valid_symbols = []

    for sym in tqdm(symbols, desc='构建索引'):
        try:
            df = load_cached_data(sym)
            if df is None or len(df) < lookback:
                continue
            img = render_kline_image(df_to_mpf(df, lookback))
            if img is None:
                continue
            feat = extract_embedding(img, model, device)
            embeddings.append(feat)
            valid_symbols.append(sym)
        except Exception:
            continue

    return np.array(embeddings), valid_symbols


def save_index(embeddings, symbols, path=EMBEDDING_FILE):
    np.savez_compressed(path, embeddings=embeddings, symbols=symbols)
    print(f'索引已保存: {path} ({len(symbols)} 只)')


def load_index(path=EMBEDDING_FILE):
    data = np.load(path, allow_pickle=True)
    return data['embeddings'], data['symbols'].tolist()


def query_similar(query_symbol, embeddings, symbols, top_k=20):
    if query_symbol not in symbols:
        return []
    idx = symbols.index(query_symbol)
    query_vec = embeddings[idx]
    sims = embeddings @ query_vec
    order = np.argsort(sims)[::-1]
    results = []
    for i in order:
        if symbols[i] == query_symbol:
            continue
        results.append((symbols[i], float(sims[i])))
        if len(results) >= top_k:
            break
    return results


# ════════════════════════════════════════════════════════
#  5. 策略辅助
# ════════════════════════════════════════════════════════

def list_strategies():
    strategies = []
    for fname in os.listdir(DATA_DIR):
        if not fname.endswith('.json'):
            continue
        if fname in ('sh_sz_stock.json', 'rz_rq_stock.json', 'block_list.json',
                     'holder_all_stocks.json', 'holder_disabled_stocks.json',
                     'embeddings.npz'):
            continue
        strategies.append(fname.replace('.json', ''))
    return sorted(strategies)


def load_strategy_stocks(strategy_name):
    filepath = os.path.join(DATA_DIR, f'{strategy_name}.json')
    if not os.path.exists(filepath):
        return None
    with open(filepath, encoding='utf-8') as f:
        data = json.load(f)
    if not data:
        return []
    if isinstance(data[0], str):
        return data
    elif isinstance(data[0], dict):
        return [item.get('symbol', '') for item in data if 'symbol' in item]
    return []


# ════════════════════════════════════════════════════════
#  6. CLI
# ════════════════════════════════════════════════════════

def cmd_build(args):
    print(f'设备: {DEVICE}')
    print('加载股票列表...')
    symbols = get_stock_symbols()
    print(f'共 {len(symbols)} 只股票')
    model = load_model(DEVICE)
    t0 = time.time()
    embeddings, valid_symbols = build_index(symbols, args.lookback, model, DEVICE)
    elapsed = time.time() - t0
    rate = len(valid_symbols) / elapsed if elapsed > 0 else 0
    print(f'完成: {len(valid_symbols)} 只, 耗时 {elapsed:.0f}s ({rate:.1f} 只/秒)')
    save_index(embeddings, valid_symbols)


def _compute_embedding(symbol, lookback=LOOKBACK, model=None, device=DEVICE):
    df = load_cached_data(symbol)
    if df is None or len(df) < lookback:
        return None
    img = render_kline_image(df_to_mpf(df, lookback))
    if img is None:
        return None
    return extract_embedding(img, model, device)


def query_by_range(symbol, start_date, end_date, candidates, top_k=20,
                   model=None, device=DEVICE):
    if model is None:
        model = load_model(device)

    df_q = load_cached_data_by_range(symbol, start_date, end_date)
    if df_q is None or len(df_q) < 5:
        print(f'错误: {symbol} 在 {start_date}~{end_date} 数据不足')
        return []

    lookback = len(df_q)
    # 参考股票用历史区间渲染（非最新数据）
    img = render_kline_image(df_to_mpf_range(df_q, start_date, end_date))
    if img is None:
        return []
    query_vec = extract_embedding(img, model, device)

    # 如果候选池较大且 lookback 与索引一致，直接用索引加速
    if len(candidates) > 500:
        idx_emb, idx_sym = load_index(EMBEDDING_FILE)
        if LOOKBACK == lookback:
            sims = idx_emb @ query_vec
            order = np.argsort(sims)[::-1]
            results = []
            for i in order:
                if idx_sym[i] == symbol:
                    continue
                results.append((idx_sym[i], float(sims[i])))
                if len(results) >= top_k:
                    break
            return results
        print(f'参考区间共 {lookback} 根K线, 索引含 {LOOKBACK} 根, 需逐票计算...')

    results = []
    for c in tqdm(candidates, desc='比对'):
        if c == symbol:
            continue
        vec = _compute_embedding(c, lookback, model, device)
        if vec is None:
            continue
        sim = float(query_vec @ vec)
        results.append((c, sim))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]


def cmd_query(args):
    symbol = args.symbol
    name_map = get_stock_name_map()
    model = load_model(DEVICE)

    # 按历史区间匹配最新走势
    if args.start_date and args.end_date:
        print(f'参考区间: {symbol}  {args.start_date} ~ {args.end_date}')

        if args.from_strategy:
            candidates = load_strategy_stocks(args.from_strategy)
            if candidates is None:
                print(f'未找到策略 "{args.from_strategy}"')
                return
            print(f'候选池: 策略({args.from_strategy}) {len(candidates)} 只')
        else:
            if not os.path.exists(EMBEDDING_FILE):
                print('未找到特征索引，请先运行: python czsc_similarity.py build')
                return
            _, all_symbols = load_index(EMBEDDING_FILE)
            candidates = all_symbols

        results = query_by_range(symbol, args.start_date, args.end_date,
                                  candidates, args.n, model, DEVICE)
        if not results:
            print('无匹配结果')
            return

        print(f'\n参考图形: {symbol} ({name_map.get(symbol, "")}) [{args.start_date} ~ {args.end_date}]')
        print(f'匹配最新走势 Top-{len(results)}:\n')
        print(f'  {"#":<4} {"代码":<12} {"名称":<10} {"相似度":<8}')
        print(f'  {"-"*35}')
        for i, (sym, sim) in enumerate(results, 1):
            name = name_map.get(sym, '')
            print(f'  {i:<4} {sym:<12} {name:<10} {sim:.4f}')

        if args.save:
            out = [{'symbol': sym, 'similarity': round(sim, 4), 'name': name_map.get(sym, '')}
                   for sym, sim in results]
            with open(args.save, 'w', encoding='utf-8') as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
            print(f'\n结果已保存: {args.save}')
        return

    # 标准模式：使用预建索引
    if not os.path.exists(EMBEDDING_FILE):
        print('未找到特征索引，请先运行: python czsc_similarity.py build')
        return
    embeddings, symbols = load_index(EMBEDDING_FILE)
    if symbol not in symbols:
        print(f'错误: {symbol} 不在索引中')
        return

    if args.from_strategy:
        candidates = load_strategy_stocks(args.from_strategy)
        if candidates is None:
            print(f'未找到策略 "{args.from_strategy}"')
            return
        candidates = [s for s in candidates if s in symbols]
        print(f'策略({args.from_strategy}): {len(candidates)} 只')
        query_vec = embeddings[symbols.index(symbol)]
        results = []
        for c in candidates:
            if c == symbol:
                continue
            sim = float(embeddings[symbols.index(c)] @ query_vec)
            results.append((c, sim))
        results.sort(key=lambda x: x[1], reverse=True)
        results = results[:args.n]
    else:
        results = query_similar(symbol, embeddings, symbols, args.n)

    if not results:
        print('无结果')
        return

    print(f'\n查询: {symbol} ({name_map.get(symbol, "")})')
    print(f'Top-{len(results)}:\n')
    print(f'  {"#":<4} {"代码":<12} {"名称":<10} {"相似度":<8}')
    print(f'  {"-"*35}')
    for i, (sym, sim) in enumerate(results, 1):
        name = name_map.get(sym, '')
        print(f'  {i:<4} {sym:<12} {name:<10} {sim:.4f}')

    if args.save:
        out = [{'symbol': sym, 'similarity': round(sim, 4), 'name': name_map.get(sym, '')}
               for sym, sim in results]
        with open(args.save, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f'\n结果已保存: {args.save}')


def cmd_list_strategies(args):
    strategies = list_strategies()
    if not strategies:
        print('无策略文件')
        return
    print('可用策略:')
    for s in strategies:
        count = len(load_strategy_stocks(s) or [])
        print(f'  {s:<24} {count} 只')


def cmd_list_stocks(args):
    symbols = get_stock_symbols()
    name_map = get_stock_name_map()
    print(f'共 {len(symbols)} 只股票')
    if args.search:
        q = args.search.lower()
        for sym, name in name_map.items():
            if q in sym.lower() or q in name.lower():
                print(f'  {sym:<12} {name}')
    else:
        for sym in symbols[:30]:
            print(f'  {sym:<12} {name_map[sym]}')
        print(f'  ... 共 {len(symbols)} 只, 使用 --search 搜索')


def main():
    parser = argparse.ArgumentParser(
        description='K线图像相似度股票筛选工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python czsc_similarity.py build
  python czsc_similarity.py query sh.600000 -n 20
  python czsc_similarity.py query sh.600000 --from 黄金分割线抄底 -n 10
  python czsc_similarity.py query sh.600000 --start 2024-01-01 --end 2024-03-01
  python czsc_similarity.py query sh.600000 --start 2024-01-01 --end 2024-03-01 --from 黄金分割线抄底
  python czsc_similarity.py query sh.600000 --save results.json
  python czsc_similarity.py list-strategies
  python czsc_similarity.py list-stocks --search 银行
        """,
    )
    subparsers = parser.add_subparsers(dest='command')

    p_build = subparsers.add_parser('build', help='构建全市场特征索引')
    p_build.add_argument('--lookback', type=int, default=LOOKBACK,
                         help=f'K线根数 (默认: {LOOKBACK})')

    p_query = subparsers.add_parser('query', help='查询相似股票')
    p_query.add_argument('symbol', help='股票代码, 如 sh.600000')
    p_query.add_argument('-n', type=int, default=20, help='返回数量 (默认: 20)')
    p_query.add_argument('--start', dest='start_date', default=None,
                         help='参考区间起始日, 如 2024-01-01')
    p_query.add_argument('--end', dest='end_date', default=None,
                         help='参考区间结束日, 如 2024-03-01')
    p_query.add_argument('--from', dest='from_strategy', default=None,
                         help='在指定策略结果中查询')
    p_query.add_argument('--save', default=None, help='结果保存到 JSON 文件')

    subparsers.add_parser('list-strategies', help='列出可用策略')

    p_lstock = subparsers.add_parser('list-stocks', help='列出/搜索股票')
    p_lstock.add_argument('--search', default=None, help='搜索关键词')

    args = parser.parse_args()

    cmds = {
        'build': cmd_build,
        'query': cmd_query,
        'list-strategies': cmd_list_strategies,
        'list-stocks': cmd_list_stocks,
    }
    fn = cmds.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
