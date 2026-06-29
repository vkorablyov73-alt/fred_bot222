import re  # <-- добавьте этот импорт в начало файла
import os
import sys
import logging
import sqlite3
import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
import uvicorn

# Импорты Фрэда
from database import (
    init_db, get_or_create_user, update_last_seen, save_message,
    get_recent_messages, update_topic_score, get_user_mode, set_user_mode,
    get_random_task, save_diagnostic_result, update_microtopic_progress,
    get_user_stats, update_user_stats, save_prediction,
    create_lesson, get_lesson, update_lesson_mode, complete_lesson,
    save_homework, check_homework, save_practice_task, get_practice_stats,
    create_exam, submit_exam, get_user_progress,
    # НОВЫЕ ФУНКЦИИ
    create_user, authenticate_user, get_user_by_id, get_user_by_email,
    update_user_role, hash_password, verify_password,
    create_family_link,
    get_family_links,
    get_student_parents,
    accept_family_link,
    get_student_stats,
    remove_family_link
)

from predictor import (
    calculate_available_hours, calculate_nvb, primary_to_test,
    get_motivation_message, get_weekly_goal, EXAM_DATE
)

# Импорты генераторов
from generators import (
    generate_task, can_generate, generate_concept_question_llm,
    evaluate_concept_answer_llm, set_deepseek_client
)

# ===== НОВОЕ: Импорт базы знаний =====
# from knowledge_base import KnowledgeBase

# Импорт OpenAI
from openai import OpenAI
from dotenv import load_dotenv


from database import (
    # ... существующие импорты ...
    create_lesson, get_lesson, update_lesson_mode, complete_lesson,
    save_homework, check_homework, save_practice_task, get_practice_stats,
    create_exam, submit_exam, get_user_progress
)


from duckduckgo_search import DDGS


load_dotenv()



# ========== НАСТРОЙКИ ==========
VSEGPT_API_KEY = "sk-or-vv-83d191cfb7900cb8eb369fe1850e6a9802f4e312b6a813fdf9d3536d714b585e"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not VSEGPT_API_KEY:
    print("❌ Ошибка: не найден VSEGPT_API_KEY")
    sys.exit(1)

# Создаём клиент DeepSeek
deepseek_client = OpenAI(
    api_key=VSEGPT_API_KEY,
    base_url="https://api.vsegpt.ru/v1"
)

# Устанавливаем клиент для генераторов
set_deepseek_client(deepseek_client)

# Инициализируем базу данных
init_db()

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Создаём FastAPI приложение
app = FastAPI(title="Фрэд Репетитор API")

# Подключаем статические файлы
app.mount("/static", StaticFiles(directory="static"), name="static")

# ===== НОВОЕ: Инициализация базы знаний =====
try:
    # kb = KnowledgeBase()
    print("✅ База знаний Фрэда инициализирована")
except Exception as e:
    print(f"⚠️ Ошибка инициализации базы знаний: {e}")
    kb = None

# Хранилище состояний диагностики
diagnostic_sessions = {}

# Модели запросов
class ChatRequest(BaseModel):
    user_id: str
    message: str
    mode: Optional[str] = "study"

class ChatResponse(BaseModel):
    reply: str


def search_internet(query: str, max_results: int = 3) -> str:
    """Поиск информации в интернете"""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            if not results:
                return ""
            
            context = "\n\n--- ИЗ ИНТЕРНЕТА ---\n"
            for i, r in enumerate(results):
                context += f"\n🔗 [{i+1}] {r['title']}\n{r['body']}\n"
            context += "\n--- КОНЕЦ ИНТЕРНЕТА ---\n"
            return context
    except Exception as e:
        logging.warning(f"Ошибка поиска в интернете: {e}")
        return ""



# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

# ===== НОВОЕ: Функция обогащения промпта знаниями =====
def enrich_prompt_with_knowledge(user_message: str, system_prompt: str) -> str:
    """Ищет в базе знаний релевантные фрагменты и добавляет их в промпт"""
    if kb is None:
        return system_prompt
    
    try:
        # results = kb.search(user_message, n_results=3)
    except Exception as e:
        logging.warning(f"Ошибка поиска в базе знаний: {e}")
        return system_prompt
    
    if not results:
        return system_prompt
    
    knowledge_context = "\n\n--- ИЗ БАЗЫ ЗНАНИЙ ФРЭДА ---\n"
    for i, r in enumerate(results):
        source = r['metadata'].get('source', 'неизвестен')
        knowledge_context += f"\n📖 [{i+1}] Источник: {source}\n{r['text']}\n"
    knowledge_context += "\n--- КОНЕЦ БАЗЫ ЗНАНИЙ ---\n"
    
    return system_prompt + knowledge_context

def get_system_prompt(mode='study'):
    """Возвращает системный промпт в зависимости от режима"""
    base_prompt = """Ты — Фрэд, репетитор по профильной математике ЕГЭ.
    
Твои правила:
1. НЕ решай за ученика. Задавай наводящие вопросы.
2. Объясняй шаг за шагом, от простого к сложному.
3. Если ученик ошибся — объясни, почему, и дай похожую задачу.
4. Используй аналогии из жизни, показывай связь математики с реальным миром.
5. Будь дружелюбным, терпеливым, с чувством юмора.
6. Если в базе знаний есть примеры по теме — обязательно используй их в объяснении.
7. При написании формул используй обозначения: умножение — точка (·), деление — двоеточие (:).
8. При написании формул используй LaTeX-разметку:
   - Отдельные формулы заключай в \[...\] 
   - Формулы внутри текста заключай в \(...\)
   - Пример: "Квадратное уравнение выглядит так: \[ x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a} \]"
   - Пример внутри текста: "Сумма углов треугольника равна \( 180^\\circ \)"
"""  
    if mode == 'exam':
        return base_prompt + "\n\nСЕЙЧАС РЕЖИМ ЭКЗАМЕНА: НЕ давай подсказок. Только проверяй ответы. Будь краток."
    elif mode == 'training':
        return base_prompt + "\n\nСЕЙЧАС РЕЖИМ ТРЕНИРОВКИ: Не давай готовых ответов. Только указывай на ошибки и дай направление."
    
    return base_prompt

def detect_topic_simple(message):
    """Простое определение темы по ключевым словам"""
    message_lower = message.lower()
    if any(word in message_lower for word in ['логарифм', 'log', 'ln']):
        return 'A3'
    if any(word in message_lower for word in ['процент', '%']):
        return 'A1'
    if any(word in message_lower for word in ['производн', 'скорость изменения', 'касательная']):
        return 'A14'
    if any(word in message_lower for word in ['квадратн', 'дискриминант', 'ax²']):
        return 'A7'
    return None

def get_topic_name(topic_id):
    """Возвращает название темы по ID"""
    names = {
        "A1": "Проценты",
        "A2": "Степени и корни",
        "A3": "Логарифмы",
        "A7": "Квадратные уравнения",
        "A10": "Показательные уравнения",
        "A12": "Системы уравнений",
        "A14": "Производная",
        "B1": "Планиметрия"
    }
    return names.get(topic_id, topic_id)

def finalize_diagnostic(session, user_id):
    """Завершает диагностику и формирует результаты"""
    results = session['results']
    
    block1_status, block1_msg = evaluate_block_standalone(1, results)
    block2_status, block2_msg = evaluate_block_standalone(2, results)
    block3_status, block3_msg = evaluate_block_standalone(3, results)
    block4_status, block4_msg = evaluate_block_standalone(4, results)
    
    recommendations = []
    if block1_status != 'full':
        recommendations.append("📚 Начни с изучения теории и основного определения.")
    if block2_status != 'mastered':
        recommendations.append("📝 Потренируйся на простых задачах.")
    if block3_status != 'mastered':
        recommendations.append("🎯 После простых задач переходи к среднему уровню.")
    if block4_status == 'not_mastered':
        recommendations.append("⭐ Сложные задачи пока рановато. Освой сначала базу.")
    elif block4_status == 'partial':
        recommendations.append("🔥 Ты уже решаешь сложные задачи, но нужна доработка.")
    
    del diagnostic_sessions[user_id]
    
    return {
        "diagnostic_completed": True,
        "evaluations": {
            "block_1": {"status": block1_status, "message": block1_msg},
            "block_2": {"status": block2_status, "message": block2_msg},
            "block_3": {"status": block3_status, "message": block3_msg},
            "block_4": {"status": block4_status, "message": block4_msg}
        },
        "overall_level": sum([1 if block1_status=='full' else 0, 1 if block2_status=='mastered' else 0, 1 if block3_status=='mastered' else 0, 0.5 if block4_status=='partial' else 1 if block4_status=='mastered' else 0]),
        "recommendations": recommendations
    }

def evaluate_block_standalone(block, results):
    """Оценивает блок диагностики"""
    if block == 1:
        score = results.get('block_1', {}).get('score', 0)
        if score >= 80:
            return "full", "✅ Полностью понимает суть темы!"
        elif score >= 50:
            return "partial", "⚠️ Частично понимает, есть пробелы."
        return "none", "🔴 Не понимает суть, нужно начинать с теории."
    
    elif block == 2:
        correct = results.get('block_2', {}).get('correct', 0)
        total = results.get('block_2', {}).get('total', 5)
        if correct >= 4:
            return "mastered", f"✅ Простые задачи решает уверенно ({correct}/{total})"
        elif correct >= 2:
            return "partial", f"⚠️ С простыми задачами справляется частично ({correct}/{total})"
        return "not_mastered", f"🔴 Простые задачи пока не получаются ({correct}/{total})"
    
    elif block == 3:
        correct = results.get('block_3', {}).get('correct', 0)
        total = results.get('block_3', {}).get('total', 4)
        if correct >= 3:
            return "mastered", f"✅ Средние задачи решает уверенно ({correct}/{total})"
        elif correct >= 2:
            return "partial", f"⚠️ Со средними задачами справляется частично ({correct}/{total})"
        return "not_mastered", f"🔴 Средние задачи пока сложны ({correct}/{total})"
    
    elif block == 4:
        correct = results.get('block_4', {}).get('correct', 0)
        total = results.get('block_4', {}).get('total', 2)
        if correct == 2:
            return "mastered", f"✅ Сложные задачи решает отлично ({correct}/{total})"
        elif correct == 1:
            return "partial", f"⚠️ Сложные задачи решает частично ({correct}/{total})"
        return "not_mastered", f"🔴 Сложные задачи пока не решает ({correct}/{total})"
    
    return "unknown", ""
def beautify_math(text: str) -> str:
    """Очищает LaTeX-обрамления и заменяет символы на читаемые"""
    # Убираем LaTeX-обрамления
    text = re.sub(r'\\\(|\\\)|\\\[|\\\]', '', text)
    
    # \cdot → ·
    text = text.replace(r'\cdot', '·')
    
    # * → · (но не **)
    text = re.sub(r'(?<!\*)\*(?!\*)', '·', text)
    
    # / → :
    text = text.replace('/', ' : ')
    
    return text

# ========== ОСНОВНЫЕ ЭНДПОИНТЫ ==========

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

# ===== ИЗМЕНЁННЫЙ ЭНДПОИНТ /api/chat с интеграцией базы знаний =====
@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    user_id = request.user_id
    user_message = request.message
    mode = request.mode
    
    get_or_create_user(user_id, None, None)
    update_last_seen(user_id)
    set_user_mode(user_id, mode)
    save_message(user_id, "user", user_message)
    
    topic_id = detect_topic_simple(user_message)
    history = get_recent_messages(user_id, limit=20)
    system_prompt = get_system_prompt(mode)
    
    # ===== НОВОЕ: ОБОГАЩЕНИЕ ПРОМПТА ЗНАНИЯМИ =====
    enhanced_prompt = enrich_prompt_with_knowledge(user_message, system_prompt)
    
    # Используем обогащённый промпт вместо обычного
    messages = [{"role": "system", "content": enhanced_prompt}] + history
    
    try:
        response = deepseek_client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=2000,
            timeout=60.0
        )
        answer = response.choices[0].message.content
        answer = beautify_math(answer)  # <-- НОВАЯ СТРОЧКА
        save_message(user_id, "assistant", answer)
        
        if topic_id:
            if any(word in answer.lower() for word in ['верно', 'правильно', 'молодец', 'отлично', '✅']):
                update_topic_score(user_id, topic_id, is_correct=True)
            elif any(word in answer.lower() for word in ['неверно', 'ошибка', 'неправильно', '❌']):
                update_topic_score(user_id, topic_id, is_correct=False)
        
        return ChatResponse(reply=answer)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        return ChatResponse(reply="😕 Ошибка, попробуй ещё раз.")

     # ===== ПОИСК В БИБЛИОТЕКЕ ЗНАНИЙ =====
    library_context = ""
    if kb:
        try:
            # results = kb.search(user_message, n_results=3)
            if results:
                library_context = "\n\n--- ИЗ БИБЛИОТЕКИ ФРЭДА ---\n"
                for i, result in enumerate(results):
                    library_context += f"\n📖 [{i+1}] {result['text']}\n"
                library_context += "\n--- КОНЕЦ БИБЛИОТЕКИ ---\n"
        except Exception as e:
            logging.warning(f"Ошибка поиска в библиотеке: {e}")
    
    # ===== ОБНОВЛЯЕМ СИСТЕМНЫЙ ПРОМПТ =====
    system_prompt = get_system_prompt(mode)
    if library_context:
        system_prompt += f"\n\nИспользуй информацию из библиотеки Фрэда для ответа. Она находится в разделе 'ИЗ БИБЛИОТЕКИ'. Если в библиотеке нет ответа, используй свои знания."
        system_prompt += library_context



    # ===== ПОИСК В ИНТЕРНЕТЕ (если в библиотеке нет ответа) =====
    # Сначала ищем в библиотеке
    library_results = []
    if kb:
        try:
            # library_results = kb.search(user_message, n_results=3)
        except:
            pass

    # Если в библиотеке мало результатов, ищем в интернете
    if not library_results or len(library_results) < 2:
        internet_context = search_internet(user_message)
        if internet_context:
            system_prompt += internet_context


@app.get("/api/library/stats")
async def get_library_stats():
    """Статистика библиотеки знаний"""
    if not kb:
        return {"status": "not_initialized"}
    stats = kb.get_stats()
    return stats

@app.post("/api/library/search")
async def search_library(request: Request):
    """Поиск в библиотеке знаний"""
    data = await request.json()
    query = data.get('query')
    n_results = data.get('n_results', 5)
    
    if not query:
        raise HTTPException(status_code=400, detail="query обязателен")
    
    if not kb:
        raise HTTPException(status_code=503, detail="Библиотека не инициализирована")
    
    # results = kb.search(query, n_results=n_results)
    return {"results": results}




# ========== АPI ДЛЯ ДИАГНОСТИКИ ==========
# (остаётся без изменений)
@app.get("/api/diagnostic/topics")
async def get_diagnostic_topics():
    conn = sqlite3.connect('fred_users.db')
    c = conn.cursor()
    c.execute("SELECT topic_id, topic_name FROM topics ORDER BY topic_id")
    rows = c.fetchall()
    conn.close()
    topics = [{"id": row[0], "name": row[1]} for row in rows]
    return {"topics": topics}

@app.post("/api/diagnostic/start")
async def start_diagnostic(request: Request):
    data = await request.json()
    user_id = data.get('user_id')
    topic_id = data.get('topic_id')
    topic_name = get_topic_name(topic_id)
    
    if not user_id or not topic_id:
        raise HTTPException(status_code=400, detail="user_id и topic_id обязательны")
    
    diagnostic_sessions[user_id] = {
        'topic_id': topic_id,
        'topic_name': topic_name,
        'current_block': 1,
        'results': {
            'block_1': {'done': False, 'score': 0, 'answers': []},
            'block_2': {'done': False, 'correct': 0, 'total': 5, 'answers': []},
            'block_3': {'done': False, 'correct': 0, 'total': 4, 'answers': []},
            'block_4': {'done': False, 'correct': 0, 'total': 2, 'answers': []},
        }
    }
    return {"status": "started", "topic_id": topic_id, "current_block": 1}

@app.get("/api/diagnostic/next")
async def get_next_question(user_id: str):
    if user_id not in diagnostic_sessions:
        raise HTTPException(status_code=404, detail="Диагностика не найдена")
    
    session = diagnostic_sessions[user_id]
    topic_id = session['topic_id']
    topic_name = session.get('topic_name', topic_id)
    current_block = session['current_block']
    
    if current_block == 1 and session['results']['block_1']['done']:
        session['current_block'] = 2
        current_block = 2
    elif current_block == 2 and session['results']['block_2']['done']:
        session['current_block'] = 3
        current_block = 3
    elif current_block == 3 and session['results']['block_3']['done']:
        session['current_block'] = 4
        current_block = 4
    elif current_block == 4 and session['results']['block_4']['done']:
        return {"completed": True, "message": "Диагностика завершена!"}
    
    session['current_block'] = current_block
    task = None
    
    if current_block == 1:
        print(f"🎯 Генерация вопроса ИИ для темы: {topic_id} - {topic_name}")
        task = generate_concept_question_llm(topic_id, topic_name)
        if task:
            task['id'] = -1
            task['block'] = 1
            task['generated_by_llm'] = True
        else:
            task = {
                "question": f"Опиши своими словами, что такое '{topic_name}'. Что это за понятие?",
                "question_type": "free_text",
                "id": -1,
                "block": 1
            }
    elif current_block == 2:
        if can_generate(topic_id, current_block):
            task = generate_task(topic_id, current_block)
            if task:
                task['id'] = -1
                task['block'] = 2
        if not task:
            task = get_random_task(topic_id, current_block)
            if task:
                task['block'] = 2
    elif current_block == 3:
        if can_generate(topic_id, current_block):
            task = generate_task(topic_id, current_block)
            if task:
                task['id'] = -1
                task['block'] = 3
                task['generated'] = True
        if not task:
            task = get_random_task(topic_id, current_block)
            if task:
                task['block'] = 3
    elif current_block == 4:
        task = get_random_task(topic_id, current_block)
        if task:
            task['block'] = 4
    
    if not task:
        return {"error": f"Нет заданий для блока {current_block} темы {topic_id}. Добавьте задания в базу данных."}
    
    session['current_task'] = task
    
    return {
        "completed": False,
        "block": current_block,
        "task_id": task['id'],
        "question": task['question'],
        "question_type": task.get('question_type', 'text'),
        "options": task.get('options')
    }

@app.post("/api/diagnostic/answer")
async def submit_answer(request: Request):
    data = await request.json()
    user_id = data.get('user_id')
    task_id = data.get('task_id')
    user_answer = data.get('user_answer')
    response_time = data.get('response_time')
    
    if user_id not in diagnostic_sessions:
        raise HTTPException(status_code=404, detail="Диагностика не найдена")
    
    session = diagnostic_sessions[user_id]
    task = session.get('current_task')
    
    if not task or task['id'] != task_id:
        raise HTTPException(status_code=400, detail="Задание не найдено")
    
    topic_id = session['topic_id']
    topic_name = session.get('topic_name', topic_id)
    block = session['current_block']
    
    is_correct = False
    score = 0
    feedback_message = ""
    
    if block == 1:
        evaluation = evaluate_concept_answer_llm(user_answer, topic_id, topic_name)
        is_correct = evaluation['is_correct']
        score = evaluation['score']
        feedback_message = evaluation['feedback']
    elif block == 2:
        correct = task.get('correct_answer', '').lower()
        user = user_answer.strip().lower()
        is_correct = user == correct
        score = 100 if is_correct else 0
        feedback_message = "✅ Правильно!" if is_correct else "❌ Неправильно."
    elif block == 3:
        correct = task.get('correct_answer', '').lower()
        user = user_answer.strip().lower()
        is_correct = user == correct
        score = 100 if is_correct else 0
        feedback_message = "✅ Правильно!" if is_correct else "❌ Неправильно."
    elif block == 4:
        correct = task.get('correct_answer', '').lower()
        user = user_answer.strip().lower()
        is_correct = user == correct
        score = 100 if is_correct else 0
        feedback_message = "✅ Правильно!" if is_correct else "❌ Неправильно."
    else:
        correct = task.get('correct_answer', '').lower()
        user = user_answer.strip().lower()
        is_correct = user == correct
        score = 100 if is_correct else 0
        feedback_message = "✅ Правильно!" if is_correct else "❌ Неправильно."
    
    if task_id != -1:
        save_diagnostic_result(
            user_id=user_id, topic_id=topic_id, task_id=task_id,
            block=block, user_answer=user_answer, is_correct=is_correct,
            score=score, response_time=response_time
        )
    
    block_key = f"block_{block}"
    block_data = session['results'][block_key]
    block_data['answers'].append({'correct': is_correct, 'answer': user_answer, 'score': score})
    
    if block == 1:
        block_data['done'] = True
        block_data['score'] = score
        update_microtopic_progress(user_id, f"{topic_id}_concept", is_correct, score)
    else:
        if is_correct:
            block_data['correct'] += 1
        if len(block_data['answers']) >= block_data['total']:
            block_data['done'] = True
    
    session['results'][block_key] = block_data
    diagnostic_sessions[user_id] = session
    
    if block_data['done']:
        if block < 4:
            return {
                "block_completed": True,
                "next_block": block + 1,
                "message": f"Блок {block} завершён! {feedback_message}"
            }
        else:
            return finalize_diagnostic(session, user_id)
    else:
        return {
            "correct": is_correct,
            "block_completed": False,
            "message": feedback_message
        }

# ========== API ДЛЯ СТАТИСТИКИ ==========

@app.get("/api/stats")
async def get_stats(user_id: str):
    from datetime import date
    try:
        print(f"1. Получаем статистику для {user_id}")
        stats = get_user_stats(user_id)
        print(f"2. Статистика: {stats}")
        
        current_primary = stats['current_primary_score']
        print(f"3. Текущий первичный балл: {current_primary}")
        
        settings = {
            'hours_per_study_day': stats['hours_per_study_day'],
            'hours_per_holiday': stats['hours_per_holiday'],
            'other_subjects_count': stats['other_subjects_count']
        }
        print(f"4. Настройки: {settings}")
        
        available_hours = calculate_available_hours(settings)
        print(f"5. Доступно часов: {available_hours}")
        
        predicted_score = calculate_nvb(current_primary, available_hours)
        print(f"6. Прогноз: {predicted_score}")
        
        current_test = primary_to_test(current_primary)
        target_test = primary_to_test(stats['target_primary_score'])
        print(f"7. Баллы: текущий={current_test}, целевой={target_test}")
        
        motivation = get_motivation_message(current_primary, stats['target_primary_score'], available_hours, predicted_score)
        print(f"8. Мотивация получена")
        
        weekly_goal = get_weekly_goal(current_primary, available_hours)
        print(f"9. Недельная цель: {weekly_goal}")
        
        save_prediction(user_id, predicted_score, available_hours, current_primary)
        print(f"10. Прогноз сохранён")
        
        return {
            "current_score": current_test,
            "target_score": target_test,
            "predicted_score": predicted_score,
            "available_hours": available_hours,
            "days_until_exam": (EXAM_DATE - date.today()).days,
            "current_primary": current_primary,
            "target_primary": stats['target_primary_score'],
            "motivation_message": motivation,
            "weekly_goal": weekly_goal,
            "settings": settings
        }
    except Exception as e:
        print(f"ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}

@app.post("/api/stats/settings")
async def update_stats_settings(request: Request):
    data = await request.json()
    user_id = data.get('user_id')
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id обязателен")
    update_user_stats(
        user_id,
        current_primary_score=data.get('current_primary_score'),
        target_primary_score=data.get('target_primary_score'),
        hours_per_study_day=data.get('hours_per_study_day'),
        hours_per_holiday=data.get('hours_per_holiday'),
        other_subjects_count=data.get('other_subjects_count')
    )
    return {"status": "updated"}

@app.get("/api/student/stats/{student_id}")
async def get_student_stats(student_id: str):
    """Получает реальную статистику ученика"""
    # Получаем данные из существующих таблиц
    conn = sqlite3.connect('fred_users.db')
    c = conn.cursor()
    
    # Количество выполненных заданий
    c.execute('SELECT COUNT(*) FROM homework WHERE user_id = ? AND is_correct = 1', (student_id,))
    correct = c.fetchone()[0] or 0
    
    c.execute('SELECT COUNT(*) FROM homework WHERE user_id = ?', (student_id,))
    total = c.fetchone()[0] or 0
    
    # Количество тем
    c.execute('SELECT COUNT(*) FROM user_topics WHERE user_id = ?', (student_id,))
    topics = c.fetchone()[0] or 0
    
    # Текущий балл
    c.execute('SELECT score FROM user_topics WHERE user_id = ? ORDER BY last_attempt DESC LIMIT 1', (student_id,))
    score_row = c.fetchone()
    score = score_row[0] if score_row else 0
    
    conn.close()
    
    # Переводим в проценты
    progress = round((correct / total * 100) if total > 0 else 0)
    
    return {
        'score': score,
        'progress': progress,
        'tasks_done': total,
        'correct_tasks': correct,
        'topics_completed': topics,
        'weekly_gain': 5,  # Можно добавить расчёт за неделю
        'last_activity': 'сегодня'  # Можно добавить расчёт
    }

# ========== API ДЛЯ УЧЕБНОГО ПРОЦЕССА ==========

@app.post("/api/lesson/start")
async def start_lesson(request: Request):
    data = await request.json()
    user_id = data.get('user_id')
    topic_id = data.get('topic_id', 'A3')
    topic_name = data.get('topic_name', 'Логарифмы')
    
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id обязателен")
    
    # Создаём урок
    lesson_id = create_lesson(user_id, topic_id, topic_name)
    
    return {"lesson_id": lesson_id, "status": "started"}

@app.post("/api/lesson/mode")
async def load_lesson_mode(request: Request):
    data = await request.json()
    user_id = data.get('user_id')
    lesson_id = data.get('lesson_id')
    mode = data.get('mode', 'theory')
    
    if not user_id or not lesson_id:
        raise HTTPException(status_code=400, detail="user_id и lesson_id обязательны")
    
    # Получаем урок
    lesson = get_lesson(lesson_id)
    if not lesson:
        return {"error": "Урок не найден"}
    
    # Генерируем контент в зависимости от режима
    if mode == 'theory':
        content = "📖 **Теория: Логарифмы**\n\nЛогарифм — это показатель степени, в которую нужно возвести основание, чтобы получить число.\n\nПример: log₂8 = 3, потому что 2³ = 8.\n\n📌 **Главное свойство:** logₐ(b·c) = logₐb + logₐc"
        question = "Проверим понимание: что такое логарифм? Напиши своими словами."
        need_answer = True
        progress = 20
        
    elif mode == 'practice':
        content = "✍️ **Практика**\n\nРеши задачу: Вычислите log₂4 + log₂8"
        question = None
        need_answer = True
        progress = 50
        
    else:  # exam
        content = "🎯 **Контрольная работа**\n\nОтветь на 5 вопросов без рассуждений."
        question = "Вопрос 1/5: log₂32 = ?"
        need_answer = True
        progress = 80
    
    return {
        "content": content,
        "question": question,
        "need_answer": need_answer,
        "progress": progress,
        "next_action": "next_task" if mode != 'exam' else "finish_lesson"
    }


@app.post("/api/lesson/theory")
async def get_theory(request: Request):
    """Возвращает теорию по теме из базы знаний"""
    data = await request.json()
    user_id = data.get('user_id')
    topic = data.get('topic', 'логарифмы')
    
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id обязателен")
    
    # Ищем в базе знаний
    theory_text = ""
    sources = []
    
    if kb:
        try:
            # Поиск по теме
            # results = kb.search(topic, n_results=5)
            if results:
                theory_text = "📖 **Теория из базы знаний Фрэда:**\n\n"
                for i, result in enumerate(results):
                    source = result['metadata'].get('source', 'неизвестен')
                    theory_text += f"{result['text']}\n\n"
                    sources.append(source)
            else:
                theory_text = "📖 **Теория:**\n\nЛогарифм — это показатель степени, в которую нужно возвести основание, чтобы получить число.\n\nПример: log₂8 = 3, потому что 2³ = 8."
        except Exception as e:
            logging.warning(f"Ошибка поиска в базе знаний: {e}")
            theory_text = "📖 **Теория:**\n\nЛогарифм — это показатель степени, в которую нужно возвести основание, чтобы получить число.\n\nПример: log₂8 = 3, потому что 2³ = 8."
    else:
        theory_text = "📖 **Теория:**\n\nЛогарифм — это показатель степени, в которую нужно возвести основание, чтобы получить число.\n\nПример: log₂8 = 3, потому что 2³ = 8."
    
    return {
        "theory": theory_text,
        "sources": sources,
        "topic": topic
    }

@app.post("/api/lesson/answer")
async def lesson_answer(request: Request):
    data = await request.json()
    user_id = data.get('user_id')
    lesson_id = data.get('lesson_id')
    mode = data.get('mode', 'theory')
    answer = data.get('answer', '')
    
    if not user_id or not lesson_id:
        raise HTTPException(status_code=400, detail="user_id и lesson_id обязательны")
    
    # Нормализуем ответ (убираем лишние пробелы, приводим к нижнему регистру)
    answer_clean = answer.strip().lower()
    progress = 0
    reply = ""
    next_action = "next_task"
    
    # ===== РЕЖИМ ТЕОРИЯ =====
    if mode == 'theory':
        # Ключевые слова для проверки понимания логарифма
        keywords = ['степень', 'показатель', 'основание', 'число', 'log', 'логарифм']
        # Проверяем, есть ли хоть одно ключевое слово в ответе
        found = any(word in answer_clean for word in keywords)
        
        if found:
            reply = "✅ Отлично! Ты правильно понимаешь суть логарифма.\n\nА теперь мини-тест: log₃9 = ?"
            progress = 40
        else:
            # Если ответ слишком короткий или не содержит ключевых слов
            if len(answer_clean) < 3:
                reply = "⚠️ Попробуй ответить развёрнуто. Логарифм — это показатель степени, в которую нужно возвести основание, чтобы получить число.\n\nНапример: log₂8 = 3, потому что 2³ = 8.\n\nТеперь твоя очередь: что такое логарифм?"
            else:
                reply = "⚠️ Почти правильно! Но давай уточним: логарифм — это показатель степени, в которую нужно возвести основание, чтобы получить число.\n\nПопробуй ещё раз: что такое логарифм?"
            progress = 20
            next_action = "stay"  # остаёмся на том же шаге
    
    # ===== РЕЖИМ ПРАКТИКА =====
    elif mode == 'practice':
        # Проверяем ответ на задачу log₂4 + log₂8 = 5
        try:
            # Если ответ содержит число 5 или пользователь ввёл 5
            if '5' in answer_clean or answer_clean == '5':
                reply = "✅ Верно! log₂4 = 2, log₂8 = 3, сумма = 5. Молодец!\n\nСледующая задача: log₂16 - log₂2 = ?"
                progress = 60
            else:
                reply = "❌ Не совсем. Вспомни: log₂4 = 2, log₂8 = 3. Сложи их и напиши ответ."
                progress = 50
                next_action = "stay"
        except:
            reply = "❌ Не понял ответ. Напиши число."
            next_action = "stay"
    
    # ===== РЕЖИМ КОНТРОЛЬНАЯ =====
    else:  # exam
        # Проверяем ответ на первый вопрос контрольной
        if answer_clean == '5':
            reply = "✅ Вопрос 1/5: верно! log₂32 = 5, потому что 2⁵ = 32.\n\nВопрос 2/5: log₃27 = ?"
            progress = 85
        else:
            reply = f"❌ Неверно. log₂32 = 5 (2⁵ = 32).\n\nПопробуй ещё раз: log₂32 = ?"
            progress = 80
            next_action = "stay"
    
    # ===== ОПРЕДЕЛЯЕМ СЛЕДУЮЩЕЕ ДЕЙСТВИЕ =====
    if progress >= 90:
        next_action = "finish_lesson"
    elif next_action == "stay":
        pass  # остаёмся на том же шаге
    else:
        next_action = "next_task"
    
    return {
        "reply": reply,
        "progress": progress,
        "next_action": next_action
    }


@app.post("/api/homework/start")
async def start_homework(request: Request):
    """Начинает новое домашнее задание по уроку"""
    data = await request.json()
    user_id = data.get('user_id')
    lesson_id = data.get('lesson_id')
    topic_id = data.get('topic_id', 'A3')
    topic_name = data.get('topic_name', 'Логарифмы')
    
    if not user_id or not lesson_id:
        raise HTTPException(status_code=400, detail="user_id и lesson_id обязательны")
    
    # Генерируем задания для ДЗ (5 задач)
    tasks = [
        {'text': 'Решите уравнение: log₂(x+3) = 4', 'answer': '13', 'type': 'equation'},
        {'text': 'Вычислите: log₅125', 'answer': '3', 'type': 'number'},
        {'text': 'log₂16 - log₂4 = ?', 'answer': '2', 'type': 'number'},
        {'text': 'log₃(2x-1) = 2', 'answer': '5', 'type': 'equation'},
        {'text': 'Чему равен log₂32?', 'answer': '5', 'type': 'number'},
    ]
    
    homework_ids = []
    for i, task in enumerate(tasks, 1):
        hw_id = create_homework_task(
            user_id=user_id,
            lesson_id=lesson_id,
            topic_id=topic_id,
            task_number=i,
            task_text=task['text'],
            task_type=task['type'],
            correct_answer=task['answer']
        )
        homework_ids.append(hw_id)
    
    return {
        'status': 'started',
        'lesson_id': lesson_id,
        'total_tasks': len(tasks),
        'homework_ids': homework_ids
    }

@app.get("/api/homework/task/{homework_id}")
async def get_homework_task(homework_id: int):
    """Получает задание ДЗ по ID"""
    conn = sqlite3.connect('fred_users.db')
    c = conn.cursor()
    c.execute('''SELECT id, task_number, task_text, task_type, user_answer, user_reasoning, attempts, score
                 FROM homework WHERE id = ?''', (homework_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Задание не найдено")
    
    return {
        'id': row[0],
        'task_number': row[1],
        'task_text': row[2],
        'task_type': row[3],
        'user_answer': row[4],
        'user_reasoning': row[5],
        'attempts': row[6],
        'score': row[7]
    }

@app.post("/api/homework/submit")
async def submit_homework(request: Request):
    """Отправляет ответ на ДЗ с пошаговыми рассуждениями"""
    data = await request.json()
    homework_id = data.get('homework_id')
    user_answer = data.get('user_answer', '')
    steps = data.get('steps', [])  # список шагов: [{"step": 1, "action": "...", "reasoning": "..."}]
    
    if not homework_id:
        raise HTTPException(status_code=400, detail="homework_id обязателен")
    
    # Получаем задание
    conn = sqlite3.connect('fred_users.db')
    c = conn.cursor()
    c.execute('SELECT task_text, correct_answer FROM homework WHERE id = ?', (homework_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Задание не найдено")
    
    task_text, correct_answer = row
    
    # Проверяем каждый шаг
    checked_steps = []
    correct_count = 0
    
    for step in steps:
        reasoning = step.get('reasoning', '').strip()
        # Простая проверка: длина > 3 (можно усложнить)
        is_correct = len(reasoning) > 3
        checked_steps.append({
            'step': step.get('step'),
            'action': step.get('action'),
            'reasoning': reasoning,
            'is_correct': is_correct,
            'feedback': '✅ Верно!' if is_correct else '❌ Проверь это место.'
        })
        if is_correct:
            correct_count += 1
    
    # Проверяем финальный ответ
    user_clean = user_answer.strip().lower()
    correct_clean = correct_answer.strip().lower()
    is_answer_correct = user_clean == correct_clean
    
    # Если ответ правильный, добавляем балл
    if is_answer_correct:
        correct_count += 1
    
    total_steps = len(steps) + 1  # +1 за финальный ответ
    score = round((correct_count / total_steps) * 100) if total_steps > 0 else 0
    is_passed = score >= 70
    
    # Сохраняем в БД
    steps_json = json.dumps(checked_steps)
    feedback = "🎉 Отлично!" if is_passed else "📖 Есть над чем поработать. Попробуй ещё раз."
    grade_homework(homework_id, is_passed, score, feedback, steps_json)
    
    return {
        'steps': checked_steps,
        'is_answer_correct': is_answer_correct,
        'score': score,
        'passed': is_passed,
        'feedback': feedback
    }

@app.get("/api/homework/stats/{user_id}")
async def get_homework_stats(user_id: str):
    """Статистика по ДЗ"""
    stats = get_homework_stats(user_id)
    return stats






# ========== API ДЛЯ АУТЕНТИФИКАЦИИ ==========

@app.post("/api/auth/register")
async def register(request: Request):
    """Регистрация нового пользователя"""
    data = await request.json()
    email = data.get('email')
    password = data.get('password')
    first_name = data.get('first_name', '')
    role = data.get('role', 'student')
    
    result = create_user(email, password, first_name, role)
    if 'error' in result:
        raise HTTPException(status_code=400, detail=result['error'])
    
    return result

@app.post("/api/auth/login")
async def login(request: Request):
    """Авторизация пользователя"""
    data = await request.json()
    email = data.get('email')
    password = data.get('password')
    
    result = authenticate_user(email, password)
    if 'error' in result:
        raise HTTPException(status_code=401, detail=result['error'])
    
    return result

@app.get("/api/auth/me")
async def get_current_user(user_id: str):
    """Получить данные текущего пользователя"""
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user

@app.get("/api/auth/check-role")
async def check_role(user_id: str):
    """Проверить роль пользователя"""
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return {'user_id': user_id, 'role': user['role']}

@app.get("/api/user/find-by-email")
async def find_user_by_email(email: str):
    conn = sqlite3.connect('fred_users.db')
    c = conn.cursor()
    c.execute('SELECT user_id, first_name, role FROM users WHERE email = ?', (email,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    return {
        'user_id': row[0],
        'first_name': row[1],
        'role': row[2]
    }


# ========== API ДЛЯ СВЯЗИ УЧЕНИК-РОДИТЕЛЬ ==========

@app.post("/api/family/link")
async def create_link(request: Request):
    data = await request.json()
    parent_id = data.get('parent_id')
    student_id = data.get('student_id')
    
    if not parent_id or not student_id:
        raise HTTPException(status_code=400, detail="parent_id и student_id обязательны")
    
    result = create_family_link(parent_id, student_id)
    if 'error' in result:
        raise HTTPException(status_code=400, detail=result['error'])
    
    # Получаем имя родителя
    conn = sqlite3.connect('fred_users.db')
    c = conn.cursor()
    c.execute('SELECT first_name FROM users WHERE user_id = ?', (parent_id,))
    row = c.fetchone()
    conn.close()
    parent_name = row[0] if row else 'Родитель'
    
    # Создаём уведомление для ученика
    create_notification(
        user_id=student_id,
        title='👨‍👩‍👧 Запрос от родителя',
        message=f'{parent_name} хочет видеть ваш прогресс. Примите запрос, чтобы начать совместное обучение.',
        link='/static/student.html'
    )
    
    return result

@app.get("/api/family/children")
async def get_children(parent_id: str):
    """Получает всех учеников родителя"""
    children = get_family_links(parent_id)
    # Добавляем статистику для каждого ребёнка
    for child in children:
        stats = get_student_stats(child['student_id'])
        child.update(stats)
    return {'children': children}

@app.get("/api/family/parents")
async def get_parents(student_id: str):
    """Получает всех родителей ученика"""
    parents = get_student_parents(student_id)
    return {'parents': parents}

@app.post("/api/family/accept")
async def accept_link(request: Request):
    """Принимает запрос на связь"""
    data = await request.json()
    link_id = data.get('link_id')
    
    if not link_id:
        raise HTTPException(status_code=400, detail="link_id обязателен")
    
    result = accept_family_link(link_id)
    return result

@app.post("/api/family/unlink")
async def unlink_child(request: Request):
    """Отвязывает ученика от родителя (только родитель)"""
    data = await request.json()
    parent_id = data.get('parent_id')
    student_id = data.get('student_id')
    
    if not parent_id or not student_id:
        raise HTTPException(status_code=400, detail="parent_id и student_id обязательны")
    
    # Проверяем, что parent_id действительно родитель
    conn = sqlite3.connect('fred_users.db')
    c = conn.cursor()
    c.execute('SELECT role FROM users WHERE user_id = ?', (parent_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    if row[0] != 'parent':
        raise HTTPException(status_code=403, detail="Только родитель может отвязать ученика")
    
    # Проверяем, что student_id действительно ученик
    conn = sqlite3.connect('fred_users.db')
    c = conn.cursor()
    c.execute('SELECT role FROM users WHERE user_id = ?', (student_id,))
    row = c.fetchone()
    conn.close()
    
    if not row or row[0] != 'student':
        raise HTTPException(status_code=400, detail="Указанный пользователь не является учеником")
    
    result = remove_family_link(parent_id, student_id, removed_by='parent')
    if 'error' in result:
        raise HTTPException(status_code=400, detail=result['error'])
    
    return result


# ========== ЗАПУСК ==========
if __name__ == "__main__":
    print("🚀 Веб-сервер Фрэда запускается...")
    print("📍 Открой в браузере: http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)