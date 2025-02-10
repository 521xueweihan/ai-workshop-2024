# OceanBase AI Workshop

[完整的 RAG 机器人教程](https://mp.weixin.qq.com/s/PqlHl3jIAcNqr5zMcG1OFQ)


## 运行

主要改动的代码：

- agents/hg_rag_agent.py：
- rag/hg_rag.py
- hg_ui.py
- embed_sql.py

```
# 导入数据并向量化
python embed_sql.py --table_name hg5

# 启动服务
TABLE_NAME=hg5 streamlit run --server.runOnSave false hg_ui.py
```
