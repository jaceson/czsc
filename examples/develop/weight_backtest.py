# https://s0cqcxuy3p.feishu.cn/wiki/Pf1fw1woQi4iJikbKJmcYToznxb
import sys

sys.path.insert(0, r"A:\ZB\git_repo\waditu\czsc")
import czsc
import rs_czsc
import pandas as pd
import streamlit as st

st.set_page_config(layout="wide")


def test_daily_performance():
    rets = [
        0.003,
        -0.0022,
        -0.0004,
        -0.0048,
        -0.0,
        0.005,
        0.0015,
        -0.0017,
        0.0017,
        0.0031,
        -0.0002,
        0.0003,
        -0.0064,
        -0.0006,
        -0.0031,
        0.0027,
        -0.0,
        -0.0013,
        -0.004,
        0.0013,
        -0.0036,
        -0.0008,
        0.0,
        0.002,
        0.0001,
        -0.0007,
        0.0006,
        -0.0006,
        0.0,
        0.0005,
        -0.0017,
        -0.0001,
        0.0008,
        0.0005,
        0.0,
        0.0019,
        -0.003,
        -0.0015,
        0.0016,
        0.0009,
        -0.0002,
        0.0009,
        0.0004,
        0.0033,
        -0.0032,
        0.0057,
        -0.0005,
        -0.0024,
        0.0002,
        0.0022,
        -0.0011,
        -0.0039,
        -0.0002,
        0.0014,
        0.001,
        -0.0012,
        0.0008,
        -0.001,
        0.0,
        0.001,
        -0.0035,
        -0.0014,
        -0.0018,
        -0.0016,
        -0.0002,
        -0.0032,
        -0.0021,
        0.0015,
        0.0008,
        0.0023,
        -0.0034,
        0.0008,
        -0.0001,
        -0.0034,
        0.0043,
        0.0036,
        0.005,
        -0.0005,
        0.0025,
        0.0001,
        -0.0005,
        0.0038,
        -0.0018,
        -0.003,
        -0.0003,
        0.0,
        -0.0013,
        0.0007,
        0.0015,
        -0.001,
        0.0026,
        -0.0009,
        0.0012,
        0.005,
        -0.0045,
        0.0,
        -0.0006,
        0.0011,
        -0.0022,
        -0.0013,
        -0.003,
        0.0,
        0.0027,
        -0.0019,
        -0.0015,
        -0.0001,
        0.0039,
        -0.0001,
        -0.0028,
        0.0007,
        -0.004,
        -0.0024,
        0.0007,
        0.005,
        0.0023,
        0.0001,
        -0.0,
        -0.0011,
        -0.0006,
        -0.0,
        -0.0003,
        0.0012,
        -0.0,
        0.0011,
        -0.0022,
        0.0002,
        0.0007,
        0.0018,
        0.0001,
        0.0029,
        -0.0004,
        0.0062,
        -0.0017,
        -0.0012,
        -0.0,
        -0.0004,
        0.003,
        0.0012,
        0.0015,
        0.0003,
        0.0002,
        0.0029,
        0.0008,
        -0.0011,
        -0.0003,
        0.0054,
        -0.0006,
        0.0019,
        0.0012,
        -0.0008,
        -0.001,
        -0.0034,
        0.0002,
        -0.0017,
        0.0017,
        0.0003,
        -0.0024,
        -0.0022,
        -0.0,
        0.0006,
        -0.0006,
        -0.0005,
        -0.0013,
        0.003,
        -0.0,
        0.0039,
        0.0001,
        0.0011,
        -0.0008,
        0.0011,
        0.0001,
        0.0001,
        0.0028,
        0.0038,
        0.0072,
        -0.0021,
        -0.0001,
        -0.0003,
        -0.0005,
        0.006,
        0.0009,
        0.0039,
        -0.0006,
        0.0071,
        -0.0032,
        0.0023,
        0.0003,
        -0.0043,
        0.0,
        0.0025,
        -0.0019,
        0.0,
        -0.0021,
        -0.0003,
        0.0005,
        0.0034,
        -0.0014,
        -0.0015,
        0.0006,
        -0.0027,
        0.0003,
        0.0003,
        0.0011,
        0.003,
        -0.0003,
        0.0047,
        0.0003,
        0.0035,
        0.0039,
        0.0011,
        0.0089,
        0.001,
        0.0001,
        -0.0004,
        0.0003,
        0.0038,
        -0.0,
        -0.0018,
        0.0004,
        -0.0002,
        0.0011,
        -0.0025,
        0.0015,
        -0.0001,
        -0.0012,
        -0.0014,
        0.0044,
        0.0007,
        0.0009,
        0.0,
        0.0018,
        0.0003,
        -0.0001,
        0.0002,
        0.0006,
        -0.0001,
        -0.0045,
        0.0005,
        -0.0027,
        0.0004,
        -0.0004,
        0.0,
        0.0049,
        -0.0017,
        0.0054,
        -0.005,
        0.0007,
        -0.0003,
        -0.0026,
        -0.0044,
        -0.0016,
        0.0004,
        0.0001,
        0.0002,
        0.003,
        0.0026,
        0.0027,
        -0.0029,
        -0.0005,
        0.0,
        -0.0021,
        0.0004,
        0.0057,
        0.0026,
        0.0113,
        -0.0003,
        0.0068,
        -0.0031,
        0.0068,
        0.0034,
        0.0045,
        0.0,
        -0.0011,
        -0.004,
        0.0003,
        -0.0044,
        -0.0017,
        -0.0,
        -0.0012,
        -0.0026,
        -0.0016,
        -0.0048,
        -0.0002,
        0.0001,
        0.0026,
        0.0005,
        0.0025,
        0.0006,
        0.0053,
        -0.0044,
        -0.0008,
        0.0003,
        -0.0006,
        -0.0,
        -0.0005,
        -0.0002,
        -0.0005,
        0.0004,
        0.0003,
        0.0002,
        0.0003,
        0.0016,
        -0.0003,
        0.0036,
        0.0003,
        -0.0001,
        -0.0035,
        -0.0034,
        -0.0009,
        0.0008,
        -0.0008,
        0.0,
        -0.0002,
        0.0011,
        -0.002,
        -0.0007,
        0.003,
        0.0004,
        0.0022,
        0.0002,
        0.0019,
        -0.0013,
        -0.0021,
        -0.0002,
        -0.0007,
        -0.0004,
        -0.0001,
        -0.0001,
        0.0049,
        -0.0,
        -0.0007,
        -0.0007,
        0.0001,
        -0.0006,
        -0.0005,
        0.0001,
        0.0031,
        0.0004,
        0.0018,
        0.0014,
        0.0034,
        -0.0003,
        0.0025,
        0.0016,
        -0.0004,
        0.0004,
        0.0014,
        -0.0,
        -0.0,
        -0.0011,
        -0.0011,
        -0.0016,
        0.0013,
        -0.0001,
        0.002,
        0.0061,
        0.0024,
        -0.0004,
        -0.0038,
        -0.0,
        -0.0002,
        -0.0004,
        0.0002,
        -0.0015,
        -0.0001,
        0.0028,
        -0.0017,
        0.0003,
        -0.0001,
        0.0003,
        0.005,
        -0.0005,
        -0.0005,
        -0.0016,
        -0.0001,
        0.0047,
        -0.0006,
        0.0005,
        0.004,
        0.0005,
        0.0021,
        -0.002,
        0.0009,
        0.0002,
        0.0026,
        -0.0018,
        0.0002,
        -0.001,
        0.0037,
        -0.0002,
        0.0082,
        0.0066,
        0.0019,
        -0.0004,
        -0.0031,
        -0.0006,
        -0.0003,
        0.0065,
        -0.0063,
        -0.0026,
        0.0023,
        0.0008,
        -0.002,
        -0.0018,
        0.0012,
        0.0006,
        -0.0012,
        0.0002,
        -0.003,
        -0.0024,
        -0.0009,
        0.0015,
        0.0019,
        0.0001,
        -0.0028,
        -0.0013,
        0.0014,
        0.0024,
        -0.0001,
        -0.0017,
        -0.0062,
        -0.0008,
        -0.0059,
        -0.0003,
        0.002,
        0.002,
        0.0001,
        0.0004,
        -0.001,
        -0.0006,
        -0.0033,
        -0.0012,
        -0.001,
        -0.0027,
        -0.0019,
        -0.0002,
        -0.0013,
        0.0014,
        0.0011,
        -0.0002,
        -0.003,
        -0.0002,
        -0.0026,
        -0.0023,
        -0.0004,
        0.0023,
        0.0021,
        -0.0,
        0.0019,
        0.0043,
        -0.0001,
        0.0056,
        0.0019,
        -0.0006,
        0.0053,
        0.0009,
        -0.0,
        0.0057,
        0.0059,
        0.0003,
        0.0096,
        -0.0089,
        0.0001,
        -0.0013,
        -0.0012,
        -0.0003,
        0.0026,
        -0.0018,
        0.0012,
        0.0028,
        0.0059,
        0.0005,
        -0.0044,
        -0.0006,
        0.0007,
        -0.0011,
        -0.0041,
        -0.0003,
        0.0024,
        -0.0025,
        0.0009,
        0.0035,
        0.0002,
        0.0001,
        0.0025,
        -0.0008,
        0.0001,
        -0.0015,
        -0.0042,
        -0.0009,
        0.0,
        0.0041,
        0.0012,
        -0.0034,
        -0.0019,
        0.0004,
        -0.0019,
        -0.0017,
        0.0013,
        0.0006,
        0.0047,
        -0.0031,
        -0.0003,
        0.0044,
        -0.0066,
        0.0014,
        0.0072,
        -0.0045,
        0.0013,
        0.0053,
        -0.0008,
        -0.0,
        0.0014,
        -0.0013,
        -0.0022,
        0.0035,
        -0.0002,
        -0.0004,
        0.0008,
        -0.0035,
        -0.0002,
        -0.0034,
        0.0002,
        -0.0032,
        -0.0027,
        0.0011,
        0.0015,
        -0.0,
        0.0002,
        -0.002,
        0.0003,
        0.0005,
        0.0007,
        0.0055,
        -0.0005,
        0.0023,
        0.0035,
        0.0011,
        0.0005,
        -0.0024,
        -0.0002,
        -0.0027,
        0.0042,
        -0.0043,
        -0.001,
        0.008,
        -0.0,
        -0.0003,
        0.0047,
        -0.0067,
        0.001,
        -0.0033,
        -0.0046,
        -0.0013,
        0.0039,
        -0.0023,
        -0.004,
        -0.0059,
        -0.0014,
        -0.0007,
        -0.0026,
        -0.0003,
        -0.0022,
        -0.0006,
        -0.0,
        -0.0002,
        0.0026,
        0.0047,
        0.0017,
        0.0029,
        0.0,
        0.0034,
        0.0071,
        -0.0036,
        0.0042,
        -0.0001,
        0.0002,
        0.0026,
        0.0051,
        -0.0004,
        0.0033,
        -0.0016,
        0.0021,
        -0.0002,
        -0.0001,
        -0.0,
        -0.0006,
        0.0003,
        -0.0004,
        0.0014,
        0.0052,
        -0.0002,
        -0.0023,
        -0.0029,
        -0.0006,
        0.0015,
        0.0012,
        0.0005,
        -0.0012,
        -0.0044,
        -0.001,
        -0.0002,
        0.0003,
        -0.0039,
        -0.0037,
        -0.0003,
        0.0012,
        0.0017,
        0.0016,
        -0.0018,
        0.0,
        0.0004,
        -0.003,
        0.0025,
        -0.0002,
        -0.0006,
        0.0004,
        -0.0014,
        -0.0005,
        -0.0007,
        0.0012,
        -0.0012,
        0.0004,
        -0.0014,
        0.0006,
        0.0016,
        -0.0018,
        -0.0012,
        -0.0014,
        0.0009,
        0.0002,
        -0.0039,
        0.0,
        0.0019,
        0.0031,
        -0.0006,
        0.0009,
        -0.0002,
        -0.0001,
        -0.0025,
        0.0013,
        0.0028,
        0.003,
        -0.0017,
        0.0005,
        0.0003,
        0.0017,
        -0.0001,
        -0.0003,
        0.0019,
        -0.0024,
        -0.0013,
        -0.0012,
        -0.0035,
        0.0004,
        0.0034,
        -0.0016,
        -0.0025,
        -0.001,
        -0.0026,
        0.0012,
        0.0017,
        0.0016,
        -0.0005,
        0.0033,
        -0.0015,
        -0.0005,
        -0.0018,
        0.0018,
        -0.0033,
        -0.0011,
        0.002,
        0.0029,
        -0.0002,
        -0.0003,
        0.0021,
        0.0025,
        0.004,
        0.0029,
        0.0015,
        0.0014,
        0.0029,
        0.0046,
        0.002,
        0.004,
        0.0032,
        -0.0009,
        -0.0066,
        0.0003,
        -0.0033,
        0.0,
        0.0078,
        0.0026,
        0.0016,
        -0.0034,
        0.0074,
        -0.0045,
        -0.0023,
        0.0006,
        -0.0037,
        -0.005,
        0.0003,
        -0.0008,
        0.0022,
        -0.0009,
        -0.0,
        0.0044,
        -0.002,
        0.0005,
        -0.0011,
        -0.0007,
        0.0025,
        -0.0022,
        -0.0027,
        0.0004,
        -0.003,
        -0.0005,
        -0.0041,
        -0.0019,
        -0.0002,
        0.0003,
        0.0029,
        0.0047,
        -0.0012,
        -0.0013,
        -0.0019,
        -0.0002,
        0.0007,
        0.0031,
        0.0053,
        0.0055,
        0.0037,
        -0.0018,
        -0.0034,
        0.002,
        -0.0002,
        -0.0006,
        0.0017,
        -0.0005,
        0.0016,
        -0.0032,
        0.0006,
        0.0079,
        -0.0029,
        0.0002,
        0.0037,
        -0.0023,
        0.0077,
        -0.0022,
        -0.0011,
        -0.0001,
        -0.0008,
        0.0,
        -0.0055,
        -0.0022,
        -0.0004,
        -0.0001,
        -0.0025,
        -0.0039,
        -0.0002,
        -0.0035,
        0.0009,
        0.0019,
        0.0024,
        0.0062,
        -0.0009,
        0.0034,
        -0.0048,
        -0.0003,
        -0.0033,
        0.003,
        -0.0015,
        0.001,
        0.0028,
        0.0032,
        0.0054,
        0.0027,
        -0.0027,
        -0.0016,
        0.009,
        -0.0058,
        -0.0026,
        0.0014,
        -0.0006,
        0.0005,
        0.0028,
        0.0033,
        0.0015,
        0.0009,
        0.0009,
        -0.0002,
        0.0102,
        -0.0117,
        -0.0024,
        0.0014,
        0.0033,
        -0.0002,
        0.0044,
        -0.0026,
        0.0062,
        0.0029,
        -0.0018,
        0.0004,
        0.0007,
        -0.0028,
        -0.0006,
        0.0023,
        0.0008,
        0.0007,
        -0.0043,
        -0.0031,
        0.0005,
        0.0018,
        -0.0032,
        -0.0007,
        0.0001,
        0.0027,
        0.0013,
        0.0003,
        0.0019,
        -0.0004,
        0.0012,
        -0.0015,
        -0.0012,
        -0.0032,
        -0.0019,
        -0.0007,
        -0.0014,
        0.0042,
        -0.0049,
        -0.0009,
        0.0015,
        0.0004,
        0.0002,
        -0.0022,
        -0.0013,
        -0.0005,
        -0.0012,
        -0.0002,
        0.0018,
        0.0034,
        -0.0012,
        -0.0003,
        0.0045,
        0.0003,
        0.0008,
        0.0012,
        -0.001,
        -0.0039,
        -0.0023,
        0.0003,
        0.0013,
        -0.0013,
        -0.0046,
        -0.0024,
        0.0005,
        -0.0001,
        0.0026,
        0.0007,
        0.0018,
        -0.0008,
        -0.0014,
        0.0003,
        0.0008,
        -0.0018,
        0.0001,
        -0.0029,
        0.0024,
        0.0017,
        -0.0015,
        0.0053,
        -0.0153,
        0.0045,
        0.0016,
        0.0001,
        0.0026,
        0.0008,
        0.0007,
        -0.0039,
        -0.0021,
        0.0001,
        -0.0001,
        -0.0,
        0.0024,
        0.0304,
        0.0084,
        -0.0086,
        -0.0081,
        -0.0016,
        0.0001,
        -0.0012,
        0.0016,
        0.0012,
        -0.0009,
        0.0019,
        -0.0008,
        0.0006,
        0.0036,
        0.0017,
        0.0019,
        -0.0028,
        -0.0016,
        0.0014,
        0.0113,
        0.0039,
        -0.0146,
        0.0032,
        0.0002,
        0.0018,
        0.0185,
        0.0112,
        -0.0109,
        0.0093,
        0.019,
        0.0052,
        0.015,
        0.0181,
        0.0241,
        -0.0058,
        0.0214,
        -0.005,
        0.005,
        0.0064,
        -0.0057,
        0.0023,
        0.0019,
        -0.0076,
        -0.0008,
        -0.0018,
        0.0038,
        -0.0079,
        0.0083,
        -0.0019,
        0.0064,
        -0.008,
        0.0011,
        -0.0063,
        0.0056,
        0.0068,
        0.0037,
        0.0128,
        0.0071,
        -0.0173,
        0.0127,
        -0.0008,
        -0.0027,
        0.0063,
        0.0098,
        -0.0081,
        -0.0013,
        -0.0023,
        -0.0003,
        -0.0001,
        -0.0035,
        -0.0003,
        0.0004,
        0.0108,
        0.0054,
        0.0084,
        -0.0076,
        0.0052,
        -0.0014,
        -0.0077,
        -0.0003,
        -0.0054,
        -0.0012,
        -0.0054,
        0.0004,
        0.0019,
        0.0018,
        0.0013,
        0.0041,
        0.0027,
        -0.0038,
        0.0026,
        0.0013,
        -0.0034,
        -0.0029,
        0.0048,
        -0.0,
        -0.0093,
        -0.0011,
        -0.0021,
        -0.0035,
        0.0008,
        0.0043,
        0.0024,
        0.0008,
        -0.0042,
        -0.0006,
        0.0044,
        -0.0021,
        0.0047,
        0.001,
        -0.0059,
        0.0009,
        0.0,
        -0.0014,
        -0.0036,
        0.0028,
        -0.0011,
        -0.0013,
        0.0002,
        0.004,
        -0.0053,
        -0.0001,
        0.001,
        0.0043,
        0.0004,
        -0.0013,
        0.0052,
        0.0081,
        0.0089,
        -0.0024,
        0.0001,
        0.0026,
        0.0008,
        -0.0016,
        0.001,
        0.001,
        0.0001,
        0.011,
        0.0061,
        0.002,
        0.0053,
        0.0072,
        0.0,
        -0.0082,
        -0.0036,
        0.0027,
        -0.0037,
        0.0021,
        -0.0012,
        -0.0023,
        -0.0022,
        -0.0036,
        0.0046,
        0.0041,
        0.0004,
        -0.0,
        0.0021,
        -0.001,
        0.0009,
        0.0004,
        0.0002,
        0.0058,
        0.0046,
        0.0018,
        -0.0009,
        0.001,
        0.0011,
        -0.003,
        0.0124,
        -0.0061,
        0.0025,
        -0.0051,
        0.0002,
        -0.0018,
        -0.0021,
        0.0045,
        0.0026,
        0.0016,
        -0.0007,
        -0.001,
        0.0024,
        0.0059,
        0.0006,
        -0.0023,
        -0.0003,
        -0.0061,
        -0.0033,
        -0.0069,
        0.0128,
        -0.0,
        0.0015,
        0.0044,
        -0.0,
        -0.0065,
        0.0027,
        -0.0,
        0.0004,
        0.0033,
        -0.0052,
        -0.0001,
        0.0047,
        0.0015,
        0.0037,
        0.0022,
        0.0057,
        0.0125,
        0.0033,
        0.0019,
        -0.0003,
        0.0042,
        0.0013,
        -0.0002,
        0.0097,
        -0.0008,
        -0.003,
        -0.0063,
        0.0041,
        -0.0018,
        0.0014,
        0.0001,
        -0.0053,
        -0.0067,
        -0.0012,
        0.0022,
        0.0035,
        0.0004,
        -0.0049,
        0.0078,
        -0.0042,
        -0.0024,
        -0.0023,
        0.0009,
        0.0006,
        0.0045,
        0.0027,
        -0.0018,
        0.0138,
        -0.0,
        -0.0055,
        -0.0047,
        0.0087,
        0.003,
        -0.0026,
        0.0004,
        -0.0088,
        -0.0052,
        0.0023,
        0.0148,
        0.0043,
        -0.0018,
        -0.0004,
        -0.0082,
        0.0008,
        -0.0043,
        0.0102,
        0.0012,
        -0.0063,
        -0.0081,
        -0.0038,
        0.0027,
        0.0046,
        0.0051,
        0.0034,
        0.0063,
        0.0072,
        0.0058,
        0.0042,
        0.0011,
        0.0024,
        -0.0043,
        -0.0089,
        0.0007,
        -0.0083,
        -0.0008,
        -0.0011,
        -0.0046,
        -0.007,
        -0.0013,
        -0.0026,
        0.0034,
        -0.0002,
        0.0005,
        0.0129,
        0.0039,
        0.0043,
        0.0036,
        -0.0056,
        -0.0032,
        0.0015,
        0.0005,
        -0.0034,
        -0.0044,
        0.0029,
        0.0048,
        0.0114,
        -0.0002,
        0.0163,
        -0.0047,
        0.0059,
        -0.0124,
        0.0119,
        -0.0013,
        0.0005,
        -0.005,
        -0.0026,
        0.0076,
        0.0115,
        0.0022,
        -0.0114,
        0.0008,
        0.0007,
        -0.0088,
        0.0012,
        -0.0011,
        -0.0016,
        -0.003,
        0.012,
        0.0006,
        0.0137,
        -0.0013,
        -0.0043,
        0.0039,
        -0.0084,
        -0.0054,
        -0.0003,
        0.0004,
        0.0016,
        -0.0026,
        -0.0019,
        -0.0011,
        -0.0031,
        0.0011,
        -0.0047,
        -0.0014,
        -0.0046,
        0.0002,
        -0.0045,
        -0.0047,
        0.0022,
        0.0029,
        0.003,
        -0.0005,
        0.0064,
        0.0002,
        0.0016,
        0.0002,
        -0.0008,
        0.0001,
        -0.0044,
        -0.0024,
        0.003,
        -0.0028,
        0.0007,
        0.0157,
        0.0053,
        0.0012,
        -0.0108,
        0.0062,
        0.0168,
        -0.015,
        -0.0097,
        -0.0005,
        0.0011,
        -0.001,
        0.0054,
        -0.0017,
        0.006,
        0.0,
        -0.0085,
        0.0009,
        -0.0017,
        -0.0021,
        0.0026,
        -0.0013,
        0.0038,
        0.0057,
        0.006,
        -0.0031,
        0.0014,
        0.0012,
        0.0015,
        -0.0106,
        0.0065,
        -0.0023,
        -0.0035,
        -0.0031,
        0.0027,
        0.008,
        -0.0069,
        -0.0006,
        -0.0077,
        -0.0066,
        0.0061,
        0.0057,
        -0.0046,
        0.0003,
        -0.0108,
        0.0053,
        -0.002,
        -0.0018,
        0.0045,
        -0.0,
        0.0031,
        -0.0198,
        0.0041,
        -0.0052,
        -0.0021,
        -0.0001,
        -0.0027,
        0.0049,
        -0.0074,
        0.0076,
        0.0016,
        0.0015,
        -0.0009,
        0.0116,
        -0.003,
        0.0002,
        0.0029,
        -0.0,
        0.002,
        0.0003,
        0.0023,
        0.004,
        -0.0121,
        -0.0002,
        0.0022,
        -0.0054,
        0.0014,
        -0.0004,
        0.0035,
        0.0012,
        -0.0058,
        0.0009,
        0.0012,
        0.0031,
        0.0111,
        -0.0001,
        -0.0088,
        0.0002,
        0.0052,
        0.0028,
        0.0009,
        -0.0,
        0.0026,
        -0.001,
        0.0056,
        -0.0036,
        -0.0045,
        0.0013,
        0.0023,
        -0.0007,
        0.0018,
        0.0062,
        -0.0028,
        -0.0012,
        0.0116,
        0.0041,
        0.0183,
        0.0081,
        -0.0134,
        0.0017,
        0.0005,
        0.005,
        0.006,
        -0.0019,
        0.0089,
        0.0123,
        0.0069,
        0.003,
        0.0018,
        -0.0065,
        0.0048,
        0.0039,
        0.0174,
        0.0047,
        0.0001,
        0.0182,
        0.0074,
        -0.0315,
        -0.0073,
        0.0057,
        0.0002,
        0.0096,
        -0.0166,
        -0.0112,
        0.0051,
        0.0164,
        -0.0,
        0.0169,
        0.0039,
        0.0299,
        -0.0271,
        0.0015,
        -0.0003,
        -0.0006,
        0.0006,
        -0.0144,
        -0.0118,
        -0.0074,
        0.0002,
        0.0013,
        0.0085,
        -0.0066,
        -0.0035,
        0.001,
        -0.0001,
        0.0081,
        -0.0027,
        -0.003,
        0.0088,
        -0.0124,
        0.0014,
        -0.0043,
        0.0038,
        0.0068,
        -0.0095,
        0.014,
        -0.0032,
        -0.0056,
        0.0039,
        -0.0067,
        0.0005,
        -0.0051,
        -0.0009,
        -0.0036,
        0.0059,
        0.0067,
        -0.005,
        -0.0018,
        -0.0009,
        -0.0076,
        -0.0021,
        0.0043,
        -0.0023,
        -0.0117,
        0.0007,
        0.0012,
        -0.009,
        -0.0018,
        -0.0059,
        -0.003,
        0.0003,
        -0.0025,
        0.0008,
        0.0006,
        0.0015,
        0.0049,
        -0.0029,
        -0.0003,
        0.0003,
        0.0021,
        -0.0006,
        -0.0039,
        0.0028,
        0.0069,
        -0.0066,
        0.006,
        0.0014,
        -0.0111,
        -0.0015,
        -0.0031,
        0.0018,
        -0.0037,
        -0.0016,
        -0.0073,
        0.0007,
        0.005,
        0.0094,
        -0.0021,
        0.0059,
        -0.0172,
        -0.0056,
        0.0068,
        -0.0117,
        0.0025,
        0.0004,
        -0.0094,
        0.0018,
        0.0012,
        -0.0006,
        -0.0002,
        -0.0003,
        -0.0001,
        0.0003,
        0.0038,
        -0.0051,
        -0.0048,
        -0.0016,
        0.0017,
        0.0103,
        0.0079,
        0.0263,
        0.0043,
        -0.0135,
        0.0203,
        -0.0287,
        -0.0034,
        0.0048,
        0.0012,
        0.0117,
        0.0017,
        -0.0054,
        -0.0111,
        -0.0004,
        0.0007,
        -0.0024,
        -0.0071,
        0.0058,
        0.0015,
        0.0021,
        -0.0006,
        -0.0005,
        0.0081,
        -0.0009,
        -0.0059,
        0.0064,
        -0.0046,
        0.0069,
        0.0023,
        -0.0004,
        -0.0045,
        -0.0,
        0.002,
        0.0049,
        0.005,
        0.0021,
        0.0058,
        -0.0083,
        -0.0033,
        -0.0013,
        0.0039,
        0.0024,
        0.012,
        -0.0053,
        0.002,
        0.0013,
        0.0033,
        0.0006,
        0.0087,
        -0.0011,
        0.0022,
        0.0032,
        -0.0144,
        0.0092,
        0.0,
        -0.0002,
        -0.0036,
        -0.0044,
        -0.0046,
        -0.008,
        -0.0024,
        0.0003,
        -0.0065,
        -0.0004,
        0.0003,
        0.0041,
        0.0066,
        0.0017,
        0.0048,
        -0.0016,
        -0.0031,
        0.001,
        0.0023,
        0.0125,
        0.0086,
        -0.0113,
        -0.0067,
        0.0002,
        0.0014,
        0.0084,
        -0.0024,
        0.0137,
        0.0173,
        0.0017,
        0.0029,
        -0.001,
        0.0035,
        -0.0015,
        0.001,
        -0.0002,
        -0.0094,
        0.0063,
        -0.0006,
        -0.0062,
        0.0144,
        0.0008,
        -0.0116,
        0.0088,
        0.001,
        -0.0104,
        0.0126,
        0.0004,
        0.0065,
        0.0172,
        -0.0026,
        0.0094,
        -0.0138,
        -0.0008,
        0.0013,
        -0.0094,
        -0.0033,
        0.0008,
        -0.0087,
        -0.0007,
        0.0008,
        -0.0136,
        0.0047,
        0.011,
        0.0078,
        -0.0023,
        -0.0123,
        -0.0015,
        -0.0033,
        0.0054,
        -0.0065,
        0.0003,
        -0.0089,
        -0.0049,
        -0.0048,
        -0.0065,
        0.0014,
        -0.0,
        -0.0116,
        0.0017,
        0.0044,
        0.0077,
        0.0041,
        -0.0,
        -0.0095,
        0.0024,
        0.0044,
        0.0005,
        -0.004,
        0.0003,
        -0.0033,
        -0.0007,
        0.001,
        0.008,
        -0.0091,
        -0.0011,
        0.0056,
        -0.003,
        -0.0039,
        0.0037,
        0.0173,
        -0.0055,
        -0.0038,
        -0.0075,
        -0.0029,
        -0.0004,
        0.0072,
        -0.0063,
        -0.0028,
        0.01,
        -0.0111,
        0.0004,
        0.0079,
        0.0006,
        -0.0055,
        0.0012,
        0.0169,
        0.0006,
        -0.0083,
        0.0023,
        -0.0054,
        0.0049,
        -0.0009,
        0.0057,
        0.0026,
        0.0026,
        -0.0033,
        -0.0027,
        0.0013,
        -0.0016,
        0.0024,
        0.0002,
        0.0112,
        0.0022,
        -0.0,
        0.0023,
        -0.0062,
        -0.0007,
        -0.0004,
        0.0019,
        0.0004,
        0.0033,
        0.0045,
        0.0019,
        0.0048,
        0.0048,
        -0.0001,
        -0.0112,
        0.0099,
        -0.0031,
        0.0055,
        0.0011,
        0.0005,
        0.0036,
        -0.0048,
        0.0024,
        0.0019,
        -0.0,
        0.0028,
        0.0003,
        -0.0081,
        -0.0074,
        -0.0011,
        0.0017,
        0.0015,
        -0.0079,
        0.0047,
        -0.0014,
        0.0023,
        0.0116,
        0.0002,
        -0.0019,
        0.0022,
        0.0049,
        -0.0011,
        -0.0074,
        -0.002,
        0.0062,
        -0.0043,
        -0.0033,
        0.0014,
        0.0028,
        0.0011,
        -0.0111,
        -0.0022,
        -0.0047,
        -0.0022,
        -0.0013,
        -0.0021,
        -0.0023,
        0.0017,
        -0.0042,
        -0.0006,
        -0.0043,
        0.0002,
        0.0006,
        0.0069,
        0.0018,
        0.0002,
        0.0006,
        0.0102,
        -0.0016,
        0.0026,
        0.0047,
        -0.0158,
        -0.0052,
        0.0067,
        0.0034,
        0.0033,
        0.0024,
        0.0018,
        -0.0047,
        0.0022,
        0.0013,
        0.0035,
        0.0002,
        0.0002,
        -0.0077,
        -0.0036,
        0.001,
        -0.0065,
        -0.0001,
        0.0015,
        0.0011,
        0.0077,
        -0.0008,
        -0.0033,
        0.0006,
        -0.0046,
        -0.0032,
        -0.0046,
        -0.0026,
        -0.0065,
        0.001,
        0.0008,
        0.0004,
        0.0042,
        -0.0046,
        0.0026,
        -0.0015,
        0.0062,
        0.0019,
        0.0069,
        0.0014,
        -0.0015,
        -0.0006,
        0.0015,
        -0.004,
        -0.0017,
        0.0013,
        -0.0037,
        -0.0002,
        0.0016,
        0.0026,
        -0.0029,
        0.0011,
        0.0039,
        0.0063,
        0.0017,
        0.0067,
        0.0071,
        0.0003,
        -0.0005,
        -0.0011,
        -0.0007,
        0.0034,
        -0.0007,
        -0.0067,
        -0.0002,
        -0.0071,
        -0.0032,
        0.0005,
        0.0001,
        0.0089,
        0.0003,
        -0.0019,
        0.0049,
        -0.001,
        0.0087,
        0.0151,
        0.0054,
        -0.0138,
        -0.0003,
        -0.003,
        0.0019,
        0.0023,
        0.0068,
        0.0044,
        -0.0007,
        -0.0003,
        0.0002,
        -0.002,
        0.0083,
        0.0044,
        0.0001,
        0.0089,
        0.0008,
        0.013,
        0.0015,
        -0.0111,
        -0.0002,
        0.0014,
        -0.0044,
        -0.0031,
        -0.0021,
        -0.0052,
        0.0001,
        -0.006,
        -0.0022,
        0.0009,
        -0.0013,
        0.0006,
        -0.0002,
        0.0058,
        -0.0083,
        -0.0012,
        -0.0002,
        0.0012,
        -0.0004,
        -0.0049,
        -0.0024,
        0.0014,
        -0.0007,
        -0.0052,
        -0.0019,
        0.002,
        -0.0004,
        -0.0004,
        -0.004,
        -0.001,
        -0.0028,
        -0.0042,
        0.0021,
        0.0006,
        0.0063,
        0.0015,
        0.0092,
        0.0118,
        -0.0093,
        -0.001,
        -0.0004,
        0.0124,
        0.0069,
        -0.0033,
        -0.0004,
        0.0001,
        0.0008,
        0.0118,
        0.0062,
        -0.0024,
        -0.0004,
        0.0003,
        -0.0019,
    ]

    s1 = czsc.daily_performance(rets)
    s2 = rs_czsc.daily_performance(rets)
    assert s1 == s2


def test_weight_backtest():
    """从持仓权重样例数据中回测"""
    dfw = pd.read_feather(r"~\Desktop\Users\zengb\Downloads\weight_example.feather")
    # dfw = pd.read_feather(r"~\Desktop\Users\zengb\Downloads\btc_weight_example.feather")

    pw = czsc.WeightBacktest(dfw.copy(), digits=2, fee_rate=0.0002, n_jobs=1, weight_type="ts")
    print("\n", sorted(pw.stats.items()))
    print("Python 版本方法：", dir(pw))

    rw = rs_czsc.WeightBacktest(dfw.copy(), digits=2, fee_rate=0.0002, n_jobs=4, weight_type="ts")
    print("\n", sorted(rw.stats.items()))
    print("RUST 版本方法：", dir(rw))


# # dfw = pd.read_feather(r"~\Desktop\Users\zengb\Downloads\weight_example.feather")
# dfw = pd.read_feather(r"A:\量化研究\BTC策略1H持仓权重和日收益241201\BTC_1H_P01-weights.feather")
# dfw = dfw[["dt", "symbol", "weight", "price"]].copy().reset_index(drop=True)
# dfw.to_feather(r"~\Desktop\Users\zengb\Downloads\btc_weight_example.feather")
# st.dataframe(dfw.tail())
# st.write(dfw.dtypes)
# czsc.show_weight_backtest(dfw)
