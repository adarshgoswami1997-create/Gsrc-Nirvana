from flask import Flask, render_template, request, redirect, session, jsonify
import sqlite3
from sentence_transformers import SentenceTransformer , util
import re
import os
from werkzeug.utils import secure_filename
from rapidfuzz import fuzz
from datetime import datetime
app = Flask(__name__)
model = SentenceTransformer("all-MiniLM-L6-v2")
UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf", "doc", "docx"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.secret_key = "secretkey123"

@app.template_filter("highlight")
def highlight(text, search):
    if not search:
        return text
    pattern = re.compile(re.escape(search), re.IGNORECASE)
    return pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", text)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS   
def find_similar_question(user_question):
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("SELECT id, question FROM questions")
    questions = c.fetchall()

    conn.close()

    for q in questions:
        score = fuzz.ratio(user_question.lower(), q[1].lower())

        if score > 90:
            return q[0]

    return None
def init_db():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT DEFAULT 'user'
        )
        """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT,
            user TEXT,
            category TEXT
        )
    """)

    try:
        c.execute("ALTER TABLE questions ADD COLUMN category TEXT")
    except:
        pass

    try:
        c.execute("ALTER TABLE questions ADD COLUMN created_at TEXT")
    except:
        pass
    try:
        c.execute("ALTER TABLE questions ADD COLUMN file_name TEXT")
    except:
        pass
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER,
            answer TEXT,
            user TEXT
        )
        """)

    conn.commit()
    conn.close()

@app.route("/add", methods=["POST"])
def add_question():
    if "user" not in session:
        return redirect("/login")

    question = request.form.get("question")
    similar_id = find_similar_question(question)

    if similar_id:
        return redirect("uestion already exists")
    category = request.form["category"]
    subcategory = request.form.get('subcategory')
    ruletype = request.form.get('subsubcategory')

    file = request.files.get("file")
    file_name = None

    if file and file.filename != "":
        if allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(file_path)
            file_name = filename

    user = session["user"]
    created_at = datetime.now().strftime("%Y-%m-%d")

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute(
        "INSERT INTO questions (question, user, category, subcategory, ruletype, created_at, file_name) VALUES                  (?, ?, ?, ?, ?, ?, ?)",
        (question, user, category, subcategory, ruletype, created_at, file_name)
    )
    
    conn.commit()
    conn.close()

    return redirect("/")

@app.route("/")
def home():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    filter_type = request.args.get("filter", "all")
    category_filter = request.args.get("category")
    page = request.args.get("page", 1, type=int)
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")

    per_page = 10
    offset = (page - 1) * per_page
    search_query = request.args.get("search", "").strip()

    base_query = """
        SELECT DISTINCT q.*
        FROM questions q
        LEFT JOIN answers a ON q.id = a.question_id
        WHERE 1=1
    """
    count_query = "SELECT COUNT(DISTINCT q.id) FROM questions q LEFT JOIN answers a ON q.id = a.question_id     WHERE 1=1" 
    params = []

# CATEGORY FILTER
    if category_filter:
        base_query += " AND q.category = ?"
        count_query += " AND q.category = ?"
        params.append(category_filter)
    # DATE FILTER
    if from_date and to_date:
        base_query += " AND q.created_at BETWEEN ? AND ?"
        params.append(from_date)
        params.append(to_date)

    elif from_date:
        base_query += " AND q.created_at = ?"
        params.append(from_date)

    if category_filter:
        base_query += " AND q.category = ?"
        params.append(category_filter)
# TODAY FILTER
    if filter_type == "today":
        base_query += " AND DATE(q.created_at) = DATE('now','localtime')"

    # 🔎 SEARCH
    if search_query:
        base_query += " AND (q.question LIKE ? OR a.answer LIKE ?)"
        params.append(f"%{search_query}%")
        params.append(f"%{search_query}%")

    # 📌 FILTER
    if filter_type == "answered":
        base_query += " AND q.id IN (SELECT question_id FROM answers)"
    elif filter_type == "unanswered":
        base_query += " AND q.id NOT IN (SELECT question_id FROM answers)"

    
    base_query += " ORDER BY q.id DESC LIMIT ? OFFSET ?"
    params.append(per_page)
    params.append(offset)
    c.execute(count_query)
    total = c.fetchone()[0]
    c.execute(base_query, params)
    questions = c.fetchall()

    c.execute("SELECT * FROM answers")
    answers = c.fetchall()
    c.execute("SELECT COUNT(*) FROM questions")
    total_questions = c.fetchone()[0]

    total_pages = (total + per_page - 1) // per_page
    # UNANSWERED COUNT
    c.execute("""
    SELECT COUNT(*)
    FROM questions
    WHERE id NOT IN (SELECT question_id FROM answers)
""")
    unanswered_count = c.fetchone()[0]
    conn.close()
    print("unanswered_count:", unanswered_count)
    return render_template(
        "index.html",
        questions=questions,
        answers=answers,
        user=session.get("user"),
        role=session.get("role"),
        current_filter=filter_type,
        search_query=search_query,
        page=page,
        total_pages=total_pages,
        unanswered_count=unanswered_count
    )

@app.route("/add_answer", methods=["POST"])
def add_answer():
    if "user" not in session:
        return redirect("/login")

    if session.get("role") != "admin":
        return redirect("/")

    question_id = request.form["question_id"]
    answer = request.form["answer"]
    user = session["user"]

    file = request.files.get("file")
    filename = None

    if file and file.filename != "":
        filename = file.filename
        file.save("static/uploads/" + filename)

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute(
        "INSERT INTO answers (question_id, answer, user, file) VALUES (?, ?, ?, ?)",
        (question_id, answer, user, filename)
    )

    conn.commit()
    conn.close()

    return redirect("/")

@app.route("/question/<int:id>")
def view_question(id):

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("SELECT * FROM questions WHERE id=?", (id,))
    question = c.fetchone()

    c.execute("SELECT * FROM answers WHERE question_id=?", (id,))
    answers = c.fetchall()

    conn.close()

    return render_template(
        "question.html",
        question=question,
        answers=answers
    )
@app.route("/similar")
def similar_questions():

    query = request.args.get("q")

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("SELECT id, question FROM questions")
    rows = c.fetchall()

    conn.close()

    if not rows:
        return jsonify(results=[])

    questions = [row[1] for row in rows]

    query_embedding = model.encode(query, convert_to_tensor=True)
    question_embeddings = model.encode(questions, convert_to_tensor=True)

    scores = util.cos_sim(query_embedding, question_embeddings)[0]

    results = []

    for i, score in enumerate(scores):
        results.append({
            "id": rows[i][0],
            "question": rows[i][1],
            "score": float(score)
        })

    # similarity के हिसाब से sort
    results = sorted(results, key=lambda x: x["score"], reverse=True)

    return jsonify(results=results[:5])


@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = sqlite3.connect("database.db")
        c = conn.cursor()
        c.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (username, password),
        )
        user = c.fetchone()
        conn.close()

        if user:
            session["user"] = username
            session["role"] = user[3]
            return redirect("/")
        else:
            return "Invalid credentials"

    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = sqlite3.connect("database.db")
        c = conn.cursor()

        try:
            c.execute(
                "INSERT INTO users (username,password,role) VALUES (?,?,?)",
                (username, password, "user")
            )
            conn.commit()
            conn.close()
            return redirect("/login")

        except sqlite3.IntegrityError:
            conn.close()
            return "Username already exists. Please login."

    return render_template("register.html")
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/delete/<int:question_id>", methods=["GET", "POST"])
def delete_question(question_id):
    if "user" not in session:
        return redirect("/login")

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    # Question owner निकालो
    c.execute("SELECT user FROM questions WHERE id=?", (question_id,))
    result = c.fetchone()

    if not result:
        conn.close()
        return "Question not found"

    owner = result[0]

    # ✅ Admin OR Owner दोनों delete कर सकते हैं
    if session.get("role") == "admin" or session.get("user") == owner:
        c.execute("DELETE FROM questions WHERE id=?", (question_id,))
        conn.commit()
        conn.close()
        return redirect("/")
    else:
        conn.close()
        return "Access Denied"

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/login")

    if session.get("role") != "admin":
        return "Access Denied"

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM questions")
    total_questions = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM answers")
    total_answers = c.fetchone()[0]

    c.execute("""
    SELECT COUNT(*) FROM questions 
    WHERE id NOT IN (SELECT question_id FROM answers)
    """)
    unanswered = c.fetchone()[0]

    c.execute("""
    SELECT COUNT(*) FROM questions 
    WHERE DATE(created_at) = DATE('now')
    """)
    today_questions = c.fetchone()[0]

    c.execute("SELECT id, username, role FROM users")
    users_list = c.fetchall()
    conn.close()

    return render_template(
    "dashboard.html",
    total_users=total_users,
    total_questions=total_questions,
    total_answers=total_answers,
    unanswered=unanswered,
    today_questions=today_questions,
    users_list=users_list
    )
@app.route("/delete_answer/<int:answer_id>", methods=["POST"])
def delete_answer(answer_id):
    if "user" not in session:
        return redirect("/login")

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    # answer owner निकालो
    c.execute("SELECT user FROM answers WHERE id=?", (answer_id,))
    result = c.fetchone()

    if not result:
        conn.close()
        return "Answer not found"

    answer_owner = result[0]

    # permission check
    if session.get("role") == "admin" or session["user"] == answer_owner:
        c.execute("DELETE FROM answers WHERE id=?", (answer_id,))
        conn.commit()
        conn.close()
        return redirect("/")
    else:
        conn.close()
        return "Access Denied"

@app.route("/delete_user/<username>", methods=["POST"])
def delete_user(username):
    if "user" not in session:
        return redirect("/login")

    if session.get("role") != "admin":
        return "Access Denied"

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("DELETE FROM users WHERE username=?", (username,))
    conn.commit()
    conn.close()

    return redirect("/dashboard")
@app.route("/edit_answer/<int:answer_id>", methods=["GET", "POST"])
def edit_answer(answer_id):
    if "user" not in session:
        return redirect("/login")

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("SELECT answer, user FROM answers WHERE id=?", (answer_id,))
    result = c.fetchone()

    if not result:
        conn.close()
        return "Answer not found"

    answer_text = result[0]
    answer_owner = result[1]

    # Permission check
    if session.get("role") != "admin" and session["user"] != answer_owner:
        conn.close()
        return "Access Denied"

    if request.method == "POST":
        new_answer = request.form.get("answer")
        c.execute("UPDATE answers SET answer=? WHERE id=?", (new_answer, answer_id))
        conn.commit()
        conn.close()
        return redirect("/")

    conn.close()
    return render_template("edit_answer.html", answer=answer_text)

@app.route("/edit_question/<int:question_id>", methods=["GET", "POST"])
def edit_question(question_id):
    if "user" not in session:
        return redirect("/login")

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("SELECT question, user FROM questions WHERE id=?", (question_id,))
    result = c.fetchone()

    if not result:
        conn.close()
        return "Question not found"

    question_text = result[0]
    question_owner = result[1]

    # Permission check
    if session.get("role") != "admin" and session["user"] != question_owner:
        conn.close()
        return "Access Denied"

    if request.method == "POST":
        new_question = request.form["question"]
        c.execute("UPDATE questions SET question=? WHERE id=?", (new_question, question_id))
        conn.commit()
        conn.close()
        return redirect("/")

    conn.close()
    return render_template("edit_question.html", question=question_text)


    return redirect("/dashboard")

@app.route('/make_admin/<int:user_id>')
def make_admin(user_id):
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("UPDATE users SET role='admin' WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    return redirect('/dashboard')


@app.route('/remove_admin/<int:user_id>')
def remove_admin(user_id):
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    # check kitne admin bache hain
    c.execute("SELECT COUNT(*) FROM users WHERE role='admin'")
    admin_count = c.fetchone()[0]

    if admin_count > 1:
        c.execute("UPDATE users SET role='user' WHERE id=?", (user_id,))
        conn.commit()

    conn.close()
    return redirect('/dashboard')
@app.route("/suggest")
def suggest():
    query = request.args.get("q", "").lower()

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    # 🔥 ALL questions (IMPORTANT - no LIMIT here)
    c.execute("SELECT id, question FROM questions ORDER BY id DESC")
    all_data = c.fetchall()

    results = []
    for index, row in enumerate(all_data):
        if query in row[1].lower():
            results.append({
                "id": row[0],
                "question": row[1],
                "page": (index // 10) + 1   # 👈 match pagination
            })

    conn.close()

    return jsonify(results)
if __name__ == "__main__":
     init_db()
     port = int(os.environ.get("PORT", 5000))
     app.run(host="0.0.0.0", port=port)

