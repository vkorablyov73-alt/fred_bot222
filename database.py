import sqlite3
from datetime import datetime
import json
import logging
from typing import List, Dict, Optional, Any
import bcrypt
import re

DB_NAME = 'fred_users.db'

def init_db():
    """Создаёт таблицы, если их нет"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Таблица пользователей (расширенная)
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        email TEXT UNIQUE,
        password_hash TEXT,
        role TEXT DEFAULT 'student',  -- student, parent, teacher
        is_active BOOLEAN DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        first_seen TIMESTAMP,
        last_seen TIMESTAMP,
        total_messages INTEGER DEFAULT 0,
        current_mode TEXT DEFAULT 'study'
    )''')
    
    # ... остальные таблицы ...
    
    # Таблица сообщений (история диалогов)
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id TEXT,
                  role TEXT,
                  content TEXT,
                  timestamp TIMESTAMP)''')
    
    # Таблица тем (список всех тем ЕГЭ)
    c.execute('''CREATE TABLE IF NOT EXISTS topics
                 (topic_id TEXT PRIMARY KEY,
                  topic_name TEXT,
                  difficulty INTEGER)''')
    
    # Таблица прогресса по темам для каждого пользователя
    c.execute('''CREATE TABLE IF NOT EXISTS user_topics
                 (user_id TEXT,
                  topic_id TEXT,
                  score INTEGER DEFAULT 3,
                  attempts INTEGER DEFAULT 0,
                  correct INTEGER DEFAULT 0,
                  last_attempt TIMESTAMP,
                  PRIMARY KEY (user_id, topic_id))''')
    
    conn.commit()
    conn.close()
    logging.info("База данных инициализирована")
    
    # Заполняем темы, если таблица пуста
    _init_topics()
    
    # Инициализируем таблицы диагностики
    init_diagnostic_tables()

   
    # ДОБАВЬТЕ ЭТУ СТРОЧКУ:
    init_learning_tables()  # <-- НОВЫЕ ТАБЛИЦЫ


    init_family_tables()
    init_notifications_tables()  # <-- ДОБАВИТЬ



# ========== ТАБЛИЦА СВЯЗЕЙ УЧЕНИК-РОДИТЕЛЬ ==========

def init_family_tables():
    """Создаёт таблицу для связей ученик-родитель"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS family_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id TEXT NOT NULL,
        student_id TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        removed_by TEXT DEFAULT NULL,  -- parent или student (кто отвязал)
        removed_at TIMESTAMP DEFAULT NULL,
        FOREIGN KEY (parent_id) REFERENCES users(user_id),
        FOREIGN KEY (student_id) REFERENCES users(user_id),
        UNIQUE(parent_id, student_id)
    )''')
    
    c.execute('CREATE INDEX IF NOT EXISTS idx_family_parent ON family_links(parent_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_family_student ON family_links(student_id)')
    
    conn.commit()
    conn.close()
    logging.info("Таблица family_links создана")




def _init_topics():
    """Заполняет список тем ЕГЭ"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Проверяем, есть ли уже темы
    c.execute("SELECT COUNT(*) FROM topics")
    if c.fetchone()[0] == 0:
        topics = [
            ("A1", "Проценты, отношения", 1),
            ("A2", "Степени и корни", 1),
            ("A3", "Логарифмы", 2),
            ("A4", "Тождественные преобразования", 1),
            ("A5", "Функции и графики", 1),
            ("A6", "Линейные уравнения", 1),
            ("A7", "Квадратные уравнения", 2),
            ("A8", "Рациональные уравнения", 2),
            ("A9", "Иррациональные уравнения", 2),
            ("A10", "Показательные уравнения", 2),
            ("A11", "Логарифмические уравнения", 2),
            ("A12", "Системы уравнений", 2),
            ("A13", "Текстовые задачи", 2),
            ("A14", "Производная (определение)", 2),
            ("A15", "Производная (исследование)", 2),
            ("B1", "Планиметрия (треугольники)", 1),
            ("B2", "Планиметрия (четырехугольники)", 2),
            ("B3", "Планиметрия (окружность)", 2),
            ("B4", "Стереометрия (многогранники)", 2),
            ("B5", "Стереометрия (тела вращения)", 2),
            ("B6", "Векторы", 1),
            ("B7", "Теория вероятностей", 2),
            ("B8", "Экономические задачи", 3),
        ]
        c.executemany("INSERT INTO topics (topic_id, topic_name, difficulty) VALUES (?, ?, ?)", topics)
        conn.commit()
        logging.info(f"Добавлено {len(topics)} тем")
    
    conn.close()

def init_diagnostic_tables():
    """Создаёт таблицы для диагностики, если их нет"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Таблица заданий
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id TEXT NOT NULL,
        microtopic_id TEXT,
        block INTEGER NOT NULL,
        difficulty INTEGER DEFAULT 1,
        question TEXT NOT NULL,
        question_type TEXT DEFAULT 'text',
        correct_answer TEXT NOT NULL,
        options TEXT,
        explanation TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('CREATE INDEX IF NOT EXISTS idx_tasks_topic ON tasks(topic_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_tasks_block ON tasks(block)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_tasks_microtopic ON tasks(microtopic_id)')
    
    # Таблица результатов диагностики
    c.execute('''CREATE TABLE IF NOT EXISTS diagnostic_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        topic_id TEXT NOT NULL,
        microtopic_id TEXT,
        task_id INTEGER,
        block INTEGER,
        user_answer TEXT,
        is_correct BOOLEAN,
        score INTEGER,
        response_time INTEGER,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (task_id) REFERENCES tasks(id)
    )''')
    
    c.execute('CREATE INDEX IF NOT EXISTS idx_results_user ON diagnostic_results(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_results_topic ON diagnostic_results(topic_id)')
    
    # Таблица прогресса по микротемам
    c.execute('''CREATE TABLE IF NOT EXISTS microtopic_progress (
        user_id TEXT NOT NULL,
        microtopic_id TEXT NOT NULL,
        status TEXT DEFAULT 'not_started',
        best_score INTEGER DEFAULT 0,
        attempts INTEGER DEFAULT 0,
        last_attempt TIMESTAMP,
        PRIMARY KEY (user_id, microtopic_id)
    )''')
    
    conn.commit()
    conn.close()
    logging.info("Таблицы для диагностики инициализированы")

def get_or_create_user(user_id, username=None, first_name=None):
    """Возвращает пользователя из БД или создаёт нового"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    
    if user is None:
        now = datetime.now().isoformat()
        c.execute('''INSERT INTO users 
                     (user_id, username, first_name, first_seen, last_seen, total_messages)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (user_id, username, first_name, now, now, 0))
        conn.commit()
        logging.info(f"Новый пользователь: {user_id}")
        
        c.execute("SELECT topic_id FROM topics")
        topics = c.fetchall()
        for topic in topics:
            c.execute('''INSERT OR IGNORE INTO user_topics 
                         (user_id, topic_id, score, attempts, correct)
                         VALUES (?, ?, 3, 0, 0)''',
                      (user_id, topic[0]))
        conn.commit()
    
    conn.close()
    return user

def update_last_seen(user_id):
    """Обновляет время последнего визита"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("UPDATE users SET last_seen = ?, total_messages = total_messages + 1 WHERE user_id = ?",
              (now, user_id))
    conn.commit()
    conn.close()

def save_message(user_id, role, content):
    """Сохраняет сообщение в историю"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute('''INSERT INTO messages (user_id, role, content, timestamp)
                 VALUES (?, ?, ?, ?)''',
              (user_id, role, content, now))
    conn.commit()
    conn.close()

def get_recent_messages(user_id, limit=20):
    """Возвращает последние N сообщений пользователя"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT role, content FROM messages 
                 WHERE user_id = ? 
                 ORDER BY timestamp DESC LIMIT ?''',
              (user_id, limit))
    rows = c.fetchall()
    conn.close()
    
    messages = [{"role": row[0], "content": row[1]} for row in reversed(rows)]
    return messages

def clear_user_history(user_id):
    """Очищает историю сообщений пользователя"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def update_topic_score(user_id, topic_id, is_correct):
    """Обновляет оценку по теме на основе правильности ответа"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute("SELECT score, attempts, correct FROM user_topics WHERE user_id = ? AND topic_id = ?",
              (user_id, topic_id))
    row = c.fetchone()
    
    if row:
        current_score, attempts, correct = row
        attempts += 1
        if is_correct:
            correct += 1
        
        ratio = correct / attempts if attempts > 0 else 0.5
        
        if ratio >= 0.95:
            new_score = 5
        elif ratio >= 0.85:
            new_score = 4
        elif ratio >= 0.70:
            new_score = 3
        else:
            new_score = 2
        
        c.execute('''UPDATE user_topics 
                     SET score = ?, attempts = ?, correct = ?, last_attempt = ?
                     WHERE user_id = ? AND topic_id = ?''',
                  (new_score, attempts, correct, datetime.now().isoformat(), user_id, topic_id))
        
        logging.info(f"Обновлена тема {topic_id} для {user_id}: score={new_score}, ratio={ratio:.2f}")
    
    conn.commit()
    conn.close()

def get_weak_topics(user_id, limit=5):
    """Возвращает самые слабые темы пользователя"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT t.topic_name, ut.score, ut.attempts, ut.correct
                 FROM user_topics ut
                 JOIN topics t ON ut.topic_id = t.topic_id
                 WHERE ut.user_id = ? AND ut.attempts >= 2
                 ORDER BY ut.score ASC, ut.attempts DESC
                 LIMIT ?''', (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows

def get_topic_summary(user_id):
    """Возвращает сводку по всем темам"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT t.topic_name, ut.score, ut.attempts
                 FROM user_topics ut
                 JOIN topics t ON ut.topic_id = t.topic_id
                 WHERE ut.user_id = ?
                 ORDER BY t.topic_id''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_user_mode(user_id):
    """Возвращает текущий режим пользователя"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT current_mode FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 'study'

def set_user_mode(user_id, mode):
    """Устанавливает режим пользователя"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET current_mode = ? WHERE user_id = ?", (mode, user_id))
    conn.commit()
    conn.close()

# ========== ФУНКЦИИ ДЛЯ ДИАГНОСТИКИ ==========

def add_task(topic_id, microtopic_id, block, difficulty, question, correct_answer, 
             question_type='text', options=None, explanation=None):
    """Добавляет новое задание в базу"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''INSERT INTO tasks 
                 (topic_id, microtopic_id, block, difficulty, question, 
                  question_type, correct_answer, options, explanation)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (topic_id, microtopic_id, block, difficulty, question, 
               question_type, correct_answer, json.dumps(options) if options else None, explanation))
    
    conn.commit()
    task_id = c.lastrowid
    conn.close()
    logging.info(f"Добавлено задание {task_id} для темы {topic_id}")
    return task_id

def get_tasks_by_topic(topic_id, block=None):
    """Получает все задания по теме"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    if block:
        c.execute('''SELECT id, topic_id, microtopic_id, block, difficulty, question, 
                            question_type, correct_answer, options, explanation
                     FROM tasks 
                     WHERE topic_id = ? AND block = ?
                     ORDER BY difficulty''', (topic_id, block))
    else:
        c.execute('''SELECT id, topic_id, microtopic_id, block, difficulty, question, 
                            question_type, correct_answer, options, explanation
                     FROM tasks 
                     WHERE topic_id = ?
                     ORDER BY block, difficulty''', (topic_id,))
    
    rows = c.fetchall()
    conn.close()
    
    tasks = []
    for row in rows:
        tasks.append({
            'id': row[0],
            'topic_id': row[1],
            'microtopic_id': row[2],
            'block': row[3],
            'difficulty': row[4],
            'question': row[5],
            'question_type': row[6],
            'correct_answer': row[7],
            'options': json.loads(row[8]) if row[8] else None,
            'explanation': row[9]
        })
    return tasks

def get_random_task(topic_id, block, difficulty=None):
    """Получает случайное задание по теме, блоку и сложности"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    if difficulty:
        c.execute('''SELECT id, question, question_type, correct_answer, options, explanation
                     FROM tasks 
                     WHERE topic_id = ? AND block = ? AND difficulty = ?
                     ORDER BY RANDOM() LIMIT 1''', (topic_id, block, difficulty))
    else:
        c.execute('''SELECT id, question, question_type, correct_answer, options, explanation
                     FROM tasks 
                     WHERE topic_id = ? AND block = ?
                     ORDER BY RANDOM() LIMIT 1''', (topic_id, block))
    
    row = c.fetchone()
    conn.close()
    
    if row:
        return {
            'id': row[0],
            'question': row[1],
            'question_type': row[2],
            'correct_answer': row[3],
            'options': json.loads(row[4]) if row[4] else None,
            'explanation': row[5]
        }
    return None

def save_diagnostic_result(user_id, topic_id, task_id, block, user_answer, is_correct, score=None, response_time=None, microtopic_id=None):
    """Сохраняет результат выполнения задания"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''INSERT INTO diagnostic_results 
                 (user_id, topic_id, microtopic_id, task_id, block, user_answer, is_correct, score, response_time)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (user_id, topic_id, microtopic_id, task_id, block, user_answer, is_correct, score, response_time))
    
    conn.commit()
    conn.close()
    logging.info(f"Сохранён результат для пользователя {user_id}, задание {task_id}")

def get_topic_diagnostic_summary(user_id, topic_id):
    """Получает сводку по диагностике темы"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''SELECT block, 
                        COUNT(*) as total,
                        SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct
                 FROM diagnostic_results 
                 WHERE user_id = ? AND topic_id = ?
                 GROUP BY block''', (user_id, topic_id))
    
    rows = c.fetchall()
    conn.close()
    
    summary = {}
    for row in rows:
        block = row[0]
        total = row[1]
        correct = row[2] or 0
        summary[block] = {
            'total': total,
            'correct': correct,
            'percentage': (correct / total * 100) if total > 0 else 0
        }
    
    return summary

def update_microtopic_progress(user_id, microtopic_id, is_correct, score):
    """Обновляет прогресс по микротеме"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('SELECT status, best_score, attempts FROM microtopic_progress WHERE user_id = ? AND microtopic_id = ?',
              (user_id, microtopic_id))
    row = c.fetchone()
    
    now = datetime.now().isoformat()
    
    if row is None:
        if is_correct and score >= 80:
            status = 'mastered'
        elif is_correct and score >= 50:
            status = 'partial'
        else:
            status = 'not_started'
        
        c.execute('''INSERT INTO microtopic_progress 
                     (user_id, microtopic_id, status, best_score, attempts, last_attempt)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (user_id, microtopic_id, status, score if is_correct else 0, 1, now))
    else:
        status, best_score, attempts = row
        new_attempts = attempts + 1
        new_best_score = max(best_score, score if is_correct else 0)
        
        if new_best_score >= 90:
            new_status = 'mastered'
        elif new_best_score >= 60:
            new_status = 'partial'
        else:
            new_status = 'not_mastered'
        
        c.execute('''UPDATE microtopic_progress 
                     SET status = ?, best_score = ?, attempts = ?, last_attempt = ?
                     WHERE user_id = ? AND microtopic_id = ?''',
                  (new_status, new_best_score, new_attempts, now, user_id, microtopic_id))
    
    conn.commit()
    conn.close()

def get_microtopic_progress(user_id, microtopic_id):
    """Получает прогресс по конкретной микротеме"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('SELECT status, best_score, attempts, last_attempt FROM microtopic_progress WHERE user_id = ? AND microtopic_id = ?', (user_id, microtopic_id))
    row = c.fetchone()
    conn.close()
    
    if row:
        return {
            'status': row[0],
            'best_score': row[1],
            'attempts': row[2],
            'last_attempt': row[3]
        }
    return {'status': 'not_started', 'best_score': 0, 'attempts': 0}

def get_all_microtopic_progress(user_id):
    """Получает прогресс по всем микротемам для пользователя"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('SELECT microtopic_id, status, best_score, attempts FROM microtopic_progress WHERE user_id = ?', (user_id,))
    rows = c.fetchall()
    conn.close()
    
    return {row[0]: {'status': row[1], 'best_score': row[2], 'attempts': row[3]} for row in rows}

# ========== ФУНКЦИИ ДЛЯ СТАТИСТИКИ ==========

def get_user_stats(user_id):
    """Получает статистику пользователя"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT current_primary_score, target_primary_score, hours_per_study_day, hours_per_holiday, other_subjects_count FROM user_stats WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    
    if row:
        return {
            'current_primary_score': row[0],
            'target_primary_score': row[1],
            'hours_per_study_day': row[2],
            'hours_per_holiday': row[3],
            'other_subjects_count': row[4]
        }
    return {
        'current_primary_score': 0,
        'target_primary_score': 17,
        'hours_per_study_day': 2,
        'hours_per_holiday': 8,
        'other_subjects_count': 3
    }

def update_user_stats(user_id, current_primary_score=None, target_primary_score=None, 
                      hours_per_study_day=None, hours_per_holiday=None, other_subjects_count=None):
    """Обновляет статистику пользователя"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    stats = get_user_stats(user_id)
    
    new_current = current_primary_score if current_primary_score is not None else stats['current_primary_score']
    new_target = target_primary_score if target_primary_score is not None else stats['target_primary_score']
    new_study_day = hours_per_study_day if hours_per_study_day is not None else stats['hours_per_study_day']
    new_holiday = hours_per_holiday if hours_per_holiday is not None else stats['hours_per_holiday']
    new_other = other_subjects_count if other_subjects_count is not None else stats['other_subjects_count']
    
    c.execute('''INSERT OR REPLACE INTO user_stats 
                 (user_id, current_primary_score, target_primary_score, 
                  hours_per_study_day, hours_per_holiday, other_subjects_count)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (user_id, new_current, new_target, new_study_day, new_holiday, new_other))
    
    conn.commit()
    conn.close()

def save_prediction(user_id, predicted_score, available_hours, current_primary):
    """Сохраняет прогноз в историю"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute('''INSERT INTO prediction_history 
                 (user_id, date, predicted_score, available_hours_remaining, current_primary_score)
                 VALUES (?, ?, ?, ?, ?)''',
              (user_id, now, predicted_score, available_hours, current_primary))
    conn.commit()
    conn.close()


# ========== НОВЫЕ ТАБЛИЦЫ ДЛЯ УЧЕБНОГО ПРОЦЕССА ==========

def init_learning_tables():
    """Создаёт таблицы для учебного процесса (уроки, ДЗ, практика, контрольные)"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # 1. Уроки (сессии занятий)
    c.execute('''CREATE TABLE IF NOT EXISTS lessons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        topic_id TEXT NOT NULL,
        topic_name TEXT,
        mode TEXT DEFAULT 'theory',
        status TEXT DEFAULT 'started',
        completed BOOLEAN DEFAULT 0,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )''')
    
    # 2. Домашние задания
    c.execute('''CREATE TABLE IF NOT EXISTS homework (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        lesson_id INTEGER NOT NULL,
        topic_id TEXT NOT NULL,
        task_number INTEGER,
        task_text TEXT,
        task_type TEXT DEFAULT 'text',
        correct_answer TEXT,
        user_answer TEXT,
        user_reasoning TEXT,
        steps TEXT,
        is_correct BOOLEAN DEFAULT 0,
        score INTEGER DEFAULT 0,
        feedback TEXT,
        attempts INTEGER DEFAULT 0,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id),
        FOREIGN KEY (lesson_id) REFERENCES lessons(id)
    )''')
    
    # 3. Практические задачи
    c.execute('''CREATE TABLE IF NOT EXISTS practice_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        topic_id TEXT NOT NULL,
        task_text TEXT,
        task_type TEXT DEFAULT 'text',
        correct_answer TEXT,
        user_answer TEXT,
        user_reasoning TEXT,
        is_correct BOOLEAN DEFAULT 0,
        difficulty INTEGER DEFAULT 1,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )''')
    
    # 4. Статистика практики по темам
    c.execute('''CREATE TABLE IF NOT EXISTS practice_stats (
        user_id TEXT NOT NULL,
        topic_id TEXT NOT NULL,
        total_solved INTEGER DEFAULT 0,
        correct_solved INTEGER DEFAULT 0,
        last_attempt TIMESTAMP,
        PRIMARY KEY (user_id, topic_id)
    )''')
    
    # 5. Контрольные работы
    c.execute('''CREATE TABLE IF NOT EXISTS exams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        topic_id TEXT NOT NULL,
        lesson_id INTEGER NOT NULL,
        questions_count INTEGER DEFAULT 0,
        correct_count INTEGER DEFAULT 0,
        score INTEGER DEFAULT 0,
        time_spent INTEGER DEFAULT 0,
        answers TEXT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id),
        FOREIGN KEY (lesson_id) REFERENCES lessons(id)
    )''')
    
    # 6. Прогресс ученика по темам
    c.execute('''CREATE TABLE IF NOT EXISTS topic_progress (
        user_id TEXT NOT NULL,
        topic_id TEXT NOT NULL,
        theory_completed BOOLEAN DEFAULT 0,
        practice_completed BOOLEAN DEFAULT 0,
        exam_completed BOOLEAN DEFAULT 0,
        total_tasks_solved INTEGER DEFAULT 0,
        correct_tasks_solved INTEGER DEFAULT 0,
        exam_score INTEGER DEFAULT 0,
        last_lesson_date TIMESTAMP,
        PRIMARY KEY (user_id, topic_id)
    )''')
    
    # Индексы
    c.execute('CREATE INDEX IF NOT EXISTS idx_lessons_user ON lessons(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_homework_user ON homework(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_practice_user ON practice_tasks(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_exams_user ON exams(user_id)')
    
    conn.commit()
    conn.close()
    logging.info("Таблицы для учебного процесса созданы")


# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С НОВЫМИ ТАБЛИЦАМИ ==========

def create_lesson(user_id: str, topic_id: str, topic_name: str) -> int:
    """Создаёт новый урок и возвращает его ID"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''INSERT INTO lessons (user_id, topic_id, topic_name, mode, status, date)
                 VALUES (?, ?, ?, 'theory', 'started', CURRENT_TIMESTAMP)''',
              (user_id, topic_id, topic_name))
    
    lesson_id = c.lastrowid
    conn.commit()
    conn.close()
    return lesson_id

def get_lesson(lesson_id: int):
    """Получает данные урока по ID"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT id, user_id, topic_id, topic_name, mode, status, completed, date
                 FROM lessons WHERE id = ?''', (lesson_id,))
    row = c.fetchone()
    conn.close()
    
    if row:
        return {
            'id': row[0],
            'user_id': row[1],
            'topic_id': row[2],
            'topic_name': row[3],
            'mode': row[4],
            'status': row[5],
            'completed': row[6],
            'date': row[7]
        }
    return None

def update_lesson_mode(lesson_id: int, mode: str):
    """Обновляет режим урока"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('UPDATE lessons SET mode = ?, status = "in_progress" WHERE id = ?', (mode, lesson_id))
    conn.commit()
    conn.close()

def complete_lesson(lesson_id: int):
    """Отмечает урок как завершённый"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('UPDATE lessons SET completed = 1, status = "completed" WHERE id = ?', (lesson_id,))
    conn.commit()
    conn.close()

def save_homework(user_id: str, lesson_id: int, topic_id: str, task_number: int,
                  task_text: str, task_type: str, correct_answer: str,
                  user_answer: str, user_reasoning: str, steps: str = None) -> int:
    """Сохраняет домашнее задание"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''INSERT INTO homework 
                 (user_id, lesson_id, topic_id, task_number, task_text, task_type,
                  correct_answer, user_answer, user_reasoning, steps, attempts, date)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)''',
              (user_id, lesson_id, topic_id, task_number, task_text, task_type,
               correct_answer, user_answer, user_reasoning, steps))
    
    homework_id = c.lastrowid
    conn.commit()
    conn.close()
    return homework_id

def check_homework(homework_id: int, is_correct: bool, score: int, feedback: str):
    """Обновляет результат проверки домашнего задания"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''UPDATE homework 
                 SET is_correct = ?, score = ?, feedback = ?, attempts = attempts + 1
                 WHERE id = ?''', (is_correct, score, feedback, homework_id))
    conn.commit()
    conn.close()

def save_practice_task(user_id: str, topic_id: str, task_text: str, task_type: str,
                       correct_answer: str, user_answer: str, user_reasoning: str,
                       is_correct: bool, difficulty: int = 1):
    """Сохраняет выполненное практическое задание"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''INSERT INTO practice_tasks 
                 (user_id, topic_id, task_text, task_type, correct_answer,
                  user_answer, user_reasoning, is_correct, difficulty, date)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
              (user_id, topic_id, task_text, task_type, correct_answer,
               user_answer, user_reasoning, is_correct, difficulty))
    
    conn.commit()
    conn.close()
    
    update_practice_stats(user_id, topic_id, is_correct)

def update_practice_stats(user_id: str, topic_id: str, is_correct: bool):
    """Обновляет статистику практики по теме"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''INSERT INTO practice_stats (user_id, topic_id, total_solved, correct_solved, last_attempt)
                 VALUES (?, ?, 1, ?, CURRENT_TIMESTAMP)
                 ON CONFLICT(user_id, topic_id) DO UPDATE SET
                 total_solved = total_solved + 1,
                 correct_solved = correct_solved + ?,
                 last_attempt = CURRENT_TIMESTAMP''',
              (user_id, topic_id, 1 if is_correct else 0, 1 if is_correct else 0))
    
    conn.commit()
    conn.close()

def get_practice_stats(user_id: str, topic_id: str) -> dict:
    """Получает статистику практики по теме"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT total_solved, correct_solved, last_attempt
                 FROM practice_stats WHERE user_id = ? AND topic_id = ?''',
              (user_id, topic_id))
    row = c.fetchone()
    conn.close()
    
    if row:
        return {
            'total_solved': row[0],
            'correct_solved': row[1],
            'last_attempt': row[2],
            'success_rate': round(row[1] / row[0] * 100, 1) if row[0] > 0 else 0
        }
    return {'total_solved': 0, 'correct_solved': 0, 'success_rate': 0}

def create_exam(user_id: str, topic_id: str, lesson_id: int) -> int:
    """Создаёт новую контрольную работу"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''INSERT INTO exams (user_id, topic_id, lesson_id, date)
                 VALUES (?, ?, ?, CURRENT_TIMESTAMP)''',
              (user_id, topic_id, lesson_id))
    
    exam_id = c.lastrowid
    conn.commit()
    conn.close()
    return exam_id

def submit_exam(exam_id: int, questions_count: int, correct_count: int,
                score: int, time_spent: int, answers: str):
    """Сохраняет результаты контрольной работы"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''UPDATE exams 
                 SET questions_count = ?, correct_count = ?, score = ?,
                     time_spent = ?, answers = ?
                 WHERE id = ?''',
              (questions_count, correct_count, score, time_spent, answers, exam_id))
    
    conn.commit()
    conn.close()

def get_user_progress(user_id: str) -> list:
    """Получает прогресс ученика по всем темам"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''SELECT topic_id, theory_completed, practice_completed, exam_completed,
                        total_tasks_solved, correct_tasks_solved, exam_score
                 FROM topic_progress WHERE user_id = ?''', (user_id,))
    rows = c.fetchall()
    conn.close()
    
    progress = []
    for row in rows:
        progress.append({
            'topic_id': row[0],
            'theory_completed': bool(row[1]),
            'practice_completed': bool(row[2]),
            'exam_completed': bool(row[3]),
            'total_tasks_solved': row[4],
            'correct_tasks_solved': row[5],
            'exam_score': row[6]
        })
    return progress



# ========== ФУНКЦИИ ДЛЯ ДОМАШНИХ ЗАДАНИЙ ==========

def get_homework_by_lesson(lesson_id: int) -> List[Dict]:
    """Получает все домашние задания по уроку"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT id, task_number, task_text, task_type, correct_answer,
                        user_answer, user_reasoning, steps, is_correct, score, feedback, attempts
                 FROM homework WHERE lesson_id = ? ORDER BY task_number''', (lesson_id,))
    rows = c.fetchall()
    conn.close()
    
    homework = []
    for row in rows:
        homework.append({
            'id': row[0],
            'task_number': row[1],
            'task_text': row[2],
            'task_type': row[3],
            'correct_answer': row[4],
            'user_answer': row[5],
            'user_reasoning': row[6],
            'steps': json.loads(row[7]) if row[7] else None,
            'is_correct': bool(row[8]),
            'score': row[9],
            'feedback': row[10],
            'attempts': row[11]
        })
    return homework

def create_homework_task(user_id: str, lesson_id: int, topic_id: str, 
                         task_number: int, task_text: str, task_type: str, 
                         correct_answer: str = None) -> int:
    """Создаёт новое задание для ДЗ"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''INSERT INTO homework 
                 (user_id, lesson_id, topic_id, task_number, task_text, task_type, correct_answer)
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (user_id, lesson_id, topic_id, task_number, task_text, task_type, correct_answer))
    
    homework_id = c.lastrowid
    conn.commit()
    conn.close()
    return homework_id

def submit_homework_answer(homework_id: int, user_answer: str, user_reasoning: str, steps: str = None):
    """Сохраняет ответ ученика на ДЗ"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''UPDATE homework 
                 SET user_answer = ?, user_reasoning = ?, steps = ?, attempts = attempts + 1
                 WHERE id = ?''', (user_answer, user_reasoning, steps, homework_id))
    conn.commit()
    conn.close()

def grade_homework(homework_id: int, is_correct: bool, score: int, feedback: str, step_feedback: str = None):
    """Выставляет оценку за ДЗ"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''UPDATE homework 
                 SET is_correct = ?, score = ?, feedback = ?, step_feedback = ?
                 WHERE id = ?''', (is_correct, score, feedback, step_feedback, homework_id))
    conn.commit()
    conn.close()

def get_homework_stats(user_id: str) -> Dict:
    """Получает статистику по ДЗ"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT COUNT(*) as total, SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct
                 FROM homework WHERE user_id = ?''', (user_id,))
    row = c.fetchone()
    conn.close()
    
    return {
        'total': row[0] or 0,
        'correct': row[1] or 0,
        'success_rate': round(row[1] / row[0] * 100, 1) if row[0] > 0 else 0
    }





import bcrypt
import re

def hash_password(password: str) -> str:
    """Хеширует пароль с помощью bcrypt"""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(password: str, password_hash: str) -> bool:
    """Проверяет пароль на соответствие хешу"""
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))

def is_valid_email(email: str) -> bool:
    """Простая проверка email"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def create_user(email: str, password: str, first_name: str = None, role: str = 'student') -> dict:
    """
    Создаёт нового пользователя в БД
    Возвращает dict с данными пользователя или None при ошибке
    """
    if not is_valid_email(email):
        return {'error': 'Неверный формат email'}
    
    if len(password) < 6:
        return {'error': 'Пароль должен содержать минимум 6 символов'}
    
    # Проверяем, существует ли email
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT user_id FROM users WHERE email = ?', (email,))
    if c.fetchone():
        conn.close()
        return {'error': 'Пользователь с таким email уже существует'}
    
    # Генерируем user_id
    import uuid
    user_id = f"user_{uuid.uuid4().hex[:8]}"
    
    # Хешируем пароль
    password_hash = hash_password(password)
    
    # Создаём запись
    now = datetime.now().isoformat()
    c.execute('''INSERT INTO users 
                 (user_id, email, first_name, password_hash, role, first_seen, last_seen)
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (user_id, email, first_name, password_hash, role, now, now))
    
    conn.commit()
    conn.close()
    
    return {
        'user_id': user_id,
        'email': email,
        'first_name': first_name,
        'role': role
    }

def get_user_by_email(email: str) -> dict:
    """Получает пользователя по email"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT user_id, email, first_name, password_hash, role, is_active
                 FROM users WHERE email = ?''', (email,))
    row = c.fetchone()
    conn.close()
    
    if row:
        return {
            'user_id': row[0],
            'email': row[1],
            'first_name': row[2],
            'password_hash': row[3],
            'role': row[4],
            'is_active': row[5]
        }
    return None

def get_user_by_id(user_id: str) -> dict:
    """Получает пользователя по user_id (без пароля)"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT user_id, email, first_name, role, is_active, created_at
                 FROM users WHERE user_id = ?''', (user_id,))
    row = c.fetchone()
    conn.close()
    
    if row:
        return {
            'user_id': row[0],
            'email': row[1],
            'first_name': row[2],
            'role': row[3],
            'is_active': row[4],
            'created_at': row[5]
        }
    return None

def authenticate_user(email: str, password: str) -> dict:
    """
    Проверяет логин и возвращает данные пользователя
    """
    user = get_user_by_email(email)
    if not user:
        return {'error': 'Пользователь не найден'}
    
    if not user.get('is_active'):
        return {'error': 'Аккаунт заблокирован'}
    
    if not verify_password(password, user['password_hash']):
        return {'error': 'Неверный пароль'}
    
    # Обновляем время последнего входа
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('UPDATE users SET last_seen = ? WHERE user_id = ?',
              (datetime.now().isoformat(), user['user_id']))
    conn.commit()
    conn.close()
    
    return {
        'user_id': user['user_id'],
        'email': user['email'],
        'first_name': user['first_name'],
        'role': user['role']
    }

def update_user_role(user_id: str, role: str):
    """Обновляет роль пользователя"""
    valid_roles = ['student', 'parent', 'teacher']
    if role not in valid_roles:
        return False
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('UPDATE users SET role = ? WHERE user_id = ?', (role, user_id))
    conn.commit()
    conn.close()
    return True


# ========== СВЯЗИ УЧЕНИК-РОДИТЕЛЬ (ДОБАВЛЕНО) ==========

def create_family_link(parent_id: str, student_id: str) -> dict:
    """Создаёт запрос на привязку ученика к родителю"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Проверяем, что оба пользователя существуют
    c.execute('SELECT role FROM users WHERE user_id = ?', (parent_id,))
    parent = c.fetchone()
    c.execute('SELECT role FROM users WHERE user_id = ?', (student_id,))
    student = c.fetchone()
    
    if not parent or not student:
        conn.close()
        return {'error': 'Пользователь не найден'}
    
    if parent[0] != 'parent':
        conn.close()
        return {'error': 'Пользователь не является родителем'}
    
    if student[0] != 'student':
        conn.close()
        return {'error': 'Пользователь не является учеником'}
    
    try:
        c.execute('''INSERT INTO family_links (parent_id, student_id, status)
                     VALUES (?, ?, 'pending')''', (parent_id, student_id))
        conn.commit()
        link_id = c.lastrowid
        conn.close()
        return {'id': link_id, 'status': 'pending'}
    except sqlite3.IntegrityError:
        conn.close()
        return {'error': 'Запрос уже существует'}

def get_family_links(parent_id: str) -> list:
    """Получает всех учеников родителя"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT f.id, f.student_id, u.first_name, u.email, f.status, f.created_at
                 FROM family_links f
                 JOIN users u ON u.user_id = f.student_id
                 WHERE f.parent_id = ? AND f.status = 'active'
                 ORDER BY f.created_at''', (parent_id,))
    rows = c.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        result.append({
            'id': row[0],
            'student_id': row[1],
            'name': row[2] or 'Без имени',
            'email': row[3],
            'status': row[4],
            'created_at': row[5]
        })
    return result

def get_student_parents(student_id: str) -> list:
    """Получает всех родителей ученика"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT f.id, f.parent_id, u.first_name, u.email, f.status
                 FROM family_links f
                 JOIN users u ON u.user_id = f.parent_id
                 WHERE f.student_id = ? AND f.status = 'active' ''', (student_id,))
    rows = c.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        result.append({
            'id': row[0],
            'parent_id': row[1],
            'name': row[2] or 'Родитель',
            'email': row[3],
            'status': row[4]
        })
    return result

def accept_family_link(link_id: int) -> dict:
    """Принимает запрос на связь"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('UPDATE family_links SET status = "active" WHERE id = ?', (link_id,))
    conn.commit()
    conn.close()
    return {'status': 'active'}


def remove_family_link(parent_id: str, student_id: str, removed_by: str = 'parent') -> dict:
    """Отвязывает ученика от родителя (только родитель)"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Проверяем, существует ли связь
    c.execute('''SELECT id, status FROM family_links 
                 WHERE parent_id = ? AND student_id = ?''', (parent_id, student_id))
    row = c.fetchone()
    
    if not row:
        conn.close()
        return {'error': 'Связь не найдена'}
    
    link_id, status = row
    
    # Если связь уже неактивна
    if status == 'removed':
        conn.close()
        return {'error': 'Связь уже удалена'}
    
    # Если связь в статусе pending, просто удаляем
    if status == 'pending':
        c.execute('DELETE FROM family_links WHERE id = ?', (link_id,))
        conn.commit()
        conn.close()
        return {'status': 'deleted', 'message': 'Запрос отменён'}
    
    # Обновляем статус на removed
    from datetime import datetime
    now = datetime.now().isoformat()
    c.execute('''UPDATE family_links 
                 SET status = 'removed', removed_by = ?, removed_at = ?
                 WHERE id = ?''', (removed_by, now, link_id))
    
    conn.commit()
    conn.close()
    return {'status': 'removed', 'removed_by': removed_by, 'message': 'Связь удалена'}


def get_student_stats(student_id: str) -> dict:
    """Получает статистику ученика для родителя"""
    # Временные данные — позже заменим на реальные из БД
    return {
        'score': 42,
        'progress': 65,
        'tasks_done': 12,
        'topics_completed': 3,
        'weekly_gain': 5
    }


def init_notifications_tables():
    """Создаёт таблицу для уведомлений"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        link TEXT,
        is_read BOOLEAN DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )''')
    
    c.execute('CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(is_read)')
    
    conn.commit()
    conn.close()
    logging.info("Таблица notifications создана")


# ========== УВЕДОМЛЕНИЯ ==========

def create_notification(user_id: str, title: str, message: str, link: str = None) -> int:
    """Создаёт уведомление для пользователя"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''INSERT INTO notifications (user_id, title, message, link, is_read)
                 VALUES (?, ?, ?, ?, 0)''', (user_id, title, message, link))
    notification_id = c.lastrowid
    conn.commit()
    conn.close()
    return notification_id

def get_notifications(user_id: str, limit: int = 10) -> list:
    """Получает уведомления для пользователя"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT id, title, message, link, is_read, created_at
                 FROM notifications 
                 WHERE user_id = ? 
                 ORDER BY created_at DESC LIMIT ?''', (user_id, limit))
    rows = c.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        result.append({
            'id': row[0],
            'title': row[1],
            'message': row[2],
            'link': row[3],
            'is_read': bool(row[4]),
            'created_at': row[5]
        })
    return result

def mark_notification_read(notification_id: int) -> dict:
    """Отмечает уведомление как прочитанное"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('UPDATE notifications SET is_read = 1 WHERE id = ?', (notification_id,))
    conn.commit()
    conn.close()
    return {'status': 'read'}

def get_unread_count(user_id: str) -> int:
    """Получает количество непрочитанных уведомлений"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0', (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count