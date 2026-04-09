# BiBLE Client

BiBLE Client 为第三方提供API调用

基于ABC创建一个BaseClient类，具有为随后的localClient（Embedded Mode）以及AsyncHttpClient（Http Mode）的具体实现做准备

- 初始化client
-  关闭client

- 向BiBLE添加Knowledge（s）
- 向BiBLE查询Knowledge Base Status
- 向BiBLE进行Semantic Search 获得  Knowledge list

- 对单条Knowledge提取Abstract简要
- 对单条Knowledge提取overview概述
- 对单条Knowledge提取全文或片段

- 提供 session context with ID, 向BiBLE进行Semantic Search，获得Knowledge list

- 提供Knowledge id或者session id，向BiBLE查询关联信息

- 提供Knowledge id或者session id，要求BiBLE建立彼此关联信息

- 创建一个新的Session Memory或者根据session id 加载已经存在的session

- 向一个Session添加消息/内容

- 将一个Session Memory提交给BiBLE

- 提供Session ID，从BiBLE下载此session的完整记忆

- 根据session id，从Session中提取上下文（本地或远程）

- 根据session id，删除本地session记录（支持批量删除）

- 根据session id，查询一个session是否存在

- 根据关键字，查询关联session，获得session list