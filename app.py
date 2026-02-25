from flask import Flask, flash, render_template, request, redirect, session
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db_connection
from ai_helper import generate_quiz_from_ai, simplify_content,generate_match_game,_safe_gemini_call , ai_grade_answer
import json
import random
import os
import PyPDF2
import markdown
from collections import defaultdict
from flashcard_routes import flashcard_bp
from werkzeug.utils import secure_filename
from markupsafe import Markup
from dotenv import load_dotenv

import re
from flask_mail import Mail
from settings_routes import settings_bp, init_mail
load_dotenv()


def strip_html(text):
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()



def extract_text_from_file(file_path):
    ext = os.path.splitext(file_path)[1].lower()

    try:
        if ext == ".txt":
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()

        if ext == ".pdf":
            text = ""
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() or ""
            return text

    except Exception:
        return ""

    return ""


app = Flask(__name__)
@app.template_filter("fromjson")
def fromjson_filter(value):
    if not value:
        return []
    return json.loads(value)
app.secret_key = "learnify_secret_key"

app.register_blueprint(flashcard_bp)

@app.template_filter("loads")
def json_loads_filter(value):
    return json.loads(value) if value else []


# Mail config (add after app.secret_key)
app.config['MAIL_SERVER']   = 'smtp.gmail.com'
app.config['MAIL_PORT']     = 587
app.config['MAIL_USE_TLS']  = True
app.config['MAIL_USERNAME'] = os.getenv("MAIL_USER")
app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASS")

mail = Mail(app)

# Register blueprint
app.register_blueprint(settings_bp)
init_mail(mail)

# ================= HOME =================
@app.route("/")
def home():
    if "user_id" in session:
        return redirect("/dashboard")
    return render_template("index.html")


# ================= AUTH =================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        db = get_db_connection()
        cursor = db.cursor()

        cursor.execute(
            "INSERT INTO users (name, email, password) VALUES (%s, %s, %s)",
            (
                request.form["name"],
                request.form["email"],
                generate_password_hash(request.form["password"])
            )
        )
        db.commit()
        return redirect("/login")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM users WHERE email=%s",
            (request.form["email"],)
        )
        user = cursor.fetchone()

        if user and check_password_hash(user["password"], request.form["password"]):
            session.clear()
            session["user_id"] = user["id"]
            return redirect("/dashboard")

        return "Invalid credentials"

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ================= DASHBOARD =================
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")

    import datetime

    user_id = session["user_id"]
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    today = datetime.date.today()
    start_date = today - datetime.timedelta(weeks=14)

    # =====================================================
# 1️⃣ HEATMAP (GAME SESSIONS + QUIZ ATTEMPTS)
# =====================================================

    cursor.execute("""
        SELECT DATE(created_at) d, COUNT(*) c
        FROM game_sessions
        WHERE user_id=%s AND completed=TRUE AND created_at >= %s
        GROUP BY d
    """, (user_id, start_date))
    game_activity = cursor.fetchall()

    cursor.execute("""
        SELECT DATE(attempted_at) d, COUNT(*) c
        FROM file_quiz_attempts
        WHERE user_id=%s AND attempted_at >= %s
        GROUP BY d
    """, (user_id, start_date))
    quiz_activity = cursor.fetchall()

    # ✅ FIXED: force all keys to datetime.date type
    activity_map = {}
    for r in game_activity:
        key = r["d"].date() if hasattr(r["d"], 'date') and callable(r["d"].date) else r["d"]
        activity_map[key] = activity_map.get(key, 0) + r["c"]
    for r in quiz_activity:
        key = r["d"].date() if hasattr(r["d"], 'date') and callable(r["d"].date) else r["d"]
        activity_map[key] = activity_map.get(key, 0) + r["c"]

    calendar = []
    total_sessions = 0

    for i in range(14 * 7):
        day = start_date + datetime.timedelta(days=i)
        count = activity_map.get(day, 0)
        total_sessions += count

        if count == 0:    level = 0
        elif count <= 2:  level = 1
        elif count <= 5:  level = 2
        elif count <= 8:  level = 3
        else:             level = 4

        calendar.append({"date": str(day), "level": level, "count": count})
    # =====================================================
    # 2️⃣ WEEKLY ACTIVITY
    # =====================================================

    weekly_activity = []
    for i in range(7):
        day = today - datetime.timedelta(days=today.weekday() - i)
        count = activity_map.get(day, 0)
        weekly_activity.append({
            "label": day.strftime("%a"),
            "active": count > 0,
            "count": count
        })

    # =====================================================
    # 3️⃣ PERFORMANCE ANALYTICS (GAMES + QUIZZES)
    # =====================================================

    cursor.execute("""
        SELECT COALESCE(SUM(correct_answers), 0) correct,
               COALESCE(SUM(total_cards), 0) total
        FROM game_sessions
        WHERE user_id=%s AND completed=TRUE
    """, (user_id,))
    game_acc = cursor.fetchone()

    cursor.execute("""
        SELECT COALESCE(SUM(score), 0) correct,
               COALESCE(SUM(total_marks), 0) total
        FROM file_quiz_attempts
        WHERE user_id=%s
    """, (user_id,))
    quiz_acc = cursor.fetchone()

    total_correct = (game_acc["correct"] or 0) + (quiz_acc["correct"] or 0)
    total_marks   = (game_acc["total"]   or 0) + (quiz_acc["total"]   or 0)
    avg_accuracy  = round((total_correct / total_marks) * 100, 1) if total_marks else 0

    # =====================================================
    # 4️⃣ TOPIC INSIGHTS (FROM FLASHCARD PROGRESS)
    # =====================================================

    cursor.execute("""
        SELECT f.topic,
               SUM(fp.knew_count) knew,
               SUM(fp.didnt_know_count) didnt
        FROM flashcard_progress fp
        JOIN flashcards f ON fp.flashcard_id = f.id
        WHERE fp.user_id=%s
        GROUP BY f.topic
    """, (user_id,))

    topic_rows  = cursor.fetchall()
    topic_stats = []

    for row in topic_rows:
        total = row["knew"] + row["didnt"]
        if total > 0:
            topic_stats.append({
                "topic":    row["topic"],
                "accuracy": round((row["knew"] / total) * 100, 1)
            })

    if topic_stats:
        weak_subject   = min(topic_stats, key=lambda x: x["accuracy"])["topic"]
        strong_subject = max(topic_stats, key=lambda x: x["accuracy"])["topic"]
        suggestion     = f"Revise flashcards in {weak_subject}."
    else:
        weak_subject   = "Not enough data"
        strong_subject = "Keep learning!"
        suggestion     = "Complete 5 more cards to see your personal insights."

    insights = {
        "weak_subject":   weak_subject,
        "strong_subject": strong_subject,
        "suggestion":     suggestion
    }

    # =====================================================
    # 5️⃣ BADGES
    # =====================================================

    cursor.execute("""
        SELECT b.name, b.icon, b.id
        FROM user_badges ub
        JOIN badges b ON ub.badge_id = b.id
        WHERE ub.user_id=%s
    """, (user_id,))

    earned_badges     = cursor.fetchall() or []
    earned_badge_keys = [b["name"] for b in earned_badges]
    earned_badge_ids  = [b["id"]   for b in earned_badges]

    cursor.execute("SELECT id, name, icon FROM badges")
    all_badges = cursor.fetchall() or []

    # =====================================================
    # 6️⃣ FLASHCARD GAME STATS
    # =====================================================

    cursor.execute("""
        SELECT 
            COALESCE(SUM(correct_answers), 0) AS total_cards_completed,
            COALESCE(ROUND(AVG(score)), 0)    AS avg_score,
            COUNT(*)                           AS total_games
        FROM game_sessions
        WHERE user_id=%s AND completed=TRUE
    """, (user_id,))
    flashcard_stats = cursor.fetchone() or {
        "total_cards_completed": 0,
        "avg_score": 0,
        "total_games": 0
    }

    # Count quiz attempts separately and add to games_played
    cursor.execute("""
        SELECT COUNT(*) AS quiz_count
        FROM file_quiz_attempts
        WHERE user_id=%s
    """, (user_id,))
    quiz_count   = cursor.fetchone()["quiz_count"] or 0
    games_played = flashcard_stats["total_games"] + quiz_count

    # Recent activity — merge game sessions + quiz attempts
    cursor.execute("""
        SELECT game_mode, topic, score, correct_answers, total_cards, created_at
        FROM game_sessions
        WHERE user_id=%s
        ORDER BY created_at DESC
        LIMIT 5
    """, (user_id,))
    recent_games = cursor.fetchall() or []

    # Trend — merge both sources
    cursor.execute("""
        SELECT DATE(created_at) AS date,
               ROUND(AVG(correct_answers * 100.0 / total_cards)) AS accuracy
        FROM game_sessions
        WHERE user_id=%s AND completed=TRUE AND total_cards > 0
        GROUP BY DATE(created_at)

        UNION ALL

        SELECT DATE(attempted_at) AS date,
               ROUND(AVG(score * 100.0 / total_marks)) AS accuracy
        FROM file_quiz_attempts
        WHERE user_id=%s AND total_marks > 0
        GROUP BY DATE(attempted_at)

        ORDER BY date ASC
        LIMIT 7
    """, (user_id, user_id))

    trend_rows   = cursor.fetchall() or []
    trend_labels = [str(r["date"])       for r in trend_rows]
    trend_values = [float(r["accuracy"]) for r in trend_rows]

    # Topic mastery bars
    cursor.execute("""
        SELECT topic AS name,
               ROUND(AVG(correct_answers * 100.0 / total_cards)) AS progress
        FROM game_sessions
        WHERE user_id=%s AND completed=TRUE AND total_cards > 0
        GROUP BY topic
    """, (user_id,))
    topic_progress = cursor.fetchall() or []

    for t in topic_progress:
        if t["name"] and t["name"].startswith("file_"):
            t["name"] = "File #" + t["name"].replace("file_", "")

    # =====================================================
    # 7️⃣ USER STATUS
    # =====================================================

    is_new_user        = total_sessions == 0
    motivation_message = (
        "Start your first session today 🚀"
        if is_new_user else
        f"You completed {total_sessions} sessions!"
    )

    cursor.close()
    db.close()

    today_weekday = today.weekday()

    return render_template(
        "dashboard.html",
        name                = session.get("name", "Learner"),
        is_new_user         = is_new_user,
        motivation_message  = motivation_message,
        calendar            = calendar,
        weekly_activity     = weekly_activity,
        badges              = all_badges,
        earned_badge_keys   = earned_badge_keys,
        insights            = insights,
        avg_accuracy        = avg_accuracy,
        total_contributions = total_sessions,
        today_weekday       = today_weekday,
        flashcard_stats     = flashcard_stats,
        recent_games        = recent_games,
        all_badges          = all_badges,
        earned_badge_ids    = earned_badge_ids,
        topic_progress      = topic_progress,
        trend_labels        = trend_labels,
        trend_values        = trend_values,
        games_played        = games_played,
        quizzes_attempted   = total_sessions,
        active_days         = len([d for d in calendar if d["count"] > 0]),
    )

@app.route("/add-topic", methods=["GET", "POST"])
def add_topic():
    if "user_id" not in session:
        return redirect("/login")

    if request.method == "POST":
        title = request.form["title"].strip()
        content = request.form.get("content", "").strip()
        file = request.files.get("file")

        db = get_db_connection()
        cursor = db.cursor()

        # 1️⃣ Insert topic (ALWAYS)
        cursor.execute(
            "INSERT INTO topics (user_id, title) VALUES (%s, %s)",
            (session["user_id"], title)
        )
        topic_id = cursor.lastrowid

        # 2️⃣ Insert text content (ONLY IF PROVIDED)
        if content:
            cursor.execute(
                "INSERT INTO topic_content (topic_id, content) VALUES (%s, %s)",
                (topic_id, content)
            )

        # 3️⃣ Handle file upload (OPTIONAL)
        if file and file.filename:
            filename = secure_filename(file.filename)
            file_type = file.content_type

            upload_dir = "static/uploads"
            os.makedirs(upload_dir, exist_ok=True)

            file_path = os.path.join(upload_dir, filename)
            file.save(file_path)

            cursor.execute("""
                INSERT INTO topic_files (topic_id, file_name, file_path, file_type)
                VALUES (%s, %s, %s, %s)
            """, (topic_id, filename, file_path, file_type))

        db.commit()
        return redirect("/my-topics")

    return render_template("add_topic.html")



@app.route("/my-topics")
def my_topics():
    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # Get all topics
    cursor.execute("""
        SELECT id, title, created_at
        FROM topics
        WHERE user_id=%s
        ORDER BY created_at DESC
    """, (session["user_id"],))

    topics = cursor.fetchall()

    # For each topic, calculate quiz count and progress
    for topic in topics:
        # Count file quizzes for this topic
        cursor.execute("""
            SELECT COUNT(DISTINCT fq.id) as count
            FROM topic_files tf
            LEFT JOIN file_quizzes fq ON tf.id = fq.file_id
            WHERE tf.topic_id = %s
        """, (topic["id"],))
        file_quiz_count = cursor.fetchone()["count"] or 0

        # Count AI quiz attempts for this topic
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM ai_quiz_attempts
            WHERE topic_id = %s AND user_id = %s
        """, (topic["id"], session["user_id"]))
        ai_quiz_count = cursor.fetchone()["count"] or 0

        # Total quiz count
        topic["quiz_count"] = file_quiz_count + ai_quiz_count

        # Calculate progress (average score from file quiz attempts)
        cursor.execute("""
            SELECT ROUND(AVG(fqa.score * 100.0 / fqa.total_marks)) as avg_score
            FROM topic_files tf
            LEFT JOIN file_quiz_attempts fqa ON tf.id = fqa.file_id
            WHERE tf.topic_id = %s AND fqa.user_id = %s
            AND fqa.total_marks > 0
        """, (topic["id"], session["user_id"]))
        
        result = cursor.fetchone()
        topic["progress"] = int(result["avg_score"] or 0)

    cursor.close()
    db.close()

    return render_template(
        "my_topics.html",
        topics=topics,
        active="topics"
    )

@app.route("/topic/<int:topic_id>")
def view_topic(topic_id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # 1️⃣ Topic info
    cursor.execute(
        "SELECT * FROM topics WHERE id=%s",
        (topic_id,)
    )
    topic = cursor.fetchone()
    if not topic:
        return "Topic not found", 404

    # 2️⃣ Text content (OPTIONAL)
    cursor.execute(
        "SELECT content FROM topic_content WHERE topic_id=%s",
        (topic_id,)
    )
    row = cursor.fetchone()
    content = row["content"] if row else None

    # 3️⃣ Files + file-level simplified text
    cursor.execute("""
        SELECT 
            f.id,
            f.file_name,
            f.file_path,
            f.file_type,
            fs.simplified_text
        FROM topic_files f
        LEFT JOIN file_simplified fs ON f.id = fs.file_id
        WHERE f.topic_id=%s
        ORDER BY f.uploaded_at DESC
    """, (topic_id,))
    files = [dict(f) for f in cursor.fetchall()]

    # 4️⃣ File-based quizzes (grouped per file)
    cursor.execute("""
    SELECT 
        fqz.id AS quiz_id,
        fqz.file_id,
        fqz.created_at
    FROM file_quizzes fqz
    JOIN topic_files tf ON fqz.file_id = tf.id
    WHERE tf.topic_id = %s
    ORDER BY fqz.created_at DESC
""", (topic_id,))

    quizzes = [dict(q) for q in cursor.fetchall()]

# attach quizzes to files
    for f in files:
       f["quizzes"] = [q for q in quizzes if q["file_id"] == f["id"]]




    return render_template(
        "view_topic.html",
        topic=topic,
        content=content,
        files=files,
        file_quizzes=quizzes
    )

@app.route("/simplify-file/<int:file_id>")
def simplify_file(file_id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # 1️⃣ Get file
    cursor.execute("""
        SELECT id, file_path, topic_id
        FROM topic_files
        WHERE id=%s
    """, (file_id,))
    file = cursor.fetchone()

    if not file:
        return "File not found", 404

    # 2️⃣ Extract text
    text = extract_text_from_file(file["file_path"])

    if not text.strip():
        return redirect(f"/topic/{file['topic_id']}")

    # 3️⃣ AI simplify
    simplified_text = simplify_content(text)

    simplified_html = markdown.markdown(
        simplified_text,
        extensions=["extra", "nl2br"]
    )

    # 4️⃣ Replace old simplified
    cursor.execute(
        "DELETE FROM file_simplified WHERE file_id=%s",
        (file_id,)
    )

    cursor.execute("""
        INSERT INTO file_simplified (file_id, simplified_text)
        VALUES (%s, %s)
    """, (file_id, simplified_html))

    db.commit()

    return redirect(f"/topic/{file['topic_id']}")


@app.route("/delete-topic-content/<int:topic_id>", methods=["POST"])
def delete_topic_content(topic_id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor()

    cursor.execute(
        "DELETE FROM topic_content WHERE topic_id=%s",
        (topic_id,)
    )
    cursor.execute(
    "DELETE FROM topic_simplified WHERE topic_id=%s",
    (topic_id,)
)
    
    db.commit()

    return redirect(f"/topic/{topic_id}")

import os

@app.route("/delete-topic-file/<int:file_id>", methods=["POST"])
def delete_topic_file(file_id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        "SELECT file_path, topic_id FROM topic_files WHERE id=%s",
        (file_id,)
    )
    file = cursor.fetchone()

    if file:
        # Delete physical file from disk
        if os.path.exists(file["file_path"]):
            os.remove(file["file_path"])

        # Delete in correct order (child tables first, parent last)
        # 1. Delete file answers (if exists)
        cursor.execute("DELETE FROM file_answers WHERE attempt_id IN (SELECT id FROM file_quiz_attempts WHERE file_id=%s)", (file_id,))
        
        # 2. Delete quiz attempts for this file
        cursor.execute("DELETE FROM file_quiz_attempts WHERE file_id=%s", (file_id,))
        
        # 3. Delete quiz questions for this file
        cursor.execute("DELETE FROM file_questions WHERE file_id=%s", (file_id,))
        
        # 4. Delete quizzes for this file
        cursor.execute("DELETE FROM file_quizzes WHERE file_id=%s", (file_id,))
        
        # 5. Delete simplified content
        cursor.execute("DELETE FROM file_simplified WHERE file_id=%s", (file_id,))
        
        # 6. Finally delete the file record
        cursor.execute("DELETE FROM topic_files WHERE id=%s", (file_id,))
        
        db.commit()

        return redirect(f"/topic/{file['topic_id']}")

    return redirect("/my-topics")




# ================= AI QUIZ =================
@app.route("/ai-quiz/<int:topic_id>")
def ai_quiz(topic_id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # 1️⃣ Get file
    cursor.execute(
        "SELECT id, file_path, file_name FROM topic_files WHERE topic_id=%s",
        (topic_id,)
    )
    file = cursor.fetchone()

    if not file:
        flash("No file found")
        return redirect(f"/topic/{topic_id}")

    # 2️⃣ Extract text
    text = extract_text_from_file(file["file_path"])

    if not text.strip():
        flash("File empty")
        return redirect(f"/topic/{topic_id}")

    # 3️⃣ Generate AI quiz
    quiz_json = generate_quiz_from_ai(text)
    clean = quiz_json.replace("```json","").replace("```","").strip()

    try:
        quiz_data = json.loads(clean)
    except:
        flash("AI error")
        return redirect(f"/topic/{topic_id}")

    questions = quiz_data.get("questions", quiz_data)

    # ⭐ SAVE QUIZ (multiple allowed)
    cursor.execute(
        "INSERT INTO file_quizzes (file_id) VALUES (%s)",
        (file["id"],)
    )
    db.commit()

    quiz_id = cursor.lastrowid

    # ⭐ SAVE QUESTIONS
    for q in questions:
        cursor.execute("""
            INSERT INTO file_questions
            (file_id, quiz_id, question, question_type, marks, correct_answer, options)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (
            file["id"],
            quiz_id,
            q.get("question",""),
            q.get("question_type","mcq"),
            int(q.get("marks") or 2),
            q.get("answer",""),
            json.dumps(q.get("options")) if q.get("options") else None
        ))

    db.commit()

    # ⭐ FETCH QUESTIONS → THIS FIXES EMPTY PAGE
    cursor.execute(
        "SELECT * FROM file_questions WHERE quiz_id=%s",
        (quiz_id,)
    )
    db_questions = cursor.fetchall()

    quiz = {
        "quiz_id": quiz_id,
        "file_name": file["file_name"]
    }

    cursor.close()
    db.close()

    # ⭐ IMPORTANT → render ai_quiz.html
    return render_template(
        "ai_quiz.html",
        quiz=quiz,
        questions=db_questions
    )

@app.route("/submit-quiz", methods=["POST"])
def submit_quiz():
    print("=== SUBMIT QUIZ DEBUG ===")
    
    if "quiz_data" not in session:
        print("ERROR: No quiz_data in session!")
        flash("No active quiz found.", "error")
        return redirect("/dashboard")

    if "ai_topic_id" not in session:
        print("ERROR: No ai_topic_id in session!")
        flash("Topic ID missing.", "error")
        return redirect("/dashboard")

    quiz = session["quiz_data"]
    topic_id = session["ai_topic_id"]
    user_id = session["user_id"]

    print(f"User ID: {user_id}")
    print(f"Topic ID: {topic_id}")
    print(f"Quiz length: {len(quiz)}")

    # Calculate score
    score = 0
    for i, q in enumerate(quiz):
        user_answer = request.form.get(f"q{i}")
        correct_answer = str(q["answer"])
        print(f"Q{i}: User='{user_answer}' | Correct='{correct_answer}'")
        
        if user_answer == correct_answer:
            score += 1

    print(f"Final score: {score}/{len(quiz)}")

    # Insert into database with explicit attempted_at
    db = get_db_connection()
    cursor = db.cursor()

    try:
        print("Attempting to insert into ai_quiz_attempts...")
        
        cursor.execute("""
            INSERT INTO ai_quiz_attempts 
            (user_id, topic_id, score, total, attempted_at)
            VALUES (%s, %s, %s, %s, NOW())
        """, (user_id, topic_id, score, len(quiz)))

        db.commit()
        print("✅ Successfully saved to database!")
        
        percentage = round((score / len(quiz)) * 100, 1) if len(quiz) > 0 else 0
        flash(f"✅ Quiz completed! You scored {score}/{len(quiz)} ({percentage}%)", "success")
        
    except Exception as e:
        db.rollback()
        print(f"❌ DATABASE ERROR: {e}")
        flash(f"Error saving quiz: {str(e)}", "error")
    
    finally:
        cursor.close()
        db.close()

    # Clear session
    session.pop("quiz_data", None)
    session.pop("ai_topic_id", None)

    print("=== END DEBUG ===")
    return redirect("/quizzes")

@app.route("/generate-file-quiz/<int:file_id>")
def generate_file_quiz(file_id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # Get file
    cursor.execute(
        "SELECT file_path, topic_id FROM topic_files WHERE id=%s",
        (file_id,)
    )
    file = cursor.fetchone()

    if not file:
        flash("File not found", "error")
        return redirect("/my-topics")

    # Extract text
    text = extract_text_from_file(file["file_path"])

    if not text.strip():
        flash("Could not extract text from file.", "error")
        return redirect(f"/topic/{file['topic_id']}")

    # Generate AI quiz
    try:
        quiz_json = generate_quiz_from_ai(text)
        clean = quiz_json.replace("```json", "").replace("```", "").strip()
        questions = json.loads(clean)

        # ✅ FIX 1: Handle {"questions": [...]} wrapper
        if isinstance(questions, dict):
            questions = questions.get("questions", [])

        if not questions:
            flash("AI didn't generate questions.", "error")
            return redirect(f"/topic/{file['topic_id']}")

    except Exception as e:
        print("AI ERROR:", e)
        flash("Error generating quiz", "error")
        return redirect(f"/topic/{file['topic_id']}")

    # Create quiz record
    cursor.execute(
        "INSERT INTO file_quizzes (file_id) VALUES (%s)",
        (file_id,)
    )
    quiz_id = cursor.lastrowid

    # Save questions
    for q in questions:
        cursor.execute("""
            INSERT INTO file_questions
            (file_id, quiz_id, question, question_type, marks, correct_answer, options)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            file_id,
            quiz_id,
            q.get("question", ""),
            q.get("question_type", "mcq"),
            int(q.get("marks") or 2),
            q.get("answer", ""),
            json.dumps(q.get("options")) if q.get("options") else None
        ))

    db.commit()
    cursor.close()
    db.close()

    # ✅ FIX 2: Redirect directly to quiz page instead of topic page
    flash("✅ Quiz generated successfully!", "success")
    return redirect(f"/file-quiz/{quiz_id}")

@app.route("/file-quiz/<int:quiz_id>")
def file_quiz(quiz_id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # 1️⃣ Get quiz + file + topic info
    cursor.execute("""
        SELECT 
            fqz.id AS quiz_id,
            fqz.file_id,
            tf.file_name,
            tf.topic_id
        FROM file_quizzes fqz
        JOIN topic_files tf ON fqz.file_id = tf.id
        WHERE fqz.id=%s
    """, (quiz_id,))
    quiz = cursor.fetchone()

    if not quiz:
        return redirect("/my-topics")

    # 2️⃣ Get questions for THIS quiz
    cursor.execute("""
        SELECT *
        FROM file_questions
        WHERE quiz_id=%s
        ORDER BY id
    """, (quiz_id,))
    questions = cursor.fetchall()

    return render_template(
        "ai_quiz.html",
        quiz=quiz,
        questions=questions
    )

@app.route("/quizzes")
def quizzes():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # Get all topics with BOTH ai_quiz_attempts AND file_quiz_attempts
    cursor.execute("""
        SELECT 
            t.id AS topic_id,
            t.title AS topic_title,
            
            -- Count AI quiz attempts
            COUNT(DISTINCT aqa.id) AS ai_attempts,
            MAX(CASE 
                WHEN aqa.total > 0 
                THEN ROUND((aqa.score * 100.0 / aqa.total), 1) 
                ELSE NULL 
            END) AS ai_best_score,
            
            -- Count file quiz attempts
            COUNT(DISTINCT fqa.id) AS file_attempts,
            MAX(CASE 
                WHEN fqa.total_marks > 0 
                THEN ROUND((fqa.score * 100.0 / fqa.total_marks), 1) 
                ELSE NULL 
            END) AS file_best_score
            
        FROM topics t
        
        -- Left join AI quiz attempts
        LEFT JOIN ai_quiz_attempts aqa 
            ON aqa.topic_id = t.id 
            AND aqa.user_id = %s
        
        -- Left join file quiz attempts via topic_files
        LEFT JOIN topic_files tf ON tf.topic_id = t.id
        LEFT JOIN file_quiz_attempts fqa 
            ON fqa.file_id = tf.id 
            AND fqa.user_id = %s
        
        WHERE t.user_id = %s
        GROUP BY t.id, t.title
        ORDER BY t.created_at DESC
    """, (user_id, user_id, user_id))

    topics = cursor.fetchall()

    # Combine attempts and best scores
    quizzes = []
    for t in topics:
        total_attempts = (t["ai_attempts"] or 0) + (t["file_attempts"] or 0)
        
        # Get best score from both types
        scores = [s for s in [t["ai_best_score"], t["file_best_score"]] if s is not None]
        best_score = max(scores) if scores else None
        
        quizzes.append({
            "topic_id": t["topic_id"],
            "topic_title": t["topic_title"],
            "attempts": total_attempts,
            "best_score": best_score
        })

    # DEBUG
    print("=== QUIZZES DEBUG ===")
    print(f"User ID: {user_id}")
    print(f"Topics found: {len(quizzes)}")
    for q in quizzes:
        print(f"  - {q['topic_title']}: {q['attempts']} attempts, {q['best_score']}% best")
    print("====================")

    cursor.close()
    db.close()

    return render_template("quizzes.html", quizzes=quizzes, active='quizzes')


@app.route("/quiz-history/<int:topic_id>")
def quiz_history(topic_id):
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT
    fqa.id,
    tf.file_name,
    fqa.score,
    fqa.total_marks,
    CASE 
        WHEN fqa.total_marks > 0
        THEN ROUND((fqa.score / fqa.total_marks) * 100, 2)
        ELSE 0
    END AS percentage,
    fqa.attempted_at
FROM file_quiz_attempts fqa
JOIN topic_files tf ON fqa.file_id = tf.id
WHERE tf.topic_id = %s
  AND fqa.user_id = %s
ORDER BY fqa.attempted_at DESC
    """, (topic_id, user_id))

    attempts = cursor.fetchall()

    cursor.execute("SELECT title FROM topics WHERE id=%s", (topic_id,))
    topic = cursor.fetchone()

    return render_template(
        "ai_quiz_history.html",
        topic=topic,
        attempts=attempts
    )

@app.route("/view-file-quiz-result/<int:attempt_id>")
def view_file_quiz_result(attempt_id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT fqa.*, tf.file_name
        FROM file_quiz_attempts fqa
        JOIN topic_files tf ON fqa.file_id = tf.id
        WHERE fqa.id=%s AND fqa.user_id=%s
    """, (attempt_id, session["user_id"]))
    attempt = cursor.fetchone()
    if not attempt:
        return redirect("/my-topics")

    cursor.execute("""
        SELECT fq.question, fq.question_type, fq.correct_answer,
               fa.user_answer, fa.marks_awarded, fq.marks
        FROM file_answers fa
        JOIN file_questions fq ON fa.question_id = fq.id
        WHERE fa.attempt_id=%s
    """, (attempt_id,))
    answers = cursor.fetchall()

    return render_template(
        "quiz_result.html",
        attempt=attempt,
        answers=answers
    )

@app.route("/view-file-quiz-answers/<int:quiz_id>")
def view_file_quiz_answers(quiz_id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # Quiz info
    cursor.execute("""
        SELECT fq.id, tf.file_name
        FROM file_quizzes fq
        JOIN topic_files tf ON fq.file_id = tf.id
        WHERE fq.id=%s
    """, (quiz_id,))
    quiz = cursor.fetchone()

    if not quiz:
        return "Quiz not found", 404

    # Questions
    cursor.execute("""
        SELECT 
            question,
            question_type,
            marks,
            correct_answer,
            options
        FROM file_questions
        WHERE quiz_id=%s
        ORDER BY id
    """, (quiz_id,))
    questions = cursor.fetchall()

    # ✅ IMPORTANT FIX: decode JSON HERE
    for q in questions:
        if q["options"]:
            q["options"] = json.loads(q["options"])
        else:
            q["options"] = []

    return render_template(
        "view_file_quiz_answers.html",
        quiz=quiz,
        questions=questions
    )

@app.route("/upload-topic-file/<int:topic_id>", methods=["POST"])
def upload_topic_file(topic_id):
    if "user_id" not in session:
        return redirect("/login")

    file = request.files.get("file")
    if not file or not file.filename:
        return redirect(f"/topic/{topic_id}")

    filename = secure_filename(file.filename)
    file_type = file.content_type

    upload_dir = "static/uploads"
    os.makedirs(upload_dir, exist_ok=True)

    file_path = os.path.join(upload_dir, filename)
    file.save(file_path)

    db = get_db_connection()
    cursor = db.cursor()

    cursor.execute("""
        INSERT INTO topic_files (topic_id, file_name, file_path, file_type)
        VALUES (%s, %s, %s, %s)
    """, (topic_id, filename, file_path, file_type))

    db.commit()

    return redirect(f"/topic/{topic_id}")

@app.route("/delete-file-simplified/<int:file_id>", methods=["POST"])
def delete_file_simplified(file_id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # get topic_id for redirect
    cursor.execute("""
        SELECT topic_id FROM topic_files WHERE id=%s
    """, (file_id,))
    file = cursor.fetchone()

    if not file:
        return redirect("/my-topics")

    topic_id = file["topic_id"]

    # delete simplified content of this file
    cursor.execute("""
        DELETE FROM file_simplified WHERE file_id=%s
    """, (file_id,))

    db.commit()

    return redirect(f"/topic/{topic_id}")


@app.route("/delete-file-quiz/<int:quiz_id>", methods=["POST"])
def delete_file_quiz(quiz_id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT tf.topic_id
        FROM file_quizzes fq
        JOIN topic_files tf ON fq.file_id = tf.id
        WHERE fq.id=%s
    """, (quiz_id,))
    data = cursor.fetchone()

    if not data:
        return redirect("/my-topics")

    # Delete quiz attempts for this specific quiz first
    cursor.execute("""
        DELETE fqa FROM file_quiz_attempts fqa
        JOIN file_quizzes fq ON fqa.file_id = fq.file_id
        WHERE fq.id = %s
    """, (quiz_id,))

    # Delete questions for this quiz
    cursor.execute(
        "DELETE FROM file_questions WHERE quiz_id=%s",
        (quiz_id,)
    )

    # Delete the quiz itself
    cursor.execute(
        "DELETE FROM file_quizzes WHERE id=%s",
        (quiz_id,)
    )

    db.commit()
    return redirect(f"/topic/{data['topic_id']}")

@app.route("/submit-file-quiz/<int:quiz_id>", methods=["POST"])
def submit_file_quiz(quiz_id):
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT file_id FROM file_quizzes WHERE id = %s", (quiz_id,))
    quiz = cursor.fetchone()

    if not quiz:
        return "Quiz not found", 404

    file_id = quiz["file_id"]

    cursor.execute("""
        SELECT id, question, question_type, marks, correct_answer
        FROM file_questions
        WHERE quiz_id = %s
        ORDER BY id
    """, (quiz_id,))
    questions = cursor.fetchall()

    total_score = 0
    total_marks = 0

    for i, q in enumerate(questions):
        marks = q["marks"] if q["marks"] and q["marks"] > 0 else 2
        total_marks += marks
        user_answer = request.form.get(f"q{i}", "").strip()

        if q["question_type"] == "mcq":
            # Auto-grade MCQ exactly as before
            correct = str(q["correct_answer"]).strip()
            if user_answer == correct:
                total_score += marks

        else:
            # ✅ AI auto-grade short/long answers
            if user_answer:
                ai_marks = ai_grade_answer(
                    question=q["question"],
                    correct_answer=q["correct_answer"],
                    user_answer=user_answer,
                    max_marks=marks
                )
                total_score += ai_marks

    cursor.execute("""
        INSERT INTO file_quiz_attempts
        (user_id, file_id, score, total_marks, attempted_at)
        VALUES (%s, %s, %s, %s, NOW())
    """, (user_id, file_id, total_score, total_marks))

    db.commit()
    cursor.close()
    db.close()

    percentage = round((total_score / total_marks) * 100, 1) if total_marks > 0 else 0
    flash(f"✅ Quiz completed! You scored {total_score}/{total_marks} ({percentage}%)", "success")
    # Award badges if earned
    from flashcard_routes import check_and_award_badges
    db2 = get_db_connection()
    cur2 = db2.cursor(dictionary=True)
    check_and_award_badges(user_id, db2, cur2)
    cur2.close()
    db2.close()
    return redirect("/quizzes")

@app.route("/game/quiz-match/<int:file_id>")


def quiz_match_game(file_id):
    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # ✅ MUST FETCH id + topic_id
    cursor.execute("""
        SELECT id, file_name, topic_id
        FROM topic_files
        WHERE id = %s
    """, (file_id,))
    file = cursor.fetchone()

    if not file:
        return "File not found", 404

    # ✅ get simplified text
    cursor.execute("""
        SELECT simplified_text
        FROM file_simplified
        WHERE file_id = %s
    """, (file_id,))
    row = cursor.fetchone()
    text = row["simplified_text"] if row else ""

    concepts = []
    definitions = []

    if text.strip():
        raw = generate_match_game(text)
        items = json.loads(raw)

        for i, it in enumerate(items, start=1):
            concepts.append({"id": i, "text": it["concept"]})
            definitions.append({"id": i, "text": it["definition"]})

        import random
        random.shuffle(concepts)
        random.shuffle(definitions)

    return render_template(
        "game_quiz_match.html",
        file=file,          # 🔴 THIS IS CRITICAL
        concepts=concepts,
        definitions=definitions
    )



@app.route("/submit-game", methods=["POST"])
def submit_game():
    if "user_id" not in session:
        return redirect("/login")

    file_id = request.form.get("file_id")
    topic_id = request.form.get("topic_id")
    score = int(request.form.get("score", 0))
    total = int(request.form.get("total", 0))
    game_type = request.form.get("game_type")

    # 🔴 ABSOLUTE SAFETY
    if not file_id or not file_id.isdigit():
        return "Invalid file_id submitted", 400

    db = get_db_connection()
    cursor = db.cursor()

    cursor.execute("""
        INSERT INTO game_scores
        (user_id, topic_id, file_id, game_type, score, total)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        session["user_id"],
        topic_id,
        int(file_id),
        game_type,
        score,
        total
    ))

    db.commit()

    return redirect(f"/topic/{topic_id}")


@app.route("/ai-quiz-analytics")
def ai_quiz_analytics():
    if "user_id" not in session:
        return redirect("/login")

    from collections import defaultdict

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    user_id = session["user_id"]

    # =====================================================
    # 1️⃣ QUIZ ANALYTICS
    # =====================================================

    cursor.execute("""
        SELECT 
            tf.file_name,
            qa.score,
            qa.total_marks AS total,
            qa.attempted_at,
            'Quiz' AS type
        FROM file_quiz_attempts qa
        JOIN topic_files tf ON qa.file_id = tf.id
        WHERE qa.user_id = %s
    """, (user_id,))
    quiz_data = cursor.fetchall()

    # =====================================================
    # 2️⃣ GAME ANALYTICS (from game_sessions table)
    # =====================================================

    cursor.execute("""
        SELECT 
            COALESCE(tf.file_name, gs.topic) AS file_name,
            gs.score,
            gs.total_cards                   AS total,
            gs.correct_answers,
            gs.game_mode,
            gs.created_at                    AS attempted_at,
            'Game'                           AS type
        FROM game_sessions gs
        LEFT JOIN topic_files tf 
               ON gs.topic = CONCAT('file_', tf.id)
        WHERE gs.user_id = %s
          AND gs.completed = TRUE
    """, (user_id,))
    game_data = cursor.fetchall()

    analytics = quiz_data + game_data

    # =====================================================
    # 3️⃣ SUMMARY COUNTS
    # =====================================================

    total_quizzes = len(quiz_data)
    total_games   = len(game_data)

    accuracies = [
        (row["score"] / row["total"]) * 100
        for row in analytics
        if row["total"] and row["total"] > 0
    ]
    avg_accuracy = round(sum(accuracies) / len(accuracies), 2) if accuracies else 0

    # =====================================================
    # 4️⃣ LINE CHART — accuracy over time
    # =====================================================

    line_labels = []
    line_data   = []

    sorted_analytics = sorted(
        [r for r in analytics if r["total"] and r["total"] > 0],
        key=lambda r: r["attempted_at"]
    )

    for row in sorted_analytics:
        line_labels.append(row["attempted_at"].strftime("%d %b"))
        line_data.append(round((row["score"] / row["total"]) * 100, 2))

    # =====================================================
    # 5️⃣ BAR CHART — accuracy by file
    # =====================================================

    file_accuracy = defaultdict(list)

    for row in analytics:
        if row["total"] and row["total"] > 0:
            acc = (row["score"] / row["total"]) * 100
            file_accuracy[row["file_name"]].append(acc)

    bar_labels = list(file_accuracy.keys())
    bar_data   = [round(sum(v) / len(v), 2) for v in file_accuracy.values()]

    # =====================================================
    # 6️⃣ GAME MODE BREAKDOWN (for mode donut chart)
    # =====================================================

    cursor.execute("""
        SELECT game_mode, COUNT(*) AS cnt
        FROM game_sessions
        WHERE user_id = %s AND completed = TRUE
        GROUP BY game_mode
    """, (user_id,))

    mode_rows   = {r["game_mode"]: r["cnt"] for r in cursor.fetchall()}
    mode_counts = [
        mode_rows.get("flip_answer",     0),
        mode_rows.get("timed_challenge", 0),
        mode_rows.get("match_game",      0)
    ]

    # =====================================================
    # 7️⃣ BEST SCORE
    # =====================================================

    cursor.execute("""
        SELECT COALESCE(MAX(score), 0) AS best
        FROM game_sessions
        WHERE user_id = %s AND completed = TRUE
    """, (user_id,))
    best_score = cursor.fetchone()["best"] or 0

    # =====================================================
    # 8️⃣ TOTAL CARDS DONE (for Flashcard Pro badge progress)
    # =====================================================

    cursor.execute("""
        SELECT COALESCE(SUM(correct_answers), 0) AS total
        FROM game_sessions
        WHERE user_id = %s AND completed = TRUE
    """, (user_id,))
    total_cards_done = int(cursor.fetchone()["total"] or 0)

    # =====================================================
    # 9️⃣ TIMED CORRECT COUNT (for Quick Thinker badge progress)
    # =====================================================

    cursor.execute("""
        SELECT COALESCE(SUM(correct_answers), 0) AS total
        FROM game_sessions
        WHERE user_id = %s
          AND game_mode = 'timed_challenge'
          AND completed = TRUE
    """, (user_id,))
    timed_correct_count = int(cursor.fetchone()["total"] or 0)

    # =====================================================
    # 🔟 TOPIC MASTERY (per file accuracy)
    # =====================================================

    cursor.execute("""
        SELECT 
            REPLACE(gs.topic, 'file_', 'File #')              AS name,
            ROUND(AVG(gs.correct_answers * 100.0 / gs.total_cards)) AS accuracy
        FROM game_sessions gs
        WHERE gs.user_id = %s
          AND gs.completed = TRUE
          AND gs.total_cards > 0
        GROUP BY gs.topic
    """, (user_id,))
    topic_mastery = cursor.fetchall() or []

    # =====================================================
    # 1️⃣1️⃣ ACTIVE DAYS
    # =====================================================

    cursor.execute("""
        SELECT COUNT(DISTINCT DATE(created_at)) AS days
        FROM game_sessions
        WHERE user_id = %s AND completed = TRUE
    """, (user_id,))
    active_days = int(cursor.fetchone()["days"] or 0)

    # =====================================================
    # 1️⃣2️⃣ EARNED BADGES
    # =====================================================

    cursor.execute("""
        SELECT b.name, b.icon
        FROM user_badges ub
        JOIN badges b ON ub.badge_id = b.id
        WHERE ub.user_id = %s
    """, (user_id,))
    earned_badges = cursor.fetchall() or []

    cursor.close()
    db.close()

    # =====================================================
    # FINAL RENDER
    # =====================================================

    return render_template(
        "ai_quiz_analytics.html",

        # Existing variables (unchanged)
        analytics        = analytics,
        total_quizzes    = total_quizzes,
        total_games      = total_games,
        avg_accuracy     = avg_accuracy,
        line_labels      = line_labels,
        line_data        = line_data,
        bar_labels       = bar_labels,
        bar_data         = bar_data,

        # New variables
        mode_counts          = mode_counts,
        best_score           = best_score,
        total_cards_done     = total_cards_done,
        timed_correct_count  = timed_correct_count,
        topic_mastery        = topic_mastery,
        active_days          = active_days,
        earned_badges        = earned_badges,
    )

from werkzeug.security import check_password_hash, generate_password_hash

# ─────────────────────────────────────
# SETTINGS — VIEW
# ─────────────────────────────────────

@app.route("/settings")
def settings():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    db      = get_db_connection()
    cursor  = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, name, email
        FROM users WHERE id = %s
    """, (user_id,))
    user = cursor.fetchone()

    cursor.close()
    db.close()

    return render_template("settings.html", user=user)


# ─────────────────────────────────────
# SETTINGS — UPDATE PROFILE
# ─────────────────────────────────────

@app.route("/settings/update-profile", methods=["POST"])
def update_profile():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    name    = request.form.get("name",  "").strip()
    email   = request.form.get("email", "").strip()

    if not name or not email:
        flash("Name and email are required.", "error")
        return redirect("/settings")

    db     = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # Check email not taken by someone else
    cursor.execute("""
        SELECT id FROM users
        WHERE email = %s AND id != %s
    """, (email, user_id))

    if cursor.fetchone():
        flash("That email is already in use by another account.", "error")
        cursor.close()
        db.close()
        return redirect("/settings")

    cursor.execute("""
        UPDATE users SET name = %s, email = %s
        WHERE id = %s
    """, (name, email, user_id))

    db.commit()
    cursor.close()
    db.close()

    session["name"] = name
    flash("Profile updated successfully!", "success")
    return redirect("/settings")


# ─────────────────────────────────────
# SETTINGS — CHANGE PASSWORD
# ─────────────────────────────────────

@app.route("/settings/change-password", methods=["POST"])
def change_password():
    if "user_id" not in session:
        return redirect("/login")

    user_id  = session["user_id"]
    current  = request.form.get("current_password", "")
    new_pw   = request.form.get("new_password",     "")
    confirm  = request.form.get("confirm_password", "")

    if not current or not new_pw or not confirm:
        flash("All password fields are required.", "error")
        return redirect("/settings")

    if new_pw != confirm:
        flash("New passwords do not match.", "error")
        return redirect("/settings")

    if len(new_pw) < 6:
        flash("Password must be at least 6 characters.", "error")
        return redirect("/settings")

    db     = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT password FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()

    if not user or not check_password_hash(user["password"], current):
        flash("Current password is incorrect.", "error")
        cursor.close()
        db.close()
        return redirect("/settings")

    cursor.execute("""
        UPDATE users SET password = %s WHERE id = %s
    """, (generate_password_hash(new_pw), user_id))

    db.commit()
    cursor.close()
    db.close()

    flash("Password changed successfully!", "success")
    return redirect("/settings")


# ─────────────────────────────────────
# SETTINGS — DELETE ACCOUNT
# ─────────────────────────────────────

@app.route("/settings/delete-account", methods=["POST"])
def delete_account():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    db      = get_db_connection()
    cursor  = db.cursor()

    # Delete in correct FK order
    cursor.execute("DELETE FROM user_badges        WHERE user_id = %s", (user_id,))
    cursor.execute("DELETE FROM user_stats         WHERE user_id = %s", (user_id,))
    cursor.execute("DELETE FROM flashcard_progress WHERE user_id = %s", (user_id,))
    cursor.execute("DELETE FROM game_sessions      WHERE user_id = %s", (user_id,))
    cursor.execute("DELETE FROM flashcards         WHERE user_id = %s", (user_id,))
    cursor.execute("DELETE FROM users              WHERE id      = %s", (user_id,))

    db.commit()
    cursor.close()
    db.close()

    session.clear()
    flash("Your account has been deleted.", "success")
    return redirect("/login")

# ================= RUN =================
if __name__ == "__main__":
    app.run(debug=True)
