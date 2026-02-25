from flask import Blueprint, render_template, request, redirect, session, flash
from werkzeug.security import check_password_hash, generate_password_hash
from db import get_db_connection
from flask_mail import Mail, Message
import secrets
import datetime

settings_bp = Blueprint('settings', __name__)

# Mail will be injected from app.py
mail = None

def init_mail(mail_instance):
    global mail
    mail = mail_instance


# ─────────────────────────────────────
# VIEW SETTINGS
# ─────────────────────────────────────
@settings_bp.route("/settings")
def settings():
    if "user_id" not in session:
        return redirect("/login")

    db     = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT id, name, email FROM users WHERE id=%s",
                   (session["user_id"],))
    user = cursor.fetchone()

    cursor.close()
    db.close()

    return render_template("settings.html", user=user)


# ─────────────────────────────────────
# UPDATE PROFILE
# ─────────────────────────────────────
@settings_bp.route("/settings/update-profile", methods=["POST"])
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

    cursor.execute("SELECT id FROM users WHERE email=%s AND id != %s",
                   (email, user_id))
    if cursor.fetchone():
        flash("That email is already in use.", "error")
        cursor.close()
        db.close()
        return redirect("/settings")

    cursor.execute("UPDATE users SET name=%s, email=%s WHERE id=%s",
                   (name, email, user_id))
    db.commit()
    cursor.close()
    db.close()

    session["name"] = name
    flash("Profile updated successfully!", "success")
    return redirect("/settings")


# ─────────────────────────────────────
# CHANGE PASSWORD
# ─────────────────────────────────────
@settings_bp.route("/settings/change-password", methods=["POST"])
def change_password():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    current = request.form.get("current_password", "")
    new_pw  = request.form.get("new_password",     "")
    confirm = request.form.get("confirm_password", "")

    if not current or not new_pw or not confirm:
        flash("All fields are required.", "error")
        return redirect("/settings")

    if new_pw != confirm:
        flash("New passwords do not match.", "error")
        return redirect("/settings")

    if len(new_pw) < 6:
        flash("Password must be at least 6 characters.", "error")
        return redirect("/settings")

    db     = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT password FROM users WHERE id=%s", (user_id,))
    user = cursor.fetchone()

    if not user or not check_password_hash(user["password"], current):
        flash("Current password is incorrect.", "error")
        cursor.close()
        db.close()
        return redirect("/settings")

    cursor.execute("UPDATE users SET password=%s WHERE id=%s",
                   (generate_password_hash(new_pw), user_id))
    db.commit()
    cursor.close()
    db.close()

    flash("Password changed successfully!", "success")
    return redirect("/settings")


# ─────────────────────────────────────
# FORGOT PASSWORD
# ─────────────────────────────────────
@settings_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()

        db     = get_db_connection()
        cursor = db.cursor(dictionary=True)

        cursor.execute("SELECT id FROM users WHERE email=%s", (email,))
        user = cursor.fetchone()

        if user:
            token   = secrets.token_urlsafe(32)
            expires = datetime.datetime.now() + datetime.timedelta(hours=1)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS password_resets (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    user_id    INT NOT NULL,
                    token      VARCHAR(100) NOT NULL,
                    expires_at DATETIME NOT NULL,
                    used       TINYINT DEFAULT 0
                )
            """)

            cursor.execute("""
                INSERT INTO password_resets (user_id, token, expires_at)
                VALUES (%s, %s, %s)
            """, (user["id"], token, expires))
            db.commit()

            reset_link = f"http://127.0.0.1:5000/reset-password/{token}"

            try:
                msg = Message(
                    subject    = "Reset Your Learnify Password",
                    sender     = mail.app.config['MAIL_USERNAME'],
                    recipients = [email]
                )
                msg.body = f"""Hi,

You requested a password reset for your Learnify account.

Click the link below to reset your password (valid for 1 hour):

{reset_link}

If you didn't request this, ignore this email.

— Learnify Team
"""
                mail.send(msg)
            except Exception as e:
                print("MAIL ERROR:", e)
                flash("Could not send email. Check mail config.", "error")
                return redirect("/forgot-password")

        cursor.close()
        db.close()

        # Always same message (don't reveal if email exists)
        flash("If that email exists, a reset link has been sent.", "success")
        return redirect("/forgot-password")

    return render_template("forgot_password.html")


# ─────────────────────────────────────
# RESET PASSWORD
# ─────────────────────────────────────
@settings_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    db     = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT * FROM password_resets
        WHERE token=%s AND used=0 AND expires_at > NOW()
    """, (token,))
    reset = cursor.fetchone()

    if not reset:
        flash("Invalid or expired reset link.", "error")
        return redirect("/login")

    if request.method == "POST":
        new_pw  = request.form.get("new_password",     "")
        confirm = request.form.get("confirm_password", "")

        if len(new_pw) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("reset_password.html", token=token)

        if new_pw != confirm:
            flash("Passwords do not match.", "error")
            return render_template("reset_password.html", token=token)

        cursor.execute("UPDATE users SET password=%s WHERE id=%s",
                       (generate_password_hash(new_pw), reset["user_id"]))
        cursor.execute("UPDATE password_resets SET used=1 WHERE token=%s",
                       (token,))
        db.commit()
        cursor.close()
        db.close()

        flash("Password reset! Please log in.", "success")
        return redirect("/login")

    cursor.close()
    db.close()
    return render_template("reset_password.html", token=token)


# ─────────────────────────────────────
# DELETE ACCOUNT
# ─────────────────────────────────────
@settings_bp.route("/settings/delete-account", methods=["POST"])
def delete_account():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    db      = get_db_connection()
    cursor  = db.cursor()

    cursor.execute("DELETE FROM user_badges        WHERE user_id=%s", (user_id,))
    cursor.execute("DELETE FROM user_stats         WHERE user_id=%s", (user_id,))
    cursor.execute("DELETE FROM flashcard_progress WHERE user_id=%s", (user_id,))
    cursor.execute("DELETE FROM game_sessions      WHERE user_id=%s", (user_id,))
    cursor.execute("DELETE FROM flashcards         WHERE user_id=%s", (user_id,))
    cursor.execute("DELETE FROM users              WHERE id=%s",      (user_id,))

    db.commit()
    cursor.close()
    db.close()

    session.clear()
    flash("Your account has been deleted.", "success")
    return redirect("/login")