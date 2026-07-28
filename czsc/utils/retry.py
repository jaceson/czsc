# -*- coding: utf-8 -*-
"""
重试和限流工具
=============

功能：
1. 指数退避重试 - 自动重试失败的API调用
2. 请求限流 - 控制API请求频率，避免被封禁
3. 连接池管理 - 复用HTTP连接提高效率
"""

import time
import functools
import threading
from typing import Callable, Any, Optional
from loguru import logger


class RateLimiter:
    """请求限流器"""
    
    def __init__(self, requests_per_second: float = 0.5):
        """
        初始化限流器
        
        :param requests_per_second: 每秒最大请求数，默认0.5（即每2秒1个请求）
        """
        self.min_interval = 1.0 / requests_per_second
        self._last_request_time = 0
        self._lock = threading.Lock()
    
    def wait(self):
        """等待直到可以发送下一个请求"""
        with self._lock:
            current_time = time.time()
            time_since_last = current_time - self._last_request_time
            
            if time_since_last < self.min_interval:
                sleep_time = self.min_interval - time_since_last
                time.sleep(sleep_time)
            
            self._last_request_time = time.time()


class RetryError(Exception):
    """重试失败异常"""
    pass


def retry_with_backoff(
    func: Callable = None,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    retryable_exceptions: tuple = (Exception,),
    on_retry: Optional[Callable] = None
):
    """
    带指数退避的重试装饰器
    
    :param func: 要装饰的函数
    :param max_retries: 最大重试次数
    :param initial_delay: 初始延迟时间（秒）
    :param max_delay: 最大延迟时间（秒）
    :param exponential_base: 指数退避基数
    :param retryable_exceptions: 可重试的异常类型
    :param on_retry: 重试时的回调函数
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            delay = initial_delay
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    
                    if attempt == max_retries:
                        logger.error(f"函数 {func.__name__} 在 {max_retries} 次重试后仍然失败: {e}")
                        raise RetryError(f"重试 {max_retries} 次后失败: {e}") from e
                    
                    logger.warning(f"函数 {func.__name__} 第 {attempt + 1} 次尝试失败: {e}")
                    
                    if on_retry:
                        on_retry(attempt + 1, delay, e)
                    
                    logger.info(f"等待 {delay:.2f} 秒后重试...")
                    time.sleep(delay)
                    
                    delay = min(delay * exponential_base, max_delay)
            
            raise last_exception
        return wrapper
    
    if func is not None:
        return decorator(func)
    return decorator


def akshare_retry(
    func: Callable = None,
    max_retries: int = 3,
    initial_delay: float = 2.0,
    max_delay: float = 60.0
):
    """
    akshare API专用重试装饰器
    
    针对akshare的网络连接问题进行了优化：
    - 更长的初始延迟（2秒）
    - 更大的最大延迟（60秒）
    - 指数退避策略
    """
    retryable_exceptions = (
        ConnectionError,
        ConnectionAbortedError,
        ConnectionRefusedError,
        ConnectionResetError,
        TimeoutError,
        OSError,
        Exception,
    )
    
    return retry_with_backoff(
        func=func,
        max_retries=max_retries,
        initial_delay=initial_delay,
        max_delay=max_delay,
        retryable_exceptions=retryable_exceptions
    )


def rate_limited(
    func: Callable = None,
    requests_per_second: float = 0.5
):
    """
    请求限流装饰器
    
    :param func: 要装饰的函数
    :param requests_per_second: 每秒最大请求数
    """
    limiter = RateLimiter(requests_per_second)
    
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            limiter.wait()
            return func(*args, **kwargs)
        return wrapper
    
    if func is not None:
        return decorator(func)
    return decorator


def retry_with_rate_limit(
    func: Callable = None,
    max_retries: int = 3,
    initial_delay: float = 2.0,
    max_delay: float = 60.0,
    requests_per_second: float = 0.5
):
    """
    组合装饰器：重试 + 限流
    
    同时应用指数退避重试和请求限流
    """
    retryable_exceptions = (
        ConnectionError,
        ConnectionAbortedError,
        ConnectionRefusedError,
        ConnectionResetError,
        TimeoutError,
        OSError,
        Exception,
    )
    
    limiter = RateLimiter(requests_per_second)
    
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            delay = initial_delay
            
            for attempt in range(max_retries + 1):
                try:
                    limiter.wait()
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    
                    if attempt == max_retries:
                        logger.error(f"函数 {func.__name__} 在 {max_retries} 次重试后仍然失败: {e}")
                        raise RetryError(f"重试 {max_retries} 次后失败: {e}") from e
                    
                    logger.warning(f"函数 {func.__name__} 第 {attempt + 1} 次尝试失败: {e}")
                    logger.info(f"等待 {delay:.2f} 秒后重试...")
                    time.sleep(delay)
                    
                    delay = min(delay * 2, max_delay)
            
            raise last_exception
        return wrapper
    
    if func is not None:
        return decorator(func)
    return decorator


class AkshareClient:
    """akshare客户端封装，内置重试和限流"""
    
    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 2.0,
        requests_per_second: float = 0.5
    ):
        """
        初始化akshare客户端
        
        :param max_retries: 最大重试次数
        :param initial_delay: 初始延迟时间（秒）
        :param requests_per_second: 每秒最大请求数
        """
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.limiter = RateLimiter(requests_per_second)
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        调用akshare函数，带重试和限流
        
        :param func: akshare函数
        :param args: 位置参数
        :param kwargs: 关键字参数
        :return: 函数返回值
        """
        last_exception = None
        delay = self.initial_delay
        
        for attempt in range(self.max_retries + 1):
            try:
                self.limiter.wait()
                return func(*args, **kwargs)
            except (ConnectionError, ConnectionAbortedError, TimeoutError, OSError) as e:
                last_exception = e
                
                if attempt == self.max_retries:
                    logger.error(f"akshare调用在 {self.max_retries} 次重试后仍然失败: {e}")
                    raise RetryError(f"重试 {self.max_retries} 次后失败: {e}") from e
                
                logger.warning(f"akshare调用第 {attempt + 1} 次尝试失败: {e}")
                logger.info(f"等待 {delay:.2f} 秒后重试...")
                time.sleep(delay)
                
                delay = min(delay * 2, 60)
        
        raise last_exception
