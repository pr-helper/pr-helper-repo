# 🤖 PR Helper — автоматический ревьюер Pull Request'ов

Бот на основе **OpenClaw** и **GitHub API**, который автоматически проверяет Pull Request'ы в указанных репозиториях и оставляет комментарии-ревью.

---

## 🏗️ Инфраструктура

- **Платформа:** Cloud.ru
- **Виртуальная машина:** Ubuntu 22.04 / 24.04
- **Агент:** OpenClaw 2026.3.13
- **LLM:** OpenRouter (через OpenClaw Gateway)

OpenClaw развернут на виртуальной машине в **Cloud.ru** и работает в режиме `gateway` с агентом `main`. Скрипт взаимодействует с агентом через `subprocess`, передавая diff для анализа.

---

## 🚀 Как это работает

Вы открываете PR в репозитории  
↓  
Cron (каждые 30 минут) запускает скрипт на ВМ в Cloud.ru  
↓  
Скрипт находит все открытые PR через GitHub API  
↓  
Получает diff изменённых файлов  
↓  
Отправляет код на анализ агенту OpenClaw  
↓  
OpenClaw (через OpenRouter) анализирует:
- логику и потенциальные ошибки  
- стиль кода  
- проблемы безопасности  
- структуру изменений  

↓  
Скрипт публикует ревью в виде комментария в PR  
↓  
Автор получает уведомление в GitHub  

---

## 📁 Структура проекта (на ВМ)

```
/home/user1/.openclaw/workspace/
├── github_pr_checker.py   # Основной скрипт
├── .openclaw.env          # GitHub токен
├── reviewed_prs.json      # Список проверенных PR
├── README.md              # Документация
└── results/               # Локальные копии ревью
```

---

## ⚙️ Настройка

### 1. Конфигурация в `github_pr_checker.py`

```python
REPOSITORIES = [
    "karanovon/hse_ap_hw_p_3",
    "25-77/Year_project",
]

CHECK_EXISTING_COMMENTS = True
MAX_DIFF_LENGTH = 6000
ENV_FILE = "/home/user1/.openclaw/workspace/.openclaw.env"
```

---

### 2. GitHub токен

Создайте токен с правами `repo` и сохраните в `.openclaw.env`.

---

### 3. Автоматический запуск через cron (на ВМ)

```bash
crontab -e

*/30 * * * * cd /home/user1/.openclaw/workspace && export $(cat .openclaw.env | xargs) && python3 github_pr_checker.py >> /home/user1/.openclaw/workspace/logs.txt 2>&1
```

---

### 4. Проверка работы OpenClaw на ВМ

```bash
openclaw status
openclaw agent --agent main -m "Тест соединения"
```

---

## 📝 Формат ревью

```markdown
🤖 **PR Helper Review**

**Что проверяли:** логика / стиль / безопасность  
**Важность:** 🔴 Критично | 🟡 Предупреждение | 🔵 Совет  
**Файл:** `main.py:12`

**❌ Проблема:**
Отсутствует проверка входных данных

**✅ Как исправить:**
Добавить валидацию перед использованием
```

---

## 🛡️ Защита от дублирования

- PR уже есть в `reviewed_prs.json`
- Уже есть комментарий с сигнатурой `🤖 **PR Helper Review**`

---

## 👤 Аккаунт бота
Бот действует от имени `pr-helper`  
Репозиторий бота - `https://github.com/pr-helper/pr-helper-repo/`  
Для доступа к приватным репозиториям этот аккаунт должен быть добавлен как collaborator с правами Read.