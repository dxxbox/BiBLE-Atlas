from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Union

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

    # ================= Knowledge Base Operations =================

    @abstractmethod
    def add_knowledge(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> KnowledgeID:
        """
        向BiBLE添加Knowledge(s)
        :param content: 知识内容
        :param metadata: 元数据
        :return: 知识ID (Knowledge ID)
        """
        pass

    @abstractmethod
    def get_kb_status(self) -> Dict[str, Any]:
        """
        向BiBLE查询Knowledge Base Status
        :return: KB状态信息 (如向量库统计、容量等)
        """
        pass

    @abstractmethod
    def search_knowledge(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        向BiBLE进行Semantic Search 获得 Knowledge list
        :param query: 查询文本
        :param top_k: 返回结果数量
        :return: 匹配的Knowledge列表
        """
        pass

    @abstractmethod
    def get_knowledge_abstract(self, knowledge_id: str) -> str:
        """
        对单条Knowledge提取Abstract简要
        :param knowledge_id: 知识ID
        :return: 简要摘要
        """
        pass

    @abstractmethod
    def get_knowledge_overview(self, knowledge_id: str) -> str:
        """
        对单条Knowledge提取overview概述
        :param knowledge_id: 知识ID
        :return: 概述文本
        """
        pass

    @abstractmethod
    def get_knowledge_content(self, knowledge_id: str, startline: int = 0, limit: Optional[int] = None) -> str:
        """
        对单条Knowledge提取全文或片段
        :param knowledge_id: 知识ID
        :return: 全文或内容片段
        """
        pass

    # ================= Session Memory Operations =================

    @abstractmethod
    def create_session(self) -> str:
        """
        创建一个新的Session Memory
        :return: 新建的Session ID
        """
        pass

    @abstractmethod
    def load_session(self, session_id: str) -> Dict[str, Any]:
        """
        根据session id 加载已经存在的session
        :param session_id: Session ID
        :return: Session 内存数据
        """
        pass

    @abstractmethod
    def add_message_to_session(self, session_id: str, message: str, metadata: Optional[Dict] = None) -> bool:
        """
        向一个Session添加消息/内容
        :param session_id: Session ID
        :param message: 消息内容
        :param metadata: 消息元数据
        :return: 是否添加成功
        """
        pass

    @abstractmethod
    def commit_session(self, session_id: str) -> bool:
        """
        将一个Session Memory提交给BiBLE
        将会话数据持久化到后端存储
        :param session_id: Session ID
        :return: 是否提交成功
        """
        pass

    @abstractmethod
    def download_session_memory(self, session_id: str) -> Dict[str, Any]:
        """
        提供Session ID，从BiBLE下载此session的完整记忆
        :param session_id: Session ID
        :return: 会话完整记忆
        """
        pass

    @abstractmethod
    def extract_session_context(self, session_id: str) -> Dict[str, Any]:
        """
        根据session id，从Session中提取上下文（本地或远程）
        :param session_id: Session ID
        :return: 提取出的上下文信息
        """
        pass

    @abstractmethod
    def delete_session(self, session_ids: List[str]) -> bool:
        """
        根据session id，删除本地session记录（支持批量删除）
        :param session_ids: Session ID 列表
        :return: 是否删除成功
        """
        pass

    @abstractmethod
    def session_exists(self, session_id: str) -> bool:
        """
        根据session id，查询一个session是否存在
        :param session_id: Session ID
        :return: 是否存在
        """
        pass

    @abstractmethod
    def find_sessions_by_keyword(self, keyword: str) -> List[str]:
        """
        根据关键字，查询关联session，获得session list
        :param keyword: 搜索关键字
        :return: 匹配的Session ID列表
        """
        pass

    # ================= Advanced Context & Relations =================

    @abstractmethod
    def search_sessions_with_context(self, session_id: str, context: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        提供 session context with ID, 向BiBLE进行Semantic Search，获得Knowledge list
        :param session_id: 当前Session ID
        :param context: 搜索上下文文本
        :return: 关联的Knowledge列表
        """
        pass

    @abstractmethod
    def get_relation_info(self, target_id: str) -> List[Dict[str, Any]]:
        """
        提供Knowledge id或者session id，向BiBLE查询关联信息
        :param target_id: 目标ID
        :return: 关联的其他ID或信息列表
        """
        pass

    @abstractmethod
    def create_relation(self, id1: str, id2: str, relation_type: str = "related") -> bool:
        """
        提供Knowledge id或者session id，要求BiBLE建立彼此关联信息
        :param id1: 第一个ID
        :param id2: 第二个ID
        :param relation_type: 关系类型
        :return: 是否建立成功
        """
        pass
