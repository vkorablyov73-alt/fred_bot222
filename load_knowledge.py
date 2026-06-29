import os
from knowledge_base import KnowledgeBase

kb = KnowledgeBase()

# Загрузка текстовых файлов
text_dir = "./knowledge/math_texts/"
if os.path.exists(text_dir):
    for file in os.listdir(text_dir):
        if file.endswith(".txt"):
            kb.load_text(
                os.path.join(text_dir, file),
                metadata={"topic": "math", "category": "theory"}
            )

# Методики
methodologies = {
    "logarithms_simple": """
    # ЛОГАРИФМЫ ДЛЯ НАЧИНАЮЩИХ
    
    Логарифм — это ответ на вопрос: «В какую степень нужно возвести основание, чтобы получить число?»
    Пример: log₂8 = 3, потому что 2³ = 8.
    Логарифмы используются в шкале Рихтера, децибелах, расчёте процентов.
    """
}

for name, content in methodologies.items():
    kb.load_methodology(
        name=name,
        content=content,
        metadata={"topic": "math", "category": "methodology"}
    )

stats = kb.get_stats()
print(f"\n📊 База знаний Фрэда содержит {stats['total_chunks']} фрагментов")

print("\n🔍 Тест поиска:")
for query in ["Что такое логарифм?", "Где используются логарифмы?"]:
    print(f"\nЗапрос: '{query}'")
    results = kb.search(query, n_results=2)
    for r in results:
        print(f"  • {r['text'][:80]}...")