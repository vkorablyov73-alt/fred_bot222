import os
import chromadb
from typing import List, Dict, Any

class KnowledgeBase:
    def __init__(self, collection_name="fred_knowledge"):
        """Инициализация базы знаний Фрэда"""
        # Используем локальную ChromaDB
        self.client = chromadb.PersistentClient(path="./chroma_db")
        
        # НЕ используем эмбеддинг-функцию — ChromaDB создаст эмбеддинги автоматически
        # с помощью встроенной модели (all-MiniLM-L6-v2)
        try:
            self.collection = self.client.get_collection(collection_name)
        except:
            self.collection = self.client.create_collection(
                name=collection_name
                # embedding_function НЕ указываем — будет использоваться default
            )
    
    def _split_text(self, text: str, chunk_size: int = 500, overlap: int = 100) -> List[str]:
        """Простое разбиение текста на куски"""
        words = text.split()
        chunks = []
        i = 0
        while i < len(words):
            chunk = ' '.join(words[i:i+chunk_size])
            chunks.append(chunk)
            i += chunk_size - overlap
        return chunks
    
    def load_text(self, file_path: str, metadata: Dict = None):
        """Загружает текстовый файл в базу знаний"""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        chunks = self._split_text(content)
        
        ids = []
        documents_text = []
        metadatas = []
        
        for i, chunk in enumerate(chunks):
            chunk_id = f"{os.path.basename(file_path)}_{i}"
            ids.append(chunk_id)
            documents_text.append(chunk)
            
            meta = {
                "source": file_path,
                "type": "text",
                "chunk": i
            }
            if metadata:
                meta.update(metadata)
            metadatas.append(meta)
        
        self.collection.add(
            ids=ids,
            documents=documents_text,
            metadatas=metadatas
        )
        
        print(f"✅ Загружено {len(chunks)} фрагментов из {file_path}")
        return len(chunks)
    
    def load_methodology(self, name: str, content: str, metadata: Dict = None):
        """Загружает методику напрямую (из текста)"""
        chunks = self._split_text(content)
        
        ids = []
        documents_text = []
        metadatas = []
        
        for i, chunk in enumerate(chunks):
            chunk_id = f"methodology_{name}_{i}"
            ids.append(chunk_id)
            documents_text.append(chunk)
            
            meta = {
                "source": f"methodology_{name}",
                "type": "methodology",
                "methodology_name": name
            }
            if metadata:
                meta.update(metadata)
            metadatas.append(meta)
        
        self.collection.add(
            ids=ids,
            documents=documents_text,
            metadatas=metadatas
        )
        
        print(f"✅ Загружена методика '{name}' ({len(chunks)} фрагментов)")
        return len(chunks)
    
    def search(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """Поиск релевантных фрагментов по запросу"""
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results
        )
        
        formatted_results = []
        for i in range(len(results['ids'][0])):
            formatted_results.append({
                'id': results['ids'][0][i],
                'text': results['documents'][0][i],
                'metadata': results['metadatas'][0][i],
                'distance': results['distances'][0][i] if 'distances' in results else None
            })
        
        return formatted_results
    
    def get_stats(self):
        """Возвращает статистику по базе знаний"""
        return {"total_chunks": self.collection.count()}