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

DATA_DIR = Path("Lecture")
INDEX_DIR = Path("index/faiss")
EMBED_MODEL = "BAAI/bge-m3"  # 多语种, 中英文都可
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
TOP_K = 5
# 直接在此填写你的 DeepSeek 密钥（不想用环境变量时）

class rag():
    def __init__(self, api_key):
        load_dotenv()
        self.LECTURE_PATTERN = re.compile(r"LT(?P<lec>\d+)_CS\d+_(?P<topic>.+?)\.pdf$", re.IGNORECASE)
        # 本地硬编码密钥：如果上面 API_KEY 已填写，则在运行时注入到环境变量
        if api_key and api_key != "":
            os.environ["DEEPSEEK_API_KEY"] = api_key
        else:
            raise ValueError("miss apikey")

        if not os.path.exists(INDEX_DIR):
            vs = self.ensure_index(DATA_DIR, INDEX_DIR, rebuild=True)
            self.vs = self.ensure_index(DATA_DIR, INDEX_DIR, rebuild=False)
        else:
            self.vs = self.ensure_index(DATA_DIR, INDEX_DIR, rebuild=False)

        self.SCORE_LIMIT = 0.5   

        

    def get_embeddings(self):
        # bge-m3 建议开启归一化, 提升向量检索质量
        return HuggingFaceEmbeddings(
            model_name=EMBED_MODEL,
            encode_kwargs={"normalize_embeddings": True}
        )

    def ensure_index(self, data_dir: Path, index_dir: Path, rebuild: bool = False) -> FAISS:
        if rebuild or not (index_dir.exists() and any(index_dir.iterdir())):
            print("[Index] Building index...")
            raw_docs = self.load_all_pdfs(data_dir)
            docs = self.split_documents(raw_docs)
            return self.build_faiss_index(docs, index_dir)
        print("[Index] Loading cached index...")
        return self.load_faiss_index(index_dir)

    def build_faiss_index(self, docs: List[Document], index_dir: Path) -> FAISS:
        embeddings = self.get_embeddings()
        vs = FAISS.from_documents(docs, embeddings)
        index_dir.mkdir(parents=True, exist_ok=True)
        vs.save_local(str(index_dir))
        return vs

    def load_faiss_index(self, index_dir: Path) -> FAISS:
        embeddings = self.get_embeddings()
        return FAISS.load_local(
            str(index_dir), embeddings, allow_dangerous_deserialization=True
        )

    def split_documents(self, docs: List[Document]) -> List[Document]:
        """按页再细分小块, 保留元数据"""
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            separators=["\n\n", "\n", "。", ".", "!", "?", " "]
        )
        return splitter.split_documents(docs)

    def load_all_pdfs(self, data_dir: Path) -> List[Document]:
        pdf_files = sorted(glob.glob(str(data_dir / "*.pdf")))
        all_docs: List[Document] = []
        for f in pdf_files:
            all_docs.extend(self.extract_pdf_as_documents(Path(f)))
        return all_docs

    def extract_pdf_as_documents(self, pdf_path: Path) -> List[Document]:
        """逐页抽取文本为 Document 列表, 元数据包含 source 与 page 等"""
        docs: List[Document] = []
        reader = PdfReader(str(pdf_path))
        lec, topic = self.parse_lecture_info(pdf_path.name)
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

    def parse_lecture_info(self, filename: str) -> Tuple[str, str]:
        """从文件名中解析课次与主题, 失败时给默认值"""
        m = self.LECTURE_PATTERN.search(Path(filename).name)
        if m:
            return m.group("lec"), m.group("topic")
        return "", Path(filename).stem

    def get_llm(self, model: str = "deepseek-chat", temperature: float = 0.2) -> ChatDeepSeek:
        # 需要 DEEPSEEK_API_KEY
        # deepseek-chat 为 V3.1 的非思考模式, 响应更快
        # deepseek-reasoner 为思考模式, 更长上下文与推理能力, 但不支持工具调用
        # 参考官方文档与 LangChain 集成说明
        return ChatDeepSeek(model=model, temperature=temperature)

    def format_citations(self, docs: List[Document]) -> str:
        seen = set()
        lines = []
        for d in docs:
            key = (d.metadata.get("source"), d.metadata.get("page"))
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {key[0]} p{key[1]}")
        return "\n".join(lines) or "- 无检索命中"

    def build_context(self, docs: List[Document]) -> str:
        blocks = []
        for i, d in enumerate(docs, 1):
            src = d.metadata.get("source")
            pg = d.metadata.get("page")
            text = d.page_content.replace("\n", " ")
            if len(text) > 1200:
                text = text[:1200] + "..."
            blocks.append(f"[{i}] {text}\n[来源 {src} p{pg}]")
        return "\n\n".join(blocks)

    def locate_topic(self, vs: FAISS, query: str, k: int = TOP_K) -> List[Tuple[str, int, float, str]]:
        """返回最相关的 文件名 页码 相似度 分句摘要"""
        results = self.vs.similarity_search_with_score(query, k=k)
        rows = []
        for doc, score in results:
            src = doc.metadata.get("source")
            pg = doc.metadata.get("page")
            snippet = doc.page_content.replace("\n", " ")
            if len(snippet) > 160:
                snippet = snippet[:160] + "..."
            rows.append((src, pg, float(score), snippet))
        return rows

    def rag_answer(self, question: str,
                model: str = "deepseek-chat",
                k: int = TOP_K) -> Dict:

        score_limit = self.SCORE_LIMIT
        hits_with_score = self.vs.similarity_search_with_score(question, k=k)
        # print("[Debug] top-k scores:", [round(s, 3) for _, s in hits_with_score[:3]])

        docs = [doc for doc, score in hits_with_score if score >= score_limit]

        llm = self.get_llm(model=model)


        if docs:
            context = self.build_context(docs)
            #print("context:", context)
            citations = self.format_citations(docs)
        else:
            context = "[None]"
            citations = ""        


        system_prompt = (
            "Any question corresponding to your identity, you should call yourself City University of Hong Kong virtual teaching assistant."
            "You are a teaching assistant from City University of Hong Kong. Use the provided lecture excerpts to answer the user’s question. "
            "If the context is insufficient, say so explicitly. Do NOT hallucinate content not in the slides. "
            "Answer first, then list citations at the end."
        )

        user_prompt = (
            f"Question:\n{question}\n\n"
            f"Relevant lecture excerpts:\n{context}\n\n"
            "Instructions:\n"
            "1. First, determine if the question is related to the lecture content.\n"
            "2. If the question IS related AND you use specific information from the excerpts to answer it, then:\n"
            "- Provide a clear answer\n"
            "- Add a final line that starts with 'Citations:' and list each source in the format [filename p#]\n"
            "3. If the question is NOT related to the lecture, OR if you don't use any excerpts in your answer:\n"
            "- Provide a normal response\n"
            "- DO NOT add the 'Citations:' line at all\n"
            "\n"
            "For such questions, answer normally without any citations."
        )

        messages = [("system", system_prompt), ("human", user_prompt)]
        resp = llm.invoke(messages)

        """
        return {
            "answer": resp.content,
            "hits": docs,
            "citations": citations
        }
        """

        return resp.content

