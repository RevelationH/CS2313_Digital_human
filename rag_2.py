"""
RAG + LangChain + DeepSeek 一文件实现

功能
- 扫描 Lecture/ 目录下的课程 PDF
- 按页抽取文本, 保留文件名与页码等元数据
- 采用 HuggingFace Embeddings + FAISS 构建向量索引
- 用 DeepSeek 聊天模型进行问答, 同时给出命中文档页位置
- 命令行两种模式
  1) --rebuild 重新构建索引
  2) --ask "问题" 直接问答并显示出处
  3) --locate "关键词或知识点" 返回最可能出现的页列表

准备
pip install -U "langchain>=0.2" langchain-community langchain-text-splitters langchain-deepseek \
  sentence-transformers faiss-cpu pypdf python-dotenv

密钥配置\nA) 直接在代码里设置 API_KEY = "你的key"（你当前的需求）\nB) 或者使用环境变量 export DEEPSEEK_API_KEY=你的key

目录结构
project/
  Lecture/  # 放课件 PDF, 例如 LT1_CS2313_intro.pdf 等
  index/      # 自动生成与持久化的 FAISS 索引
  rag.py  # 本文件

注意
- 如果你的课件是扫描版, pypdf 可能抽不到文本, 需要先 OCR
- 如果还存在 .pptx, 可额外用 python-pptx 读取, 原理相同
"""

from __future__ import annotations
import os
import re
import glob
import argparse
from pathlib import Path
from typing import List, Tuple, Dict

from dotenv import load_dotenv
from pypdf import PdfReader

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_deepseek import ChatDeepSeek

# -----------------------------
# 配置
# -----------------------------
DATA_DIR = Path("Lecture")
INDEX_DIR = Path("index/faiss")
EMBED_MODEL = "BAAI/bge-m3"  # 多语种, 中英文都可
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
TOP_K = 5
# 直接在此填写你的 DeepSeek 密钥（不想用环境变量时）
API_KEY = "sk-61cf109d660d4ba6a9d80ebf38737f06"

# -----------------------------
# 工具函数
# -----------------------------
LECTURE_PATTERN = re.compile(r"LT(?P<lec>\d+)_CS\d+_(?P<topic>.+?)\.pdf$", re.IGNORECASE)

def parse_lecture_info(filename: str) -> Tuple[str, str]:
    """从文件名中解析课次与主题, 失败时给默认值"""
    m = LECTURE_PATTERN.search(Path(filename).name)
    if m:
        return m.group("lec"), m.group("topic")
    return "", Path(filename).stem


def extract_pdf_as_documents(pdf_path: Path) -> List[Document]:
    """逐页抽取文本为 Document 列表, 元数据包含 source 与 page 等"""
    docs: List[Document] = []
    reader = PdfReader(str(pdf_path))
    lec, topic = parse_lecture_info(pdf_path.name)
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = text.strip()
        if not text:
            # 空页或扫描图, 也保留占位, 以便手动回查
            text = "[No extractable text on this page, might be scanned image]"
        meta = {
            "source": pdf_path.name,
            "page": i + 1,  # 1-based
            "lecture": lec,
            "topic": topic,
        }
        docs.append(Document(page_content=text, metadata=meta))
    return docs


def load_all_pdfs(data_dir: Path) -> List[Document]:
    pdf_files = sorted(glob.glob(str(data_dir / "*.pdf")))
    all_docs: List[Document] = []
    for f in pdf_files:
        all_docs.extend(extract_pdf_as_documents(Path(f)))
    return all_docs


def split_documents(docs: List[Document]) -> List[Document]:
    """按页再细分小块, 保留元数据"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", ".", "!", "?", " "]
    )
    return splitter.split_documents(docs)


def get_embeddings():
    # bge-m3 建议开启归一化, 提升向量检索质量
    return HuggingFaceEmbeddings(
        model_name=EMBED_MODEL,
        encode_kwargs={"normalize_embeddings": True}
    )


def build_faiss_index(docs: List[Document], index_dir: Path) -> FAISS:
    embeddings = get_embeddings()
    vs = FAISS.from_documents(docs, embeddings)
    index_dir.mkdir(parents=True, exist_ok=True)
    vs.save_local(str(index_dir))
    return vs


def load_faiss_index(index_dir: Path) -> FAISS:
    embeddings = get_embeddings()
    return FAISS.load_local(
        str(index_dir), embeddings, allow_dangerous_deserialization=True
    )


def ensure_index(data_dir: Path, index_dir: Path, rebuild: bool = False) -> FAISS:
    if rebuild or not (index_dir.exists() and any(index_dir.iterdir())):
        print("[Index] Building index...")
        raw_docs = load_all_pdfs(data_dir)
        docs = split_documents(raw_docs)
        return build_faiss_index(docs, index_dir)
    print("[Index] Loading cached index...")
    return load_faiss_index(index_dir)


# -----------------------------
# DeepSeek LLM
# -----------------------------

def get_llm(model: str = "deepseek-chat", temperature: float = 0.2) -> ChatDeepSeek:
    # 需要 DEEPSEEK_API_KEY
    # deepseek-chat 为 V3.1 的非思考模式, 响应更快
    # deepseek-reasoner 为思考模式, 更长上下文与推理能力, 但不支持工具调用
    # 参考官方文档与 LangChain 集成说明
    return ChatDeepSeek(model=model, temperature=temperature)


# -----------------------------
# RAG 核心
# -----------------------------

def format_citations(docs: List[Document]) -> str:
    seen = set()
    lines = []
    for d in docs:
        key = (d.metadata.get("source"), d.metadata.get("page"))
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {key[0]} p{key[1]}")
    return "\n".join(lines) or "- 无检索命中"


def build_context(docs: List[Document]) -> str:
    blocks = []
    for i, d in enumerate(docs, 1):
        src = d.metadata.get("source")
        pg = d.metadata.get("page")
        text = d.page_content.replace("\n", " ")
        if len(text) > 1200:
            text = text[:1200] + "..."
        blocks.append(f"[{i}] {text}\n[来源 {src} p{pg}]")
    return "\n\n".join(blocks)


SCORE_LIMIT = 0.5          

def rag_answer2(vs: FAISS, question: str,
               model: str = "deepseek-chat",
               k: int = TOP_K,
               score_limit: float = SCORE_LIMIT) -> Dict:


    hits_with_score = vs.similarity_search_with_score(question, k=k)
   # print("[Debug] top-k scores:", [round(s, 3) for _, s in hits_with_score[:3]])

    docs = [doc for doc, score in hits_with_score if score >= score_limit]

    llm = get_llm(model=model)


    if docs:
        context = build_context(docs)
        #print("context:", context)
        citations = format_citations(docs)
    else:
        context = "[None]"
        citations = ""        


    system_prompt = (
        "You are a teaching assistant. Use the provided lecture excerpts to answer the user’s question. "
        "If the context is insufficient, say so explicitly. Do NOT hallucinate content not in the slides. "
        "Answer first, then list citations at the end."
    )

    user_prompt = (
        f"Question:\n{question}\n\n"
        f"Relevant lecture excerpts:\n{context}\n\n"
        "Provide a clear answer. "
        #At the end, write '  ' if there is no citations or 'Citations:' and list sources in the format [filename p#] only if there are any."
        #"If there are no citations, do **not** add any extra line."
        "If you use any excerpt, add a final line that starts with 'Citations:' "
        "and list each source in the format [filename p#]. "
        "If you do not use any excerpt or the question is unrelated to the lecture, do NOT add this line."

    )

    messages = [("system", system_prompt), ("human", user_prompt)]
    resp = llm.invoke(messages)


    return {
        "answer": resp.content,
        "hits": docs,
        "citations": citations
    }



def rag_answer(vs: FAISS, question: str, model: str = "deepseek-chat", k: int = TOP_K) -> Dict:
    retriever = vs.as_retriever(search_kwargs={"k": k})
    docs: List[Document] = retriever.get_relevant_documents(question)

    llm = get_llm(model=model)

    system_prompt = (
        "You are a teaching assistant. Use the provided lecture excerpts to answer the user’s question. "
        "If the context is insufficient, say so explicitly. Do NOT hallucinate content not in the slides. "
        "Answer first, then list citations at the end."
    )

    context = build_context(docs)

    user_prompt = (
        f"Question:\n{question}\n\n"
        f"Relevant lecture excerpts:\n{context}\n\n"
        "Provide a clear answer. At the end, write 'Citations:' and list sources in the format [filename p#]."
    )

    messages = [("system", system_prompt), ("human", user_prompt)]
    resp = llm.invoke(messages)

    return {
        "answer": resp.content,
        "hits": docs,
        "citations": format_citations(docs)
    }


def locate_topic(vs: FAISS, query: str, k: int = TOP_K) -> List[Tuple[str, int, float, str]]:
    """返回最相关的 文件名 页码 相似度 分句摘要"""
    results = vs.similarity_search_with_score(query, k=k)
    rows = []
    for doc, score in results:
        src = doc.metadata.get("source")
        pg = doc.metadata.get("page")
        snippet = doc.page_content.replace("\n", " ")
        if len(snippet) > 160:
            snippet = snippet[:160] + "..."
        rows.append((src, pg, float(score), snippet))
    return rows


# -----------------------------
# CLI
# -----------------------------

def main():
    load_dotenv()

    # 本地硬编码密钥：如果上面 API_KEY 已填写，则在运行时注入到环境变量
    if API_KEY and API_KEY != "":
        os.environ["DEEPSEEK_API_KEY"] = API_KEY

    parser = argparse.ArgumentParser(description="RAG with DeepSeek for course PDFs")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild index")
    #parser.add_argument("--ask", type=str, default=None, help="Ask a question")
    parser.add_argument("--ask", nargs='+', help="Ask a question")
    parser.add_argument("--locate", type=str, default=None, help="Locate a keyword/topic")
    parser.add_argument("--model", type=str, default="deepseek-chat", help="deepseek-chat 或 deepseek-reasoner")
    parser.add_argument("--k", type=int, default=TOP_K, help="Number of retrieved chunks")
    args = parser.parse_args()

    vs = ensure_index(DATA_DIR, INDEX_DIR, rebuild=args.rebuild)

    if args.ask:
        question = " ".join(args.ask)
        out = rag_answer2(vs, question, model=args.model, k=args.k)
        print("\n=== Answer ===\n")
        print(out["answer"])  # 已包含模型生成文本
    #    print("\n=== Citations (retrieved) ===\n")
    #    print(out["citations"])  # 由检索命中直接给出
        return

    if args.locate:
        rows = locate_topic(vs, args.locate, k=args.k)
        print("\nLikely locations\n")
        for i, (src, pg, score, snip) in enumerate(rows, 1):
            print(f"{i}. {src} p{pg} | score={score:.3f}")
            print(f"   {snip}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
