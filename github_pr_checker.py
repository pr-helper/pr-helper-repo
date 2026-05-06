#!/usr/bin/env python3
"""
PR Review Bot for OpenClaw
Проверяет Pull Request'ы в указанных репозиториях и оставляет ревью от имени бота
"""

import os
import sys
import subprocess
import tempfile
import json
import base64
import urllib.request
import urllib.parse
from datetime import datetime
from dotenv import load_dotenv
from github import Github, Auth, GithubException

# ========== КОНФИГУРАЦИЯ ==========
ENV_FILE = "/home/user1/.openclaw/workspace/.openclaw.env"
OUTPUT_DIR = "/home/user1/.openclaw/results/pr_comments"
STATE_FILE = "/home/user1/.openclaw/workspace/reviewed_prs.json"

# Список репозиториев для проверки
REPOSITORIES = [
    "karanovon/hse_ap_hw_p_3",
    "25-77/Year_project",
]

# Имя бота
BOT_SIGNATURE = "🤖 **PR Helper Review**"

# Настройки проверки
CHECK_EXISTING_COMMENTS = True
MAX_DIFF_LENGTH = 12000  # Увеличен для ноутбуков
TIMEOUT_SECONDS = 300     # 5 минут на ответ агента
# ==================================

def load_token():
    """Загружает GITHUB_TOKEN из .env файла"""
    if os.path.exists(ENV_FILE):
        load_dotenv(dotenv_path=ENV_FILE)
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise SystemExit("❌ GITHUB_TOKEN not found in .env file")
    return token

def load_reviewed_prs():
    """Загружает список уже проверенных PR"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_reviewed_prs(reviewed_set):
    """Сохраняет список проверенных PR"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(list(reviewed_set), f, indent=2)

def extract_code_from_ipynb(content):
    """Извлекает Python код из Jupyter Notebook с номерами ячеек"""
    try:
        notebook = json.loads(content)
        code_cells = []
        
        for idx, cell in enumerate(notebook.get('cells', [])):
            if cell.get('cell_type') == 'code':
                source = cell.get('source', [])
                if isinstance(source, list):
                    source = ''.join(source)
                if source and source.strip():
                    code_cells.append(f"# Ячейка {idx + 1}\n{source}")
        
        if code_cells:
            return "\n\n".join(code_cells)
        else:
            return None
    except Exception as e:
        print(f"    ⚠️ Ошибка парсинга .ipynb: {e}")
        return None

def get_notebook_content_via_api(repo, filename, sha):
    """Получение содержимого ноутбука через GitHub API"""
    try:
        contents = repo.get_contents(filename, ref=sha)
        if contents.content:
            decoded = base64.b64decode(contents.content).decode('utf-8')
            return extract_code_from_ipynb(decoded)
    except Exception as e:
        print(f"    ⚠️ API метод не сработал: {e}")
    return None

def get_notebook_content_via_raw(repo_full_name, filename, sha):
    """Получение содержимого ноутбука через raw.githubusercontent.com с экранированием"""
    try:
        # Экранируем пробелы и спецсимволы в имени файла
        encoded_filename = urllib.parse.quote(filename)
        raw_url = f"https://raw.githubusercontent.com/{repo_full_name}/{sha}/{encoded_filename}"
        print(f"    📡 Raw URL: {raw_url}")  # Для отладки
        
        with urllib.request.urlopen(raw_url, timeout=30) as response:
            raw_content = response.read().decode('utf-8')
            return extract_code_from_ipynb(raw_content)
    except urllib.error.HTTPError as e:
        print(f"    ⚠️ HTTP ошибка {e.code}: {e.reason}")
    except Exception as e:
        print(f"    ⚠️ Raw метод не сработал: {e}")
    return None

def get_pr_diff_enhanced(repo, pr_number):
    """Получает diff с ПРИОРИТЕТНОЙ поддержкой Jupyter Notebook"""
    pr = repo.get_pull(pr_number)
    files = pr.get_files()
    
    diff_text = []
    notebook_count = 0
    
    for f in files:
        if f.filename.endswith('.ipynb'):
            notebook_count += 1
            diff_text.append(f"\n## 📓 {f.filename}\n")
            
            # Метод 1: Через GitHub API
            code = get_notebook_content_via_api(repo, f.filename, pr.head.sha)
            
            # Метод 2: Через raw.githubusercontent.com
            if not code:
                code = get_notebook_content_via_raw(repo.full_name, f.filename, pr.head.sha)
            
            if code:
                if len(code) > 5000:
                    code = code[:5000] + "\n# ... (ноутбук обрезан, ячейки с 1 по 5 показаны)"
                diff_text.append(f"```python\n{code}\n```")
                diff_text.append(f"*(✅ Код успешно извлечён из Jupyter Notebook)*\n")
            else:
                diff_text.append(f"```\n❌ НЕ УДАЛОСЬ ИЗВЛЕЧЬ КОД ИЗ НОУТБУКА\n")
                diff_text.append(f"Файл: {f.filename}\n")
                diff_text.append(f"Статус: {f.status}\n")
                diff_text.append(f"Рекомендация: экспортируйте ноутбук в .py или добавьте ссылку на код\n```\n")
        
        elif f.filename.endswith('.py'):
            diff_text.append(f"\n## 🐍 {f.filename}\n")
            patch = f.patch if f.patch else 'Нет изменений'
            if patch and len(patch) > 4000:
                patch = patch[:4000] + "\n... (файл обрезан)"
            diff_text.append(f"```diff\n{patch}\n```\n")
        
        else:
            # README, .md, .txt и другие текстовые файлы
            patch = f.patch if f.patch else None
            if patch and len(patch) < 2000:  # Только небольшие изменения
                ext = f.filename.split('.')[-1] if '.' in f.filename else 'text'
                diff_text.append(f"\n## 📄 {f.filename}\n")
                diff_text.append(f"```diff\n{patch}\n```\n")
    
    if notebook_count > 0:
        diff_text.insert(0, f"⚠️ **В PR обнаружено {notebook_count} Jupyter Notebook(ов). Код из них извлечён и будет проанализирован.**\n")
    
    full_diff = "\n".join(diff_text)
    
    # Динамическое ограничение длины
    max_length = MAX_DIFF_LENGTH + (2000 * notebook_count) if notebook_count > 0 else MAX_DIFF_LENGTH
    if len(full_diff) > max_length:
        full_diff = full_diff[:max_length] + "\n\n... (diff обрезан из-за длины)"
    
    return full_diff

def has_bot_commented(pr):
    """Проверяет, оставлял ли бот уже комментарий"""
    if not CHECK_EXISTING_COMMENTS:
        return False
    
    try:
        comments = pr.get_issue_comments()
        for comment in comments:
            if BOT_SIGNATURE in comment.body:
                print(f"    🤖 Бот уже комментировал (ID: {comment.id})")
                return True
        return False
    except Exception as e:
        print(f"    ⚠️ Ошибка проверки комментариев: {e}")
        return False

def get_review_from_agent(diff_text, filename_hint=""):
    """Отправляет diff агенту OpenClaw и получает ревью"""
    
    # Динамическое сокращение для больших diff
    if len(diff_text) > 10000:
        diff_text = diff_text[:10000] + "\n\n... (остальной код обрезан для ускорения проверки)"
    
    prompt = f"""Ты — PR ревьюер. Проанализируй код и напиши краткое ревью.

ВАЖНЫЕ ПРАВИЛА:
1. Если видишь код из Jupyter Notebook (комментарий "✅ Код успешно извлечён") — анализируй как обычный Python код
2. Если код не извлечён — укажи это как проблему 🔴
3. Не пиши больше 5 замечаний
4. Не анализируй README.md и документацию (только код)

Формат ответа (строго):
{BOT_SIGNATURE}

**Что проверяли:** 
**Важность:** 🔴/🟡/🔵
**Файл:** 

**❌ Проблема:**
**✅ Как исправить:**

---
Код для анализа:
{diff_text[:8000]}"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write(prompt)
        prompt_file = f.name
    
    try:
        result = subprocess.run(
            f'openclaw agent --agent main -m "$(cat {prompt_file})"',
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            shell=True,
            executable='/bin/bash'
        )
        
        os.unlink(prompt_file)
        
        if result.stdout:
            return result.stdout
        elif result.stderr:
            if "error" in result.stderr.lower():
                return f"⚠️ Ошибка агента: {result.stderr[:300]}"
            return result.stderr
        else:
            return "Агент не вернул ответ"
            
    except subprocess.TimeoutExpired:
        os.unlink(prompt_file)
        return f"⏰ Таймаут ({TIMEOUT_SECONDS} сек). PR слишком большой для анализа."
    except Exception as e:
        try:
            os.unlink(prompt_file)
        except:
            pass
        return f"❌ Ошибка: {e}"

def post_review_comment(pr, review_text):
    """Публикует ревью в PR"""
    if not review_text or review_text.strip() == "":
        print("    ❌ Пустое ревью")
        return False
    
    try:
        if len(review_text) > 65000:
            review_text = review_text[:65000] + "\n\n... (комментарий обрезан)"
        
        full_comment = f"{review_text}\n\n---\n*Автоматическая проверка от PR Helper | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"
        pr.create_issue_comment(full_comment)
        print(f"    ✅ Ревью опубликовано")
        return True
    except GithubException as e:
        print(f"    ❌ Ошибка публикации: {e}")
        return False

def check_repository(g, repo_name, reviewed_prs):
    """Проверяет все открытые PR в репозитории"""
    print(f"\n{'='*60}")
    print(f"📁 Репозиторий: {repo_name}")
    print(f"{'='*60}")
    
    try:
        repo = g.get_repo(repo_name)
    except GithubException as e:
        print(f"❌ Ошибка доступа: {e}")
        return reviewed_prs
    
    try:
        pulls = list(repo.get_pulls(state='open', sort='created', direction='desc'))
    except Exception as e:
        print(f"❌ Ошибка получения PR: {e}")
        return reviewed_prs
    
    if not pulls:
        print("📭 Нет открытых PR")
        return reviewed_prs
    
    print(f"📋 Найдено открытых PR: {len(pulls)}")
    
    for pr in pulls:
        pr_id = f"{repo_name}#{pr.number}"
        print(f"\n---")
        print(f"🔍 PR #{pr.number}: {pr.title[:60]}...")
        print(f"   👤 Автор: @{pr.user.login}")
        print(f"   📅 Создан: {pr.created_at.strftime('%Y-%m-%d')}")
        
        if pr_id in reviewed_prs:
            print(f"   ⏭️  Уже проверен ранее")
            continue
        
        if has_bot_commented(pr):
            print(f"   ⏭️  Бот уже комментировал")
            reviewed_prs.add(pr_id)
            continue
        
        print(f"   📥 Получаю diff...")
        diff = get_pr_diff_enhanced(repo, pr.number)
        
        if not diff or diff.strip() == "":
            print(f"   ⚠️ Нет изменений для анализа")
            continue
        
        print(f"   🤖 Отправляю агенту ({len(diff)} символов, таймаут {TIMEOUT_SECONDS} сек)...")
        review = get_review_from_agent(diff)
        
        if review and review.strip():
            print(f"   📝 Публикую ревью...")
            success = post_review_comment(pr, review)
            
            if success:
                reviewed_prs.add(pr_id)
                
                os.makedirs(OUTPUT_DIR, exist_ok=True)
                safe_repo = repo_name.replace('/', '_')
                output_file = f"{OUTPUT_DIR}/{safe_repo}_pr_{pr.number}.md"
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(f"# {repo_name} PR #{pr.number}\n")
                    f.write(f"**Название:** {pr.title}\n")
                    f.write(f"**Автор:** @{pr.user.login}\n")
                    f.write(f"**Дата:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    f.write("## Ревью\n\n")
                    f.write(review)
                print(f"   💾 Ревью сохранено")
        else:
            print(f"   ❌ Не удалось получить ревью")
    
    return reviewed_prs

def main():
    print("🚀 PR Helper Bot v2.0 (с поддержкой Jupyter Notebook)")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📁 Репозиториев: {len(REPOSITORIES)}")
    for repo in REPOSITORIES:
        print(f"   - {repo}")
    
    try:
        github_token = load_token()
        auth = Auth.Token(github_token)
        g = Github(auth=auth)
        user = g.get_user()
        print(f"✅ Аутентификация успешна (аккаунт: @{user.login})")
    except Exception as e:
        print(f"❌ Ошибка аутентификации: {e}")
        return
    
    reviewed_prs = load_reviewed_prs()
    print(f"📊 Уже проверено PR: {len(reviewed_prs)}")
    
    for repo_name in REPOSITORIES:
        reviewed_prs = check_repository(g, repo_name, reviewed_prs)
        save_reviewed_prs(reviewed_prs)
    
    save_reviewed_prs(reviewed_prs)
    
    print(f"\n{'='*60}")
    print(f"🏁 Проверка завершена!")
    print(f"📊 Всего проверено: {len(reviewed_prs)} PR")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()