from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Union

from fastapi import Response

class KnowledgeID(str):
    """Knowledge ID类型定义"""
    pass

class BaseClient(ABC):
    """
    BaseClient 抽象基类
    为 BiBLE 系统的交互提供标准接口，支持 Local (Embedded) 和 Async HTTP 模式。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化client
        :param config: 客户端配置参数
        """
        self.config = config or {}
        self._initialize()

    def _initialize(self):
        """子类可重写以执行具体的初始化逻辑"""
        pass

    @abstractmethod
    def close(self) -> None:
        """
        关闭client
        释放资源，断开连接
        """
        pass
