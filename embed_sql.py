from typing import List
import dotenv
import pymysql
import os
import uuid
import argparse
import dotenv

dotenv.load_dotenv()

from langchain_oceanbase.vectorstores import OceanbaseVectorStore
from langchain_core.documents import Document
from rag.embeddings import get_embedding
from datetime import datetime
from tqdm import tqdm
import json

connection_args = {
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "db_name": os.getenv("DB_NAME"),
}

parser = argparse.ArgumentParser()
parser.add_argument(
    "--table_name",
    type=str,
    help="Name of the table to insert documents into.",
    default="corpus",
)
parser.add_argument(
    "--batch_size",
    type=int,
    help="Number of documents to insert in a batch.",
    default=4,
)
parser.add_argument(
    "--limit",
    type=int,
    default=300,
    help="Maximum number of documents to insert.",
)
parser.add_argument(
    "--echo",
    action="store_true",
    help="Echo SQL queries.",
)

args = parser.parse_args()
print("args", args)

embeddings = get_embedding(
    ollama_url=os.getenv("OLLAMA_URL") or None,
    ollama_token=os.getenv("OLLAMA_TOKEN") or None,
    ollama_model=os.getenv("OLLAMA_MODEL") or None,
    base_url=os.getenv("OPENAI_EMBEDDING_BASE_URL") or None,
    api_key=os.getenv("OPENAI_EMBEDDING_API_KEY") or None,
    model=os.getenv("OPENAI_EMBEDDING_MODEL") or None,
)

vs = OceanbaseVectorStore(
    embedding_function=embeddings,
    table_name=args.table_name,
    connection_args=connection_args,
    metadata_field="metadata",
    echo=args.echo,
)

vals = []
params = vs.obvector.perform_raw_text_sql(
    "SHOW PARAMETERS LIKE '%ob_vector_memory_limit_percentage%'"
)
for row in params:
    val = int(row[6])
    vals.append(val)
if len(vals) == 0:
    print("ob_vector_memory_limit_percentage not found in parameters.")
    exit(1)
if any(val == 0 for val in vals):
    try:
        vs.obvector.perform_raw_text_sql(
            "ALTER SYSTEM SET ob_vector_memory_limit_percentage = 30"
        )
    except Exception as e:
        print("Failed to set ob_vector_memory_limit_percentage to 30.")
        print("Error message:", e)
        exit(1)
vs.obvector.perform_raw_text_sql("SET ob_query_timeout=100000000")


def insert_batch(docs: list[Document]):
    vs.add_documents(
        docs,
        ids=[str(uuid.uuid4()) for _ in range(len(docs))],
    )


def query_sql_and_generate_documents() -> List[Document]:
    """
    Query the OceanBase SQL database and generate documents based on the query results.

    Args:
        sql_query (str): The SQL query to execute.

    Returns:
        List[Document]: A list of LangChain Document objects.
    """
    sql_query = """
      SELECT
       repository.name,
       repository.url,
       repository.title,
       repository.summary,
       volume.name AS volume_name,
       category.name AS category_name,
       volume.publish_at,
       repository.primary_lang,
       repository.license,
       repository.stars
      FROM
       periodical
      LEFT JOIN volume ON periodical.volume_id = volume.id
      LEFT JOIN category ON periodical.category_id = category.id
      LEFT JOIN repository ON periodical.repo_id = repository.id
    """

    # 初始化结果列表
    document_list = []
    # Initialize the database connection
    # 连接到数据库
    connection = pymysql.connect(
        host=connection_args["host"],
        user=connection_args["user"],
        password=connection_args["password"],
        database=connection_args["db_name"],
        port=int(connection_args["port"]),
        charset="utf8mb4",
    )

    # 使用游标执行 SQL 查询
    with connection.cursor() as cursor:
        cursor.execute(sql_query)
        rows = cursor.fetchall()

        columns = [desc[0] for desc in cursor.description]  # 获取列名

        # 将查询结果转为文档
        for fi_row in rows:
            row = {columns[i]: fi_row[i] for i in range(len(columns))}

            # 构建内容
            content = f"""{row.get('name', '未知')}：{row.get('title', '未知标题')}。{row.get('summary', '暂无概要')}"""

            # 构建元数据
            metadata = {
                "repository_name": row.get("name", "N/A"),  # 仓库完整名称
                "repository_url": row.get("url", "N/A"),  # 仓库链接
                "description": row.get("description", "N/A"),  # 项目描述
                "volume_name": row.get("volume_name", "N/A"),  # 卷册名称
                "category_name": row.get("category_name", "N/A"),  # 类别名称
                "language": row.get("primary_lang", "N/A"),  # 主要编程语言
                "license": row.get("license", "N/A"),  # 开源协议
                "stars": int(row.get("stars", 0)),  # Star 数量，转换为整数
                "chunk_title": row.get("name", "N/A"),
                "doc_name": f'《HelloGitHub》第 {row.get("volume_name", "N/A")} 期',  # 文档名称
                "doc_url": f'https://github.com/521xueweihan/HelloGitHub/blob/master/content/HelloGitHub{row.get("volume_name", "N/A")}.md',  # 文档路径
                "enhanced_title": f'内容 -> {row.get("category_name", "N/A")} -> {row.get("name", "N/A")}',  # 增强标题
                "published_at": (
                    row.get("publish_at").strftime("%Y-%m-%d")
                    if isinstance(row.get("publish_at"), datetime)
                    else row.get("publish_at", "N/A").split(" ")[0]
                    if isinstance(row.get("publish_at"), str)
                    else "N/A"
                )
            }

            # 将内容和元数据添加到文档
            document_list.append(Document(page_content=content.strip(), metadata=metadata))
    return document_list


documents = query_sql_and_generate_documents()
batch = []
pbar = tqdm(total=len(documents), desc="Processing", unit="row")
for doc in documents:
    if len(batch) == args.batch_size:
        insert_batch(batch)
        pbar.update(len(batch))
        batch = []
    batch.append(doc)
if len(batch) > 0:
    insert_batch(batch)
