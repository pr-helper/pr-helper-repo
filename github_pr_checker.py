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
import hashlib
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from github import Github, Auth, GithubException

# ========== КОНФИГУРАЦИЯ ==========
ENV_FILE = "/home/user1/.openclaw/workspace/.openclaw.env"
OUTPUT_DIR = "/home/user1/.openclaw/results/pr_comments"
STATE_FILE = "/home/user1/.openclaw/workspace/reviewed_prs.json"  # Храним ID проверенных PR

# Список репозиториев для проверки (добавляйте любые)
REPOSITORIES = [
    "karanovon/hse_ap_hw_p_3",
    # "karanovon/another-repo",      # раскомментируйте для добавления
    # "username/your-repo",           # добавляйте другие репозитории
]

# Имя бота (как он подписывает комментарии)
BOT_NAME = "PR Helper Bot"
BOT_SIGNATURE = "🤖 **PR Helper Review**"  # Уникальная сигнатура бота

# Настройки проверки
CHECK_EXISTING_COMMENTS = True  # Проверять, оставлял ли бот уже комментарий
MAX_DIFF_LENGTH = 6000  # Максимальная длина diff для отправки агенту
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
    """Загружает список уже проверенных PR из файла состояния"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_reviewed_prs(reviewed_set):
    """Сохраняет список проверенных PR в файл"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(list(reviewed_set), f, indent=2)

def has_bot_commented(pr):
    """Проверяет, оставлял ли бот уже комментарий в этом PR"""
    if not CHECK_EXISTING_COMMENTS:
        return False
    
    try:
        comments = pr.get_issue_comments()
        for comment in comments:
            # Проверяем по сигнатуре бота
            if BOT_SIGNATURE in comment.body:
                print(f"    🤖 Бот уже комментировал этот PR (комментарий #{comment.id})")
                return True
        return False
    except Exception as e:
        print(f"    ⚠️ Ошибка проверки комментариев: {e}")
        return False

def get_pr_diff(repo, pr_number):
    """Получает diff всех файлов в PR"""
    pr = repo.get_pull(pr_number)
    files = pr.get_files()
    
    diff_text = []
    for f in files:
        diff_text.append(f"## Файл: {f.filename}\n")
        patch = f.patch if f.patch else 'Нет изменений'
        # Ограничиваем размер каждого файла
        if len(patch) > 2000:
            patch = patch[:2000] + "\n... (файл обрезан)"
        diff_text.append(f"```diff\n{patch}\n```\n")
    
    full_diff = "\n".join(diff_text)
    
    # Обрезаем общий diff
    if len(full_diff) > MAX_DIFF_LENGTH:
        full_diff = full_diff[:MAX_DIFF_LENGTH] + "\n\n... (diff обрезан из-за длины)"
    
    return full_diff

def get_review_from_agent(diff_text):
    """Отправляет diff агенту OpenClaw и получает ревью"""
    
    prompt = f"""Ты — PR ревьюер. Проанализируй этот код и напиши ревью на русском языке.

Формат ответа (обязательно используй этот формат):
{BOT_SIGNATURE}

**Что проверяли:** [логика/стиль/безопасность/структура]
**Важность:** 🔴 Критично | 🟡 Предупреждение | 🔵 Совет
**Файл:** `путь/файл.расширение`

**❌ Проблема:**
[Описание]

**✅ Как исправить:**
[Предложение]

---
Код для анализа:
{diff_text}"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write(prompt)
        prompt_file = f.name
    
    try:
        result = subprocess.run(
            f'openclaw agent --agent main -m "$(cat {prompt_file})"',
            capture_output=True,
            text=True,
            timeout=180,
            shell=True,
            executable='/bin/bash'
        )
        
        os.unlink(prompt_file)
        
        if result.stdout:
            return result.stdout
        elif result.stderr:
            return result.stderr
        else:
            return "Нет ответа от агента"
            
    except Exception as e:
        try:
            os.unlink(prompt_file)
        except:
            pass
        return f"Ошибка при вызове агента: {e}"

def post_review_comment(pr, review_text):
    """Публикует ревью как комментарий в PR"""
    if not review_text or review_text.strip() == "":
        print("    ❌ Пустое ревью, комментарий не опубликован")
        return False
    
    try:
        # Добавляем подпись бота и дату
        full_comment = f"{review_text}\n\n---\n*Автоматическая проверка от {BOT_NAME} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"
        pr.create_issue_comment(full_comment)
        print(f"    ✅ Ревью опубликовано")
        return True
    except GithubException as e:
        print(f"    ❌ Ошибка публикации: {e}")
        return False

def check_repository(g, repo_name, reviewed_prs):
    """Проверяет все открытые PR в одном репозитории"""
    print(f"\n{'='*60}")
    print(f"📁 Репозиторий: {repo_name}")
    print(f"{'='*60}")
    
    try:
        repo = g.get_repo(repo_name)
    except GithubException as e:
        print(f"❌ Ошибка доступа к репозиторию: {e}")
        return reviewed_prs
    
    try:
        pulls = list(repo.get_pulls(state='open', sort='created', direction='desc'))
    except Exception as e:
        print(f"❌ Ошибка получения PR: {e}")
        return reviewed_prs
    
    if not pulls:
        print("📭 Нет открытых Pull Request'ов")
        return reviewed_prs
    
    print(f"📋 Найдено открытых PR: {len(pulls)}")
    
    for pr in pulls:
        pr_id = f"{repo_name}#{pr.number}"
        print(f"\n---")
        print(f"🔍 PR #{pr.number}: {pr.title[:50]}...")
        print(f"   👤 Автор: @{pr.user.login}")
        print(f"   🔗 Ссылка: {pr.html_url}")
        
        # Проверяем, не проверяли ли уже этот PR
        if pr_id in reviewed_prs:
            print(f"   ⏭️  Уже был проверен ранее (в файле состояния), пропускаем")
            continue
        
        # Проверяем, есть ли уже комментарий от бота
        if has_bot_commented(pr):
            print(f"   ⏭️  Бот уже оставлял комментарий, пропускаем")
            # Добавляем в список проверенных, чтобы не проверять снова
            reviewed_prs.add(pr_id)
            continue
        
        print(f"   📥 Получаю diff...")
        diff = get_pr_diff(repo, pr.number)
        
        if not diff or diff.strip() == "":
            print(f"   ⚠️ Нет изменений для анализа")
            continue
        
        print(f"   🤖 Отправляю агенту на анализ (diff: {len(diff)} символов)...")
        review = get_review_from_agent(diff)
        
        if review and review.strip():
            print(f"   📝 Публикую ревью...")
            success = post_review_comment(pr, review)
            
            if success:
                # Добавляем в список проверенных только после успешной публикации
                reviewed_prs.add(pr_id)
                
                # Сохраняем ревью локально
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
                print(f"   💾 Ревью сохранено в {output_file}")
        else:
            print(f"   ❌ Не удалось получить ревью от агента")
    
    return reviewed_prs

def main():
    print("🚀 Запуск PR ревьюера")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📁 Репозитории для проверки: {len(REPOSITORIES)}")
    for repo in REPOSITORIES:
        print(f"   - {repo}")
    
    # Загружаем токен
    try:
        github_token = load_token()
        auth = Auth.Token(github_token)
        g = Github(auth=auth)
        print("✅ Токен загружен, аутентификация успешна")
        
        # Проверяем доступ
        user = g.get_user()
        print(f"👤 Аккаунт: @{user.login}")
        
    except Exception as e:
        print(f"❌ Ошибка аутентификации: {e}")
        return
    
    # Загружаем список уже проверенных PR
    reviewed_prs = load_reviewed_prs()
    print(f"📊 Уже проверено PR: {len(reviewed_prs)}")
    
    # Проверяем каждый репозиторий
    for repo_name in REPOSITORIES:
        reviewed_prs = check_repository(g, repo_name, reviewed_prs)
        # Сохраняем состояние после каждого репозитория
        save_reviewed_prs(reviewed_prs)
    
    # Финальное сохранение
    save_reviewed_prs(reviewed_prs)
    
    print(f"\n{'='*60}")
    print(f"🏁 Проверка завершена!")
    print(f"📊 Всего проверено PR за эту сессию: {len(reviewed_prs)}")
    print(f"📁 Состояние сохранено в: {STATE_FILE}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
