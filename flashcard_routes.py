from ai_helper import generate_flashcards_from_content

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
import mysql.connector
from datetime import datetime
import random

# Create Blueprint
flashcard_bp = Blueprint('flashcard', __name__, url_prefix='/flashcard')

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Database connection
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="root",
        database="learnify"
    )

# ============================================
# HELPER FUNCTION - AUTO GENERATE FLASHCARDS
# ============================================

def get_or_generate_flashcards_for_file(file_id, user_id):
    """Get existing flashcards or generate new ones from file's simplified content"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get file name from topic_files table
    cursor.execute("""
        SELECT file_name
        FROM topic_files
        WHERE id = %s
    """, (file_id,))
    
    file_data = cursor.fetchone()
    
    if not file_data:
        cursor.close()
        conn.close()
        return None, "File not found."
    
    # Get simplified text from file_simplified table
    cursor.execute("""
        SELECT simplified_text
        FROM file_simplified
        WHERE file_id = %s
    """, (file_id,))
    
    simplified_data = cursor.fetchone()
    
    if not simplified_data or not simplified_data.get('simplified_text'):
        cursor.close()
        conn.close()
        return None, "Please simplify this file first before playing games."
    
    # Check if flashcards already exist for this file
    cursor.execute("""
        SELECT * FROM flashcards 
        WHERE user_id = %s AND topic = %s
        ORDER BY RAND()
    """, (user_id, f"file_{file_id}"))
    
    flashcards = cursor.fetchall()
    
    # If no flashcards exist, generate them using AI
    if not flashcards:
        print(f"Generating flashcards for file {file_id}: {file_data['file_name']}")
        
        generated_cards = generate_flashcards_from_content(
            simplified_data['simplified_text'],
            file_data['file_name'],
            num_cards=12
        )
        
        if not generated_cards:
            cursor.close()
            conn.close()
            return None, "Failed to generate flashcards. Please try again."
        
        # Save generated flashcards to database
        for card in generated_cards:
            cursor.execute("""
                INSERT INTO flashcards (user_id, topic, question, answer, difficulty)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, f"file_{file_id}", card['question'], card['answer'], 
                  card.get('difficulty', 'medium')))
        
        conn.commit()
        
        # Fetch the newly created flashcards
        cursor.execute("""
            SELECT * FROM flashcards 
            WHERE user_id = %s AND topic = %s
            ORDER BY RAND()
        """, (user_id, f"file_{file_id}"))
        
        flashcards = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return flashcards, None

# ============================================
# MAIN DASHBOARD
# ============================================

@flashcard_bp.route('/dashboard')
@login_required
def dashboard():
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get topics
    cursor.execute("""
        SELECT DISTINCT topic, COUNT(*) as card_count 
        FROM flashcards 
        WHERE user_id = %s 
        GROUP BY topic
    """, (user_id,))
    topics = cursor.fetchall()
    
    # Get recent games
    cursor.execute("""
        SELECT * FROM game_sessions 
        WHERE user_id = %s 
        ORDER BY created_at DESC 
        LIMIT 10
    """, (user_id,))
    recent_games = cursor.fetchall()
    
    # Get earned badges
    cursor.execute("""
        SELECT b.*, ub.earned_at 
        FROM badges b
        JOIN user_badges ub ON b.id = ub.badge_id
        WHERE ub.user_id = %s
        ORDER BY ub.earned_at DESC
    """, (user_id,))
    earned_badges = cursor.fetchall()
    
    # Get all badges
    cursor.execute("SELECT * FROM badges")
    all_badges = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('flashcard/dashboard.html', 
                         topics=topics, 
                         recent_games=recent_games,
                         earned_badges=earned_badges,
                         all_badges=all_badges)

# ============================================
# CREATE FLASHCARDS (KEEP FOR MANUAL USE)
# ============================================

@flashcard_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_flashcard():
    if request.method == 'POST':
        user_id = session['user_id']
        topic = request.form.get('topic')
        question = request.form.get('question')
        answer = request.form.get('answer')
        difficulty = request.form.get('difficulty', 'medium')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO flashcards (user_id, topic, question, answer, difficulty)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, topic, question, answer, difficulty))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Flashcard created successfully'})
    
    return render_template('flashcard/create.html')

@flashcard_bp.route('/bulk-create', methods=['POST'])
@login_required
def bulk_create_flashcards():
    user_id = session['user_id']
    flashcards = request.json.get('flashcards', [])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    for card in flashcards:
        cursor.execute("""
            INSERT INTO flashcards (user_id, topic, question, answer, difficulty)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, card['topic'], card['question'], card['answer'], 
              card.get('difficulty', 'medium')))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True, 'count': len(flashcards)})


# ============================================
# FILE-BASED GAME MODE 1: FLIP & ANSWER
# ============================================

@flashcard_bp.route('/game/flip-answer/file/<int:file_id>')
@login_required
def flip_answer_game_file(file_id):
    user_id = session['user_id']
    
    # Get or generate flashcards
    flashcards, error = get_or_generate_flashcards_for_file(file_id, user_id)
    
    if error:
        return f"""
        <html>
        <head><title>Error</title></head>
        <body style="font-family: Arial; padding: 50px; text-align: center;">
            <h2>⚠️ {error}</h2>
            <a href="/my-topics" style="color: #007bff; text-decoration: none;">← Go Back to Topics</a>
        </body>
        </html>
        """, 400
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get file info from topic_files
    cursor.execute("SELECT file_name FROM topic_files WHERE id = %s", (file_id,))
    file_info = cursor.fetchone()
    
    # Create game session
    cursor.execute("""
        INSERT INTO game_sessions (user_id, game_mode, topic, total_cards)
        VALUES (%s, 'flip_answer', %s, %s)
    """, (user_id, f"file_{file_id}", len(flashcards)))
    
    session_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()
    
    return render_template('flashcard/flip_answer.html', 
                         flashcards=flashcards, 
                         session_id=session_id,
                         topic=file_info['file_name'],
                         file_id=file_id)  # ADD THIS

# ============================================
# FILE-BASED GAME MODE 2: TIMED CHALLENGE
# ============================================

@flashcard_bp.route('/game/timed-challenge/file/<int:file_id>')
@login_required
def timed_challenge_file(file_id):
    user_id = session['user_id']
    
    # Get or generate flashcards
    flashcards, error = get_or_generate_flashcards_for_file(file_id, user_id)
    
    if error:
        return f"""
        <html>
        <head><title>Error</title></head>
        <body style="font-family: Arial; padding: 50px; text-align: center;">
            <h2>⚠️ {error}</h2>
            <a href="/my-topics" style="color: #007bff; text-decoration: none;">← Go Back to Topics</a>
        </body>
        </html>
        """, 400
    
    # Limit to 10-15 cards for timed challenge
    num_cards = min(random.randint(10, 15), len(flashcards))
    flashcards = flashcards[:num_cards]
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get file info from topic_files
    cursor.execute("SELECT file_name FROM topic_files WHERE id = %s", (file_id,))
    file_info = cursor.fetchone()
    
    # Create game session
    cursor.execute("""
        INSERT INTO game_sessions (user_id, game_mode, topic, total_cards)
        VALUES (%s, 'timed_challenge', %s, %s)
    """, (user_id, f"file_{file_id}", len(flashcards)))
    
    session_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()
    
    return render_template('flashcard/timed_challenge.html', 
                         flashcards=flashcards, 
                         session_id=session_id,
                         topic=file_info['file_name'],
                         file_id=file_id)  # ADD THIS

# ============================================
# FILE-BASED GAME MODE 3: MATCH GAME
# ============================================

@flashcard_bp.route('/game/match/file/<int:file_id>')
@login_required
def match_game_file(file_id):
    user_id = session['user_id']
    
    # Get or generate flashcards
    flashcards, error = get_or_generate_flashcards_for_file(file_id, user_id)
    
    if error:
        return f"""
        <html>
        <head><title>Error</title></head>
        <body style="font-family: Arial; padding: 50px; text-align: center;">
            <h2>⚠️ {error}</h2>
            <a href="/my-topics" style="color: #007bff; text-decoration: none;">← Go Back to Topics</a>
        </body>
        </html>
        """, 400
    
    # Limit to 6-8 cards for match game
    num_cards = min(random.randint(6, 8), len(flashcards))
    flashcards = flashcards[:num_cards]
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Get file info from topic_files
    cursor.execute("SELECT file_name FROM topic_files WHERE id = %s", (file_id,))
    file_info = cursor.fetchone()
    
    # Create game session
    cursor.execute("""
        INSERT INTO game_sessions (user_id, game_mode, topic, total_cards)
        VALUES (%s, 'match_game', %s, %s)
    """, (user_id, f"file_{file_id}", len(flashcards)))
    
    session_id = cursor.lastrowid
    conn.commit()
    cursor.close()
    conn.close()
    
    return render_template('flashcard/match_game.html', 
                         flashcards=flashcards, 
                         session_id=session_id,
                         topic=file_info['file_name'],
                         file_id=file_id)  # ADD THIS






# ============================================
# GAME SUBMIT ROUTES (UNCHANGED)
# ============================================

@flashcard_bp.route('/game/flip-answer/submit', methods=['POST'])
@login_required
def submit_flip_answer():
    user_id = session['user_id']
    data = request.json
    
    flashcard_id = data.get('flashcard_id')
    knew_it = data.get('knew_it')
    session_id = data.get('session_id')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if knew_it:
        cursor.execute("""
            INSERT INTO flashcard_progress (user_id, flashcard_id, knew_count)
            VALUES (%s, %s, 1)
            ON DUPLICATE KEY UPDATE knew_count = knew_count + 1
        """, (user_id, flashcard_id))
    else:
        cursor.execute("""
            INSERT INTO flashcard_progress (user_id, flashcard_id, didnt_know_count)
            VALUES (%s, %s, 1)
            ON DUPLICATE KEY UPDATE didnt_know_count = didnt_know_count + 1
        """, (user_id, flashcard_id))
    
    cursor.execute("""
        UPDATE game_sessions 
        SET correct_answers = correct_answers + %s
        WHERE id = %s
    """, (1 if knew_it else 0, session_id))
    
    cursor.execute("""
        INSERT INTO user_stats (user_id, total_cards_completed)
        VALUES (%s, 1)
        ON DUPLICATE KEY UPDATE total_cards_completed = total_cards_completed + 1
    """, (user_id,))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    check_and_award_badges(user_id)
    
    return jsonify({'success': True})

@flashcard_bp.route('/game/timed-challenge/submit', methods=['POST'])
@login_required
def submit_timed_challenge():
    user_id = session['user_id']
    data = request.json
    
    session_id = data.get('session_id')
    correct_answers = data.get('correct_answers')
    time_taken = data.get('time_taken')
    
    score = max(0, (correct_answers * 100) - (time_taken * 0.5))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE game_sessions 
        SET score = %s, correct_answers = %s, time_taken = %s, completed = TRUE
        WHERE id = %s
    """, (score, correct_answers, time_taken, session_id))
    
    cursor.execute("""
        INSERT INTO user_stats (user_id, total_cards_completed)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE total_cards_completed = total_cards_completed + %s
    """, (user_id, correct_answers, correct_answers))
    
    cursor.execute("SELECT total_cards FROM game_sessions WHERE id = %s", (session_id,))
    total_cards = cursor.fetchone()[0]
    won = (correct_answers / total_cards) >= 0.7
    
    if won:
        cursor.execute("UPDATE user_stats SET consecutive_losses = 0 WHERE user_id = %s", (user_id,))
    else:
        cursor.execute("""
            INSERT INTO user_stats (user_id, consecutive_losses)
            VALUES (%s, 1)
            ON DUPLICATE KEY UPDATE consecutive_losses = consecutive_losses + 1
        """, (user_id,))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    new_badges = check_and_award_badges(user_id)
    
    return jsonify({'success': True, 'score': score, 'new_badges': new_badges})

@flashcard_bp.route('/game/match/submit', methods=['POST'])
@login_required
def submit_match_game():
    user_id = session['user_id']
    data = request.json
    
    session_id = data.get('session_id')
    matches = data.get('matches')
    time_taken = data.get('time_taken')
    
    score = (matches * 50) - (time_taken * 0.3)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE game_sessions 
        SET score = %s, correct_answers = %s, time_taken = %s, completed = TRUE
        WHERE id = %s
    """, (score, matches, time_taken, session_id))
    
    cursor.execute("""
        INSERT INTO user_stats (user_id, total_cards_completed)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE total_cards_completed = total_cards_completed + %s
    """, (user_id, matches, matches))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    new_badges = check_and_award_badges(user_id)
    
    return jsonify({'success': True, 'score': score, 'new_badges': new_badges})

# ============================================
# BADGE SYSTEM
# ============================================

def check_and_award_badges(user_id, db, cursor):

    # ── Get badge IDs ──
    cursor.execute("SELECT id, name FROM badges")
    all_badges = {b["name"]: b["id"] for b in cursor.fetchall()}

    # ── Already earned ──
    cursor.execute("SELECT badge_id FROM user_badges WHERE user_id=%s", (user_id,))
    already_earned = {r["badge_id"] for r in cursor.fetchall()}

    def award(badge_name):
        badge_id = all_badges.get(badge_name)
        if badge_id and badge_id not in already_earned:
            cursor.execute("""
                INSERT INTO user_badges (user_id, badge_id)
                VALUES (%s, %s)
            """, (user_id, badge_id))
            already_earned.add(badge_id)

    # ── Concept Master: avg accuracy >= 90% ──
    cursor.execute("""
        SELECT ROUND(AVG(correct_answers * 100.0 / total_cards)) AS acc
        FROM game_sessions
        WHERE user_id=%s AND completed=TRUE AND total_cards > 0
    """, (user_id,))
    row = cursor.fetchone()
    if row and row["acc"] and row["acc"] >= 90:
        award("Concept Master")

    # Also check quiz attempts
    cursor.execute("""
        SELECT ROUND(AVG(score * 100.0 / total_marks)) AS acc
        FROM file_quiz_attempts
        WHERE user_id=%s AND total_marks > 0
    """, (user_id,))
    row = cursor.fetchone()
    if row and row["acc"] and row["acc"] >= 90:
        award("Concept Master")

    # ── Quick Thinker: 10 correct in timed mode ──
    cursor.execute("""
        SELECT COALESCE(SUM(correct_answers), 0) AS total
        FROM game_sessions
        WHERE user_id=%s AND game_mode='timed_challenge' AND completed=TRUE
    """, (user_id,))
    if cursor.fetchone()["total"] >= 10:
        award("Quick Thinker")

    # ── Flashcard Pro: 100 cards done ──
    cursor.execute("""
        SELECT COALESCE(SUM(correct_answers), 0) AS total
        FROM game_sessions
        WHERE user_id=%s AND completed=TRUE
    """, (user_id,))
    if cursor.fetchone()["total"] >= 100:
        award("Flashcard Pro")

    db.commit()
    

@flashcard_bp.route('/badges')
@login_required
def view_badges():
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT b.*, 
               ub.earned_at,
               CASE WHEN ub.id IS NOT NULL THEN 1 ELSE 0 END as earned
        FROM badges b
        LEFT JOIN user_badges ub ON b.id = ub.badge_id AND ub.user_id = %s
        ORDER BY earned DESC, b.id
    """, (user_id,))
    badges = cursor.fetchall()
    
    cursor.execute("SELECT * FROM user_stats WHERE user_id = %s", (user_id,))
    stats = cursor.fetchone()
    
    cursor.close()
    conn.close()
    
    return render_template('flashcard/badges.html', badges=badges, stats=stats)

# ============================================
# STATISTICS
# ============================================

@flashcard_bp.route('/stats')
@login_required
def statistics():
    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT 
            COUNT(*) as total_games,
            AVG(score) as avg_score,
            SUM(correct_answers) as total_correct,
            SUM(total_cards) as total_attempted
        FROM game_sessions
        WHERE user_id = %s AND completed = TRUE
    """, (user_id,))
    overall = cursor.fetchone()
    
    cursor.execute("""
        SELECT 
            game_mode,
            COUNT(*) as games_played,
            AVG(score) as avg_score,
            MAX(score) as best_score
        FROM game_sessions
        WHERE user_id = %s AND completed = TRUE
        GROUP BY game_mode
    """, (user_id,))
    by_mode = cursor.fetchall()
    
    cursor.execute("""
        SELECT 
            topic,
            COUNT(*) as games_played,
            AVG(correct_answers * 100.0 / total_cards) as accuracy
        FROM game_sessions
        WHERE user_id = %s AND completed = TRUE AND topic IS NOT NULL
        GROUP BY topic
    """, (user_id,))
    by_topic = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('flashcard/stats.html', 
                         overall=overall, 
                         by_mode=by_mode, 
                         by_topic=by_topic)