#!/usr/bin/env python3
import os
import subprocess
import tempfile
from dotenv import load_dotenv
from github import Github, Auth

# --- Configuration ---
ENV_FILE = "/home/user1/.openclaw/workspace/.openclaw.env"
OWNER = "karanovon"
REPO = "hse_ap_hw_p_3"
PR_NUMBER = None

OUTPUT_DIR = "/home/user1/.openclaw/results/pr_comments"
# --- End Configuration ---

# Unique marker to prevent duplicate comments
AI_REVIEW_TAG = "<!-- AI_PR_REVIEW -->"


def load_token():
    if os.path.exists(ENV_FILE):
        load_dotenv(dotenv_path=ENV_FILE)
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN not found")
    return token


def get_pr_diff(repo, pr_number):
    pr = repo.get_pull(pr_number)
    files = pr.get_files()
    
    diff_text = []
    for f in files:
        diff_text.append(f"## Файл: {f.filename}\n")
        diff_text.append(f"```diff\n{f.patch if f.patch else 'Нет изменений'}\n```")
        
    return "\n".join(diff_text)


def get_review_from_agent(diff_text):
    """Send diff to OpenClaw agent using session-id"""
    
    max_length = 6000
    if len(diff_text) > max_length:
        diff_text = diff_text[:max_length] + "\n\n... (diff обрезан)"
    
    prompt = f"""Ты — PR ревьюер. Проанализируй код и напиши краткое ревью на русском.

Формат:
🤖 **Review**
**Проблема:** 
**Исправление:** 

Код:
{diff_text}"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write(prompt)
        prompt_file = f.name
    
    try:
        result = subprocess.run(
            f'openclaw agent --session-id pr-review-$(date +%s) -m "$(cat {prompt_file})"',
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
        return f"Ошибка: {e}"


def post_review_comment(repo, pr_number, review_text):
    if not review_text or review_text.strip() == "":
        print("❌ Пустое ревью")
        return False
    
    pr = repo.get_pull(pr_number)
    
    # Check for existing AI review to avoid duplicates
    try:
        existing_comments = pr.get_issue_comments()
        for comment in existing_comments:
            if AI_REVIEW_TAG in (comment.body or ''):
                print(f"✅ Ревью от данного агента уже существует в PR #{pr_number}. Пропуск дублирования.")
                return False
    except Exception:
        # If we can't fetch comments for any reason, continue and attempt to post
        pass
    
    # Append tag to help future deduplication
    full_review_text = f"{review_text}\n\n{AI_REVIEW_TAG}"
    
    try:
        pr.create_issue_comment(full_review_text)
        print(f"✅ Новое ревью опубликовано в PR #{pr_number}")
        return True
    except Exception as e:
        print(f"❌ Ошибка при публикации комментария: {e}")
        return False


def main():
    print("🚀 Запуск PR ревьюера...")
    
    try:
        github_token = load_token()
        auth = Auth.Token(github_token)
        g = Github(auth=auth)
        print("✅ Токен загружен")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return
    
    repo = g.get_repo(f"{OWNER}/{REPO}")
    
    if PR_NUMBER:
        pr_number = PR_NUMBER
    else:
        pulls = list(repo.get_pulls(state='open'))
        if not pulls:
            print("❌ Нет открытых PR")
            return
        pr_number = pulls[0].number
        print(f"📌 PR #{pr_number}")
    
    print("📥 Получаю diff...")
    diff = get_pr_diff(repo, pr_number)
    
    if not diff.strip():
        print("❌ Нет изменений")
        return
    
    print(f"✅ Diff: {len(diff)} символов")
    print("🤖 Отправляю агенту...")
    
    review = get_review_from_agent(diff)
    
    print(f"📝 Ответ: {len(review)} символов")
    if review:
        print(review[:500])
    
    if review and review.strip():
        post_review_comment(repo, pr_number, review)
    else:
        print("❌ Нет ревью для публикации")
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_file = f"{OUTPUT_DIR}/pr_{pr_number}_review.md"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"# PR #{pr_number}\n\n{review if review else 'Пусто'}")
    
    print(f"✅ Сохранено в {output_file}")


if __name__ == "__main__":
    main()
